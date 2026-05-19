from pathlib import Path
import unittest


class SchemaMigrationTests(unittest.TestCase):
    def test_research_current_step_migration_is_idempotent(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "001_add_research_current_step.sql"

        sql = migration.read_text()

        self.assertIn("ALTER TABLE research_tasks", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS current_step", sql)
