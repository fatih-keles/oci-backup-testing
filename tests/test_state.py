from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oci_backup_testing.state import mark_execution_cleaned, prune_state


class StateTests(unittest.TestCase):
    def test_mark_execution_cleaned_updates_matching_run(self):
        state = {"executions": [{"run_id": "run-1"}]}

        marked = mark_execution_cleaned(
            state,
            {"run_id": "run-1", "actions": [{"status": "deleted"}]},
        )

        self.assertTrue(marked)
        execution = state["executions"][0]
        self.assertEqual(execution["cleanup_status"], "cleaned")
        self.assertEqual(execution["cleanup"]["run_id"], "run-1")
        self.assertIn("cleaned_at", execution)

    def test_prune_state_removes_old_cleaned_runs_only(self):
        state = {
            "executions": [
                {
                    "run_id": "old-cleaned",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "cleaned_at": "2026-01-02T00:00:00+00:00",
                    "cleanup_status": "cleaned",
                },
                {
                    "run_id": "old-not-cleaned",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            ],
        }

        summary = prune_state(
            state,
            max_executions=None,
            max_age_days=30,
            prune_only_cleaned=True,
            now=datetime(2026, 5, 15, tzinfo=timezone.utc),
        )

        self.assertEqual(summary["pruned_count"], 1)
        self.assertEqual(state["executions"][0]["run_id"], "old-not-cleaned")
        self.assertTrue(summary["retention_limit_met"])

    def test_prune_state_uses_max_executions_for_oldest_cleaned_runs(self):
        state = {
            "executions": [
                {
                    "run_id": "run-1",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "cleaned_at": "2026-01-02T00:00:00+00:00",
                    "cleanup_status": "cleaned",
                },
                {
                    "run_id": "run-2",
                    "created_at": "2026-01-03T00:00:00+00:00",
                    "cleaned_at": "2026-01-04T00:00:00+00:00",
                    "cleanup_status": "cleaned",
                },
                {
                    "run_id": "run-3",
                    "created_at": "2026-01-05T00:00:00+00:00",
                    "cleaned_at": "2026-01-06T00:00:00+00:00",
                    "cleanup_status": "cleaned",
                },
            ],
        }

        summary = prune_state(
            state,
            max_executions=2,
            max_age_days=None,
            prune_only_cleaned=True,
            now=datetime(2026, 5, 15, tzinfo=timezone.utc),
        )

        self.assertEqual(summary["pruned_count"], 1)
        self.assertEqual(summary["pruned"][0]["run_id"], "run-1")
        self.assertEqual([item["run_id"] for item in state["executions"]], ["run-2", "run-3"])


if __name__ == "__main__":
    unittest.main()
