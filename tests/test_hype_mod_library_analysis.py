"""Regression tests for the private, read-only Meus Mods analysis export."""
import hashlib
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from flask import Blueprint, Flask

from modules.hype_mod_staging import register_mod_release_routes


def valid_jar():
    stream = io.BytesIO()
    with ZipFile(stream, "w") as jar:
        jar.writestr("fabric.mod.json", json.dumps({
            "schemaVersion": 1,
            "id": "hypeclient", "name": "HYPE Client", "version": "10.0.42",
            "depends": {"minecraft": "1.21.1", "fabricloader": ">=0.17.2"},
            "entrypoints": {"client": ["br.hype.client.Client"]},
        }))
        jar.writestr("br/hype/client/Client.class", b"example class for test")
        jar.writestr("assets/hypeclient/lang/pt_br.json", b"{}")
    return stream.getvalue()


class FakeStorage:
    def __init__(self, raw, path):
        self.raw, self.path = raw, path
        self.reads, self.writes, self.public = 0, 0, False

    def get_bucket(self, name):
        assert name == "hype-mod-originals"
        return {"public": self.public}

    def from_(self, name):
        assert name == "hype-mod-originals"
        return self

    def download(self, path):
        assert path == self.path
        self.reads += 1
        return self.raw

    def upload(self, **kwargs):
        self.writes += 1
        raise AssertionError("Analysis must never upload any JAR")

    def remove(self, paths):
        self.writes += 1
        raise AssertionError("Analysis must never delete any JAR")


class FakeQuery:
    def __init__(self, db):
        self.db, self.filters = db, []

    def select(self, *_fields):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, count):
        return self

    def execute(self):
        matches = [self.db.record] if all(
            self.db.record.get(column) == value for column, value in self.filters
        ) else []
        return SimpleNamespace(data=matches)


class FakeDB:
    def __init__(self):
        raw = valid_jar()
        sha = hashlib.sha256(raw).hexdigest()
        path = f"hypeclient/{'a' * 32}/{sha}.jar"
        self.record = {
            "id": 21,
            "module_id": "hypeclient",
            "version": "10.0.42",
            "sha256": sha,
            "size_bytes": len(raw),
            "storage_path": path,
            "original_filename": "HYPE-CLIENT-10.0.42.jar",
            "created_at": "2026-11-26T20:00:00Z",
            "status": "aguardando_protecao",
        }
        self.storage = FakeStorage(raw, path)

    def table(self, name):
        assert name == "hype_mod_release_drafts"
        return FakeQuery(self)


class LibraryAnalysisTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "HYPE_MOD_STAGING_ENABLED": "1",
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "off",
        })
        env.start()
        self.addCleanup(env.stop)
        self.db = FakeDB()
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="test-key")
        bp = Blueprint("hype_mod_admin", __name__)
        register_mod_release_routes(bp, lambda: True, None, self.db)
        app.register_blueprint(bp)
        self.client = app.test_client()
        self.url = "/admin/modulos/releases/arquivo/21/analisar"

    def login(self):
        with self.client.session_transaction() as session:
            session["usuario_email"] = "owner@example.com"

    def test_anonymous_cannot_read_private_binary_or_metadata(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.storage.reads, 0)
        self.assertEqual(self.client.get(self.url + "?formato=pacote").status_code, 403)

    def test_admin_gets_verified_static_report(self):
        self.login()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        report = response.get_json()
        self.assertEqual(report["mod"]["fabric_id"], "hypeclient")
        self.assertEqual(report["mod"]["version"], "10.0.42")
        self.assertEqual(report["mod"]["sha256"], self.db.record["sha256"])
        self.assertEqual(report["archive"]["class_count"], 1)
        self.assertEqual(report["fabric"]["depends"]["minecraft"], "1.21.1")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")
        self.assertEqual(self.db.storage.writes, 0)

    def test_owner_can_download_jar_with_report(self):
        self.login()
        response = self.client.get(self.url + "?formato=pacote")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        with ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["analise.json", "original.jar"])
            self.assertEqual(archive.read("original.jar"), valid_jar())
            report = json.loads(archive.read("analise.json"))
            self.assertEqual(report["mod"]["fabric_id"], "hypeclient")
            self.assertEqual(report["mod"]["sha256"], self.db.record["sha256"])
        self.assertEqual(self.db.storage.writes, 0)

    def test_draft_not_found_and_unexpected_format(self):
        self.login()
        self.assertEqual(self.client.get(
            "/admin/modulos/releases/arquivo/999/analisar"
        ).status_code, 404)
        self.assertEqual(self.client.get(self.url + "?formato=delete").status_code, 400)
        self.assertEqual(self.db.storage.writes, 0)

    def test_tampered_binary_is_rejected(self):
        self.login()
        self.db.storage.raw = b"not a jar"
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.db.storage.writes, 0)

    def test_unverified_storage_path_is_rejected(self):
        self.login()
        self.db.record["storage_path"] = "../secret.jar"
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.db.storage.reads, 0)

    def test_public_bucket_fails_closed(self):
        self.login()
        self.db.storage.public = True
        self.assertEqual(self.client.get(self.url).status_code, 503)
        self.assertEqual(self.db.storage.reads, 0)


if __name__ == "__main__":
    unittest.main()
