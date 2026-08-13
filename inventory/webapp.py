"""Локальный веб-интерфейс ODE без внешних зависимостей."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from .core.application import ApplicationContext, ensure_application_context
from .core.web_runtime import prepare_web_runtime, validate_runtime_database_contours
from .db import DEFAULT_DB_PATH
from .knowledge import KnowledgeNotFound, KnowledgePermissionError
from .monitoring.facade import MonitoringError
from .routes import RouteRuntime
from .routes import administration as administration_routes
from .routes import knowledge as knowledge_routes
from .routes import monitoring as monitoring_routes
from .routes import reports as reports_routes
from .routes import vacations as vacations_routes, warehouse as warehouse_routes
from .routes.csv import (
    RECEIPT_HEADERS,
    REPORT_HEADERS,
    USER_CSV_TEMPLATES,
    csv_download_bytes,
    localized as _localized,
)
from .service import WarehouseError, WarehouseService
from .templates import PRODUCT_VERSION, build_web_templates
from .warehouse.migration_full_review import (
    full_migration_requested,
    validate_full_migration_database,
)
from .warehouse.migration_pilot_review import (
    migration_pilot_requested,
    validate_migration_pilot_database,
)
from .warehouse.baseline.posting_policy import WarehousePostingBlocked
from .warehouse.baseline.workspace import WorkspaceError
from .warehouse.baseline.xlsx_parser import FullInventoryXlsxError
from .warehouse.sites import (
    DEFAULT_SITE_KEY,
    build_warehouse_site_registry,
    configured_solar_path,
)

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
LOGGER = logging.getLogger(__name__)
# Test and migration contours are resolved before the templates are assembled.
ODE_TEST_MODE = os.environ.get("ODE_TEST_MODE") == "1"
ODE_MIGRATION_PILOT = migration_pilot_requested()
ODE_FULL_MIGRATION_CANDIDATE = full_migration_requested()
LOGIN_HTML, HTML = build_web_templates(
    test_mode=ODE_TEST_MODE,
    migration_pilot=ODE_MIGRATION_PILOT,
    full_migration_candidate=ODE_FULL_MIGRATION_CANDIDATE,
)


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def make_handler(application: WarehouseService | ApplicationContext) -> type[BaseHTTPRequestHandler]:
    app_context = ensure_application_context(application)
    service = app_context.service_adapter()
    settings = (
        app_context.configuration.settings
        if app_context.configuration is not None
        else {}
    )
    selected_solar = (
        configured_solar_path(settings)
        if settings.get("warehouse_sites_enabled")
        else settings.get("solar_db_path")
    )
    validate_runtime_database_contours(
        test_mode=ODE_TEST_MODE,
        db_path=service.db_path,
        solar_db_path=selected_solar,
        vacations_db_path=app_context.vacations.db_path,
        warehouse_contour=(
            app_context.configuration.warehouse_contour
            if app_context.configuration is not None
            else "unknown"
        ),
    )
    migration_full_status = validate_full_migration_database(service.db_path)
    migration_pilot_status = validate_migration_pilot_database(service.db_path)
    database_stat = service.db_path.stat()
    database_fingerprint = migration_full_status.get("database_fingerprint") or (
        f"local:{database_stat.st_dev:x}:{database_stat.st_ino:x}:{service.db_path.name}"
    )
    route_runtime = RouteRuntime(
        app_context=app_context,
        service=service,
        migration_full_status=migration_full_status,
        migration_pilot_status=migration_pilot_status,
        database_fingerprint=str(database_fingerprint),
        warehouse_key=DEFAULT_SITE_KEY,
        warehouse_label="IXcellerate",
    )
    warehouse_sites = build_warehouse_site_registry(app_context, route_runtime)
    sessions: dict[str, dict[str, str]] = {}
    sessions_lock = threading.Lock()
    session_ttl_seconds = 12 * 60 * 60
    max_sessions = 500
    login_attempts: dict[tuple[str, str], dict[str, Any]] = {}
    login_attempts_lock = threading.Lock()
    login_attempt_window_seconds = 5 * 60
    login_block_seconds = 15 * 60
    max_login_failures = 5
    max_login_attempt_keys = 2_000

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                return
            if path.startswith("/static/"):
                self._send_static(path)
                return
            email = self._session_email()
            if not email:
                if path == "/":
                    self._send(200, LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
                else:
                    self._send_json(401, {"error": "Требуется вход"})
                return
            try:
                with app_context.administration.user_context(
                    email,
                    author_name=self._session_author(),
                    role_override=self._session_role_override(),
                ):
                    self._do_GET()
            except WarehouseError as error:
                self._send_json(403, {"error": str(error)})

        def _do_GET(self) -> None:
            parsed = urlparse(self.path)
            path, query = parsed.path, parse_qs(parsed.query)
            try:
                if path == "/":
                    self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/warehouses":
                    selected = self._selected_warehouse_key()
                    self._send_json(
                        200,
                        {
                            "warehouses": warehouse_sites.public(selected),
                            "selected": selected,
                        },
                    )
                elif path.startswith("/static/"):
                    self._send_static(path)
                elif administration_routes.handle_get(
                    self, route_runtime, path, query
                ):
                    return
                elif reports_routes.handle_get(self, route_runtime, path, query):
                    return
                elif monitoring_routes.handle_get(
                    self, route_runtime, path, query
                ):
                    return
                elif knowledge_routes.handle_get(
                    self, route_runtime, path, query
                ):
                    return
                elif vacations_routes.handle_get(self, route_runtime, path, query): return
                else:
                    selected = self._selected_warehouse_site()
                    with warehouse_sites.actor_context(
                        selected,
                        app_context,
                        author_name=self._session_author(),
                        role_override=self._session_role_override(),
                    ):
                        if warehouse_routes.handle_get(
                            self, selected.runtime, path, query
                        ) is not False:
                            return
                    self._send_json(404, {"error": "Страница не найдена"})
            except KnowledgeNotFound as error:
                self._send_json(404, {"error": str(error)})
            except KnowledgePermissionError as error:
                self._send_json(403, {"error": str(error)})
            except (WarehouseError, WorkspaceError, FullInventoryXlsxError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception:
                LOGGER.exception("Unhandled GET error path=%s", path)
                self._send_json(500, {"error": "Внутренняя ошибка сервера"})
        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin and (
                urlparse(origin).netloc != host or not self._host_allowed(host)
            ):
                self._send_json(403, {"error": "Источник запроса не разрешен"})
                return
            if path == "/api/login":
                self._login()
                return
            email = self._session_email()
            if not email:
                self._send_json(401, {"error": "Требуется вход"})
                return
            if path == "/api/warehouse/select":
                try:
                    with app_context.administration.user_context(
                        email,
                        author_name=self._session_author(),
                        role_override=self._session_role_override(),
                    ):
                        self._select_warehouse()
                except (WarehouseError, ValueError, json.JSONDecodeError) as error:
                    self._send_json(400, {"error": str(error)})
                return
            selected = self._selected_warehouse_site()
            selected_runtime = selected.runtime
            migration_pilot_status = selected_runtime.migration_pilot_status
            migration_full_status = selected_runtime.migration_full_status
            if (migration_pilot_status.get("enabled") and path != "/api/logout") or (
                migration_full_status.get("read_only")
                and path != "/api/logout"
            ):
                self._send_json(403, {
                    "error": (
                        "ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА работает только в режиме просмотра"
                        if migration_full_status.get("read_only")
                        else "МИГРАЦИОННЫЙ ПИЛОТ работает только в режиме просмотра"
                    )
                })
                return
            try:
                with app_context.administration.user_context(
                    email,
                    author_name=self._session_author(),
                    role_override=self._session_role_override(),
                ):
                    with warehouse_sites.actor_context(
                        selected,
                        app_context,
                        author_name=self._session_author(),
                        role_override=self._session_role_override(),
                    ):
                        if (
                            path.startswith("/api/full-inventory/")
                            or path == "/api/monitoring/manual-search"
                        ):
                            self._do_POST()
                        else:
                            with service.lock, selected_runtime.service.lock:
                                if path == "/api/logout":
                                    self._logout()
                                else:
                                    self._do_POST()
            except WarehousePostingBlocked as error:
                self._send_json(409, {"error": str(error), "code": error.code})
            except (WorkspaceError, FullInventoryXlsxError) as error:
                self._send_json(400, {"error": str(error), "code": getattr(error, "code", "")})
            except MonitoringError as error:
                self._send_json(400, {"error": str(error)})
            except WarehouseError as error:
                self._send_json(403, {"error": str(error)})
            except Exception:
                self._send_json(500, {"error": "Внутренняя ошибка сервера"})

        def _do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/vacations/") and vacations_routes.handle_post(self, route_runtime, parsed.path): return
            if parsed.path.startswith("/api/knowledge/"):
                knowledge_routes.handle_post(self, route_runtime, parsed.path)
                return
            if monitoring_routes.handle_post(self, route_runtime, parsed.path):
                return
            if warehouse_routes.handle_post(
                self, self._selected_warehouse_site().runtime, parsed
            ) is not False:
                return
            if parsed.path == "/api/preview-csv":
                self._import_csv(
                    self._query(parse_qs(parsed.query), "kind") or "receipt", preview=True
                )
                return
            if parsed.path == "/api/import-csv":
                self._import_csv(self._query(parse_qs(parsed.query), "kind") or "equipment")
                return
            if parsed.path == "/api/preview-xlsx":
                reports_routes.preview_work_log_xlsx(
                    self,
                    route_runtime,
                    self._query(parse_qs(parsed.query), "sheet") or "Логи",
                )
                return
            if parsed.path == "/api/upload-prod-db":
                self._require_admin_session()
                administration_routes.upload_production_database(
                    self,
                    route_runtime,
                    confirmed=self._query(parse_qs(parsed.query), "confirmed") == "1",
                )
                return
            if parsed.path != "/api/action":
                self._send_json(404, {"error": "Страница не найдена"})
                return
            try:
                data = self._read_json_object(1_000_000)
                self._validate_action_payload(data)
                action = data.get("action")
                if action in {
                    "RECEIPT", "ISSUE", "MOVE", "ADD", "STOCK_RECEIPT",
                    "ASSIGN_INVENTORY_NUMBER", "UPDATE_POSITION_CARD", "STOCK_ISSUE",
                    "CONFIRM_SCANNED_RECEIPTS", "CONFIRM_SCANNED_ISSUES",
                    "CONFIRM_SCANNED_ISSUE_PAIRS", "CONFIRM_IMPORT_PREVIEW",
                    "CONFIRM_BULK_ISSUE", "CONFIRM_DELIVERY",
                    "UPDATE_DELIVERY_LINES", "ACCEPT_DELIVERY_SERIAL",
                    "ACCEPT_DELIVERY_BATCH", "CLOSE_DELIVERY",
                    "ADD_REFERENCE", "TOGGLE_REFERENCE", "PROPOSE_REFERENCE",
                    "REFERENCE_RENAME", "REFERENCE_MERGE",
                    "FILL_RECEIPT_FIELDS", "FILL_RECEIPT_DATE",
                    "CORRECT_DUPLICATE_SERIAL", "DELETE_DUPLICATE_RECEIPT",
                }:
                    self._selected_warehouse_site().runtime.app_context.warehouse.assert_posting_allowed(
                        str(action)
                    )
                if action in {
                    "CREATE_BACKUP", "CREATE_RUNTIME_BACKUP",
                    "CHECK_DATABASE", "RESTORE_BACKUP", "CREATE_USER",
                    "CHANGE_PASSWORD", "UPDATE_PROFILE", "REFERENCE_RENAME",
                    "REFERENCE_MERGE_PREVIEW", "REFERENCE_MERGE",
                }:
                    self._require_admin_session(allow_password_change=action == "CHANGE_PASSWORD")
                response: dict[str, Any] = {"ok": True}
                if reports_routes.handle_action(
                    self, route_runtime, str(action), data, response
                ):
                    pass
                elif warehouse_routes.handle_action(
                    self,
                    self._selected_warehouse_site().runtime,
                    str(action),
                    data,
                    response,
                ):
                    pass
                elif administration_routes.handle_action(
                    self, route_runtime, str(action), data, response
                ):
                    pass
                else:
                    raise WarehouseError("Неизвестная операция")
                self._send_json(200, response)
            except WarehousePostingBlocked as error:
                self._send_json(409, {"error": str(error), "code": error.code})
            except (WarehouseError, ValueError, KeyError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception:
                self._send_json(500, {"error": "Внутренняя ошибка сервера"})

        def _knowledge_POST(self, path: str) -> None:
            knowledge_routes.handle_post(self, route_runtime, path)

        def do_PUT(self) -> None:  # noqa: N802
            self._knowledge_mutation("PUT")

        def do_DELETE(self) -> None:  # noqa: N802
            self._knowledge_mutation("DELETE")

        def _knowledge_mutation(self, method: str) -> None:
            knowledge_routes.mutate(self, route_runtime, method)

        def _import_csv(self, kind: str, preview: bool = False) -> None:
            warehouse_routes.import_csv(
                self,
                self._selected_warehouse_site().runtime,
                kind=kind,
                preview=preview,
            )

        def _login(self) -> None:
            try:
                data = self._read_json_object(100_000)
                for field in ("mode", "email", "password", "full_name"):
                    if field in data and not isinstance(data[field], str):
                        raise WarehouseError(f"Поле {field} должно быть строкой")
                mode = data.get("mode", "")
                if mode not in {"admin", "engineer"}:
                    raise WarehouseError("Неизвестный режим входа")
                if mode == "admin":
                    email = data.get("email", "")
                    rate_key = self._login_rate_key(email)
                    if self._login_rate_limited(rate_key):
                        self._send_json(429, {
                            "error": "Слишком много неудачных попыток входа. Повторите позже."
                        })
                        return
                    try:
                        if (
                            migration_pilot_status.get("enabled")
                            or migration_full_status.get("read_only")
                        ):
                            user = app_context.administration.authenticate(
                                email,
                                data.get("password", ""),
                                record_login=False,
                            )
                        else:
                            user = app_context.administration.authenticate(
                                email, data.get("password", "")
                            )
                    except WarehouseError:
                        if self._record_login_failure(rate_key):
                            self._send_json(429, {
                                "error": "Слишком много неудачных попыток входа. Повторите позже."
                            })
                            return
                        raise
                    self._clear_login_failures(rate_key)
                    session = {
                        "email": str(user["email"]),
                        "author": "",
                        "mode": "admin",
                        "warehouse": DEFAULT_SITE_KEY,
                    }
                else:
                    full_name = " ".join(str(data.get("full_name", "")).split())
                    if len(full_name) < 3:
                        raise WarehouseError("Укажите ФИО инженера")
                    user = app_context.administration.get_user("lokolis")
                    session = {
                        "email": "lokolis",
                        "author": full_name,
                        "mode": "engineer",
                        "warehouse": DEFAULT_SITE_KEY,
                    }
                    user = {
                        **user,
                        "display_name": full_name,
                        "position": "Дежурный инженер",
                        "role": "engineer",
                        "must_change_password": 0,
                    }
                token = secrets.token_urlsafe(32)
                session["last_seen"] = str(time.monotonic())
                with sessions_lock:
                    self._purge_sessions_locked()
                    while len(sessions) >= max_sessions:
                        sessions.pop(next(iter(sessions)), None)
                    sessions[token] = session
                LOGGER.info(
                    "Login succeeded mode=%s user_id=%s",
                    mode,
                    user.get("id"),
                )
                self._pending_cookie = (
                    f"ode_session={token}; Path=/; HttpOnly; SameSite=Strict"
                )
                self._send_json(200, {"ok": True, "user": user})
            except (WarehouseError, ValueError, json.JSONDecodeError) as error:
                self._send_json(401, {"error": str(error)})

        def _logout(self) -> None:
            token = self._session_token()
            with sessions_lock:
                session = sessions.pop(token, None)
            LOGGER.info(
                "Logout completed mode=%s",
                (session or {}).get("mode", "unknown"),
            )
            self._pending_cookie = (
                "ode_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            )
            self._send_json(200, {"ok": True})

        def _session_token(self) -> str:
            cookie = SimpleCookie()
            try:
                cookie.load(getattr(self, "headers", {}).get("Cookie", ""))
                return cookie["ode_session"].value if "ode_session" in cookie else ""
            except CookieError:
                return ""

        def _session_email(self) -> str:
            return self._session_data().get("email", "")

        def _session_author(self) -> str:
            return self._session_data().get("author", "")

        def _session_role_override(self) -> str | None:
            return "engineer" if self._session_data().get("mode") == "engineer" else None

        def _selected_warehouse_key(self) -> str:
            return warehouse_sites.selected_key(self._session_data())

        def _selected_warehouse_site(self):
            return warehouse_sites.get(self._selected_warehouse_key())

        def _select_warehouse(self) -> None:
            data = self._read_json_object(10_000)
            selected = warehouse_sites.select_session(
                sessions, sessions_lock, token=self._session_token(),
                requested=str(data.get("warehouse") or ""),
                last_seen=str(time.monotonic()), purge=self._purge_sessions_locked,
            )
            self._send_json(200, {"ok": True, "selected": selected.key,
                                  "warehouse": selected.public(selected=True)})

        def _current_user_payload(self) -> dict[str, Any]:
            current_user = app_context.administration.current_user()
            selected_name = self._session_author().strip()
            if selected_name:
                parts = selected_name.split(maxsplit=1)
                current_user = {
                    **current_user,
                    "first_name": parts[1] if len(parts) > 1 else "",
                    "last_name": parts[0],
                    "display_name": selected_name,
                    "position": "Дежурный инженер",
                    "role": "engineer",
                    "must_change_password": 0,
                }
            else:
                current_user = {
                    **current_user,
                    "display_name": " ".join(
                        part for part in (
                            str(current_user.get("last_name") or "").strip(),
                            str(current_user.get("first_name") or "").strip(),
                        ) if part
                    ),
                }
            return current_user

        def _full_inventory_actor(self):
            warehouse_context = self._selected_warehouse_site().runtime.app_context
            return warehouse_context.full_inventory.actor_snapshot(
                app_context.administration.current_user(),
                display_override=self._session_author(),
            )

        def _correlation_id(self) -> str:
            supplied = self.headers.get("X-Correlation-ID", "").strip()
            if 16 <= len(supplied) <= 200 and re.fullmatch(r"[A-Za-z0-9._:-]+", supplied):
                return supplied
            return "corr_" + secrets.token_hex(16)

        def _require_admin_session(self, *, allow_password_change: bool = False) -> None:
            if self._session_data().get("mode") != "admin":
                raise WarehouseError("Откройте отдельный режим администратора")
            user = app_context.administration.current_user()
            if user.get("must_change_password") and not allow_password_change:
                raise WarehouseError("Сначала смените начальный пароль администратора")

        def _session_data(self) -> dict[str, str]:
            token = self._session_token()
            if not token:
                return {}
            with sessions_lock:
                self._purge_sessions_locked()
                session = sessions.get(token)
                if session is None:
                    return {}
                session["last_seen"] = str(time.monotonic())
                return dict(session)

        @staticmethod
        def _purge_sessions_locked() -> None:
            cutoff = time.monotonic() - session_ttl_seconds
            expired = [
                token for token, session in sessions.items()
                if float(session.get("last_seen", "0") or 0) < cutoff
            ]
            for token in expired:
                sessions.pop(token, None)

        def _login_rate_key(self, email: str) -> tuple[str, str]:
            address = getattr(self, "client_address", ("", 0))
            client = str(address[0]) if isinstance(address, tuple) and address else ""
            return client or "unknown", email.strip().casefold()

        @staticmethod
        def _login_rate_limited(key: tuple[str, str]) -> bool:
            now = time.monotonic()
            with login_attempts_lock:
                Handler._purge_login_attempts_locked(now)
                attempt = login_attempts.get(key)
                return bool(attempt and float(attempt.get("blocked_until", 0)) > now)

        @staticmethod
        def _record_login_failure(key: tuple[str, str]) -> bool:
            now = time.monotonic()
            with login_attempts_lock:
                Handler._purge_login_attempts_locked(now)
                previous = login_attempts.get(key, {})
                cutoff = now - login_attempt_window_seconds
                failures = [
                    float(value) for value in previous.get("failures", [])
                    if float(value) >= cutoff
                ]
                failures.append(now)
                blocked_until = float(previous.get("blocked_until", 0) or 0)
                if len(failures) >= max_login_failures:
                    blocked_until = max(blocked_until, now + login_block_seconds)
                login_attempts.pop(key, None)
                login_attempts[key] = {
                    "failures": failures,
                    "blocked_until": blocked_until,
                    "last_seen": now,
                }
                while len(login_attempts) > max_login_attempt_keys:
                    login_attempts.pop(next(iter(login_attempts)), None)
                return blocked_until > now

        @staticmethod
        def _clear_login_failures(key: tuple[str, str]) -> None:
            with login_attempts_lock:
                login_attempts.pop(key, None)

        @staticmethod
        def _purge_login_attempts_locked(now: float) -> None:
            cutoff = now - login_attempt_window_seconds
            stale = [
                key for key, attempt in login_attempts.items()
                if float(attempt.get("blocked_until", 0) or 0) <= now
                and float(attempt.get("last_seen", 0) or 0) < cutoff
            ]
            for key in stale:
                login_attempts.pop(key, None)

        @staticmethod
        def _host_allowed(host: str) -> bool:
            configured = {
                value.strip().casefold()
                for value in os.environ.get("ODE_ALLOWED_HOSTS", "").split(",")
                if value.strip()
            }
            hostname = urlparse("//" + host).hostname or ""
            if hostname.casefold() in {"localhost", *configured}:
                return True
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                return False
            return address.is_loopback or address.is_private

        @staticmethod
        def _query(query: dict[str, list[str]], name: str) -> str:
            return query.get(name, [""])[0]

        @classmethod
        def _query_int(
            cls,
            query: dict[str, list[str]],
            name: str,
            *,
            default: int | None = None,
            minimum: int | None = None,
            maximum: int | None = None,
        ) -> int:
            raw = cls._query(query, name)
            if not raw:
                if default is None:
                    raise WarehouseError(f"Укажите параметр {name}")
                value = default
            else:
                try:
                    value = int(raw)
                except ValueError as error:
                    raise WarehouseError(f"Параметр {name} должен быть целым числом") from error
            if minimum is not None and value < minimum:
                raise WarehouseError(f"Параметр {name} должен быть не меньше {minimum}")
            if maximum is not None and value > maximum:
                raise WarehouseError(f"Параметр {name} должен быть не больше {maximum}")
            return value

        @staticmethod
        def _query_int_value(raw: Any, name: str, *, minimum: int = 1) -> int:
            try:
                value = int(raw)
            except (TypeError, ValueError) as error:
                raise WarehouseError(f"Параметр {name} должен быть целым числом") from error
            if value < minimum:
                raise WarehouseError(f"Параметр {name} должен быть не меньше {minimum}")
            return value


        def _read_json_object(self, maximum_size: int) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise WarehouseError("Некорректный размер запроса") from error
            if length <= 0 or length > maximum_size:
                raise WarehouseError("Некорректный размер запроса")
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeError) as error:
                raise WarehouseError("Тело запроса должно содержать корректный JSON") from error
            if not isinstance(data, dict):
                raise WarehouseError("JSON-запрос должен быть объектом")
            return data

        @staticmethod
        def _optional_json_int(data: dict[str, Any], name: str) -> int | None:
            value = data.get(name)
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError) as error:
                raise WarehouseError(f"Поле {name} должно быть целым числом") from error

        @staticmethod
        def _validate_action_payload(data: dict[str, Any]) -> None:
            action = data.get("action")
            if not isinstance(action, str) or not action:
                raise WarehouseError("Поле action должно быть непустой строкой")
            collection_fields: dict[str, dict[str, type]] = {
                "WORK_LOG": {"pnr_checklist": list},
                "ASSIGN_SECTION": {"ids": list},
                "UPDATE_WORK_LOG": {"pnr_checklist": list},
                "WORK_LOGS": {"rows": list},
                "CONFIRM_SCANNED_RECEIPTS": {"common_fields": dict, "serial_numbers": list},
                "CONFIRM_SCANNED_ISSUES": {"common_fields": dict, "serial_numbers": list},
                "CONFIRM_SCANNED_ISSUE_PAIRS": {"common_fields": dict, "pairs": list},
                "UPDATE_DELIVERY_LINES": {"line_ids": list, "values": dict},
                "ACCEPT_DELIVERY_SERIAL": {"values": dict},
                "ACCEPT_DELIVERY_BATCH": {"line_ids": list, "common_values": dict},
                "UPDATE_POSITION_CARD": {"fields": dict},
                "FILL_RECEIPT_FIELDS": {"values": dict},
            }
            allowed = collection_fields.get(action, {})
            numeric_fields = {
                "equipment_id", "quantity", "delivery_id", "reference_id",
                "source_id", "target_id", "id", "receipt_id",
            }
            boolean_fields = {"only_empty", "unplanned", "is_active", "confirmed"}
            for key, value in data.items():
                if key == "action":
                    continue
                if key in allowed:
                    if not isinstance(value, allowed[key]):
                        raise WarehouseError(f"Поле {key} имеет неверный тип")
                    Handler._validate_action_collection(value, key)
                elif key in numeric_fields:
                    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                        raise WarehouseError(f"Поле {key} должно быть числом")
                elif key in boolean_fields:
                    Handler._json_boolean(value, key)
                elif not isinstance(value, str):
                    raise WarehouseError(f"Поле {key} должно быть строкой")

        @staticmethod
        def _validate_action_collection(value: Any, field: str) -> None:
            if field in {"rows", "pairs"}:
                if any(not isinstance(item, dict) for item in value):
                    raise WarehouseError("Поле rows должно быть списком объектов")
                mappings = value
            elif field == "serial_numbers":
                if any(not isinstance(item, str) for item in value):
                    raise WarehouseError("Поле serial_numbers должно быть списком строк")
                return
            elif field == "pnr_checklist":
                if any(not isinstance(item, str) for item in value):
                    raise WarehouseError("Поле pnr_checklist должно быть списком строк")
                return
            elif field in {"line_ids", "ids"}:
                if any(
                    isinstance(item, bool) or not isinstance(item, (str, int))
                    for item in value
                ):
                    raise WarehouseError(f"Поле {field} должно быть списком идентификаторов")
                return
            else:
                mappings = [value]
            for mapping in mappings:
                for key, item in mapping.items():
                    if not isinstance(key, str) or item is None or isinstance(item, (dict, list)):
                        raise WarehouseError(f"Поле {field} содержит неверный тип значения")
                    if not isinstance(item, (str, int, float, bool)):
                        raise WarehouseError(f"Поле {field} содержит неверный тип значения")

        @staticmethod
        def _json_boolean(value: Any, field: str) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().casefold()
                if normalized in {"1", "true", "yes", "on"}:
                    return True
                if normalized in {"", "0", "false", "no", "off"}:
                    return False
            raise WarehouseError(f"Поле {field} должно быть логическим значением")

        def _balance_filters(self, query: dict[str, list[str]]) -> dict[str, str]:
            return {
                name: self._query(query, name)
                for name in (
                    "query", "project", "object_name", "equipment_type", "component_type",
                    "cable_type", "unit", "datacenter", "category", "item_type",
                    "supplier", "vendor", "stock_state", "sort_by", "sort_dir",
                )
            }

        def _send_template(self, filename: str, text: str) -> None:
            self._send_download(filename, ("\ufeff" + text).encode("utf-8"))

        def _send_knowledge_attachment(self, attachment_id: int) -> None:
            knowledge_routes.send_attachment(
                self, route_runtime, attachment_id
            )

        def _send_json(self, status: int, data: Any) -> None:
            self._send(status, _json_bytes(data), "application/json; charset=utf-8")

        def _send_csv(
            self,
            filename: str,
            rows: list[dict[str, Any]],
            *,
            delimiter: str = ";",
            fieldnames: list[str] | None = None,
        ) -> None:
            self._send_download(
                filename,
                csv_download_bytes(rows, delimiter, fieldnames=fieldnames),
            )

        def _send_download(self, filename: str, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _send_binary_download(
            self, filename: str, body: bytes, content_type: str
        ) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _send_static(self, path: str) -> None:
            relative = Path(unquote(path.removeprefix("/static/")))
            if relative.is_absolute() or ".." in relative.parts:
                self._send_json(404, {"error": "Файл не найден"})
                return
            target = STATIC_ROOT / relative
            if not target.is_file():
                self._send_json(404, {"error": "Файл не найден"})
                return
            content_types = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
            }
            self._send(
                200,
                target.read_bytes(),
                content_types.get(target.suffix.lower(), "application/octet-stream"),
            )

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            if cookie := getattr(self, "_pending_cookie", ""):
                self.send_header("Set-Cookie", cookie)
                self._pending_cookie = ""
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ODE — учет работ и склада")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="путь к файлу SQLite")
    parser.add_argument("--solar-db", default=None, help="отдельный путь Solar DB; с --db включает Multi-Warehouse")
    parser.add_argument("--vacations-db", default=None, help="отдельная БД отпусков")
    parser.add_argument("--host", default="127.0.0.1", help="адрес локального сервера")
    parser.add_argument("--port", type=int, default=8765, help="порт локального сервера")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    parser.add_argument(
        "--warehouse-contour",
        choices=("production", "demo"),
        default="production",
        help="production использует рабочий предварительный баланс; demo разрешён только на отдельной БД",
    )
    parser.add_argument(
        "--inventory-state-root",
        default=None,
        help="внешний application state root для FULL inventory Preview",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        runtime = prepare_web_runtime(
            db_path=args.db,
            solar_db_path=args.solar_db,
            vacations_db_path=args.vacations_db,
            warehouse_contour=args.warehouse_contour,
            inventory_state_root=args.inventory_state_root,
            test_mode=ODE_TEST_MODE,
        )
    except RuntimeError as error:
        parser.error(str(error))
    try:
        handler_type = make_handler(runtime.app_context)
        print(runtime.contour_label)
        print(f"Path: {runtime.service.db_path.resolve()}")
        if runtime.solar_path is not None:
            print(f"Solar path: {runtime.solar_path}")
        print(f"ODE version: {PRODUCT_VERSION}")
        print(f"Cards: {runtime.cards}")
        print(f"Integrity: {runtime.integrity_status}")
        server = ThreadingHTTPServer((args.host, args.port), handler_type)
        url = f"http://{args.host}:{server.server_port}"
        print(f"Интерфейс открыт: {url}")
        print("Для завершения нажмите Ctrl+C.")
        if not args.no_browser:
            threading.Timer(0.35, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nРабота завершена.")
        finally:
            server.server_close()
        return 0
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
