"""A queued JAR must be cancelable; a running protection job must stay intact."""
import unittest
from unittest.mock import Mock

from modules.hype_mod_staging import stop_queued_protection_before_delete


def fake_db(jobs, updated=None):
    db = Mock()
    table = db.table.return_value
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = jobs
    table.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = (
        [{"id": "job-one", "status": "failed"}] if updated is None else updated
    )
    return db


class CancelQueuedProtectionTests(unittest.TestCase):
    def test_no_job_needs_no_update(self):
        db = fake_db([])
        stop_queued_protection_before_delete(db, "draft-1")
        db.table.return_value.update.assert_not_called()

    def test_completed_job_needs_no_update(self):
        db = fake_db([{"id": "job-one", "status": "completed"}])
        stop_queued_protection_before_delete(db, "draft-1")
        db.table.return_value.update.assert_not_called()

    def test_running_job_blocks_deletion(self):
        db = fake_db([{"id": "job-one", "status": "running"}])
        with self.assertRaisesRegex(ValueError, "proteção já começou"):
            stop_queued_protection_before_delete(db, "draft-1")
        db.table.return_value.update.assert_not_called()

    def test_queued_job_is_canceled_conditionally(self):
        db = fake_db([{"id": "job-one", "status": "queued"}])
        stop_queued_protection_before_delete(db, "draft-1")
        updated = db.table.return_value.update.call_args.args[0]
        self.assertEqual(updated["status"], "failed")
        self.assertIn("Cancelado", updated["failure_reason"])
        db.table.return_value.update.return_value.eq.assert_called_with("id", "job-one")
        db.table.return_value.update.return_value.eq.return_value.eq.assert_called_with("status", "queued")

    def test_claim_race_prevents_deletion(self):
        db = fake_db([{"id": "job-one", "status": "queued"}], updated=[])
        with self.assertRaisesRegex(ValueError, "começou durante a exclusão"):
            stop_queued_protection_before_delete(db, "draft-1")


if __name__ == "__main__":
    unittest.main()
