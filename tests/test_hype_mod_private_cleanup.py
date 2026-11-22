"""Admin-only cleanup of unused private Fabric JAR drafts."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from flask import Blueprint, Flask

from modules.hype_mod_staging import register_mod_release_routes


class Storage:
    def __init__(self):
        self.public = False
        self.removed = []

    def get_bucket(self, name):
        assert name == "hype-mod-originals"
        return {"public": self.public}

    def from_(self, name):
        assert name == "hype-mod-originals"
        return self

    def remove(self, paths):
        self.removed.extend(paths)
        return paths


class Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.is_delete = False

    def select(self, *_fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, _count):
        return self

    def delete(self):
        self.is_delete = True
        return self

    def execute(self):
        if self.table == "hype_mod_release_drafts":
            source = self.db.drafts
        elif self.table == "hype_mod_published_releases":
            source = self.db.published
        else:
            raise AssertionError(self.table)
        rows = [r for r in source if all(r.get(key) == value for key, value in self.filters)]
        if self.is_delete:
            for row in rows:
                source.remove(row)
        return SimpleNamespace(data=[row.copy() for row in rows])


class Database:
    def __init__(self):
        self.drafts = []
        self.published = []
        self.storage = Storage()

    def table(self, name):
        return Query(self, name)


class PrivateCleanupTests(unittest.TestCase):
    def setUp(self):
        flag = patch.dict(os.environ, {"HYPE_MOD_STAGING_ENABLED": "1",
                                        "HYPE_MOD_PUBLISH_ENABLED": "0"})
        flag.start()
        self.addCleanup(flag.stop)
        self.db = Database()
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        bp = Blueprint("hype_mod_admin", __name__)

        @bp.get("/admin/modulos")
        def painel():
            return "ok"

        register_mod_release_routes(bp, lambda: True, None, self.db)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()
        self.draft_id = str(uuid4())
        self.sha = "a" * 64
        self.original = f"hypeclient/{uuid4().hex}/{self.sha}.jar"
        self.db.drafts.append({
            "id": self.draft_id, "module_id": "hypeclient",
            "version": "TEST-1", "status": "aguardando_protecao",
            "sha256": self.sha, "storage_path": self.original, "meta": {},
        })

    def login(self):
        with self.client.session_transaction() as sess:
            sess["usuario_email"] = "admin@example.com"

    def delete(self, draft_id=None, confirmed=True):
        return self.client.post("/admin/modulos/releases/excluir", data={
            "draft_id": draft_id or self.draft_id,
            "confirm_delete": "yes" if confirmed else "no",
        })

    def test_admin_authentication_required(self):
        self.assertEqual(self.delete().status_code, 403)
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_pending_draft_deleted_without_touching_other_objects(self):
        self.login()
        second = dict(self.db.drafts[0], id=str(uuid4()),
                      storage_path=f"hypeclient/{uuid4().hex}/{self.sha}.jar")
        self.db.drafts.append(second)
        self.assertEqual(self.delete().status_code, 302)
        self.assertEqual(self.db.drafts, [second])
        self.assertEqual(self.db.storage.removed, [self.original])

    def test_rejected_draft_deletes_its_protected_candidate_too(self):
        self.login()
        self.db.drafts[0]["status"] = "rejeitado"
        sha = "b" * 64
        protected = f"hypeclient/{self.draft_id}/protected/{uuid4().hex}/{sha}.jar"
        self.db.drafts[0]["meta"] = {"protected": {
            "sha256": sha, "storage_path": protected,
        }}
        self.assertEqual(self.delete().status_code, 302)
        self.assertEqual(self.db.storage.removed, [self.original, protected])

    def test_testing_and_approved_builds_are_not_deleted(self):
        self.login()
        for status in ("em_teste", "pronto_para_aprovacao"):
            with self.subTest(status=status):
                self.db.drafts[0]["status"] = status
                self.assertEqual(self.delete().status_code, 302)
                self.assertEqual(len(self.db.drafts), 1)
                self.assertEqual(self.db.storage.removed, [])

    def test_published_reference_blocks_even_rejected_draft(self):
        self.login()
        self.db.drafts[0]["status"] = "rejeitado"
        self.db.published.append({"release": 2, "draft_id": self.draft_id,
                                  "storage_path": "other/path.jar", "status": "disabled"})
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_published_storage_path_blocks_cleanup(self):
        self.login()
        self.db.published.append({"release": 2, "draft_id": "other",
                                  "storage_path": self.original, "status": "disabled"})
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_public_bucket_or_unsafe_paths_are_rejected(self):
        self.login()
        self.db.storage.public = True
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.db.storage.public = False
        self.db.drafts[0]["storage_path"] = "../escape.jar"
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_requires_explicit_confirmation_and_valid_id(self):
        self.login()
        self.delete(confirmed=False)
        self.delete(draft_id="../foo")
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])


if __name__ == "__main__":
    unittest.main()
