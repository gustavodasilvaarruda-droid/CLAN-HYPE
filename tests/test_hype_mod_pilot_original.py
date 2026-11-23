"""Isolated owner-only pilot tests, using the existing unittest CI runner."""
import base64
import hashlib
import io
import json
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile, ZIP_STORED

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from modules import hype_signed_release as signed
from modules import hype_manifest_signer as signer
from modules.hype_mod_pilot_original import (
    pilot_original_enabled, publish_pilot_original, find_pilot_original,
    download_pilot_original, InvalidPrivateRelease,
)

EMAIL = "test-owner@example.com"
MODULE = "hype_pokedex"


def jar_bytes(version):
    out = io.BytesIO()
    with ZipFile(out, "w", ZIP_STORED) as z:
        z.writestr("fabric.mod.json", json.dumps({
            "schemaVersion": 1, "id": MODULE, "version": version,
            "depends": {"minecraft": "1.21.1"},
        }))
        z.writestr("br/hype/Test.class", b"fake class data " * 128)
    return out.getvalue()


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.where, self.data, self.max_rows = [], None, None

    def select(self, *args): return self
    def eq(self, col, val):
        self.where.append((col, val))
        return self
    def order(self, *args, **kw): return self
    def limit(self, val):
        self.max_rows = val
        return self
    def update(self, data):
        self.data = data
        return self
    def execute(self):
        rows = [r for r in self.db.rows if all(r.get(k) == v for k, v in self.where)]
        if self.max_rows is not None:
            rows = rows[:self.max_rows]
        if self.data is not None:
            for row in rows:
                row.update(self.data)
        return SimpleNamespace(data=[dict(row) for row in rows])


class Storage:
    def __init__(self, jars):
        self.jars = jars
    def get_bucket(self, name): return {"public": False}
    def from_(self, name): return self
    def download(self, path): return self.jars[path]


class DB:
    def __init__(self, drafts, jars):
        self.rows, self.storage = drafts, Storage(jars)
    def table(self, name):
        assert name == "hype_mod_release_drafts"
        return Query(self, name)


def fixture_db(version="1.0"):
    raw = jar_bytes(version)
    sha = hashlib.sha256(raw).hexdigest()
    draft_id = str(uuid.uuid4())
    path = f"{MODULE}/{uuid.uuid4().hex}/{sha}.jar"
    draft = {
        "id": draft_id, "module_id": MODULE, "version": version,
        "status": "aguardando_protecao", "sha256": sha,
        "size_bytes": len(raw), "storage_path": path, "meta": {},
    }
    return DB([draft], {path: raw}), raw, draft


class OwnerPilotTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        pub = base64.b64encode(self.key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo,
        )).decode("ascii")
        self.patchers = [
            patch.object(signed, "PUBLIC_KEY_DER_B64", pub),
            patch.object(signer, "PUBLIC_KEY_DER_B64", pub),
            patch.dict(os.environ, {
                "HYPE_MOD_PILOT_ORIGINAL_ENABLED": "1",
                "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                "HYPE_PRIVATE_MOD_TESTER_EMAIL": EMAIL,
            }),
        ]
        for p in self.patchers: p.start()
        self.addCleanup(self.cleanup_patches)

    def cleanup_patches(self):
        for p in reversed(self.patchers): p.stop()

    def test_off_by_default(self):
        with patch.dict(os.environ, {"HYPE_MOD_PILOT_ORIGINAL_ENABLED": "0"}):
            self.assertFalse(pilot_original_enabled(EMAIL))

    def test_private_original_signed_publish_download(self):
        db, raw, draft = fixture_db()
        manifest = signer.sign_private_mod_manifest(raw, self.key, 1)
        row = publish_pilot_original(db, draft_id=draft["id"],
                                     manifest_bytes=manifest, published_by=EMAIL)
        self.assertEqual(row["sha256"], draft["sha256"])
        latest = find_pilot_original(db, MODULE)
        self.assertEqual(latest[1]["manifest"], manifest.decode("ascii"))
        self.assertEqual(download_pilot_original(db, latest[0]).read(), raw)
        self.assertIsNone(find_pilot_original(db, MODULE, sha256="a" * 64))

    def test_wrong_account_never_enabled(self):
        db, raw, draft = fixture_db()
        manifest = signer.sign_private_mod_manifest(raw, self.key, 3)
        self.assertFalse(pilot_original_enabled("another@example.com"))
        with self.assertRaises(InvalidPrivateRelease):
            publish_pilot_original(db, draft_id=draft["id"],
                                   manifest_bytes=manifest, published_by="another@example.com")

    def test_unsigned_manifest_rejected(self):
        db, raw, draft = fixture_db()
        manifest = signer.sign_private_mod_manifest(raw, self.key, 2)
        corrupted = manifest.replace(b"signature=", b"signature=AAAA", 1)
        with self.assertRaises(InvalidPrivateRelease):
            publish_pilot_original(db, draft_id=draft["id"],
                                   manifest_bytes=corrupted, published_by=EMAIL)

    def test_latest_release_increasing(self):
        db, raw, draft = fixture_db("1.0")
        publish_pilot_original(db, draft_id=draft["id"],
                               manifest_bytes=signer.sign_private_mod_manifest(raw, self.key, 4),
                               published_by=EMAIL)
        other, raw2, draft2 = fixture_db("1.1")
        db.rows += other.rows
        db.storage.jars.update(other.storage.jars)
        with self.assertRaises(InvalidPrivateRelease):
            publish_pilot_original(db, draft_id=draft2["id"],
                                   manifest_bytes=signer.sign_private_mod_manifest(raw2, self.key, 4),
                                   published_by=EMAIL)
        publish_pilot_original(db, draft_id=draft2["id"],
                               manifest_bytes=signer.sign_private_mod_manifest(raw2, self.key, 5),
                               published_by=EMAIL)
        self.assertEqual(find_pilot_original(db, MODULE)[1]["release"], 5)

    def test_tampered_original_never_served(self):
        db, raw, draft = fixture_db()
        publish_pilot_original(db, draft_id=draft["id"],
                               manifest_bytes=signer.sign_private_mod_manifest(raw, self.key, 1),
                               published_by=EMAIL)
        db.storage.jars[draft["storage_path"]] = raw + b"x"
        with self.assertRaises((ValueError, InvalidPrivateRelease)):
            download_pilot_original(db, db.rows[0])


if __name__ == "__main__":
    unittest.main()
