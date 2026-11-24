"""Tests for the one-screen HYPE release upload; no public release is created."""
import hashlib
import io
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from flask import Blueprint, Flask
from jinja2 import Environment
from modules.hype_mod_staging import TABLE, register_mod_release_routes
from modules.hype_mod_protection_queue import JOBS


def jar_bytes(label, version="1.0"):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({
            "schemaVersion": 1, "id": "hype_pokedex", "version": version,
        }))
        archive.writestr("br/hype/Pokedex.class", label.encode("utf-8"))
    return stream.getvalue()


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters = []
        self.values = None

    def select(self, *_fields):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, _count):
        return self

    def update(self, values):
        self.values = values
        return self

    def execute(self):
        found = [row for row in self.db.rows[self.table]
                 if all(row.get(k) == v for k, v in self.filters)]
        if self.values is not None:
            for row in found:
                row.update(self.values)
        return SimpleNamespace(data=[dict(row) for row in found])


class FakeStorage:
    def __init__(self, stored):
        self.stored = stored
        self.added = []

    def get_bucket(self, _bucket):
        return {"public": False}

    def from_(self, _bucket):
        return self

    def download(self, path):
        return self.stored[path]

    def upload(self, path, file, file_options):
        assert file_options["upsert"] == "false"
        self.stored[path] = file
        self.added.append(path)

    def remove(self, paths):
        for path in paths:
            self.stored.pop(path, None)


class FakeDB:
    def __init__(self):
        original = jar_bytes("original")
        sha = hashlib.sha256(original).hexdigest()
        path = f"hype_pokedex/{'b' * 32}/{sha}.jar"
        self.rows = {
            TABLE: [{
                "id": 21, "module_id": "hype_pokedex", "version": "1.0",
                "sha256": sha, "storage_path": path, "status": "aguardando_protecao",
                "meta": {},
            }],
            JOBS: [],
        }
        self.storage = FakeStorage({path: original})

    def table(self, name):
        return FakeQuery(self, name)


class QuickReleaseFlowTests(unittest.TestCase):
    def make_client(self, *, queue_enabled=False):
        self.db = FakeDB()
        environment = patch.dict(os.environ, {
            "HYPE_MOD_STAGING_ENABLED": "1",
            "HYPE_MOD_PROTECTED_UPLOAD_ENABLED": "1",
            "HYPE_MOD_PROTECTION_QUEUE_ENABLED": "1" if queue_enabled else "0",
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "off",
        })
        environment.start()
        self.addCleanup(environment.stop)
        app = Flask(__name__)
        app.secret_key = "isolated-unit-test-key"
        app.testing = True
        bp = Blueprint("hype_mod_admin", __name__)
        register_mod_release_routes(bp, lambda: True, None, db=self.db)
        app.register_blueprint(bp)
        client = app.test_client()
        with client.session_transaction() as session:
            session["usuario_email"] = "owner@example.com"
        return client

    def upload(self, client, raw):
        with patch("modules.hype_mod_staging.check_candidate_compatibility",
                   return_value={"entrypoints_checked": 1}), patch(
                     "modules.hype_mod_staging.audit_candidate_pair",
                     return_value={"status": "passed", "entrypoints_checked": 1}):
            return client.post("/admin/modulos/releases/protegido", data={
                "draft_id": "21",
                "jar": (io.BytesIO(raw), "hype_pokedex-protected.jar"),
            }, content_type="multipart/form-data")

    def test_pending_original_one_step_to_protected_candidate(self):
        client = self.make_client()
        result = self.upload(client, jar_bytes("protected"))
        self.assertEqual(result.status_code, 302)
        row = self.db.rows[TABLE][0]
        self.assertEqual(row["status"], "em_teste")
        self.assertEqual(row["meta"]["protected"]["sha256"],
                         hashlib.sha256(jar_bytes("protected")).hexdigest())
        self.assertEqual(row["meta"]["automatic_review"]["status"], "passed")
        self.assertEqual(len(self.db.storage.added), 1)
        self.assertNotIn("pilot_original", row["meta"])
        self.assertNotIn("manual_review", row["meta"])

    def test_version_mismatch_does_not_change_original(self):
        client = self.make_client()
        result = self.upload(client, jar_bytes("different", "9.9"))
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.db.rows[TABLE][0]["status"], "aguardando_protecao")
        self.assertNotIn("protected", self.db.rows[TABLE][0]["meta"])
        self.assertEqual(self.db.storage.added, [])

    def test_queue_job_blocks_manual_protected_upload(self):
        client = self.make_client(queue_enabled=True)
        self.db.rows[JOBS].append({"draft_id": "21", "status": "queued"})
        result = self.upload(client, jar_bytes("protected"))
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.db.rows[TABLE][0]["status"], "aguardando_protecao")
        self.assertEqual(self.db.storage.added, [])

    def test_approved_original_cannot_receive_candidate(self):
        client = self.make_client()
        self.db.rows[TABLE][0]["status"] = "pronto_para_aprovacao"
        self.upload(client, jar_bytes("protected"))
        self.assertEqual(self.db.rows[TABLE][0]["status"], "pronto_para_aprovacao")
        self.assertEqual(self.db.storage.added, [])

    def test_direct_publishing_replaces_legacy_private_channel(self):
        template = (Path(__file__).resolve().parents[1] /
                    "templates" / "admin_hype_mod_releases.html").read_text(encoding="utf-8")
        Environment().parse(template)
        self.assertIn('id="hpub-publish"', template)
        self.assertIn('id="hpub-private-test"', template)
        self.assertIn('id="hpub-protected-release"', template)
        self.assertIn('Não precisa do JAR protegido', template)
        self.assertEqual(template.count("url_for('hype_mod_admin.mod_release_publish_original_pilot')"), 1)
        self.assertEqual(template.count("url_for('hype_mod_admin.mod_release_publish_private')"), 1)
        self.assertNotIn("Canal privado: Pokédex", template)
        self.assertIn('name="confirm_pilot"', template)
        self.assertIn('name="confirm_release"', template)
        self.assertIn('href="#hpub-publish"', template)

    def test_template_contains_quick_actions_and_valid_jinja(self):
        template = (Path(__file__).resolve().parents[1] /
                    "templates" / "admin_hype_mod_releases.html").read_text(encoding="utf-8")
        Environment().parse(template)
        for marker in ('id="hpub-quick"', 'id="hpub-advanced"',
                       'data-hpub-mode="original"', 'data-hpub-mode="protected"',
                       'data-hpub-new-version', 'data-hpub-select-protected',
                       'mod_release_delete', 'mod_release_upload'):
            self.assertIn(marker, template)


if __name__ == "__main__":
    unittest.main()
