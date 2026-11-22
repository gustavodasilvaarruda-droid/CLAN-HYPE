"""End-to-end contract tests for reusing a privately stored candidate JAR.

No Fabric code is executed and no update is ever published.
"""
import hashlib
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from flask import Blueprint, Flask
from modules.hype_mod_staging import register_mod_release_routes


def fake_jar(body: bytes, version="R7.19-TEST"):
    meta = {
        "id": "hypeclient", "version": version,
        "depends": {"minecraft": "1.21.1"},
        "entrypoints": {"client": ["br.clanhype.client.HypeClient"]},
    }
    buff = io.BytesIO()
    with ZipFile(buff, "w", ZIP_DEFLATED) as jar:
        jar.writestr("fabric.mod.json", json.dumps(meta))
        jar.writestr("br/clanhype/client/HypeClient.class", bytes.fromhex("cafebabe"))
        jar.writestr("br/clanhype/client/update/HypeAutoUpdateClient.class",
                     bytes.fromhex("cafebabe"))
        jar.writestr("asset.txt", body)
    return buff.getvalue()


class Storage:
    def __init__(self):
        self.files = {}

    def get_bucket(self, _name):
        return {"public": False}

    def from_(self, _name):
        return self

    def download(self, path):
        return self.files[path]

    def upload(self, *, path, file, file_options):
        if path in self.files:
            raise AssertionError("Overwriting an existing private artifact")
        self.files[path] = file

    def remove(self, paths):
        for path in paths:
            self.files.pop(path, None)


class Query:
    def __init__(self, db):
        self.db = db
        self.predicates = []
        self.change = None

    def select(self, *_fields):
        return self

    def eq(self, field, value):
        self.predicates.append((field, value))
        return self

    def limit(self, _n):
        return self

    def order(self, *_a, **_kw):
        return self

    def update(self, change):
        self.change = change
        return self

    def execute(self):
        items = [r for r in self.db.rows.values()
                 if all(r.get(key) == val for key, val in self.predicates)]
        if self.change is not None:
            for item in items:
                item.update(self.change)
        return SimpleNamespace(data=[item.copy() for item in items])


class DB:
    def __init__(self):
        self.storage = Storage()
        self.original_id = str(uuid4())
        self.candidate_id = str(uuid4())
        self.original = fake_jar(b"source")
        self.candidate = fake_jar(b"obfuscated")
        self.rows = {}
        for draft_id, label, raw in (
            (self.original_id, "ORIGINAL.jar", self.original),
            (self.candidate_id, "PROTEGIDO-PILOTO.jar", self.candidate),
        ):
            path = f"hypeclient/{draft_id}.jar"
            self.storage.files[path] = raw
            self.rows[draft_id] = {
                "id": draft_id,
                "module_id": "hypeclient",
                "version": "R7.19-TEST",
                "status": "em_teste",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "storage_path": path,
                "original_filename": label,
                "meta": {},
            }

    def table(self, name):
        if name != "hype_mod_release_drafts":
            raise AssertionError("Unexpected table")
        return Query(self)


class ReuseCandidateTests(unittest.TestCase):
    def setUp(self):
        flags = patch.dict(os.environ, {
            "HYPE_MOD_STAGING_ENABLED": "1",
            "HYPE_MOD_PROTECTED_UPLOAD_ENABLED": "1",
            "HYPE_MOD_PUBLISH_ENABLED": "0",
        })
        flags.start()
        self.addCleanup(flags.stop)
        self.db = DB()
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="testing")
        bp = Blueprint("hype_mod_admin", __name__)

        @bp.get("/admin/modulos")
        def painel():
            return "ok"

        register_mod_release_routes(bp, lambda: True, None, self.db)
        app.register_blueprint(bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["usuario_email"] = "tester@example.com"

    def link(self, original=None, candidate=None):
        return self.client.post("/admin/modulos/releases/vincular-existente", data={
            "draft_id": original or self.db.original_id,
            "source_id": candidate or self.db.candidate_id,
        })

    def test_copies_existing_candidate_to_new_private_path_with_sha_audit(self):
        result = self.link()
        self.assertEqual(result.status_code, 302)
        protected = self.db.rows[self.db.original_id]["meta"]["protected"]
        self.assertEqual(protected["sha256"], hashlib.sha256(self.db.candidate).hexdigest())
        self.assertEqual(protected["source_draft_id"], self.db.candidate_id)
        self.assertEqual(self.db.storage.files[protected["storage_path"]], self.db.candidate)
        self.assertEqual(self.db.rows[self.db.original_id]["meta"]["automatic_review"]["status"],
                         "passed")
        self.assertEqual(self.db.rows[self.db.candidate_id]["meta"], {})
        self.assertEqual(self.db.rows[self.db.original_id]["status"], "em_teste")

    def test_cannot_link_file_to_itself_or_duplicate_candidate(self):
        self.link(original=self.db.candidate_id, candidate=self.db.candidate_id)
        self.assertNotIn("protected", self.db.rows[self.db.candidate_id]["meta"])
        self.link()
        original_copy = self.db.rows[self.db.original_id]["meta"]["protected"].copy()
        self.link()
        self.assertEqual(original_copy, self.db.rows[self.db.original_id]["meta"]["protected"])

    def test_mismatched_version_never_links(self):
        self.db.rows[self.db.candidate_id]["version"] = "other-version"
        self.link()
        self.assertNotIn("protected", self.db.rows[self.db.original_id]["meta"])

    def test_inspection_keeps_actual_stored_drafts_in_view(self):
        def fake_template(_name, **kwargs):
            return "stored=" + str(len(kwargs["drafts"]))
        with patch("modules.hype_mod_staging.render_template", side_effect=fake_template):
            response = self.client.post("/admin/modulos/releases/analisar", data={
                "jar": (io.BytesIO(self.db.original), "ORIGINAL.jar"),
            }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"stored=2", response.data)


if __name__ == "__main__":
    unittest.main()
