"""Data models exposed by the knowledge base module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


CATEGORY_LABELS = {
    "instructions": "Инструкции",
    "specifications": "Спецификации",
}


@dataclass(frozen=True)
class KnowledgeAttachment:
    id: int
    article_id: int
    original_name: str
    content_type: str
    size_bytes: int
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "KnowledgeAttachment":
        return cls(
            id=int(row["id"]),
            article_id=int(row["article_id"]),
            original_name=str(row["original_name"]),
            content_type=str(row["content_type"]),
            size_bytes=int(row["size_bytes"]),
            created_at=str(row["created_at"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "article_id": self.article_id,
            "original_name": self.original_name,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "download_url": f"/api/knowledge/attachments/{self.id}",
        }


@dataclass(frozen=True)
class KnowledgeArticle:
    id: int
    title: str
    summary: str
    content: str
    category: str
    created_at: str
    updated_at: str
    created_by: int | None
    author_name: str
    is_active: bool
    attachment_count: int = 0
    tags: tuple[str, ...] = ()

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "KnowledgeArticle":
        keys = set(row.keys())
        return cls(
            id=int(row["id"]),
            title=str(row["title"]),
            summary=str(row["summary"] or ""),
            content=str(row["content"] or ""),
            category=str(row["category"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            created_by=int(row["created_by"]) if row["created_by"] is not None else None,
            author_name=str(row["author_name"] or ""),
            is_active=bool(row["is_active"]),
            attachment_count=int(row["attachment_count"]) if "attachment_count" in keys else 0,
            tags=tuple(
                tag.strip()
                for tag in str(row["tags"] or "").split("\x1f")
                if tag.strip()
            ) if "tags" in keys else (),
        )

    def as_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "category_label": CATEGORY_LABELS[self.category],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "author_name": self.author_name or "Не указан",
            "attachment_count": self.attachment_count,
            "tags": list(self.tags),
        }
        if include_content:
            result["content"] = self.content
        return result
