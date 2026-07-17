"""SQLite repository for the isolated knowledge base module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inventory.db import connect
from inventory.shared.audit import write_audit_entry

from .models import KnowledgeArticle, KnowledgeAttachment


class KnowledgeRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @staticmethod
    def _article_select() -> str:
        return """SELECT a.*,
                         COALESCE(NULLIF(trim(a.created_by_name), ''),
                                  NULLIF(trim(u.last_name || ' ' || u.first_name), ''),
                                  'Не указан') AS author_name,
                         (SELECT count(*) FROM knowledge_attachments ka
                          WHERE ka.article_id = a.id) AS attachment_count,
                         COALESCE((SELECT group_concat(tag, char(31))
                                   FROM (SELECT kt.tag
                                         FROM knowledge_article_tags kt
                                         WHERE kt.article_id = a.id
                                         ORDER BY kt.tag COLLATE NOCASE)), '') AS tags
                  FROM knowledge_articles a
                  LEFT JOIN users u ON u.id = a.created_by"""

    def list_articles(
        self,
        category: str,
        *,
        query: str = "",
        tag: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[KnowledgeArticle], int]:
        filters = ["a.category = ?", "a.is_active = 1"]
        values: list[Any] = [category]
        if query:
            pattern = f"%{query}%"
            filters.append(
                "(a.title LIKE ? COLLATE NOCASE OR a.summary LIKE ? COLLATE NOCASE "
                "OR a.content LIKE ? COLLATE NOCASE)"
            )
            values.extend((pattern, pattern, pattern))
        if tag:
            filters.append(
                "EXISTS (SELECT 1 FROM knowledge_article_tags fkt "
                "WHERE fkt.article_id = a.id AND fkt.tag_key = ?)"
            )
            values.append(tag.casefold())
        where = " AND ".join(filters)
        with connect(self.db_path) as db:
            total = int(db.execute(
                f"SELECT count(*) FROM knowledge_articles a WHERE {where}",
                values,
            ).fetchone()[0])
            rows = db.execute(
                self._article_select()
                + f" WHERE {where} ORDER BY a.updated_at DESC, "
                  "a.title COLLATE NOCASE, a.id DESC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
        return [KnowledgeArticle.from_row(row) for row in rows], total

    def list_tags(self, category: str) -> list[str]:
        with connect(self.db_path) as db:
            rows = db.execute(
                """SELECT DISTINCT kt.tag
                   FROM knowledge_article_tags kt
                   JOIN knowledge_articles a ON a.id = kt.article_id
                   WHERE a.category = ? AND a.is_active = 1
                   ORDER BY kt.tag COLLATE NOCASE""",
                (category,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def get_article(self, article_id: int) -> KnowledgeArticle | None:
        with connect(self.db_path) as db:
            row = db.execute(
                self._article_select() + " WHERE a.id = ? AND a.is_active = 1",
                (article_id,),
            ).fetchone()
        return KnowledgeArticle.from_row(row) if row is not None else None

    @staticmethod
    def _replace_tags(db: Any, article_id: int, tags: list[str]) -> None:
        db.execute("DELETE FROM knowledge_article_tags WHERE article_id = ?", (article_id,))
        db.executemany(
            "INSERT INTO knowledge_article_tags(article_id, tag, tag_key) VALUES (?, ?, ?)",
            [(article_id, tag, tag.casefold()) for tag in tags],
        )

    def create_article(
        self,
        *,
        title: str,
        summary: str,
        content: str,
        category: str,
        tags: list[str],
        author_id: int | None,
        author_name: str,
    ) -> int:
        with connect(self.db_path) as db:
            cursor = db.execute(
                """INSERT INTO knowledge_articles(
                       title, summary, content, category, created_by, created_by_name
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (title, summary, content, category, author_id, author_name),
            )
            article_id = int(cursor.lastrowid)
            self._replace_tags(db, article_id, tags)
            write_audit_entry(
                db,
                action="KNOWLEDGE_ARTICLE_CREATE",
                entity_type="knowledge_article",
                entity_id=article_id,
                author=author_name,
                details={"title": title, "category": category, "tags": tags},
            )
            return article_id

    def update_article(
        self,
        article_id: int,
        *,
        title: str,
        summary: str,
        content: str,
        category: str,
        tags: list[str],
        author_name: str,
    ) -> bool:
        with connect(self.db_path) as db:
            cursor = db.execute(
                """UPDATE knowledge_articles
                   SET title = ?, summary = ?, content = ?, category = ?,
                       updated_at = datetime('now', 'localtime')
                   WHERE id = ? AND is_active = 1""",
                (title, summary, content, category, article_id),
            )
            if cursor.rowcount != 1:
                return False
            self._replace_tags(db, article_id, tags)
            write_audit_entry(
                db,
                action="KNOWLEDGE_ARTICLE_UPDATE",
                entity_type="knowledge_article",
                entity_id=article_id,
                author=author_name,
                details={"title": title, "category": category, "tags": tags},
            )
            return True

    def soft_delete_article(self, article_id: int, *, author_name: str) -> bool:
        with connect(self.db_path) as db:
            cursor = db.execute(
                """UPDATE knowledge_articles
                   SET is_active = 0, updated_at = datetime('now', 'localtime')
                   WHERE id = ? AND is_active = 1""",
                (article_id,),
            )
            if cursor.rowcount != 1:
                return False
            write_audit_entry(
                db,
                action="KNOWLEDGE_ARTICLE_DELETE",
                entity_type="knowledge_article",
                entity_id=article_id,
                author=author_name,
                details={"soft_delete": True},
            )
            return True

    def list_attachments(self, article_id: int) -> list[KnowledgeAttachment]:
        with connect(self.db_path) as db:
            rows = db.execute(
                """SELECT id, article_id, original_name, content_type, size_bytes, created_at
                   FROM knowledge_attachments WHERE article_id = ? ORDER BY id""",
                (article_id,),
            ).fetchall()
        return [KnowledgeAttachment.from_row(row) for row in rows]

    def add_attachment(
        self,
        *,
        article_id: int,
        original_name: str,
        stored_name: str,
        relative_path: str,
        content_type: str,
        size_bytes: int,
        author_id: int | None,
        author_name: str,
    ) -> int:
        with connect(self.db_path) as db:
            cursor = db.execute(
                """INSERT INTO knowledge_attachments(
                       article_id, original_name, stored_name, relative_path,
                       content_type, size_bytes, uploaded_by, uploaded_by_name
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    article_id, original_name, stored_name, relative_path,
                    content_type, size_bytes, author_id, author_name,
                ),
            )
            attachment_id = int(cursor.lastrowid)
            db.execute(
                """UPDATE knowledge_articles
                   SET updated_at = datetime('now', 'localtime') WHERE id = ?""",
                (article_id,),
            )
            write_audit_entry(
                db,
                action="KNOWLEDGE_ATTACHMENT_ADD",
                entity_type="knowledge_article",
                entity_id=article_id,
                author=author_name,
                details={"attachment_id": attachment_id, "filename": original_name},
            )
            return attachment_id

    def get_attachment_record(self, attachment_id: int) -> dict[str, Any] | None:
        with connect(self.db_path) as db:
            row = db.execute(
                """SELECT ka.* FROM knowledge_attachments ka
                   JOIN knowledge_articles a ON a.id = ka.article_id
                   WHERE ka.id = ? AND a.is_active = 1""",
                (attachment_id,),
            ).fetchone()
        return dict(row) if row is not None else None
