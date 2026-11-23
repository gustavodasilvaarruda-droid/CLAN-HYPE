"""Test-only validation of archived original JARs; never a player release."""
import hashlib
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_STORED

from modules.hype_mod_staging import (
    BUCKET, InvalidJar, read_original_for_admin_test
)


class _Table:
    def __init__(self, db):
        self.db = db
        self.filters = []

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        row = self.db.record
        found = all(row.get(key) == val for key, val in self.filters)
        return SimpleNamespace(data=[dict(row)] if found else [])


class _Storage:
    def __init__(self, db):
        self.db = db
        self.public = False

    def get_bucket(self, name):
        assert name == BUCKET
        return {"public": self.public}

    def from_(self, name):
        assert name == BUCKET
        return self

    def download(self, path):
        if path != self.db.record["storage_path"]:
            raise RuntimeError("path mismatch")
        return self.db.raw


class _DB:
    def __init__(self):
        output = io.BytesIO()
        with ZipFile(output, "w", ZIP_STORED) as jar:
            jar.writestr("fabric.mod.json", json.dumps({
                "id": "hype_pokedex", "version": "2.0.0-test",
                "depends": {"minecraft": "1.21.1"}
            }))
            jar.writestr("br/clanhype/test.class", b"x" * 2048)
        self.raw = output.getvalue()
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.record = {
            "id": "c957d4c1-15e4-4b43-af6d-5d5cc4dc6d97",
            "module_id": "hype_pokedex", "version": "2.0.0-test",
            "status": "em_teste", "sha256": self.sha,
            "storage_path": f"hype_pokedex/{'a'*32}/{self.sha}.jar"
        }
        self.storage = _Storage(self)

    def table(self, name):
        assert name == "hype_mod_release_drafts"
        return _Table(self)


class OriginalAdminTestDownloadTests(unittest.TestCase):
    def setUp(self):
        self.db = _DB()

    def read(self):
        return read_original_for_admin_test(self.db, self.db.record["id"])

    def test_original_verified_and_returned_privately(self):
        raw, info = self.read()
        self.assertEqual(raw, self.db.raw)
        self.assertEqual(info["module_id"], "hype_pokedex")
        self.assertEqual(info["sha256"], self.db.sha)
        self.assertEqual(self.db.record["status"], "em_teste")

    def test_rejects_public_bucket(self):
        self.db.storage.public = True
        with self.assertRaises(RuntimeError):
            self.read()

    def test_rejects_unsafe_path(self):
        self.db.record["storage_path"] = "../secrets.jar"
        with self.assertRaises(InvalidJar):
            self.read()

    def test_rejects_mismatched_checksum(self):
        self.db.raw += b"modified"
        with self.assertRaises((InvalidJar, ValueError)):
            self.read()

    def test_rejects_wrong_version(self):
        self.db.record["version"] = "2.0.1-test"
        with self.assertRaises(InvalidJar):
            self.read()

    def test_rejects_rejected_original(self):
        self.db.record["status"] = "rejeitado"
        with self.assertRaises(InvalidJar):
            self.read()

    def test_rejects_nonexistent_draft(self):
        with self.assertRaises(InvalidJar):
            read_original_for_admin_test(
                self.db, "c957d4c1-15e4-4b43-af6d-5d5cc4dc6d98"
            )

    def test_download_route_requires_admin_and_opt_in(self):
        src = (Path(__file__).resolve().parents[1] / "modules" /
               "hype_mod_staging.py").read_text(encoding="utf-8")
        route = src.split('def mod_release_original_test_download(draft_id):', 1)[1].split(
            '    @bp.get("/admin/modulos/releases")', 1
        )[0]
        self.assertIn("admin_only()", route)
        self.assertIn("if not original_test_download_enabled", route)
        self.assertIn('response.headers["Cache-Control"] = "private, no-store, max-age=0"', route)
        self.assertNotIn("published", route)


if __name__ == "__main__":
    unittest.main()
