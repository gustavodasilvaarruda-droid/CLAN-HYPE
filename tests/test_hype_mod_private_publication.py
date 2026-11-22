"""Private releases never publish an unsigned/unreviewed/unprotected JAR."""
import os
import unittest
from unittest.mock import patch

from modules.hype_mod_private_releases import InvalidPrivateRelease
from modules.hype_mod_private_publication import (
    validate_private_publication, publish_first_private_release,
)
from test_hype_mod_private_downloads import (
    PrivateModDownloadTests, Query, FakeDB, MOD, DRAFT_ID,
)


class WritingQuery(Query):
    def insert(self, data):
        self.to_insert = dict(data)
        return self

    def execute(self):
        if hasattr(self, "to_insert"):
            row = self.to_insert
            self.db.rows.setdefault(self.table, []).append(row)
            from types import SimpleNamespace
            return SimpleNamespace(data=[row])
        return super().execute()


class WritingDB(FakeDB):
    def table(self, name):
        return WritingQuery(self, name)


class PrivatePublicationTests(unittest.TestCase):
    def setUp(self):
        fixture = PrivateModDownloadTests(
            methodName="test_flags_off_even_for_valid_token")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.db = WritingDB()
        self.db.rows = fixture.db.rows
        self.db.blobs = fixture.db.blobs
        self.db.rows["hype_mod_restricted_releases"] = []
        self.draft = self.db.rows["hype_mod_release_drafts"][0]
        self.manifest = fixture.signed_manifest().encode("ascii")
        self.kw = dict(
            draft_id=DRAFT_ID, manifest_bytes=self.manifest,
            published_by="admin@example.org")
        compatibility = patch(
            "modules.hype_mod_private_publication.check_candidate_compatibility",
            return_value={"entrypoints_checked": 1})
        inspect = patch(
            "modules.hype_mod_private_publication.inspect_original",
            return_value={
                "module_id": MOD, "version": "2.0.0-test",
                "size_bytes": len(fixture.jar)})
        compatibility.start()
        inspect.start()
        self.addCleanup(compatibility.stop)
        self.addCleanup(inspect.stop)

    def expect_denial(self):
        with self.assertRaises((InvalidPrivateRelease, ValueError)):
            validate_private_publication(self.db, **self.kw)
        self.assertFalse(self.db.rows["hype_mod_restricted_releases"])

    def test_all_four_checks_signer_and_sha_enable_first_release(self):
        prepared = validate_private_publication(self.db, **self.kw)
        self.assertEqual(prepared["sha256"], self.fixture.sha)
        self.assertEqual(prepared["module_id"], MOD)
        self.assertEqual(prepared["status"], "published")
        self.assertFalse(self.db.rows["hype_mod_restricted_releases"])
        saved = publish_first_private_release(self.db, **self.kw)
        self.assertEqual(saved["release"], 1)
        self.assertEqual(len(self.db.rows["hype_mod_restricted_releases"]), 1)

    def test_rejects_active_prior_version(self):
        self.db.rows["hype_mod_restricted_releases"].append(
            {"release": 1, "status": "published", "module_id": MOD})
        with self.assertRaises(InvalidPrivateRelease):
            validate_private_publication(self.db, **self.kw)

    def test_rejects_nonincreasing_previous_release(self):
        self.db.rows["hype_mod_restricted_releases"].append(
            {"release": 1, "status": "disabled", "module_id": MOD})
        with self.assertRaises(InvalidPrivateRelease):
            validate_private_publication(self.db, **self.kw)

    def test_rejects_unsigned_manifest(self):
        self.kw["manifest_bytes"] = self.manifest.replace(b"signature=", b"wrong_sig=")
        self.expect_denial()

    def test_rejects_modified_signed_fields(self):
        self.kw["manifest_bytes"] = self.manifest.replace(b"channel=stable", b"channel=beta")
        self.expect_denial()

    def test_rejects_unapproved_original(self):
        self.draft["status"] = "em_teste"
        self.expect_denial()

    def test_rejects_missing_game_test(self):
        self.draft["meta"]["manual_review"]["checks"]["no_crashes"] = False
        self.expect_denial()

    def test_rejects_tampered_candidate_hash(self):
        self.db.blobs[self.fixture.path] = self.fixture.jar[:-1] + b"x"
        self.expect_denial()

    def test_rejects_public_storage(self):
        self.db.storage.public = True
        self.expect_denial()

    def test_rejects_missing_candidate(self):
        del self.draft["meta"]["protected"]
        self.expect_denial()

    def test_rejects_mismatched_candidate_sha_review(self):
        self.draft["meta"]["manual_review"]["candidate_sha256"] = "0" * 64
        self.expect_denial()

    def test_rejects_wrong_signed_candidate_size(self):
        self.draft["meta"]["protected"]["size_bytes"] += 1
        self.expect_denial()

    def test_rejects_fake_admin(self):
        self.kw["published_by"] = ""
        self.expect_denial()


if __name__ == "__main__":
    unittest.main()
