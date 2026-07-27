"""HTTP routes for the common vacation planning module."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from ..vacations import VacationError, VacationNotFound
from .runtime import RouteRuntime


def handle_get(
    handler: Any,
    runtime: RouteRuntime,
    path: str,
    query: dict[str, list[str]],
) -> bool:
    vacations = runtime.app_context.vacations
    try:
        if path == "/api/vacations/bootstrap":
            handler._send_json(
                200,
                vacations.bootstrap(
                    handler._query(query, "date_from"),
                    handler._query(query, "date_to"),
                ),
            )
            return True
        if path == "/api/vacations/history":
            handler._send_json(
                200,
                {
                    "history": vacations.history(
                        handler._query_int(
                            query,
                            "limit",
                            default=200,
                            minimum=1,
                            maximum=1_000,
                        )
                    )
                },
            )
            return True
        return False
    except VacationNotFound as error:
        handler._send_json(404, {"error": str(error)})
        return True
    except VacationError as error:
        handler._send_json(400, {"error": str(error)})
        return True
    except sqlite3.DatabaseError:
        handler._send_json(500, {"error": "Не удалось прочитать данные отпусков"})
        return True


def handle_post(handler: Any, runtime: RouteRuntime, path: str) -> bool:
    vacations = runtime.app_context.vacations
    actor = _actor(handler)
    try:
        if path == "/api/vacations/employees":
            employee = vacations.create_employee(
                handler._read_json_object(50_000), actor=actor
            )
            handler._send_json(201, {"ok": True, "employee": employee})
            return True
        if path == "/api/vacations/requests":
            result = vacations.create_request(
                handler._read_json_object(100_000), actor=actor
            )
            handler._send_json(201, {"ok": True, **result})
            return True
        match = re.fullmatch(r"/api/vacations/requests/(\d+)/update", path)
        if match:
            result = vacations.update_request(
                int(match.group(1)),
                handler._read_json_object(100_000),
                actor=actor,
            )
            handler._send_json(200, {"ok": True, **result})
            return True
        match = re.fullmatch(r"/api/vacations/conflicts/(\d+)/resolve", path)
        if match:
            payload = handler._read_json_object(50_000)
            result = vacations.resolve_conflicts(
                int(match.group(1)),
                str(payload.get("decision") or ""),
                str(payload.get("comment") or ""),
                actor=actor,
            )
            handler._send_json(200, {"ok": True, **result})
            return True
        match = re.fullmatch(r"/api/vacations/employees/(\d+)/assignment", path)
        if match:
            result = vacations.change_assignment(
                int(match.group(1)),
                handler._read_json_object(50_000),
                actor=actor,
            )
            handler._send_json(200, {"ok": True, **result})
            return True
        return False
    except VacationNotFound as error:
        handler._send_json(404, {"error": str(error)})
        return True
    except VacationError as error:
        handler._send_json(400, {"error": str(error)})
        return True
    except sqlite3.IntegrityError as error:
        if "vacation_employees.full_name" in str(error):
            message = "Сотрудник с таким ФИО уже существует"
        else:
            message = "Изменение конфликтует с существующими данными"
        handler._send_json(409, {"error": message})
        return True
    except sqlite3.DatabaseError:
        handler._send_json(500, {"error": "Не удалось сохранить данные отпусков"})
        return True


def _actor(handler: Any) -> str:
    selected = str(handler._session_author() or "").strip()
    if selected:
        return selected
    user = handler._current_user_payload()
    return (
        str(user.get("display_name") or "").strip()
        or str(user.get("email") or "").strip()
        or "Пользователь ODE"
    )
