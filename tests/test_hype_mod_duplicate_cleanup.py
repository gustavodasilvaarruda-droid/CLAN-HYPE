"""Old copies of a published binary can be cleaned without deleting the active JAR."""
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from flask import Blueprint, Flask
from modules.hype_mod_staging import register_mod_release_routes


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.deleting = db, table, [], False

    def select(self, *_):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, _number):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def delete(self):
        self.deleting = True
        return self

    def execute(self):
        source = getattr(self.db, self.table)
        result = [row for row in source
                  if all(row.get(field) == value for field, value in self.filters)]
        if self.deleting:
            for row in result:
                source.remove(row)
        return SimpleNamespace(data=[dict(row) for row in result])


class Storage:
    def __init__(self):
        self.removed = []

    def get_bucket(self, _bucket):
        return {"public": False}

    def from_(self, _bucket):
        return self

    def remove(self, paths):
        self.removed.extend(paths)


class FakeDB:
    def __init__(self, rows):
        self.hype_mod_release_drafts = rows
        self.hype_mod_published_releases = []
        self.hype_mod_restricted_releases = []
        self.hype_mod_protection_jobs = []
        self.storage = Storage()

    def table(self, table):
        return Query(self, table)


def published_row(when, sha=None):
    mod_id = "hype_pokedex"
    sha = sha or "a" * 64
    return {
        "id": str(uuid4()), "module_id": mod_id, "version": "1.0",
        "status": "aguardando_protecao",
        "sha256": sha, "size_bytes": 1234,
        "storage_path": f"{mod_id}/{uuid4().hex}/{sha}.jar",
        "original_filename": "pokedex.jar",
        "created_at": when,
        "meta": {
            "library_upload": True, "mod_name": "HYPE Pokedex",
            "bootstrap_publication": {
                "source": "original", "module_id": mod_id, "version": "1.0",
                "sha256": sha, "published_by": "test-owner@example.test",
                "published_at": when,
            }
        },
    }


class DuplicateCleanupTests(unittest.TestCase):
    def setUp(self):
        flags = patch.dict(os.environ, {
            "HYPE_MOD_STAGING_ENABLED": "1",
            "HYPE_AUTO_SIMPLE_PUBLISH_ENABLED": "1",
            "HYPE_AUTO_SIGNED_CATALOG_ENABLED": "1",
            "HYPE_AUTO_SIGNED_DOWNLOADS_ENABLED": "1",
            "HYPE_AUTO_REQUIRE_APPROVED_CANDIDATE": "0",
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "off",
        })
        flags.start()
        self.addCleanup(flags.stop)
        self.old = published_row("2026-11-27T02:00:00+00:00")
        self.active = published_row("2026-11-27T03:00:00+00:00")
        self.db = FakeDB([self.old, self.active])
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY="test", TESTING=True)
        bp = Blueprint("hype_mod_admin", __name__)
        register_mod_release_routes(bp, lambda: True, None, self.db)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()
        with self.client.session_transaction() as s:
            s["usuario_email"] = "test-owner@example.test"

    def delete(self, row, confirmed=True):
        return self.client.post("/admin/modulos/releases/excluir", data={
            "draft_id": row["id"], "confirm_delete": "yes",
            "confirm_duplicate_retire": "yes" if confirmed else "no",
        }, headers={"X-HYPE-BATCH": "1"})

    def test_delete_query_includes_all_eligibility_fields(self):
        # Regression: the delete route used to omit size/filename, causing
        # _eligible(draft) to always reject old published copies.
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] / "modules" /
               "hype_mod_staging.py").read_text(encoding="utf-8")
        delete_route = src.split('def mod_release_delete():', 1)[1]
        self.assertIn(
            '"id,module_id,version,status,sha256,size_bytes,storage_path,original_filename,created_at,meta"',
            delete_route.split("if not rows:", 1)[0],
        )

    def test_catalog_selects_exactly_one_live_copy(self):
        from modules.hype_auto_signed_catalogue import latest_uploaded_mods
        selected = latest_uploaded_mods(self.db)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["id"], self.active["id"])

    def test_active_published_jar_cannot_be_deleted(self):
        response = self.delete(self.active)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(len(self.db.hype_mod_release_drafts), 2)
        self.assertEqual(self.db.storage.removed, [])

    def test_unconfirmed_duplicate_remains_protected(self):
        response = self.delete(self.old, confirmed=False)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(len(self.db.hype_mod_release_drafts), 2)

    def test_exact_old_duplicate_may_be_deleted(self):
        response = self.delete(self.old)
        self.assertTrue(response.get_json(), response.data)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(self.db.hype_mod_release_drafts, [self.active])
        self.assertEqual(self.db.storage.removed, [self.old["storage_path"]])
        from modules.hype_auto_signed_catalogue import latest_uploaded_mods
        self.assertEqual(latest_uploaded_mods(self.db)[0]["id"], self.active["id"])

    def test_old_different_binary_is_not_a_duplicate(self):
        self.old["sha256"] = "b" * 64
        self.old["storage_path"] = f"hype_pokedex/{uuid4().hex}/{'b' * 64}.jar"
        self.old["meta"]["bootstrap_publication"]["sha256"] = "b" * 64
        response = self.delete(self.old)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(len(self.db.hype_mod_release_drafts), 2)

    def test_linked_release_keeps_published_duplicate(self):
        self.db.hype_mod_published_releases.append({
            "draft_id": self.old["id"],
            "release": 42,
            "storage_path": self.old["storage_path"],
        })
        response = self.delete(self.old)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(len(self.db.hype_mod_release_drafts), 2)
        self.assertEqual(self.db.storage.removed, [])


if __name__ == "__main__":
    unittest.main()
