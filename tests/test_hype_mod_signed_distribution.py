"""Tests for signed HYPE Client manifests and managed read-only delivery."""
import base64
import hashlib
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from flask import Flask
from modules import hype_signed_release as signed
from modules.hype_updates import hype_updates_bp


class FakeQuery:
    def __init__(self, db):
        self.db = db
        self.filters = {}

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        rows = [r for r in self.db.rows if all(r.get(k) == v for k, v in self.filters.items())]
        return SimpleNamespace(data=rows)


class FakeStorage:
    def __init__(self, jar):
        self.jar = jar

    def from_(self, bucket):
        assert bucket == "hype-mod-originals"
        return self

    def download(self, path):
        assert path.startswith("hypeclient/")
        return self.jar


class FakeDb:
    def __init__(self, rows, jar):
        self.rows = rows
        self.storage = FakeStorage(jar)

    def table(self, name):
        assert name == "hype_mod_published_releases"
        return FakeQuery(self)


class SignedDistributionTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        der = self.key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        self.key_patch = patch.object(signed, "PUBLIC_KEY_DER_B64", base64.b64encode(der).decode())
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.jar = b"not-a-real-jar-for-delivery-test" * 45
        self.sha = hashlib.sha256(self.jar).hexdigest()
        self.version = "R7.19-ALPHA7-PREVIEW10.0.42-CHAVE-TESTE1"

    def manifest(self, release=3, url=None, sha=None, signature=True):
        values = {
            "release": str(release), "version": self.version,
            "url": url or f"{signed.ROOT_URL}hypeclient-r{release}.jar",
            "sha256": sha or self.sha, "size": str(len(self.jar)),
            "minecraft": "1.21.1", "mod_id": "hypeclient", "channel": "stable"
        }
        canonical = "".join(f"{key}={values[key]}\n" for key in signed.FIELDS).encode()
        sig = base64.b64encode(self.key.sign(canonical)).decode() if signature else "bad"
        return canonical + f"signature={sig}\n".encode()

    def test_signature_matches_client_canonical_order(self):
        parsed = signed.verify_signed_manifest(
            self.manifest(), version=self.version,
            sha256=self.sha, size_bytes=len(self.jar))
        self.assertEqual(parsed["release"], 3)
        self.assertEqual(parsed["filename"], "hypeclient-r3.jar")

    def test_unsigned_wrong_hash_and_wrong_host_are_rejected(self):
        samples = [
            self.manifest(signature=False),
            self.manifest(sha="0" * 64),
            self.manifest(url="https://wrong.example/hypeclient-r3.jar"),
            self.manifest() + b"release=4\n",
        ]
        for raw in samples:
            with self.subTest(raw=raw[-80:]), self.assertRaises(signed.InvalidRelease):
                signed.verify_signed_manifest(raw, version=self.version,
                                              sha256=self.sha, size_bytes=len(self.jar))

    def test_managed_manifest_and_jar_use_database_and_private_storage(self):
        manifest = self.manifest().decode()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.extensions["hype_release_db"] = FakeDb([{
            "release": 3, "manifest": manifest, "status": "published",
            "sha256": self.sha, "size_bytes": len(self.jar),
            "storage_path": f"hypeclient/a/{self.sha}.jar"
        }], self.jar)
        self.app.register_blueprint(hype_updates_bp)
        with patch.dict(os.environ, {"HYPE_MOD_DISTRIBUTION_ENABLED": "1"}):
            client = self.app.test_client()
            self.assertEqual(client.get("/hype-updates/manifest.properties").status_code, 200)
            self.assertEqual(client.get("/hype-updates/manifest.properties").data.decode(), manifest)
            response = client.get("/hype-updates/releases/hypeclient-r3.jar")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, self.jar)
            self.assertEqual(client.get("/hype-updates/releases/hypeclient-r4.jar").status_code, 404)

    def test_disabled_or_missing_release_never_falls_back_to_unmanaged_file(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.extensions["hype_release_db"] = FakeDb([], self.jar)
        app.register_blueprint(hype_updates_bp)
        with patch.dict(os.environ, {"HYPE_MOD_DISTRIBUTION_ENABLED": "1"}):
            self.assertEqual(app.test_client().get("/hype-updates/manifest.properties").status_code, 404)


if __name__ == "__main__":
    unittest.main()
