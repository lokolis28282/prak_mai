"""FULL inventory Slice 1 application service.

The service owns only external source/workspace state. The operational
``warehouse.db`` is opened read-only for reference fingerprints and legacy
matching and is never changed by these use cases.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unicodedata
import uuid
from typing import Any, BinaryIO, Iterable

from inventory.shared.reference_normalization import normalize_reference_key
from inventory.shared.validators import WarehouseError

from .models import (
    ActorSnapshot,
    COMPATIBILITY_MAPPING_VERSION,
    INACTIVE_STATUSES,
    IN_PROGRESS_STATUSES,
    PARSER_VERSION,
    REVIEW_STATUSES,
    SessionStatus,
    SystemState,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    InventoryPaths,
    PreviewFinding,
)
from .workspace import (
    SCHEMA_VERSION,
    WorkspaceError,
    WorkspaceStore,
    create_workspace,
    iter_workspace_files,
    secure_directory,
    secure_file,
    verify_workspace,
)
from .xlsx_parser import (
    IDENTIFIER_COLUMNS,
    INVENTORY_COLUMNS,
    MAX_UPLOAD_BYTES,
    Cell,
    FullInventoryXlsxError,
    SourceRow,
    WorkbookInfo,
    inspect_workbook,
    template_bytes,
)
from baseline_rehearsal import build_candidate, validate_candidate


ACTIVE_SESSION_STATUSES = IN_PROGRESS_STATUSES | REVIEW_STATUSES
ALLOWED_CREATE_ROLES = {"admin", "engineer"}
ALLOWED_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
    "",
}
REQUIRED_MANIFEST = {
    "TemplateId",
    "TemplateVersion",
    "InventoryExternalId",
    "WarehouseCode",
    "CountStartedAt",
    "CountFinishedAt",
    "CountedBy",
    "TimeZone",
    "ReferenceVersion",
}
REQUIRED_ROW_FIELDS = {
    "RowId",
    "ItemKind",
    "WarehouseCode",
    "LocationCode",
    "Description",
    "Quantity",
    "UOM",
    "Condition",
    "CountedBy",
}

RESOLUTION_ACTIONS = {
    "LINK_EXISTING_EQUIPMENT",
    "CREATE_NEW_EQUIPMENT_CANDIDATE",
    "CHOOSE_CATALOG_ITEM",
    "CHOOSE_TARGET_LOCATION",
    "CORRECT_VALUE",
    "CONFIRM_LITERAL_IDENTIFIER",
    "EXCLUDE_ROW",
    "QUARANTINE_ROW",
    "MARK_DUPLICATE",
    "DEFER_ROW",
}
ROW_DISPOSITIONS = {"EXCLUDE_ROW", "QUARANTINE_ROW", "MARK_DUPLICATE"}


def default_inventory_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ODE" / "full_inventory"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "ODE" / "full_inventory"
    return Path.home() / ".local" / "state" / "ode" / "full_inventory"


def _now_us() -> int:
    return time.time_ns() // 1_000


def _uuid7() -> str:
    timestamp = int(time.time() * 1000) & ((1 << 48) - 1)
    random_bits = int.from_bytes(os.urandom(10), "big")
    value = (timestamp << 80) | (0x7 << 76) | (random_bits & ((1 << 76) - 1))
    value &= ~(0b11 << 62)
    value |= 0b10 << 62
    return str(uuid.UUID(int=value))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).digest()


def _serial_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _sqlite_nocase_key(value: str) -> str:
    """Mirror SQLite built-in NOCASE (ASCII only) after SQL trim()."""
    return value.strip().translate(str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
    ))


def _parse_timestamp(value: str, field: str) -> datetime:
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{field} обязателен")
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} должен содержать timezone")
    return parsed


def _read_only_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


class FullInventoryService:
    def __init__(
        self,
        operational_db: str | Path,
        *,
        state_root: str | Path | None = None,
    ):
        self.operational_db = Path(operational_db).expanduser().resolve()
        self.paths = InventoryPaths(
            Path(state_root).expanduser().resolve()
            if state_root is not None
            else default_inventory_root().resolve()
        )
        self._path_error = self._validate_path_policy()

    def _validate_path_policy(self) -> str:
        root = self.paths.root
        repository = Path(__file__).resolve().parents[3]
        try:
            root.relative_to(repository)
            return "Full inventory state root не может находиться в repository"
        except ValueError:
            pass
        if root == self.operational_db.parent:
            return "Full inventory state root должен быть отделён от operational DB"
        return ""

    @staticmethod
    def actor_snapshot(user: dict[str, Any], *, display_override: str = "") -> ActorSnapshot:
        stable_id = user.get("id")
        if stable_id in (None, ""):
            stable_id = str(user.get("email") or "").strip()
        if not stable_id:
            raise WarehouseError("Невозможно доказать stable actor identifier")
        display = display_override.strip() or " ".join(
            str(user.get(key) or "").strip() for key in ("last_name", "first_name")
        ).strip()
        if not display:
            display = str(user.get("email") or stable_id)
        return ActorSnapshot(
            actor_id=f"legacy-user:{stable_id}",
            display=display,
            role=str(user.get("role") or ""),
        )

    @staticmethod
    def _require_operator(actor: ActorSnapshot) -> None:
        if actor.role not in ALLOWED_CREATE_ROLES:
            raise WarehouseError("Недостаточно прав для FULL inventory Preview")

    def _source_path(self, source_key: str) -> Path:
        if not source_key.startswith("src_"):
            raise WorkspaceError("Invalid source opaque key")
        digest = source_key.removeprefix("src_")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise WorkspaceError("Invalid source opaque key")
        return self.paths.sources / digest[:2] / f"{digest}.xlsx"

    def _workspace_candidates(self) -> list[tuple[Path, dict[str, Any]]]:
        result: list[tuple[Path, dict[str, Any]]] = []
        for path in iter_workspace_files(self.paths.previews):
            verified = verify_workspace(path)
            for session in verified["sessions"]:
                result.append((path, session))
        return result

    def _verify_session_source(self, session: dict[str, Any]) -> None:
        key = str(session.get("source_opaque_key") or "")
        if not key:
            if session.get("session_status") != SessionStatus.DRAFT.value:
                raise WorkspaceError("Inventory source provenance is incomplete")
            return
        path = self._source_path(key)
        if path.is_symlink() or not path.is_file():
            raise WorkspaceError("Inventory source file is missing")
        expected = bytes(session.get("source_sha256") or b"")
        key_digest = key.removeprefix("src_")
        if len(expected) != 32 or expected.hex() != key_digest:
            raise WorkspaceError("Inventory source key/hash provenance mismatch")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.digest() != expected:
            raise WorkspaceError("Inventory source hash mismatch")

    def system_status(self) -> dict[str, Any]:
        public = {
            "state": SystemState.NOT_INITIALIZED.value,
            "authoritative": False,
            "balance_kind": "HISTORICAL_CALCULATION",
            "baseline_timestamp": None,
            "posting_allowed": False,
            "active_session": None,
            "degraded_reason": "",
            "ready_reachable": False,
        }
        if self._path_error:
            return {**public, "state": SystemState.DEGRADED.value, "degraded_reason": self._path_error}
        try:
            candidates = self._workspace_candidates()
            active = [item for item in candidates if item[1]["session_status"] in ACTIVE_SESSION_STATUSES]
            failed = [item for item in candidates if item[1]["session_status"] == SessionStatus.FAILED.value]
            if len(active) > 1:
                raise WorkspaceError("Несколько active FULL inventory sessions")
            if failed and not active:
                raise WorkspaceError("Последняя FULL inventory session завершилась ошибкой")
            if not active:
                return public
            path, session = active[0]
            self._verify_session_source(session)
            status = str(session["session_status"])
            state = (
                SystemState.INVENTORY_IN_PROGRESS.value
                if status in IN_PROGRESS_STATUSES
                else SystemState.INVENTORY_REVIEW.value
            )
            return {
                **public,
                "state": state,
                "active_session": self._public_session(session),
                "workspace_schema_version": SCHEMA_VERSION,
                "compatibility_mapping_version": COMPATIBILITY_MAPPING_VERSION,
            }
        except (OSError, sqlite3.Error, WorkspaceError) as error:
            return {
                **public,
                "state": SystemState.DEGRADED.value,
                "degraded_reason": str(error),
            }

    @staticmethod
    def _public_session(session: dict[str, Any]) -> dict[str, Any]:
        result = dict(session)
        for key in ("source_sha256", "reference_fingerprint", "preview_digest"):
            value = result.get(key)
            result[key] = bytes(value).hex() if value is not None else ""
        result.pop("session_id", None)
        result.pop("source_opaque_key", None)
        return result

    def create_session(self, actor: ActorSnapshot, *, correlation_id: str) -> dict[str, Any]:
        self._require_operator(actor)
        if self._path_error:
            raise WorkspaceError(self._path_error)
        if len(correlation_id) < 16:
            raise WarehouseError("Некорректный correlation ID")
        status = self.system_status()
        if status["state"] != SystemState.NOT_INITIALIZED.value:
            raise WarehouseError("Активная FULL inventory session уже существует")
        session_id = _uuid7()
        opaque = uuid.uuid4().hex
        workspace_path = self.paths.workspace(opaque)
        create_workspace(workspace_path)
        now = _now_us()
        with closing(WorkspaceStore(workspace_path).connect()) as db:
            db.execute(
                """INSERT INTO preview_sessions(
                       session_id,public_id,session_type,session_status,
                       warehouse_scope_raw,compatibility_mapping_version,
                       counted_by_raw,count_started_at,count_finished_at,
                       created_actor_id,created_actor_display,created_actor_role,
                       created_at,updated_at
                   ) VALUES (?,?, 'FULL','DRAFT','',?,'','','',?,?,?,?,?)""",
                (
                    session_id,
                    session_id,
                    COMPATIBILITY_MAPPING_VERSION,
                    actor.actor_id,
                    actor.display,
                    actor.role,
                    now,
                    now,
                ),
            )
            self._append_activity(
                db, session_id, "SESSION_CREATED", actor, correlation_id, {"session_type": "FULL"}, now
            )
            db.commit()
            session = dict(db.execute("SELECT * FROM preview_sessions").fetchone())
        secure_file(workspace_path)
        return self._public_session(session)

    def _find_session(self, public_id: str) -> tuple[Path, dict[str, Any]]:
        if not public_id or len(public_id) > 100:
            raise WarehouseError("Некорректный session ID")
        for path, session in self._workspace_candidates():
            if str(session["public_id"]) == public_id:
                return path, session
        raise WarehouseError("FULL inventory session не найдена")

    def get_session(self, public_id: str) -> dict[str, Any]:
        path, session = self._find_session(public_id)
        self._verify_session_source(session)
        result = self._public_session(session)
        result["workspace_schema_version"] = SCHEMA_VERSION
        result["workspace_schema_fingerprint"] = verify_workspace(path)["schema_fingerprint"]
        return result

    @staticmethod
    def _active_resolutions(
        db: sqlite3.Connection, session_id: str
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in db.execute(
            """SELECT z.*,r.source_row_number,r.source_row_id,
                      f.code AS finding_code,
                      COALESCE(f.field_code,
                          CASE WHEN z.action_code='CORRECT_VALUE' THEN z.target_public_id END,
                          '') AS field_code
                 FROM preview_resolutions z
                 JOIN preview_runs p ON p.run_id=z.run_id
                 LEFT JOIN preview_rows r ON r.row_id=z.row_id
                 LEFT JOIN preview_findings f ON f.finding_id=z.finding_id
                WHERE p.session_id=?
                  AND NOT EXISTS (
                      SELECT 1 FROM preview_resolutions newer
                       WHERE newer.supersedes_resolution_id=z.resolution_id
                  )
                ORDER BY z.resolution_id""",
            (session_id,),
        )]

    @staticmethod
    def _resolution_scope(resolution: dict[str, Any]) -> tuple[Any, ...]:
        action = str(resolution["action_code"])
        row_number = int(resolution["source_row_number"])
        if action in ROW_DISPOSITIONS | {"DEFER_ROW"}:
            return (row_number, "DISPOSITION")
        if action == "CORRECT_VALUE":
            return (row_number, "VALUE", str(resolution.get("field_code") or ""))
        if action == "CHOOSE_TARGET_LOCATION":
            return (row_number, "TARGET_LOCATION")
        if action in {"LINK_EXISTING_EQUIPMENT", "CREATE_NEW_EQUIPMENT_CANDIDATE"}:
            return (row_number, "EQUIPMENT")
        if action == "CHOOSE_CATALOG_ITEM":
            return (row_number, "CATALOG")
        return (
            row_number,
            action,
            str(resolution.get("finding_code") or ""),
            str(resolution.get("field_code") or ""),
        )

    def list_resolutions(self, public_id: str) -> dict[str, Any]:
        path, session = self._find_session(public_id)
        with closing(WorkspaceStore(path).connect(read_only=True)) as db:
            resolutions = self._active_resolutions(db, session["session_id"])
        for resolution in resolutions:
            resolution["resolution_checksum"] = bytes(
                resolution["resolution_checksum"]
            ).hex()
            resolution.pop("run_id", None)
        return {"resolutions": resolutions, "total": len(resolutions)}

    def record_resolution(
        self,
        public_id: str,
        actor: ActorSnapshot,
        *,
        action_code: str,
        reason: str,
        correlation_id: str,
        row_id: int | None = None,
        finding_id: int | None = None,
        field_code: str = "",
        target_public_id: str = "",
        replacement_value: str = "",
        supersedes_resolution_id: int | None = None,
    ) -> dict[str, Any]:
        self._require_operator(actor)
        action = action_code.strip().upper()
        reason = reason.strip()
        if action not in RESOLUTION_ACTIONS:
            raise WarehouseError("Неподдерживаемое resolution action")
        if not reason or len(reason) > 2_000:
            raise WarehouseError("Resolution требует reason до 2000 символов")
        if len(target_public_id) > 500 or len(replacement_value) > 4_000:
            raise WarehouseError("Resolution value превышает допустимый размер")
        if action == "CORRECT_VALUE" and replacement_value == "":
            raise WarehouseError("CORRECT_VALUE требует replacement_value")
        if action in {
            "LINK_EXISTING_EQUIPMENT", "CHOOSE_CATALOG_ITEM", "CHOOSE_TARGET_LOCATION"
        } and not target_public_id.strip():
            raise WarehouseError(f"{action} требует target_public_id")
        path, session = self._find_session(public_id)
        if session["session_status"] not in REVIEW_STATUSES:
            raise WarehouseError("Resolution доступно только после успешного Preview")
        now = _now_us()
        with closing(WorkspaceStore(path).connect()) as db:
            active_run_id = str(session["active_run_id"] or "")
            row = None
            finding = None
            if finding_id is not None:
                finding = db.execute(
                    """SELECT f.*,r.source_row_number,r.source_row_id
                         FROM preview_findings f
                         LEFT JOIN preview_rows r ON r.row_id=f.row_id
                        WHERE f.finding_id=? AND f.run_id=?""",
                    (int(finding_id), active_run_id),
                ).fetchone()
                if finding is None:
                    raise WarehouseError("Finding не принадлежит active Preview")
                if finding["row_id"] is not None:
                    if row_id is not None and int(row_id) != int(finding["row_id"]):
                        raise WarehouseError("Finding и row resolution не совпадают")
                    row_id = int(finding["row_id"])
            if row_id is not None:
                row = db.execute(
                    "SELECT * FROM preview_rows WHERE row_id=? AND run_id=?",
                    (int(row_id), active_run_id),
                ).fetchone()
                if row is None:
                    raise WarehouseError("Row не принадлежит active Preview")
            if row is None:
                raise WarehouseError("Resolution требует Preview row")
            finding_field = str(finding["field_code"] or "") if finding else ""
            field_code = field_code.strip() or finding_field
            if finding_field and field_code != finding_field:
                raise WarehouseError("field_code не совпадает с finding")
            if action == "CORRECT_VALUE" and field_code not in INVENTORY_COLUMNS:
                raise WarehouseError("CORRECT_VALUE требует допустимый field_code")
            candidate = {
                "action_code": action,
                "source_row_number": int(row["source_row_number"]),
                "source_row_id": str(row["source_row_id"]),
                "finding_code": str(finding["code"] or "") if finding else "",
                "field_code": field_code,
                "target_public_id": target_public_id,
                "replacement_value": replacement_value,
                "reason": reason,
                "actor": actor.actor_id,
                "supersedes_resolution_id": supersedes_resolution_id,
            }
            checksum = _sha(_canonical_json(candidate))
            duplicate = db.execute(
                "SELECT resolution_id FROM preview_resolutions WHERE run_id=? AND resolution_checksum=?",
                (active_run_id, checksum),
            ).fetchone()
            if duplicate is not None:
                return self.list_resolutions(public_id)
            active = self._active_resolutions(db, session["session_id"])
            conflicts = [
                item for item in active
                if self._resolution_scope(item) == self._resolution_scope(candidate)
            ]
            if conflicts:
                expected = int(conflicts[-1]["resolution_id"])
                if supersedes_resolution_id != expected:
                    raise WarehouseError(
                        f"RESOLUTION_CONFLICT: укажите supersedes_resolution_id={expected}"
                    )
            elif supersedes_resolution_id is not None:
                raise WarehouseError("supersedes_resolution_id не является active resolution")
            cursor = db.execute(
                """INSERT INTO preview_resolutions(
                       run_id,finding_id,row_id,action_code,target_public_id,
                       replacement_value_public_id,reason,actor_user_public_id,
                       actor_display_name,created_at_us,supersedes_resolution_id,
                       resolution_checksum
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    active_run_id,
                    int(finding_id) if finding_id is not None else None,
                    int(row_id),
                    action,
                    field_code if action == "CORRECT_VALUE" else target_public_id or None,
                    replacement_value if action == "CORRECT_VALUE" else None,
                    reason,
                    actor.actor_id,
                    actor.display,
                    now,
                    supersedes_resolution_id,
                    checksum,
                ),
            )
            db.execute(
                "UPDATE preview_sessions SET session_status='REVIEW_REQUIRED',updated_at=? WHERE session_id=?",
                (now, session["session_id"]),
            )
            self._append_activity(
                db,
                session["session_id"],
                "RESOLUTION_RECORDED",
                actor,
                correlation_id,
                {"action": action, "resolution_id": int(cursor.lastrowid)},
                now,
            )
            db.commit()
        return self.list_resolutions(public_id)

    @classmethod
    def _resolution_plan(
        cls, db: sqlite3.Connection, session_id: str
    ) -> tuple[dict[int, list[dict[str, Any]]], list[bytes]]:
        plan: dict[int, list[dict[str, Any]]] = {}
        checksums: list[bytes] = []
        for resolution in cls._active_resolutions(db, session_id):
            row_number = int(resolution["source_row_number"])
            plan.setdefault(row_number, []).append(resolution)
            checksums.append(bytes(resolution["resolution_checksum"]))
        return plan, checksums

    @staticmethod
    def _finding_resolved(
        finding: PreviewFinding, resolutions: list[dict[str, Any]]
    ) -> bool:
        for resolution in resolutions:
            action = str(resolution["action_code"])
            if action in ROW_DISPOSITIONS:
                return True
            same_field = str(resolution.get("field_code") or "") == finding.field_code
            if action == "CORRECT_VALUE" and same_field:
                return finding.code in {"FORMULA_CELL", "IDENTIFIER_NOT_TEXT"}
            if action == "CONFIRM_LITERAL_IDENTIFIER" and same_field:
                return finding.code == "IDENTIFIER_NOT_TEXT"
            if action == "CHOOSE_TARGET_LOCATION" and finding.code in {
                "UNKNOWN_LOCATION", "AMBIGUOUS_LOCATION", "INACTIVE_OR_CANDIDATE_LOCATION"
            }:
                return True
            if action in {"LINK_EXISTING_EQUIPMENT", "CREATE_NEW_EQUIPMENT_CANDIDATE"}:
                return finding.code == "UNRESOLVED_NEW_EQUIPMENT"
            if action == "CHOOSE_CATALOG_ITEM":
                return finding.code == "AMBIGUOUS_CATALOG_ITEM"
        return False

    @staticmethod
    def _manifest_values(workbook: WorkbookInfo) -> dict[str, str]:
        return {key: cell.display_value for key, cell in workbook.manifest.items()}

    def _validate_manifest(self, workbook: WorkbookInfo) -> dict[str, str]:
        values = self._manifest_values(workbook)
        missing = [key for key in REQUIRED_MANIFEST if not values.get(key, "").strip()]
        if missing:
            raise FullInventoryXlsxError("Manifest: отсутствуют " + ", ".join(sorted(missing)))
        if values["TemplateId"].strip() != TEMPLATE_ID:
            raise FullInventoryXlsxError("Manifest TemplateId не поддерживается")
        if values["TemplateVersion"].strip() != TEMPLATE_VERSION:
            raise FullInventoryXlsxError("Manifest TemplateVersion не поддерживается")
        start = _parse_timestamp(values["CountStartedAt"], "CountStartedAt")
        finish = _parse_timestamp(values["CountFinishedAt"], "CountFinishedAt")
        if finish < start:
            raise FullInventoryXlsxError("CountFinishedAt раньше CountStartedAt")
        if len(values.get("Comment", "")) > 2_000:
            raise FullInventoryXlsxError("Manifest Comment превышает 2000 символов")
        for key, cell in workbook.manifest.items():
            if cell.has_formula:
                raise FullInventoryXlsxError(f"Manifest formula запрещена: {key}")
        return values

    def upload_source(
        self,
        public_id: str,
        *,
        filename: str,
        content_type: str,
        content_length: int,
        stream: BinaryIO,
        actor: ActorSnapshot,
        correlation_id: str,
    ) -> dict[str, Any]:
        self._require_operator(actor)
        path, session = self._find_session(public_id)
        if session["session_status"] not in {SessionStatus.DRAFT.value, SessionStatus.UPLOADED.value}:
            raise WarehouseError("Source можно загрузить только в DRAFT/UPLOADED session")
        original_name = Path(filename).name
        if not original_name or original_name != filename or Path(original_name).suffix.casefold() != ".xlsx":
            raise WarehouseError("Разрешено безопасное имя файла с расширением .xlsx")
        normalized_type = content_type.split(";", 1)[0].strip().casefold()
        if normalized_type not in ALLOWED_CONTENT_TYPES:
            raise WarehouseError("Недопустимый Content-Type для XLSX")
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            raise WarehouseError("Размер XLSX вне допустимого диапазона")
        secure_directory(self.paths.sources)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".upload_", suffix=".xlsx", dir=self.paths.sources
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        remaining = content_length
        try:
            with os.fdopen(descriptor, "wb") as output:
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise WarehouseError("XLSX загружен не полностью")
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                if stream.read(1):
                    raise WarehouseError("Получено больше XLSX bytes, чем заявлено")
                output.flush()
                os.fsync(output.fileno())
            hex_digest = digest.hexdigest()
            source_key = f"src_{hex_digest}"
            source_path = self._source_path(source_key)
            secure_directory(source_path.parent)
            if source_path.exists():
                if source_path.is_symlink() or source_path.stat().st_size != content_length:
                    raise WorkspaceError("Source vault collision")
                temporary.unlink()
            else:
                os.replace(temporary, source_path)
            secure_file(source_path)
            workbook = inspect_workbook(source_path)
            manifest = self._validate_manifest(workbook)
            fingerprint = self.reference_fingerprint()
            now = _now_us()
            with closing(WorkspaceStore(path).connect()) as db:
                db.execute(
                    """UPDATE preview_sessions SET
                           session_status='UPLOADED',warehouse_scope_raw=?,counted_by_raw=?,
                           count_started_at=?,count_finished_at=?,updated_at=?,
                           source_opaque_key=?,source_original_filename=?,source_content_type=?,
                           source_size_bytes=?,source_sha256=?,template_version=?,
                           reference_fingerprint=?,active_run_id=NULL,row_count=0,
                           blocker_count=0,warning_count=0,informational_count=0,
                           preview_digest=NULL,rejection_reason='',rejected_at=NULL,
                           rejected_by_actor_id=''
                       WHERE session_id=?""",
                    (
                        manifest["WarehouseCode"],
                        manifest["CountedBy"],
                        manifest["CountStartedAt"],
                        manifest["CountFinishedAt"],
                        now,
                        source_key,
                        original_name[:255],
                        normalized_type,
                        content_length,
                        digest.digest(),
                        TEMPLATE_VERSION,
                        fingerprint,
                        session["session_id"],
                    ),
                )
                self._append_activity(
                    db,
                    session["session_id"],
                    "SOURCE_UPLOADED",
                    actor,
                    correlation_id,
                    {"filename": original_name[:255], "size_bytes": content_length, "sha256": hex_digest},
                    now,
                )
                db.commit()
                updated = dict(db.execute(
                    "SELECT * FROM preview_sessions WHERE session_id=?", (session["session_id"],)
                ).fetchone())
            return self._public_session(updated)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def reference_fingerprint(self) -> bytes:
        digest = hashlib.sha256()
        with closing(_read_only_db(self.operational_db)) as db:
            tables = {
                str(row[0])
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'reference_%_v2'"
                )
            }
            required = {"reference_domains_v2", "reference_values_v2", "reference_aliases_v2"}
            if not required.issubset(tables):
                raise WorkspaceError("Canonical reference tables are unavailable")
            for row in db.execute(
                """SELECT d.domain_key,v.id,v.canonical_value,v.display_name,
                          v.normalized_key,v.scope_key,v.active,v.approval_status
                   FROM reference_values_v2 v
                   JOIN reference_domains_v2 d ON d.id=v.domain_id
                   ORDER BY d.domain_key,v.id"""
            ):
                digest.update(_canonical_json(list(row)).encode("utf-8"))
            for row in db.execute(
                """SELECT d.domain_key,a.id,a.source_value,a.normalized_source_key,
                          a.canonical_id,a.resolution_status
                   FROM reference_aliases_v2 a
                   JOIN reference_domains_v2 d ON d.id=a.domain_id
                   ORDER BY d.domain_key,a.id"""
            ):
                digest.update(_canonical_json(list(row)).encode("utf-8"))
        return digest.digest()

    def _reference_index(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        index: dict[str, dict[str, list[dict[str, Any]]]] = {}
        with closing(_read_only_db(self.operational_db)) as db:
            rows = db.execute(
                """SELECT d.domain_key,v.id,v.canonical_value,v.display_name,
                          v.normalized_key,v.active,v.approval_status,
                          a.normalized_source_key
                   FROM reference_domains_v2 d
                   JOIN reference_values_v2 v ON v.domain_id=d.id
                   LEFT JOIN reference_aliases_v2 a ON a.domain_id=d.id
                        AND a.canonical_id=v.id
                        AND a.resolution_status IN ('APPROVED','AUTO_APPROVED')
                   WHERE d.active=1 ORDER BY d.domain_key,v.id,a.id"""
            ).fetchall()
        for row in rows:
            value = {
                "id": row["id"], "display_name": row["display_name"],
                "active": row["active"], "approval_status": row["approval_status"],
            }
            keys = {
                "n:" + str(row["normalized_key"]),
                "c:" + _sqlite_nocase_key(str(row["display_name"])),
                "c:" + _sqlite_nocase_key(str(row["canonical_value"])),
            }
            if row["normalized_source_key"]:
                keys.add("n:" + str(row["normalized_source_key"]))
            domain_index = index.setdefault(str(row["domain_key"]), {})
            for key in keys:
                bucket = domain_index.setdefault(key, [])
                if not any(item["id"] == value["id"] for item in bucket):
                    bucket.append(value)
        return index

    def _resolve_reference(
        self,
        domain: str,
        raw: str,
        reference_index: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_reference_key(raw)
        source = reference_index if reference_index is not None else self._reference_index()
        domain_index = source.get(domain, {})
        rows_by_id: dict[int, dict[str, Any]] = {}
        for key in ("n:" + normalized, "c:" + _sqlite_nocase_key(raw)):
            for row in domain_index.get(key, []):
                rows_by_id[int(row["id"])] = row
        rows = list(rows_by_id.values())
        approved = [row for row in rows if row["active"] and row["approval_status"] == "APPROVED"]
        unresolved = [row for row in rows if row not in approved]
        return {
            "normalized": normalized,
            "approved": [dict(row) for row in approved],
            "unresolved": [dict(row) for row in unresolved],
        }

    @staticmethod
    def _finding(
        code: str,
        message: str,
        *,
        field: str = "",
        blocking: bool = True,
        severity: str | None = None,
        evidence: dict[str, Any] | None = None,
        row_number: int | None = None,
    ) -> PreviewFinding:
        return PreviewFinding(
            code=code,
            severity=severity or ("ERROR" if blocking else "WARNING"),
            blocking=blocking,
            field_code=field,
            message=message,
            evidence=evidence or {},
            row_number=row_number,
        )

    def _mapping_findings(
        self,
        row_number: int,
        warehouse: str,
        location: str,
        reference_index: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    ) -> tuple[list[PreviewFinding], dict[str, Any]]:
        findings: list[PreviewFinding] = []
        normalized: dict[str, Any] = {
            "warehouse_raw": warehouse,
            "location_raw": location,
            "compatibility_mapping_version": COMPATIBILITY_MAPPING_VERSION,
        }
        datacenter = self._resolve_reference("datacenter", warehouse, reference_index)
        if len(datacenter["approved"]) == 1:
            normalized["compatibility_warehouse_reference_id"] = datacenter["approved"][0]["id"]
            normalized["warehouse_resolution"] = "APPROVED_DATACENTER"
        elif len(datacenter["approved"]) > 1:
            findings.append(self._finding("AMBIGUOUS_WAREHOUSE", "WarehouseCode неоднозначен", field="WarehouseCode", row_number=row_number))
            normalized["warehouse_resolution"] = "AMBIGUOUS"
        else:
            findings.append(self._finding("UNKNOWN_WAREHOUSE", "WarehouseCode не найден среди approved datacenter", field="WarehouseCode", row_number=row_number))
            normalized["warehouse_resolution"] = "UNRESOLVED"
        shelf = self._resolve_reference("shelf", location, reference_index)
        if len(shelf["approved"]) == 1:
            normalized["compatibility_location_reference_id"] = shelf["approved"][0]["id"]
            normalized["location_resolution"] = "APPROVED_SHELF"
        elif len(shelf["approved"]) > 1:
            findings.append(self._finding("AMBIGUOUS_LOCATION", "LocationCode неоднозначен", field="LocationCode", row_number=row_number))
            normalized["location_resolution"] = "AMBIGUOUS"
        else:
            legacy_location = self._resolve_reference(
                "warehouse_location", location, reference_index
            )
            if legacy_location["approved"] or legacy_location["unresolved"]:
                code = "INACTIVE_OR_CANDIDATE_LOCATION"
                message = "warehouse_location не считается подтверждённой Preview location"
            else:
                code = "UNKNOWN_LOCATION"
                message = "LocationCode не найден среди approved shelf"
            findings.append(self._finding(code, message, field="LocationCode", row_number=row_number))
            normalized["location_resolution"] = "UNRESOLVED"
        return findings, normalized

    def _validate_row(
        self,
        row: SourceRow,
        manifest: dict[str, str],
        seen_row_ids: set[str],
        seen_serials: set[str],
        seen_inventory_numbers: dict[str, tuple[int, str]],
        resolutions: list[dict[str, Any]] | None = None,
        reference_index: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[PreviewFinding], list[Cell]]:
        original_raw = {name: cell.display_value for name, cell in row.cells.items()}
        raw = dict(original_raw)
        resolutions = resolutions or []
        overrides: dict[str, str] = {}
        disposition = ""
        resolution_choices: dict[str, str] = {}
        for resolution in resolutions:
            action = str(resolution["action_code"])
            if action == "CORRECT_VALUE":
                field = str(resolution.get("field_code") or "")
                if field in INVENTORY_COLUMNS:
                    value = str(resolution.get("replacement_value_public_id") or "")
                    raw[field] = value
                    overrides[field] = value
            elif action == "CHOOSE_TARGET_LOCATION":
                value = str(resolution.get("target_public_id") or "")
                raw["LocationCode"] = value
                overrides["LocationCode"] = value
            elif action in ROW_DISPOSITIONS:
                disposition = action
            elif action != "DEFER_ROW":
                resolution_choices[action] = str(resolution.get("target_public_id") or "")
        findings: list[PreviewFinding] = []
        if row.hidden:
            findings.append(self._finding("HIDDEN_DATA_ROW", "Скрытая Inventory row требует проверки", row_number=row.row_number))
        if any(name.startswith("__EXTRA__") for name in row.cells):
            findings.append(self._finding("UNKNOWN_COLUMN_DATA", "Данные вне approved columns сохранены", blocking=False, row_number=row.row_number))
        for field in REQUIRED_ROW_FIELDS:
            if not raw.get(field, "").strip():
                findings.append(self._finding("REQUIRED_VALUE_MISSING", f"{field} обязателен", field=field, row_number=row.row_number))
        for field, cell in row.cells.items():
            if cell.has_formula:
                findings.append(self._finding("FORMULA_CELL", "Formula cells запрещены", field=field, row_number=row.row_number))
            if field in IDENTIFIER_COLUMNS and cell.display_value and cell.cell_type not in {"s", "inlineStr"}:
                findings.append(self._finding("IDENTIFIER_NOT_TEXT", f"{field} должен быть Excel text", field=field, evidence={"cell_type": cell.cell_type, "raw": cell.raw_value}, row_number=row.row_number))
        row_id = raw.get("RowId", "")
        duplicate_row_id = False
        if row_id:
            if len(row_id) > 100:
                findings.append(self._finding("ROW_ID_TOO_LONG", "RowId превышает 100 символов", field="RowId", row_number=row.row_number))
            duplicate_row_id = row_id in seen_row_ids
            if duplicate_row_id:
                findings.append(self._finding("DUPLICATE_ROW_ID", "RowId повторяется", field="RowId", row_number=row.row_number))
            seen_row_ids.add(row_id)
        kind = raw.get("ItemKind", "").strip().upper()
        if kind not in {"SERIALIZED", "BULK", "CABLE", "CONSUMABLE"}:
            findings.append(self._finding("UNKNOWN_ITEM_KIND", "ItemKind не поддерживается", field="ItemKind", row_number=row.row_number))
            kind = "BULK"
        warehouse = raw.get("WarehouseCode", "")
        location = raw.get("LocationCode", "")
        mapping_findings, normalized = self._mapping_findings(
            row.row_number, warehouse, location, reference_index
        )
        normalized["row_id_duplicate"] = duplicate_row_id
        findings.extend(mapping_findings)
        if warehouse != manifest.get("WarehouseCode", ""):
            findings.append(self._finding("WAREHOUSE_SCOPE_MISMATCH", "WarehouseCode row не совпадает с Manifest", field="WarehouseCode", row_number=row.row_number))
        serial_raw = raw.get("SerialNumber", "")
        serial_key = _serial_key(serial_raw) if serial_raw else ""
        inventory_number_raw = raw.get("InventoryNumber", "")
        inventory_number_key = (
            _serial_key(inventory_number_raw) if inventory_number_raw else ""
        )
        normalized["serial_number_raw"] = serial_raw
        normalized["serial_match_key"] = serial_key
        normalized["inventory_number_raw"] = inventory_number_raw
        normalized["inventory_number_match_key"] = inventory_number_key
        if kind == "SERIALIZED":
            if not serial_raw:
                findings.append(self._finding("SERIAL_REQUIRED", "SerialNumber обязателен для SERIALIZED", field="SerialNumber", row_number=row.row_number))
            if serial_key:
                if serial_key in seen_serials:
                    findings.append(self._finding("DUPLICATE_SERIAL", "SerialNumber повторяется в source", field="SerialNumber", row_number=row.row_number))
                seen_serials.add(serial_key)
        if inventory_number_key:
            first_inventory_row = seen_inventory_numbers.get(inventory_number_key)
            if first_inventory_row is not None:
                first_row_number, first_row_id = first_inventory_row
                findings.append(self._finding(
                    "DUPLICATE_INVENTORY_NUMBER",
                    "InventoryNumber повторяется в source",
                    field="InventoryNumber",
                    evidence={
                        "first_source_row_number": first_row_number,
                        "first_row_id": first_row_id,
                    },
                    row_number=row.row_number,
                ))
            else:
                seen_inventory_numbers[inventory_number_key] = (
                    row.row_number,
                    row_id or f"source-row-{row.row_number}",
                )
        quantity_text = raw.get("Quantity", "").strip()
        try:
            quantity = Decimal(quantity_text)
            if not quantity.is_finite() or quantity <= 0:
                raise InvalidOperation
            if kind == "SERIALIZED" and quantity != 1:
                findings.append(self._finding("SERIALIZED_QUANTITY", "SERIALIZED quantity должна быть 1", field="Quantity", row_number=row.row_number))
            normalized["quantity_decimal"] = format(quantity, "f")
        except (InvalidOperation, ValueError):
            findings.append(self._finding("INVALID_QUANTITY", "Quantity должна быть positive decimal text", field="Quantity", row_number=row.row_number))
        if kind == "SERIALIZED" and not raw.get("Vendor", "").strip():
            findings.append(self._finding("VENDOR_REQUIRED", "Vendor обязателен для SERIALIZED", field="Vendor", row_number=row.row_number))
        if not raw.get("PartNumber", "").strip() and not serial_raw:
            findings.append(self._finding("PART_NUMBER_REQUIRED", "PartNumber обязателен для новой позиции без S/N", field="PartNumber", row_number=row.row_number))
        condition = raw.get("Condition", "").strip().upper()
        if condition not in {"AVAILABLE", "QUARANTINED", "DAMAGED"}:
            findings.append(self._finding("UNKNOWN_CONDITION", "Condition не поддерживается", field="Condition", row_number=row.row_number))
        unit = self._resolve_reference(
            "unit_of_measure", raw.get("UOM", ""), reference_index
        )
        if len(unit["approved"]) != 1:
            findings.append(self._finding("UNKNOWN_UOM", "UOM не найден однозначно", field="UOM", row_number=row.row_number))
        else:
            normalized["uom_reference_id"] = unit["approved"][0]["id"]
        try:
            start = _parse_timestamp(manifest["CountStartedAt"], "CountStartedAt")
            finish = _parse_timestamp(manifest["CountFinishedAt"], "CountFinishedAt")
            if raw.get("CountedAt", "").strip():
                counted = _parse_timestamp(raw["CountedAt"], "CountedAt")
                if counted < start or counted > finish:
                    findings.append(self._finding("COUNTED_AT_OUTSIDE_INTERVAL", "CountedAt вне интервала инвентаризации", field="CountedAt", row_number=row.row_number))
        except ValueError as error:
            findings.append(self._finding("INVALID_TIMESTAMP", str(error), row_number=row.row_number))
        if len(raw.get("Comment", "")) > 4_000:
            findings.append(self._finding("COMMENT_TOO_LONG", "Comment превышает 4000 символов", field="Comment", row_number=row.row_number))
        normalized.update({
            "row_id": row_id,
            "item_kind": kind,
            "condition": condition,
            "mapping_version": COMPATIBILITY_MAPPING_VERSION,
            "resolution_overrides": overrides,
            "resolution_disposition": disposition,
            "resolution_choices": resolution_choices,
        })
        cells = [cell for name, cell in row.cells.items() if name in IDENTIFIER_COLUMNS or cell.has_formula or name in {"WarehouseCode", "LocationCode"}]
        return original_raw, normalized, findings, cells

    def _legacy_match_index(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        with closing(_read_only_db(self.operational_db)) as db:
            rows = db.execute(
                """SELECT id,serial_number,inventory_number,item_name
                   FROM stock_receipts
                   WHERE trim(serial_number) <> '' ORDER BY id""",
            ).fetchall()
        for row in rows:
            key = _sqlite_nocase_key(str(row["serial_number"]))
            matches = result.setdefault(key, [])
            if len(matches) < 3:
                matches.append(dict(row))
        return result

    def build_preview(
        self, public_id: str, actor: ActorSnapshot, *, correlation_id: str
    ) -> dict[str, Any]:
        self._require_operator(actor)
        path, session = self._find_session(public_id)
        if session["session_status"] not in {
            SessionStatus.UPLOADED.value,
            SessionStatus.REVIEW_REQUIRED.value,
            SessionStatus.READY_FOR_APPROVAL.value,
        }:
            raise WarehouseError("Preview требует загруженный XLSX")
        self._verify_session_source(session)
        current_fingerprint = self.reference_fingerprint()
        source_key = str(session["source_opaque_key"])
        source_path = self._source_path(source_key)
        run_id = _uuid7()
        now = _now_us()
        with closing(WorkspaceStore(path).connect()) as db:
            attempt = int(db.execute(
                "SELECT COALESCE(MAX(attempt),0)+1 FROM preview_runs WHERE session_id=?",
                (session["session_id"],),
            ).fetchone()[0])
            db.execute(
                """INSERT INTO preview_runs(
                       run_id,session_id,attempt,session_status,run_status,
                       source_object_key,source_sha256,source_size_bytes,
                       template_version,parser_version,schema_version,
                       reference_fingerprint,observed_snapshot_public_id,
                       observed_ledger_head,freeze_token_hash,started_at_us
                   ) VALUES (?,?,?,'PREVIEWING','RUNNING',?,?,?,?,?,?,?,NULL,0,?,?)""",
                (
                    run_id,
                    session["session_id"],
                    attempt,
                    source_key,
                    bytes(session["source_sha256"]),
                    int(session["source_size_bytes"]),
                    TEMPLATE_VERSION,
                    PARSER_VERSION,
                    str(SCHEMA_VERSION),
                    current_fingerprint,
                    _sha(f"slice1-no-freeze:{run_id}"),
                    now,
                ),
            )
            db.execute(
                "UPDATE preview_sessions SET session_status='PREVIEWING',active_run_id=?,updated_at=? WHERE session_id=?",
                (run_id, now, session["session_id"]),
            )
            self._append_activity(db, session["session_id"], "PREVIEW_STARTED", actor, correlation_id, {"attempt": attempt}, now)
            db.commit()
        try:
            workbook = inspect_workbook(source_path)
            manifest = self._validate_manifest(workbook)
            legacy_match_index = self._legacy_match_index()
            reference_index = self._reference_index()
            with closing(WorkspaceStore(path).connect()) as db:
                resolution_plan, resolution_checksums = self._resolution_plan(
                    db, session["session_id"]
                )
                global_findings: list[PreviewFinding] = []
                if workbook.unknown_sheets:
                    global_findings.append(self._finding("UNKNOWN_SHEET", "Неизвестные листы проигнорированы", blocking=False, evidence={"sheets": list(workbook.unknown_sheets)}))
                if workbook.merged_inventory_ranges:
                    global_findings.append(self._finding("MERGED_DATA_AREA", "Merged cells в Inventory запрещены", evidence={"ranges": list(workbook.merged_inventory_ranges)}))
                if manifest["ReferenceVersion"].strip().casefold() not in {
                    current_fingerprint.hex().casefold(),
                    f"sha256:{current_fingerprint.hex()}".casefold(),
                }:
                    global_findings.append(self._finding("REFERENCE_VERSION_MISMATCH", "ReferenceVersion не совпадает с текущим reference fingerprint", field="ReferenceVersion"))
                manifest_mapping, _ = self._mapping_findings(
                    0, manifest["WarehouseCode"], "", reference_index
                )
                global_findings.extend(item for item in manifest_mapping if item.field_code == "WarehouseCode")
                seen_row_ids: set[str] = set()
                seen_serials: set[str] = set()
                seen_inventory_numbers: dict[str, tuple[int, str]] = {}
                row_count = 0
                blocker_count = warning_count = info_count = 0
                ordered_row_hashes: list[bytes] = []
                ordered_finding_hashes: list[bytes] = []
                for source_row in workbook.rows:
                    raw, normalized, findings, cells = self._validate_row(
                        source_row,
                        manifest,
                        seen_row_ids,
                        seen_serials,
                        seen_inventory_numbers,
                        resolution_plan.get(source_row.row_number, []),
                        reference_index,
                    )
                    effective_serial = str(
                        normalized.get("resolution_overrides", {}).get(
                            "SerialNumber", raw.get("SerialNumber", "")
                        )
                    )
                    matches = legacy_match_index.get(_sqlite_nocase_key(effective_serial), [])
                    if len(matches) > 1:
                        findings.append(self._finding("AMBIGUOUS_LEGACY_SERIAL", "S/N соответствует нескольким historical rows", field="SerialNumber", row_number=source_row.row_number))
                    normalized["legacy_match_count"] = len(matches)
                    row_hash = _sha(_canonical_json({"row": source_row.row_number, "raw": raw, "normalized": normalized}))
                    row_resolutions = resolution_plan.get(source_row.row_number, [])
                    finding_states = [
                        "RESOLVED" if self._finding_resolved(finding, row_resolutions) else "OPEN"
                        for finding in findings
                    ]
                    blocked = any(
                        finding.blocking and status == "OPEN"
                        for finding, status in zip(findings, finding_states)
                    )
                    warned = bool(normalized.get("resolution_disposition")) or any(
                        not finding.blocking and status == "OPEN"
                        for finding, status in zip(findings, finding_states)
                    )
                    row_status = "BLOCKED" if blocked else "WARNING" if warned else "VALID"
                    cursor = db.execute(
                        """INSERT INTO preview_rows(
                               run_id,source_sheet,source_row_number,source_row_id,
                               row_sha256,raw_payload_json,normalized_payload_json,
                               row_status,stock_subject_kind,proposed_match_key,processed_at_us
                           ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            run_id,
                            "Inventory",
                            source_row.row_number,
                            (
                                f"{raw.get('RowId')}#source-row-{source_row.row_number}"
                                if normalized.get("row_id_duplicate")
                                else raw.get("RowId") or f"row-{source_row.row_number}"
                            ),
                            row_hash,
                            _canonical_json(raw),
                            _canonical_json(normalized),
                            row_status,
                            normalized["item_kind"],
                            normalized.get("serial_match_key", ""),
                            _now_us(),
                        ),
                    )
                    row_db_id = int(cursor.lastrowid)
                    ordered_row_hashes.append(row_hash)
                    for cell in cells:
                        preservation = "BLOCKED" if cell.has_formula or (cell.display_value and cell.cell_type not in {"s", "inlineStr"}) else "TEXT_EXACT"
                        db.execute(
                            """INSERT INTO preview_cells(
                                   row_id,column_code,coordinate,excel_cell_type,
                                   number_format,raw_xml_value,display_value,
                                   preservation_status,cell_sha256
                               ) VALUES (?,?,?,?,?,?,?,?,?)""",
                            (
                                row_db_id,
                                next((name for name, candidate in source_row.cells.items() if candidate is cell), cell.column),
                                cell.coordinate,
                                cell.cell_type,
                                cell.number_format,
                                cell.raw_value,
                                cell.display_value,
                                preservation,
                                _sha(_canonical_json([cell.coordinate, cell.cell_type, cell.raw_value, cell.display_value])),
                            ),
                        )
                    if matches:
                        for match in matches:
                            checksum = _sha(_canonical_json(match))
                            db.execute(
                                """INSERT INTO preview_matches(
                                       run_id,row_id,candidate_type,candidate_public_id,
                                       match_kind,score_basis_json,is_selected,match_checksum
                                   ) VALUES (?,?,?,?,?,?,?,?)""",
                                (
                                    run_id,
                                    row_db_id,
                                    "LEGACY_RECEIPT",
                                    f"legacy-receipt:{match['id']}",
                                    "EXACT" if len(matches) == 1 else "CONFLICT",
                                    _canonical_json({"serial_number": match["serial_number"]}),
                                    1 if len(matches) == 1 else 0,
                                    checksum,
                                ),
                            )
                    for finding, finding_status in zip(findings, finding_states):
                        finding_hash = self._insert_finding(
                            db, run_id, row_db_id, finding, finding_status=finding_status
                        )
                        ordered_finding_hashes.append(finding_hash)
                        if finding_status != "OPEN":
                            continue
                        if finding.blocking:
                            blocker_count += 1
                        elif finding.severity == "WARNING":
                            warning_count += 1
                        else:
                            info_count += 1
                    row_count += 1
                for finding in global_findings:
                    finding_hash = self._insert_finding(db, run_id, None, finding)
                    ordered_finding_hashes.append(finding_hash)
                    if finding.blocking:
                        blocker_count += 1
                    elif finding.severity == "WARNING":
                        warning_count += 1
                    else:
                        info_count += 1
                for code, value in (
                    ("ROW_COUNT", row_count),
                    ("BLOCKER_COUNT", blocker_count),
                    ("WARNING_COUNT", warning_count),
                    ("INFORMATIONAL_COUNT", info_count),
                ):
                    db.execute(
                        "INSERT INTO preview_statistics(run_id,metric_code,value_integer,statistics_checksum) VALUES (?,?,?,?)",
                        (run_id, code, value, _sha(_canonical_json([code, value]))),
                    )
                digest = hashlib.sha256()
                for part in (
                    bytes(session["source_sha256"]),
                    TEMPLATE_VERSION.encode(),
                    PARSER_VERSION.encode(),
                    str(SCHEMA_VERSION).encode(),
                    current_fingerprint,
                    *resolution_checksums,
                    *ordered_row_hashes,
                    *ordered_finding_hashes,
                ):
                    digest.update(part)
                preview_digest = digest.digest()
                completed = _now_us()
                session_status = (
                    SessionStatus.REVIEW_REQUIRED.value
                    if blocker_count
                    else SessionStatus.READY_FOR_APPROVAL.value
                )
                existing_ready = db.execute(
                    """SELECT run_id,session_status FROM preview_runs
                       WHERE session_id=? AND preview_digest=?
                         AND run_status='READY' AND run_id<>?
                       ORDER BY attempt LIMIT 1""",
                    (session["session_id"], preview_digest, run_id),
                ).fetchone()
                if existing_ready is not None:
                    db.execute(
                        """UPDATE preview_runs SET session_status=?,run_status='CANCELLED',
                               completed_at_us=?,last_checkpoint_row=?,row_count=?,
                               finding_count=?,preview_digest=?,
                               failure_code='IDENTICAL_PREVIEW_REUSED',
                               failure_message='Identical validated Preview evidence already exists'
                           WHERE run_id=?""",
                        (
                            existing_ready["session_status"],
                            completed,
                            row_count,
                            row_count,
                            blocker_count + warning_count + info_count,
                            preview_digest,
                            run_id,
                        ),
                    )
                    db.execute(
                        """UPDATE preview_sessions SET session_status=?,active_run_id=?,
                               updated_at=?,row_count=?,blocker_count=?,warning_count=?,
                               informational_count=?,preview_digest=?,reference_fingerprint=?
                           WHERE session_id=?""",
                        (
                            existing_ready["session_status"],
                            existing_ready["run_id"],
                            completed,
                            row_count,
                            blocker_count,
                            warning_count,
                            info_count,
                            preview_digest,
                            current_fingerprint,
                            session["session_id"],
                        ),
                    )
                    self._append_activity(
                        db,
                        session["session_id"],
                        "PREVIEW_COMPLETED",
                        actor,
                        correlation_id,
                        {
                            "attempt": attempt,
                            "rows": row_count,
                            "blockers": blocker_count,
                            "warnings": warning_count,
                            "identical_ready_evidence_reused": True,
                        },
                        completed,
                    )
                    db.commit()
                    return self.preview_summary(public_id)
                db.execute(
                    """UPDATE preview_runs SET session_status=?,run_status='READY',
                           completed_at_us=?,last_checkpoint_row=?,row_count=?,
                           finding_count=?,preview_digest=? WHERE run_id=?""",
                    (
                        session_status,
                        completed,
                        row_count,
                        row_count,
                        blocker_count + warning_count + info_count,
                        preview_digest,
                        run_id,
                    ),
                )
                db.execute(
                    """UPDATE preview_sessions SET session_status=?,updated_at=?,
                           row_count=?,blocker_count=?,warning_count=?,
                           informational_count=?,preview_digest=?,reference_fingerprint=?
                       WHERE session_id=?""",
                    (
                        session_status,
                        completed,
                        row_count,
                        blocker_count,
                        warning_count,
                        info_count,
                        preview_digest,
                        current_fingerprint,
                        session["session_id"],
                    ),
                )
                self._append_activity(
                    db,
                    session["session_id"],
                    "PREVIEW_COMPLETED",
                    actor,
                    correlation_id,
                    {"attempt": attempt, "rows": row_count, "blockers": blocker_count, "warnings": warning_count},
                    completed,
                )
                db.commit()
            return self.preview_summary(public_id)
        except Exception as error:
            failed = _now_us()
            with closing(WorkspaceStore(path).connect()) as db:
                db.execute(
                    """UPDATE preview_runs SET session_status='FAILED',run_status='FAILED',
                           completed_at_us=?,failure_code=?,failure_message=? WHERE run_id=?""",
                    (failed, getattr(error, "code", "PREVIEW_FAILED"), str(error)[:500], run_id),
                )
                db.execute(
                    "UPDATE preview_sessions SET session_status='FAILED',updated_at=? WHERE session_id=?",
                    (failed, session["session_id"]),
                )
                self._append_activity(db, session["session_id"], "PREVIEW_FAILED", actor, correlation_id, {"code": getattr(error, "code", "PREVIEW_FAILED")}, failed)
                db.commit()
            raise

    @staticmethod
    def _insert_finding(
        db: sqlite3.Connection,
        run_id: str,
        row_id: int | None,
        finding: PreviewFinding,
        *,
        finding_status: str = "OPEN",
    ) -> bytes:
        payload = {
            "code": finding.code,
            "severity": finding.severity,
            "blocking": finding.blocking,
            "field": finding.field_code,
            "message": finding.message,
            "evidence": finding.evidence,
            "row": finding.row_number,
        }
        checksum = _sha(_canonical_json(payload))
        db.execute(
            """INSERT INTO preview_findings(
                   run_id,row_id,code,severity,blocking,field_code,message,
                   evidence_json,finding_checksum,finding_status
               ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                row_id,
                finding.code,
                finding.severity,
                1 if finding.blocking else 0,
                finding.field_code or None,
                finding.message,
                _canonical_json(finding.evidence),
                checksum,
                finding_status,
            ),
        )
        return checksum

    @staticmethod
    def _append_activity(
        db: sqlite3.Connection,
        session_id: str,
        event_type: str,
        actor: ActorSnapshot,
        correlation_id: str,
        metadata: dict[str, Any],
        occurred_at: int,
    ) -> None:
        forbidden = {"password", "password_hash", "token", "session_token", "path", "payload"}
        if forbidden.intersection(key.casefold() for key in metadata):
            raise WorkspaceError("Sensitive activity metadata is forbidden")
        db.execute(
            """INSERT INTO preview_activity_events(
                   session_id,event_type,actor_id,actor_display_snapshot,
                   actor_role_snapshot,occurred_at,correlation_id,safe_metadata_json
               ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                session_id,
                event_type,
                actor.actor_id,
                actor.display,
                actor.role,
                occurred_at,
                correlation_id,
                _canonical_json(metadata),
            ),
        )

    def preview_summary(self, public_id: str) -> dict[str, Any]:
        path, session = self._find_session(public_id)
        with closing(WorkspaceStore(path).connect(read_only=True)) as db:
            run = db.execute(
                "SELECT * FROM preview_runs WHERE run_id=?",
                (session["active_run_id"],),
            ).fetchone()
            public_run = dict(run) if run else None
            if public_run:
                for key in (
                    "source_sha256", "reference_fingerprint", "freeze_token_hash",
                    "preview_digest",
                ):
                    value = public_run.get(key)
                    public_run[key] = bytes(value).hex() if value is not None else ""
                public_run.pop("session_id", None)
                public_run.pop("source_object_key", None)
            result = {
                "session": self._public_session(session),
                "run": public_run,
                "compatibility_notice": (
                    "Локации сопоставлены через временный compatibility mapping. "
                    "Перед публикацией первоначального baseline потребуется "
                    "подтверждение target warehouse/location."
                ),
                "approval_available": False,
                "baseline_published": False,
                "catalog_validation": "DEFERRED",
            }
            digest = bytes(session.get("preview_digest") or b"").hex()
            candidate_path = self.paths.candidates / f"{digest}.db" if digest else None
            if candidate_path is not None and candidate_path.exists():
                candidate = validate_candidate(candidate_path)
                candidate.pop("path", None)
                candidate["candidate_file"] = candidate_path.name
                result["candidate_rehearsal"] = candidate
            else:
                result["candidate_rehearsal"] = None
            return result

    def build_candidate_rehearsal(
        self, public_id: str, actor: ActorSnapshot, *, correlation_id: str
    ) -> dict[str, Any]:
        if actor.role != "admin":
            raise WarehouseError("Candidate rehearsal требует роль admin")
        path, session = self._find_session(public_id)
        digest = bytes(session.get("preview_digest") or b"").hex()
        if len(digest) != 64:
            raise WarehouseError("Candidate требует завершённый Preview digest")
        secure_directory(self.paths.candidates)
        candidate_path = self.paths.candidates / f"{digest}.db"
        report = build_candidate(
            path,
            session,
            candidate_path,
            actor,
            correlation_id=correlation_id,
        )
        report.pop("path", None)
        report["candidate_file"] = candidate_path.name
        return report

    def preview_rows(
        self, public_id: str, *, limit: int = 100, offset: int = 0, status: str = ""
    ) -> dict[str, Any]:
        path, session = self._find_session(public_id)
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        params: list[Any] = [session["active_run_id"]]
        where = "run_id=?"
        if status:
            if status not in {"VALID", "WARNING", "BLOCKED"}:
                raise WarehouseError("Некорректный row status")
            where += " AND row_status=?"
            params.append(status)
        with closing(WorkspaceStore(path).connect(read_only=True)) as db:
            total = int(db.execute(f"SELECT COUNT(*) FROM preview_rows WHERE {where}", params).fetchone()[0])
            rows = [dict(row) for row in db.execute(
                f"""SELECT row_id,source_row_number,source_row_id,row_status,
                            stock_subject_kind,raw_payload_json,normalized_payload_json
                     FROM preview_rows WHERE {where} ORDER BY row_id LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            )]
        for row in rows:
            row["raw"] = json.loads(row.pop("raw_payload_json"))
            row["normalized"] = json.loads(row.pop("normalized_payload_json"))
        return {"rows": rows, "total": total, "limit": limit, "offset": offset}

    def preview_findings(
        self,
        public_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        severity: str = "",
        blocking: str = "",
    ) -> dict[str, Any]:
        path, session = self._find_session(public_id)
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        params: list[Any] = [session["active_run_id"]]
        where = "f.run_id=?"
        if severity:
            if severity not in {"INFO", "WARNING", "ERROR"}:
                raise WarehouseError("Некорректная severity")
            where += " AND f.severity=?"
            params.append(severity)
        if blocking:
            if blocking not in {"0", "1"}:
                raise WarehouseError("Некорректный blocking filter")
            where += " AND f.blocking=?"
            params.append(int(blocking))
        with closing(WorkspaceStore(path).connect(read_only=True)) as db:
            total = int(db.execute(f"SELECT COUNT(*) FROM preview_findings f WHERE {where}", params).fetchone()[0])
            rows = [dict(row) for row in db.execute(
                f"""SELECT f.finding_id,f.row_id,r.source_row_number,f.code,f.severity,
                            f.blocking,f.field_code,f.message,f.evidence_json,
                            f.finding_status
                     FROM preview_findings f
                     LEFT JOIN preview_rows r ON r.row_id=f.row_id
                     WHERE {where}
                     ORDER BY f.blocking DESC,f.severity DESC,f.finding_id
                     LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            )]
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json"))
        return {"findings": rows, "total": total, "limit": limit, "offset": offset}

    def reject_session(
        self, public_id: str, actor: ActorSnapshot, *, correlation_id: str
    ) -> dict[str, Any]:
        self._require_operator(actor)
        path, session = self._find_session(public_id)
        if session["session_status"] == SessionStatus.REJECTED.value:
            return self._public_session(session)
        now = _now_us()
        with closing(WorkspaceStore(path).connect()) as db:
            if session["active_run_id"]:
                db.execute(
                    """UPDATE preview_runs SET run_status='CANCELLED',session_status='REJECTED',
                           completed_at_us=COALESCE(completed_at_us,?) WHERE run_id=?
                       AND run_status IN ('QUEUED','RUNNING')""",
                    (now, session["active_run_id"]),
                )
            db.execute(
                """UPDATE preview_sessions SET session_status='REJECTED',
                       rejection_reason='USER_CANCELLED',rejected_at=?,
                       rejected_by_actor_id=?,updated_at=? WHERE session_id=?""",
                (now, actor.actor_id, now, session["session_id"]),
            )
            self._append_activity(db, session["session_id"], "SESSION_REJECTED", actor, correlation_id, {"reason": "USER_CANCELLED"}, now)
            db.commit()
            updated = dict(db.execute(
                "SELECT * FROM preview_sessions WHERE session_id=?", (session["session_id"],)
            ).fetchone())
        return self._public_session(updated)

    @staticmethod
    def template() -> bytes:
        return template_bytes()
