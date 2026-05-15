from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oci_backup_testing.queue import (
    clear_queue,
    init_queue,
    load_queue,
    save_queue,
    upsert_queue_execution,
)


class QueueTests(unittest.TestCase):
    def test_init_queue_resets_executions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "queue.json"
            queue = init_queue(path)
            queue["executions"].append({"run_id": "old"})
            save_queue(path, queue)

            reset = init_queue(path)

            self.assertNotEqual(queue["batch_id"], reset["batch_id"])
            self.assertEqual(reset["executions"], [])

    def test_upsert_queue_execution_updates_existing_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "queue.json"
            queue = init_queue(path)
            upsert_queue_execution(queue, {"run_id": "run-1", "phase": "planned"})
            upsert_queue_execution(queue, {"run_id": "run-1", "phase": "validated"})

            self.assertEqual(len(queue["executions"]), 1)
            self.assertEqual(queue["executions"][0]["phase"], "validated")

    def test_clear_queue_removes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "queue.json"
            init_queue(path)

            self.assertTrue(clear_queue(path))
            self.assertFalse(path.exists())

    def test_load_queue_can_create_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "queue.json"

            queue = load_queue(path, create_if_missing=True)

            self.assertTrue(path.exists())
            self.assertEqual(queue["executions"], [])


if __name__ == "__main__":
    unittest.main()
