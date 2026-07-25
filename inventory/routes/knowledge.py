"""Knowledge Base HTTP routes."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from ..knowledge import KnowledgeError, KnowledgeNotFound, KnowledgePermissionError
from .runtime import RouteRuntime


def handle_get(
    handler: Any,
    runtime: RouteRuntime,
    path: str,
    query: dict[str, list[str]],
) -> bool:
    """Handle Knowledge Base reads and attachment downloads."""
    knowledge = runtime.app_context.knowledge
    if path == "/api/knowledge/articles":
        handler._send_json(200, knowledge.list_articles(
            handler._query(query, "category"),
            query=handler._query(query, "query"),
            tag=handler._query(query, "tag"),
            page=handler._query_int(
                query, "page", default=1, minimum=1, maximum=1_000_000
            ),
            page_size=handler._query_int(
                query, "page_size", default=20, minimum=1, maximum=100
            ),
        ))
        return True
    match = re.fullmatch(r"/api/knowledge/articles/(\d+)", path)
    if match:
        handler._send_json(
            200, {"article": knowledge.get_article(int(match.group(1)))}
        )
        return True
    match = re.fullmatch(r"/api/knowledge/attachments/(\d+)", path)
    if match:
        send_attachment(handler, runtime, int(match.group(1)))
        return True
    return False


def handle_post(handler: Any, runtime: RouteRuntime, path: str) -> None:
    """Create Knowledge Base articles and attachments."""
    knowledge = runtime.app_context.knowledge
    try:
        if path == "/api/knowledge/articles":
            article = knowledge.create_article(handler._read_json_object(300_000))
            handler._send_json(201, {"ok": True, "article": article})
            return
        match = re.fullmatch(r"/api/knowledge/articles/(\d+)/attachments", path)
        if match:
            try:
                length = int(handler.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise KnowledgeError("Некорректный размер файла") from error
            if length <= 0 or length > knowledge.MAX_ATTACHMENT_BYTES:
                maximum = knowledge.MAX_ATTACHMENT_BYTES // 1024 // 1024
                raise KnowledgeError(
                    f"Размер файла должен быть от 1 байта до {maximum} МБ"
                )
            attachment = knowledge.add_attachment(
                int(match.group(1)),
                unquote(handler.headers.get("X-Filename", "")),
                handler.headers.get(
                    "Content-Type", "application/octet-stream"
                ),
                handler.rfile.read(length),
            )
            handler._send_json(201, {"ok": True, "attachment": attachment})
            return
        handler._send_json(404, {"error": "Страница не найдена"})
    except KnowledgeNotFound as error:
        handler._send_json(404, {"error": str(error)})
    except KnowledgePermissionError as error:
        handler._send_json(403, {"error": str(error)})
    except KnowledgeError as error:
        handler._send_json(400, {"error": str(error)})
    except (OSError, sqlite3.DatabaseError):
        handler._send_json(
            500, {"error": "Не удалось сохранить данные базы знаний"}
        )


def mutate(handler: Any, runtime: RouteRuntime, method: str) -> None:
    """Update or delete one Knowledge Base article."""
    path = urlparse(handler.path).path
    origin = handler.headers.get("Origin", "")
    host = handler.headers.get("Host", "")
    if origin and (
        urlparse(origin).netloc != host or not handler._host_allowed(host)
    ):
        handler._send_json(403, {"error": "Источник запроса не разрешен"})
        return
    if not handler._session_email():
        handler._send_json(401, {"error": "Требуется вход"})
        return
    if (
        runtime.migration_pilot_status.get("enabled")
        or runtime.migration_full_status.get("read_only")
    ):
        handler._send_json(
            403, {"error": "База работает только в режиме просмотра"}
        )
        return
    match = re.fullmatch(r"/api/knowledge/articles/(\d+)", path)
    if match is None:
        handler._send_json(404, {"error": "Страница не найдена"})
        return
    context = runtime.app_context
    try:
        with context.administration.user_context(
            handler._session_email(),
            author_name=handler._session_author(),
            role_override=handler._session_role_override(),
        ), runtime.service.lock:
            article_id = int(match.group(1))
            if method == "PUT":
                article = context.knowledge.update_article(
                    article_id, handler._read_json_object(300_000)
                )
                handler._send_json(200, {"ok": True, "article": article})
            else:
                context.knowledge.delete_article(article_id)
                handler._send_json(200, {"ok": True})
    except KnowledgeNotFound as error:
        handler._send_json(404, {"error": str(error)})
    except KnowledgePermissionError as error:
        handler._send_json(403, {"error": str(error)})
    except KnowledgeError as error:
        handler._send_json(400, {"error": str(error)})
    except sqlite3.DatabaseError:
        handler._send_json(
            500, {"error": "Не удалось сохранить данные базы знаний"}
        )


def send_attachment(
    handler: Any,
    runtime: RouteRuntime,
    attachment_id: int,
) -> None:
    """Stream one validated Knowledge Base attachment."""
    path, record = runtime.app_context.knowledge.attachment_download(
        attachment_id
    )
    body = path.read_bytes()
    original_name = str(record["original_name"])
    fallback = "attachment" + Path(original_name).suffix.casefold()
    handler.send_response(200)
    handler.send_header("Content-Type", str(record["content_type"]))
    handler.send_header(
        "Content-Disposition",
        f"attachment; filename=\"{fallback}\"; filename*=UTF-8''"
        f"{quote(original_name, safe='')}",
    )
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.end_headers()
    handler.wfile.write(body)
