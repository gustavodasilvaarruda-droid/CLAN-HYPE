"""Verify that private mod uploads store metadata without publishing files."""
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from flask import Blueprint, Flask
from modules.hype_mod_staging import register_mod_release_routes


def sample_jar():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({
            "id": "hypeclient",
            "version": "4.0-test",
            "depends": {"minecraft": "1.21.1", "fabricloader": ">=0.16.0"},
        }))
        archive.writestr("br/hype/client/Example.class", b"test only")
    return buffer.getvalue()


class Storage:
    def __init__(self, is_public=False):
        self.is_public = is_public
        self.uploads = []
        self.removed = []

    def get_bucket(self, name):
        assert name == "hype-mod-originals"
        return {"public": self.is_public}

    def from_(self, name):
        assert name == "hype-mod-originals"
        return self

    def upload(self, *, path, file, file_options):
        self.uploads.append((path, file, file_options))

    def remove(self, paths):
        self.removed.extend(paths)


class Query:
    def __init__(self, database):
        self.database = database
        self.to_insert = None

    def select(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def insert(self, record):
        self.to_insert = record
        return self

    def execute(self):
        if self.to_insert is not None:
            self.database.saved.append(self.to_insert)
            return SimpleNamespace(data=[{"id": len(self.database.saved)}])
        return SimpleNamespace(data=[])


class Database:
    def __init__(self, public=False):
        self.storage = Storage(public)
        self.saved = []

    def table(self, name):
        assert name == "hype_mod_release_drafts"
        return Query(self)


class PrivateUploadTests(unittest.TestCase):
    def setUp(self):
        self.flag = patch.dict(os.environ, {"HYPE_MOD_STAGING_ENABLED": "1"})
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.db = Database()
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        self.bp = Blueprint("hype_mod_admin", __name__)

        @self.bp.get("/admin/modulos")
        def painel():
            return "ok"

        register_mod_release_routes(self.bp, lambda: True, None, self.db)
        self.app.register_blueprint(self.bp)
        self.client = self.app.test_client()

    def login(self):
        with self.client.session_transaction() as user_session:
            user_session["usuario_email"] = "admin@example.com"

    def upload(self):
        return self.client.post("/admin/modulos/releases/upload", data={
            "jar": (io.BytesIO(sample_jar()), "hypeclient-test.jar")
        }, content_type="multipart/form-data")

    def test_only_authenticated_admin_can_store_jar(self):
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.db.saved, [])
        self.assertEqual(self.db.storage.uploads, [])

    def test_private_upload_keeps_sha_and_compatibility(self):
        self.login()
        response = self.upload()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.db.saved), 1)
        self.assertEqual(len(self.db.storage.uploads), 1)
        draft = self.db.saved[0]
        self.assertEqual(draft["status"], "aguardando_protecao")
        self.assertEqual(draft["module_id"], "hypeclient")
        self.assertEqual(draft["version"], "4.0-test")
        self.assertEqual(draft["meta"]["compatibility"]["minecraft"], "1.21.1")
        self.assertEqual(draft["meta"]["compatibility"]["fabricloader"], ">=0.16.0")
        self.assertEqual(draft["sha256"], self.db.storage.uploads[0][0].split("/")[-1].removesuffix(".jar"))
        self.assertEqual(self.client.get("/hype-updates/manifest.properties").status_code, 404)

    def test_audit_log_failure_does_not_rollback_saved_jar(self):
        self.login()
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        second = Blueprint("hype_mod_admin", __name__)
        @second.get("/admin/modulos")
        def painel():
            return "ok"
        def failing_log(*_args, **_kwargs):
            raise RuntimeError("audit service unavailable")
        register_mod_release_routes(second, lambda: True, failing_log, self.db)
        self.app.register_blueprint(second)
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["usuario_email"] = "admin@example.com"
        result = client.post("/admin/modulos/releases/upload", data={
            "jar": (io.BytesIO(sample_jar()), "hypeclient-test.jar")
        }, content_type="multipart/form-data")
        self.assertEqual(result.status_code, 302)
        self.assertEqual(len(self.db.saved), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_basic_upload_does_not_run_advanced_protection(self):
        self.login()
        with patch("modules.hype_mod_staging.check_fabric_classes",
                   side_effect=AssertionError("advanced scan not requested")):
            response = self.upload()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.db.saved), 1)
        self.assertEqual(self.db.saved[0]["meta"]["static_audit"]["status"], "not_requested")

    def test_public_bucket_blocks_upload(self):
        self.login()
        self.db.storage.is_public = True
        response = self.upload()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.saved, [])
        self.assertEqual(self.db.storage.uploads, [])


if __name__ == "__main__":
    unittest.main()
