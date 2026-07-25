from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inventory.db import connect, initialize


class KnowledgeMigrationTest(unittest.TestCase):
    def test_schema_is_idempotent_and_foreign_keys_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "warehouse.db"
            initialize(db_path)
            initialize(db_path)
            with connect(db_path) as db:
                tables = {
                    str(row[0])
                    for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                indexes = {
                    str(row[0])
                    for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    )
                }
                foreign_key_errors = db.execute("PRAGMA foreign_key_check").fetchall()
            self.assertTrue({
                "knowledge_articles", "knowledge_attachments", "knowledge_article_tags"
            } <= tables)
            self.assertIn("idx_knowledge_articles_category_updated", indexes)
            self.assertIn("idx_knowledge_article_tags_tag", indexes)
            self.assertEqual(foreign_key_errors, [])


if __name__ == "__main__":
    unittest.main()
