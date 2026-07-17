"""Public knowledge base facade with validation and secure file handling."""

from __future__ import annotations

import re
import sqlite3
import io
import os
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from inventory.shared.helpers import WarehouseError

from .markdown import render_markdown
from .models import CATEGORY_LABELS
from .repository import KnowledgeRepository


class KnowledgeError(WarehouseError):
    """A user-facing knowledge base error."""


class KnowledgeNotFound(KnowledgeError):
    """Requested article or attachment does not exist."""


class KnowledgePermissionError(KnowledgeError):
    """The authenticated user cannot modify the knowledge base."""


class KnowledgeFacade:
    MAX_TITLE_LENGTH = 200
    MAX_SUMMARY_LENGTH = 1_000
    MAX_CONTENT_LENGTH = 250_000
    MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
    MAX_TAGS = 10
    MAX_TAG_LENGTH = 40
    ALLOWED_TYPES = {
        ".pdf": {"application/pdf"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        ".txt": {"text/plain"},
        ".png": {"image/png"},
        ".jpg": {"image/jpeg"},
        ".jpeg": {"image/jpeg"},
    }

    def __init__(self, service: Any, *, upload_root: str | Path | None = None):
        self.service = service
        self.db_path = Path(service.db_path)
        self.repository = KnowledgeRepository(self.db_path)
        configured_root = upload_root or os.environ.get("ODE_KNOWLEDGE_UPLOAD_DIR")
        self.upload_root = Path(configured_root) if configured_root else self.db_path.parent / "uploads"
        configured_mb = os.environ.get("ODE_KNOWLEDGE_MAX_ATTACHMENT_MB", "15")
        try:
            attachment_mb = min(max(int(configured_mb), 1), 50)
        except ValueError:
            attachment_mb = 15
        self.MAX_ATTACHMENT_BYTES = attachment_mb * 1024 * 1024

    @staticmethod
    def category_label(category: str) -> str:
        return CATEGORY_LABELS[category]

    @staticmethod
    def _category(value: Any) -> str:
        category = str(value or "").strip().casefold()
        if category not in CATEGORY_LABELS:
            raise KnowledgeError("Выберите корректную категорию: Инструкции или Спецификации")
        return category

    @staticmethod
    def _text(value: Any, label: str, maximum: int, *, required: bool = True) -> str:
        if not isinstance(value, str):
            raise KnowledgeError(f"Поле «{label}» должно содержать текст")
        result = value.strip()
        if required and not result:
            raise KnowledgeError(f"Поле «{label}» не может быть пустым")
        if len(result) > maximum:
            raise KnowledgeError(f"Поле «{label}» не должно превышать {maximum} символов")
        return result

    def _editor(self) -> tuple[int | None, str]:
        user = self.service.current_user()
        if str(user.get("role") or "") not in {"admin", "engineer"}:
            raise KnowledgePermissionError("Недостаточно прав для изменения базы знаний")
        author_id = int(user["id"]) if user.get("id") is not None else None
        actor_name = ""
        actor_context = getattr(self.service, "_actor_name", None)
        if actor_context is not None:
            actor_name = str(actor_context.get() or "").strip()
        if not actor_name:
            actor_name = " ".join(
                part for part in (str(user.get("last_name") or "").strip(), str(user.get("first_name") or "").strip()) if part
            )
        return author_id, actor_name or str(user.get("email") or "Пользователь")

    @classmethod
    def _tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, list) else str(value).split(",")
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            tag = re.sub(r"\s+", " ", str(raw or "").strip())
            if not tag:
                continue
            if len(tag) > cls.MAX_TAG_LENGTH:
                raise KnowledgeError(
                    f"Тег не должен превышать {cls.MAX_TAG_LENGTH} символов"
                )
            key = tag.casefold()
            if key not in seen:
                seen.add(key)
                result.append(tag)
        if len(result) > cls.MAX_TAGS:
            raise KnowledgeError(f"У статьи может быть не более {cls.MAX_TAGS} тегов")
        return result

    def list_articles(
        self,
        category: str,
        *,
        query: str = "",
        tag: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        normalized = self._category(category)
        clean_query = re.sub(r"\s+", " ", str(query or "").strip())[:200]
        clean_tag = re.sub(r"\s+", " ", str(tag or "").strip())[: self.MAX_TAG_LENGTH]
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 100)
        articles, total = self.repository.list_articles(
            normalized,
            query=clean_query,
            tag=clean_tag,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {
            "articles": [article.as_dict() for article in articles],
            "category": normalized,
            "query": clean_query,
            "tag": clean_tag,
            "tags": self.repository.list_tags(normalized),
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    def get_article(self, article_id: int) -> dict[str, Any]:
        if article_id < 1:
            raise KnowledgeNotFound("Статья не найдена")
        article = self.repository.get_article(article_id)
        if article is None:
            raise KnowledgeNotFound("Статья не найдена")
        result = article.as_dict(include_content=True)
        result["content_html"] = render_markdown(article.content)
        result["attachments"] = [item.as_dict() for item in self.repository.list_attachments(article_id)]
        return result

    def create_article(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise KnowledgeError("Данные статьи должны быть объектом")
        title = self._text(data.get("title"), "Название статьи", self.MAX_TITLE_LENGTH)
        summary = self._text(
            data.get("summary", ""), "Краткое описание", self.MAX_SUMMARY_LENGTH, required=False
        )
        content = self._text(data.get("content"), "Основной текст", self.MAX_CONTENT_LENGTH)
        category = self._category(data.get("category"))
        tags = self._tags(data.get("tags", []))
        author_id, author_name = self._editor()
        try:
            article_id = self.repository.create_article(
                title=title,
                summary=summary,
                content=content,
                category=category,
                tags=tags,
                author_id=author_id,
                author_name=author_name,
            )
        except sqlite3.DatabaseError as error:
            raise KnowledgeError("Не удалось сохранить статью в базе данных") from error
        return self.get_article(article_id)

    def update_article(self, article_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if article_id < 1 or self.repository.get_article(article_id) is None:
            raise KnowledgeNotFound("Статья не найдена")
        if not isinstance(data, dict):
            raise KnowledgeError("Данные статьи должны быть объектом")
        title = self._text(data.get("title"), "Название статьи", self.MAX_TITLE_LENGTH)
        summary = self._text(
            data.get("summary", ""), "Краткое описание", self.MAX_SUMMARY_LENGTH,
            required=False,
        )
        content = self._text(data.get("content"), "Основной текст", self.MAX_CONTENT_LENGTH)
        category = self._category(data.get("category"))
        tags = self._tags(data.get("tags", []))
        _, author_name = self._editor()
        try:
            updated = self.repository.update_article(
                article_id,
                title=title,
                summary=summary,
                content=content,
                category=category,
                tags=tags,
                author_name=author_name,
            )
        except sqlite3.DatabaseError as error:
            raise KnowledgeError("Не удалось обновить статью в базе данных") from error
        if not updated:
            raise KnowledgeNotFound("Статья не найдена")
        return self.get_article(article_id)

    def delete_article(self, article_id: int) -> None:
        if article_id < 1:
            raise KnowledgeNotFound("Статья не найдена")
        _, author_name = self._editor()
        try:
            deleted = self.repository.soft_delete_article(article_id, author_name=author_name)
        except sqlite3.DatabaseError as error:
            raise KnowledgeError("Не удалось удалить статью") from error
        if not deleted:
            raise KnowledgeNotFound("Статья не найдена")

    @classmethod
    def _safe_original_name(cls, value: str) -> tuple[str, str]:
        raw = str(value or "").strip().replace("\\", "/")
        parts = raw.split("/")
        if not raw or any(part in {".", ".."} for part in parts):
            raise KnowledgeError("Некорректное имя файла")
        name = parts[-1].strip()
        name = re.sub(r"[^\w.()\[\] -]+", "_", name, flags=re.UNICODE)
        name = re.sub(r"\s+", " ", name).strip(" .")[:180]
        suffix = Path(name).suffix.casefold()
        if not name or suffix not in cls.ALLOWED_TYPES:
            allowed = ", ".join(sorted(cls.ALLOWED_TYPES))
            raise KnowledgeError(f"Разрешены только файлы: {allowed}")
        return name, suffix

    @classmethod
    def _validate_content(cls, suffix: str, content_type: str, payload: bytes) -> str:
        size = len(payload)
        if size <= 0:
            raise KnowledgeError("Нельзя прикрепить пустой файл")
        if size > cls.MAX_ATTACHMENT_BYTES:
            raise KnowledgeError("Размер файла превышает 15 МБ")
        mime = str(content_type or "application/octet-stream").split(";", 1)[0].strip().casefold()
        if mime not in cls.ALLOWED_TYPES[suffix] | {"application/octet-stream"}:
            raise KnowledgeError("Тип файла не соответствует его расширению")
        if payload.startswith(b"MZ"):
            raise KnowledgeError("Исполняемые файлы запрещены")
        signatures = {
            ".pdf": (b"%PDF-",),
            ".docx": (b"PK\x03\x04",),
            ".xlsx": (b"PK\x03\x04",),
            ".png": (b"\x89PNG\r\n\x1a\n",),
            ".jpg": (b"\xff\xd8\xff",),
            ".jpeg": (b"\xff\xd8\xff",),
        }
        if suffix in signatures and not any(payload.startswith(signature) for signature in signatures[suffix]):
            raise KnowledgeError("Содержимое файла не соответствует его расширению")
        if suffix in {".docx", ".xlsx"}:
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    names = set(archive.namelist())
            except (OSError, zipfile.BadZipFile) as error:
                raise KnowledgeError("Поврежденный файл Office Open XML") from error
            expected = "word/" if suffix == ".docx" else "xl/"
            if "[Content_Types].xml" not in names or not any(
                name.startswith(expected) for name in names
            ):
                raise KnowledgeError("Содержимое файла не соответствует его расширению")
        return next(iter(cls.ALLOWED_TYPES[suffix])) if mime == "application/octet-stream" else mime

    def add_attachment(
        self,
        article_id: int,
        original_name: str,
        content_type: str,
        payload: bytes,
    ) -> dict[str, Any]:
        if self.repository.get_article(article_id) is None:
            raise KnowledgeNotFound("Статья не найдена")
        author_id, author_name = self._editor()
        safe_name, suffix = self._safe_original_name(original_name)
        mime = self._validate_content(suffix, content_type, payload)
        stored_name = uuid4().hex + suffix
        relative_path = Path("knowledge") / stored_name
        root = self.upload_root.resolve()
        target = (root / relative_path).resolve()
        if root != target and root not in target.parents:
            raise KnowledgeError("Некорректный путь файла")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(payload)
            attachment_id = self.repository.add_attachment(
                article_id=article_id,
                original_name=safe_name,
                stored_name=stored_name,
                relative_path=relative_path.as_posix(),
                content_type=mime,
                size_bytes=len(payload),
                author_id=author_id,
                author_name=author_name,
            )
        except FileExistsError as error:
            raise KnowledgeError("Не удалось создать уникальное имя файла") from error
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return next(
            item.as_dict()
            for item in self.repository.list_attachments(article_id)
            if item.id == attachment_id
        )

    def attachment_download(self, attachment_id: int) -> tuple[Path, dict[str, Any]]:
        record = self.repository.get_attachment_record(attachment_id)
        if record is None:
            raise KnowledgeNotFound("Файл не найден")
        root = self.upload_root.resolve()
        target = (root / str(record["relative_path"])).resolve()
        if root != target and root not in target.parents:
            raise KnowledgeNotFound("Файл не найден")
        if not target.is_file():
            raise KnowledgeNotFound("Файл не найден")
        return target, record
