"""Administration HTTP routes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from ..service import WarehouseError
from .runtime import RouteRuntime


def handle_get(
    handler: Any,
    runtime: RouteRuntime,
    path: str,
    query: dict[str, list[str]],
) -> bool:
    """Handle Administration reads and exports."""
    if path == "/api/admin":
        if handler._query(query, "section") == "references":
            handler._send_json(
                200, runtime.app_context.warehouse.get_reference_editor()
            )
        else:
            handler._require_admin_session()
            handler._send_json(
                200,
                runtime.app_context.administration.get_administration_overview(),
            )
        return True
    if path == "/export/audit.csv":
        handler._require_admin_session()
        rows = runtime.app_context.administration.list_audit_entries(limit=5000)
        headers = {
            "event_date": "Дата и время",
            "author": "Пользователь",
            "action": "Действие",
            "entity_type": "Раздел",
            "entity_id": "ID",
            "details": "Детали",
        }
        localized = [
            {headers[key]: row.get(key, "") for key in headers} for row in rows
        ]
        handler._send_csv("action_log.csv", localized)
        return True
    return False


def handle_action(
    handler: Any,
    runtime: RouteRuntime,
    action: str,
    data: dict[str, Any],
    response: dict[str, Any],
) -> bool:
    """Handle Administration mutations routed through its facade."""
    administration = runtime.app_context.administration
    if action == "CREATE_RUNTIME_BACKUP":
        response["backup"] = administration.create_runtime_database_backup(
            str(data.get("database_id") or "")
        )
    elif action == "CREATE_BACKUP":
        raise WarehouseError(
            "Выберите конкретную runtime-базу для резервного копирования"
        )
    elif action == "CHECK_DATABASE":
        response["integrity"] = administration.check_integrity()
    elif action == "RESTORE_BACKUP":
        raise WarehouseError(
            "Восстановление временно недоступно: сначала требуется "
            "проверяемая подготовка и одноразовое подтверждение"
        )
    elif action == "CREATE_USER":
        response["user_id"] = administration.create_user(
            data.get("first_name", ""),
            data.get("last_name", ""),
            data.get("position", ""),
            data.get("email", ""),
            data.get("password", ""),
            data.get("role", ""),
        )
    elif action == "CHANGE_PASSWORD":
        administration.change_password(
            data.get("old_password", ""), data.get("new_password", "")
        )
    elif action == "UPDATE_PROFILE":
        response["user"] = administration.update_profile(
            data.get("first_name", ""),
            data.get("last_name", ""),
            data.get("position", ""),
        )
    else:
        return False
    return True


def upload_production_database(
    handler: Any,
    runtime: RouteRuntime,
    *,
    confirmed: bool,
) -> None:
    """Validate and stage an uploaded production database for Administration."""
    temporary: Path | None = None
    try:
        filename = unquote(handler.headers.get("X-Filename", ""))
        if Path(filename).suffix.lower() != ".db":
            raise WarehouseError("Выберите SQLite-файл с расширением .db")
        length = int(handler.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000_000:
            raise WarehouseError("Некорректный размер файла базы")
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".prod_upload_",
            suffix=".db",
            dir=str(runtime.service.db_path.parent),
        )
        temporary = Path(temp_name)
        with os.fdopen(descriptor, "wb") as output:
            remaining = length
            while remaining:
                chunk = handler.rfile.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise WarehouseError("Файл базы загружен не полностью")
                output.write(chunk)
                remaining -= len(chunk)
        result = runtime.app_context.administration.replace_production_database(
            temporary, confirmed=confirmed
        )
        result["uploaded"] = filename
        handler._send_json(200, result)
    except (WarehouseError, OSError, ValueError) as error:
        handler._send_json(400, {"error": str(error)})
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
