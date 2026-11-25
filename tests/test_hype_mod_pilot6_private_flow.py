"""The owner can retry a stored original and test a protected candidate without publishing."""
import hashlib
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from flask import Blueprint, Flask
from modules.hype_mod_staging import register_mod_release_routes


def jar(marker):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({
            "id": "hypeclient", "version": "pilot6-test",
            "entrypoints": {"client": [
                "br.clanhype.client.HypeClient",
                "br.clanhype.client.update.HypeAutoUpdateClient",
            ]},
            "depends": {"minecraft": "1.21.1", "java": ">=21"},
        }))
        archive.writestr("br/clanhype/client/HypeClient.class", b"\\xca\\xfe\\xba\\xbe" + b"x" * 1024)
        archive.writestr("br/clanhype/client/update/HypeAutoUpdateClient.class",
                         b"\\xca\\xfe\\xba\\xbe" + b"y" * 1024)
        archive.writestr("assets/hype/test.txt", marker * 64)
    return output.getvalue()


class Storage:
    def __init__(self):
        self.public = False
        self.blobs = {}

    def get_bucket(self, name):
        assert name == "hype-mod-originals"
        return {"public": self.public}

    def from_(self, name):
        assert name == "hype-mod-originals"
        return self

    def download(self, path):
        return self.blobs[path]


class Query:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.filters = []
        self.changes = None

    def select(self, *_fields):
        return self

    def eq(self, name, value):
        self.filters.append((name, value))
        return self

    def limit(self, _limit):
        return self

    def update(self, changes):
        self.changes = changes
        return self

    def execute(self):
        rows = self.db.rows[self.name]
        matched = [item for item in rows if all(item.get(k) == v for k, v in self.filters)]
        if self.changes:
            for item in matched:
                item.update(self.changes)
        return SimpleNamespace(data=[dict(item) for item in matched])


class Database:
    def __init__(self):
        self.storage = Storage()
        self.rows = {
            "hype_mod_release_drafts": [],
            "hype_mod_published_releases": [],
            "hype_mod_restricted_releases": [],
            "hype_mod_protection_jobs": [],
        }

    def table(self, name):
        return Query(self, name)


class ClientPilotSixPrivateTests(unittest.TestCase):
    def setUp(self):
        flags = patch.dict(os.environ, {
            "HYPE_MOD_STAGING_ENABLED": "1",
            "HYPE_MOD_PROTECTED_UPLOAD_ENABLED": "1",
            "HYPE_MOD_PUBLISH_ENABLED": "0",
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "off",
        })
        flags.start()
        self.addCleanup(flags.stop)
        self.db = Database()
        self.original = jar(b"original")
        self.protected = jar(b"protected")
        self.origsha = hashlib.sha256(self.original).hexdigest()
        self.protsha = hashlib.sha256(self.protected).hexdigest()
        self.id = str(uuid4())
        self.origpath = f"hypeclient/{'a'*32}/{self.origsha}.jar"
        self.protpath = f"hypeclient/{self.id}/protected/{'b'*32}/{self.protsha}.jar"
        self.db.storage.blobs = {self.origpath: self.original, self.protpath: self.protected}
        self.record = {
            "id": self.id, "module_id": "hypeclient", "version": "pilot6-test",
            "status": "rejeitado", "sha256": self.origsha,
            "size_bytes": len(self.original), "storage_path": self.origpath,
            "meta": {},
        }
        self.db.rows["hype_mod_release_drafts"].append(self.record)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="pilot-tests")
        bp = Blueprint("hype_mod_admin", __name__)
        @bp.get("/admin/modulos")
        def painel():
            return "ok"
        register_mod_release_routes(bp, lambda: True, None, self.db)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def login(self):
        with self.client.session_transaction() as sess:
            sess["usuario_email"] = "owner@example.com"

    def retry(self):
        return self.client.post("/admin/modulos/releases/reabrir-teste", data={
            "draft_id": self.id, "confirm_retry": "yes",
        })

    def ready_candidate(self):
        self.record["status"] = "em_teste"
        self.record["meta"] = {
            "protected": {"sha256": self.protsha, "storage_path": self.protpath,
                          "size_bytes": len(self.protected)},
            "automatic_review": {"status": "passed", "candidate_sha256": self.protsha},
        }

    def test_private_retry_requires_admin(self):
        self.assertEqual(self.retry().status_code, 403)
        self.assertEqual(self.record["status"], "rejeitado")

    def test_rejected_original_can_be_reused_without_new_upload(self):
        self.login()
        self.assertEqual(self.retry().status_code, 302)
        self.assertEqual(self.record["status"], "aguardando_protecao")
        self.assertEqual(self.db.rows["hype_mod_published_releases"], [])
        self.assertEqual(self.db.storage.blobs[self.origpath], self.original)

    def test_retry_never_undoes_published_or_protected_record(self):
        self.login()
        self.record["meta"]["protected"] = {"sha256": self.protsha}
        self.retry()
        self.assertEqual(self.record["status"], "rejeitado")
        self.record["meta"] = {}
        self.db.rows["hype_mod_published_releases"].append({"draft_id": self.id, "release": 1})
        self.retry()
        self.assertEqual(self.record["status"], "rejeitado")

    def test_private_candidate_download_requires_admin(self):
        self.ready_candidate()
        response = self.client.get(f"/admin/modulos/releases/protegido-teste/{self.id}")
        self.assertEqual(response.status_code, 403)

    def test_candidate_download_is_exact_hash_and_no_store(self):
        self.login()
        self.ready_candidate()
        result = self.client.get(f"/admin/modulos/releases/protegido-teste/{self.id}")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, self.protected)
        self.assertEqual(result.headers["Cache-Control"], "private, no-store, max-age=0")
        self.assertEqual(self.db.rows["hype_mod_published_releases"], [])

    def test_candidate_download_blocks_corrupt_or_rejected(self):
        self.login()
        self.ready_candidate()
        self.db.storage.blobs[self.protpath] = self.protected + b"unexpected"
        self.assertEqual(self.client.get(
            f"/admin/modulos/releases/protegido-teste/{self.id}"
        ).status_code, 404)
        self.db.storage.blobs[self.protpath] = self.protected
        self.record["status"] = "rejeitado"
        self.assertEqual(self.client.get(
            f"/admin/modulos/releases/protegido-teste/{self.id}"
        ).status_code, 404)

    def test_public_bucket_never_yields_test_jar(self):
        self.login()
        self.ready_candidate()
        self.db.storage.public = True
        self.assertEqual(self.client.get(
            f"/admin/modulos/releases/protegido-teste/{self.id}"
        ).status_code, 503)


if __name__ == "__main__":
    unittest.main()
