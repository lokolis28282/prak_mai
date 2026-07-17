from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.db import connect
from inventory.knowledge import KnowledgeError, KnowledgeNotFound, KnowledgePermissionError
from inventory.knowledge.markdown import render_markdown
from inventory.service import WarehouseService


class KnowledgeBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.upload_root = Path(self.tmp.name) / "uploads"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.context.knowledge.upload_root = self.upload_root

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create_article(self, **overrides):
        payload = {
            "title": "Перезапуск сервера",
            "summary": "Порядок безопасного перезапуска",
            "content": "# Подготовка\n\n1. Проверить алерты\n2. Уведомить поддержку",
            "category": "instructions",
        }
        payload.update(overrides)
        with self.service.user_context("lokolis", author_name="Иванов Иван"):
            return self.context.knowledge.create_article(payload)

    def test_migration_persistence_categories_and_russian_text(self) -> None:
        with connect(self.db_path) as db:
            tables = {str(row[0]) for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
        self.assertTrue({"knowledge_articles", "knowledge_attachments"} <= tables)
        created = self.create_article()
        self.assertEqual(created["title"], "Перезапуск сервера")
        self.assertEqual(created["author_name"], "Иванов Иван")
        self.assertIn("<h1>Подготовка</h1>", created["content_html"])
        restarted = create_application_context(
            self.db_path, service=WarehouseService(self.db_path)
        )
        articles = restarted.knowledge.list_articles("instructions")["articles"]
        self.assertEqual([item["id"] for item in articles], [created["id"]])
        self.assertEqual(
            restarted.knowledge.list_articles("specifications")["articles"], []
        )

    def test_validation_and_viewer_permission(self) -> None:
        for payload in (
            {"title": "", "content": "Текст", "category": "instructions"},
            {"title": "Название", "content": "", "category": "instructions"},
            {"title": "Название", "content": "Текст", "category": "other"},
        ):
            with self.subTest(payload=payload), self.service.user_context("lokolis"):
                with self.assertRaises(KnowledgeError):
                    self.context.knowledge.create_article(payload)
        with self.service.user_context("lokolis"):
            self.service.create_user(
                "Только", "Просмотр", "Наблюдатель", "viewer-knowledge@test", "secret1", "viewer"
            )
        with self.service.user_context("viewer-knowledge@test"):
            self.assertEqual(
                self.context.knowledge.list_articles("instructions")["articles"], []
            )
            with self.assertRaises(KnowledgePermissionError):
                self.context.knowledge.create_article({
                    "title": "Нельзя", "content": "Текст", "category": "instructions"
                })

    def test_search_tags_pagination_update_and_soft_delete(self) -> None:
        first = self.create_article(tags=["Серверы", "Аварии"])
        self.create_article(
            title="Настройка коммутатора",
            summary="Сеть",
            content="Cisco C9300",
            tags="Сеть, Cisco",
        )
        by_query = self.context.knowledge.list_articles(
            "instructions", query="коммутатора", page_size=1
        )
        self.assertEqual(by_query["total"], 1)
        self.assertEqual(by_query["articles"][0]["title"], "Настройка коммутатора")
        by_tag = self.context.knowledge.list_articles(
            "instructions", tag="серверы", page_size=1
        )
        self.assertEqual(by_tag["total"], 1)
        self.assertEqual(by_tag["articles"][0]["id"], first["id"])
        self.assertIn("Серверы", by_tag["tags"])
        page = self.context.knowledge.list_articles(
            "instructions", page=2, page_size=1
        )
        self.assertEqual(page["pages"], 2)
        with self.service.user_context("lokolis", author_name="Редактор"):
            updated = self.context.knowledge.update_article(first["id"], {
                "title": "Обновленная инструкция",
                "summary": "Новая версия",
                "content": "# Новый текст",
                "category": "specifications",
                "tags": ["Dell"],
            })
        self.assertEqual(updated["tags"], ["Dell"])
        self.assertEqual(updated["category"], "specifications")
        with self.service.user_context("lokolis", author_name="Редактор"):
            self.context.knowledge.delete_article(first["id"])
        with self.assertRaises(KnowledgeNotFound):
            self.context.knowledge.get_article(first["id"])
        self.assertEqual(
            self.context.knowledge.list_articles("specifications")["total"], 0
        )

    def test_safe_markdown_escapes_html_and_unsafe_links(self) -> None:
        rendered = render_markdown(
            "# Заголовок\n\n**Жирный** и *курсив*.\n\n"
            "[Сайт](https://example.com) [Опасно](javascript:alert(1))\n\n"
            "<script>alert('x')</script>\n\n```\n<tag>\n```"
        )
        self.assertIn("<strong>Жирный</strong>", rendered)
        self.assertIn("<em>курсив</em>", rendered)
        self.assertIn('href="https://example.com"', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("<pre><code>&lt;tag&gt;</code></pre>", rendered)

    def test_secure_attachments_unique_names_and_safe_download(self) -> None:
        article = self.create_article(category="specifications", title="Dell R760")
        payload = b"%PDF-1.7\nexample"
        with self.service.user_context("lokolis", author_name="Иванов Иван"):
            first = self.context.knowledge.add_attachment(
                article["id"], "Спецификация R760.pdf", "application/pdf", payload
            )
            second = self.context.knowledge.add_attachment(
                article["id"], "Спецификация R760.pdf", "application/pdf", payload
            )
        self.assertNotEqual(first["id"], second["id"])
        with connect(self.db_path) as db:
            records = [dict(row) for row in db.execute(
                "SELECT stored_name, relative_path FROM knowledge_attachments ORDER BY id"
            )]
        self.assertNotEqual(records[0]["stored_name"], records[1]["stored_name"])
        self.assertTrue(all(not Path(row["relative_path"]).is_absolute() for row in records))
        path, record = self.context.knowledge.attachment_download(first["id"])
        self.assertEqual(path.read_bytes(), payload)
        self.assertEqual(record["original_name"], "Спецификация R760.pdf")
        with self.service.user_context("lokolis"):
            with self.assertRaises(KnowledgeError):
                self.context.knowledge.add_attachment(
                    article["id"], "../../danger.pdf", "application/pdf", payload
                )
            with self.assertRaises(KnowledgeError):
                self.context.knowledge.add_attachment(
                    article["id"], "danger.exe", "application/octet-stream", b"MZ"
                )
            with self.assertRaises(KnowledgeError):
                self.context.knowledge.add_attachment(
                    article["id"], "fake.png", "image/png", b"not a png"
                )


if __name__ == "__main__":
    unittest.main()
