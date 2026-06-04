import unittest
from pathlib import Path


class SchemaMigrationTests(unittest.TestCase):
    def test_research_current_step_migration_is_idempotent(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "001_add_research_current_step.sql"

        sql = migration.read_text()

        self.assertIn("ALTER TABLE research_tasks", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS current_step", sql)

    def test_reliable_research_task_migration_adds_worker_state(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "004_reliable_research_tasks.sql"

        sql = migration.read_text()

        self.assertIn("dead_letter", sql)
        self.assertIn("cancelled", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS attempt_count", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS max_attempts", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS locked_by", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS heartbeat_at", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS cancel_requested_at", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS dead_letter_reason", sql)
        self.assertIn("idx_tasks_lease", sql)
