"""Offline checks extracted from the SQL migration used by PR 106.

SQLite is only an isolated approximation of the selection logic; this is not a
PostgreSQL transaction, row-locking, Supabase RLS, or worker integration test.
No production data is read or changed.
"""
from __future__ import annotations

import re
import sqlite3
import unittest
from pathlib import Path
from uuid import uuid4

MIGRATION = Path(__file__).resolve().parents[1] / "sql" / "20261125_hype_mod_claim_valid_drafts.sql"
SHA = "a" * 64
OTHER_SHA = "b" * 64


def translated_selection():
    """Extract the actual PR selection rather than silently testing a second query."""
    sql = MIGRATION.read_text(encoding="utf-8")
    match = re.search(
        r"\bwith\s+selected\s+as\s*\(\s*(select\s+j\.id\s+from\s+.*?limit\s+1\s+for\s+update\s+of\s+j\s+skip\s+locked)\s*\),\s*claimed\s+as\b",
        sql, re.I | re.S,
    )
    if not match:
        raise AssertionError("Missing selected CTE in SQL migration")
    query = re.sub(r"\bpublic\.", "", match.group(1))
    query = query.replace("d.id::text", "CAST(d.id AS TEXT)")
    query = query.replace(
        "coalesce(d.meta, '{}'::jsonb) ? 'protected'",
        "json_type(coalesce(d.meta,'{}'), '$.protected') IS NOT NULL",
    )
    return re.sub(r"\s+for\s+update\s+of\s+j\s+skip\s+locked\s*$", "", query, flags=re.I)


class HypeClaimSelectionOfflineTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
            CREATE TABLE hype_mod_release_drafts (
                id TEXT PRIMARY KEY, module_id TEXT NOT NULL, sha256 TEXT NOT NULL,
                status TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE hype_mod_protection_jobs (
                id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, module_id TEXT NOT NULL,
                original_sha256 TEXT NOT NULL, status TEXT NOT NULL,
                requested_at INTEGER NOT NULL
            );
        """)
        self.query = translated_selection()
        self.assertIn("JOIN", self.query.upper())

    def draft(self, module="hypeclient", sha=SHA, status="aguardando_protecao", meta="{}"):
        key = str(uuid4())
        self.conn.execute("INSERT INTO hype_mod_release_drafts VALUES (?,?,?,?,?)",
                          (key, module, sha, status, meta))
        return key

    def job(self, draft_id, module="hypeclient", sha=SHA, status="queued", at=10):
        key = str(uuid4())
        self.conn.execute("INSERT INTO hype_mod_protection_jobs VALUES (?,?,?,?,?,?)",
                          (key, draft_id, module, sha, status, at))
        return key

    def selected(self):
        return [r[0] for r in self.conn.execute(self.query).fetchall()]

    def test_valid_original_is_selected(self):
        key = self.job(self.draft())
        self.assertEqual(self.selected(), [key])

    def test_eight_older_orphans_are_skipped_and_preserved(self):
        orphans = [self.job(str(uuid4()), at=n) for n in range(8)]
        valid = self.job(self.draft(), at=100)
        self.assertEqual(self.selected(), [valid])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM hype_mod_protection_jobs").fetchone()[0], 9)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM hype_mod_protection_jobs WHERE status='queued'").fetchone()[0], 9)
        for key in orphans:
            self.assertEqual(self.conn.execute("SELECT status FROM hype_mod_protection_jobs WHERE id=?", (key,)).fetchone()[0], "queued")

    def test_hash_mismatch_is_rejected(self):
        self.job(self.draft(), sha=OTHER_SHA)
        self.assertEqual(self.selected(), [])

    def test_module_mismatch_is_rejected(self):
        self.job(self.draft(), module="hype_pokedex")
        self.assertEqual(self.selected(), [])

    def test_rejected_original_is_skipped(self):
        self.job(self.draft(status="rejeitado"))
        self.assertEqual(self.selected(), [])

    def test_already_protected_is_skipped(self):
        self.job(self.draft(meta='{"protected":{"sha256":"abc"}}'))
        self.assertEqual(self.selected(), [])

    def test_failed_job_is_skipped(self):
        self.job(self.draft(), status="failed")
        self.assertEqual(self.selected(), [])

    def test_in_test_without_candidate_is_selected(self):
        key = self.job(self.draft(status="em_teste"))
        self.assertEqual(self.selected(), [key])

    def test_fifo_still_holds_among_valid_jobs(self):
        self.job(self.draft(), at=100)
        earlier = self.job(self.draft(), at=50)
        self.assertEqual(self.selected(), [earlier])

    def test_migration_has_no_deletion_or_public_access_grant(self):
        sql = MIGRATION.read_text(encoding="utf-8").lower()
        self.assertNotRegex(sql, r"\bdelete\s+from\b")
        self.assertNotRegex(sql, r"\btruncate\b")
        self.assertIn("security invoker", sql)
        self.assertIn("revoke all on function", sql)
        self.assertIn("grant execute on function", sql)
        self.assertIn("to service_role", sql)


if __name__ == "__main__":
    unittest.main()
