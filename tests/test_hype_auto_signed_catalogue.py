"""Offline tests for the opt-in Render-held Ed25519 bootstrap signer."""
import base64
import hashlib
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, NoEncryption, PublicFormat,
)

from modules import hype_signed_release as signed
from modules.hype_auto_signed_catalogue import (
    AutoCatalogUnavailable, signed_catalog_for_uploaded_client,
    uploaded_client_binary,
)
from modules.hype_mod_catalog import verify_signed_catalogue
from modules.hype_updates import _auto_client_distribution_enabled


def jar():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({
            "schemaVersion": 1, "id": "hypeclient",
            "version": "1.4", "name": "HYPE Client",
        }))
        archive.writestr("assets/padding.bin", b"X" * 1400)
    return buffer.getvalue()


class Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_):
        return self

    def eq(self, field, value):
        self.rows = [r for r in self.rows if r.get(field) == value]
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, number):
        self.rows = self.rows[:number]
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class Storage:
    def __init__(self, blobs):
        self.blobs = blobs

    def from_(self, bucket):
        assert bucket == "hype-mod-originals"
        return self

    def download(self, path):
        return self.blobs[path]


class Db:
    def __init__(self, row, data):
        self.row = row
        self.storage = Storage({row["storage_path"]: data})

    def table(self, table):
        assert table == "hype_mod_release_drafts"
        return Query([self.row.copy()])


class RenderSignerTests(unittest.TestCase):
    def setUp(self):
        self.data = jar()
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.row = {
            "module_id": "hypeclient", "version": "1.4", "sha256": self.sha,
            "size_bytes": len(self.data), "status": "aguardando_protecao",
            "storage_path": f"hypeclient/{'a' * 32}/{self.sha}.jar",
            "meta": {"library_upload": True},
            "created_at": "2026-11-25T22:00:00Z",
        }
        self.db = Db(self.row, self.data)
        self.key = Ed25519PrivateKey.generate()
        private_pem = self.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        self.env = patch.dict(os.environ, {
            "HYPE_AUTO_SIGNING_PRIVATE_KEY_PEM_B64": base64.b64encode(private_pem).decode(),
        })
        self.public = patch.object(
            signed, "PUBLIC_KEY_DER_B64",
            base64.b64encode(self.key.public_key().public_bytes(
                Encoding.DER, PublicFormat.SubjectPublicKeyInfo,
            )).decode(),
        )
        self.env.start()
        self.public.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.public.stop)

    def test_catalog_has_verified_signature_and_proper_download_url(self):
        raw = signed_catalog_for_uploaded_client(self.db)
        cat = verify_signed_catalogue(raw)
        self.assertEqual(cat["mods"][0]["sha256"], self.sha)
        self.assertEqual(cat["mods"][0]["version"], "1.4")
        self.assertTrue(cat["mods"][0]["required"])

    def test_download_validates_binary_and_hash(self):
        self.assertEqual(uploaded_client_binary(self.db, self.sha), self.data)
        self.db.storage.blobs[self.row["storage_path"]] = b"corrupted"
        with self.assertRaises(AutoCatalogUnavailable):
            uploaded_client_binary(self.db, self.sha)

    def test_rejected_or_non_library_record_never_published(self):
        self.row["status"] = "rejeitado"
        with self.assertRaises(AutoCatalogUnavailable):
            signed_catalog_for_uploaded_client(Db(self.row, self.data))
        self.row["status"] = "aguardando_protecao"
        self.row["meta"] = {"library_upload": False}
        with self.assertRaises(AutoCatalogUnavailable):
            signed_catalog_for_uploaded_client(Db(self.row, self.data))

    def test_different_public_key_rejected(self):
        with patch.object(signed, "PUBLIC_KEY_DER_B64", base64.b64encode(
            Ed25519PrivateKey.generate().public_key().public_bytes(
                Encoding.DER, PublicFormat.SubjectPublicKeyInfo,
            )).decode()):
            with self.assertRaises(AutoCatalogUnavailable):
                signed_catalog_for_uploaded_client(self.db)

    def test_both_distribution_switches_are_required(self):
        for flag_a, flag_b, expected in [
            ("0", "0", False), ("1", "0", False), ("0", "1", False), ("1", "1", True),
        ]:
            with patch.dict(os.environ, {
                "HYPE_AUTO_SIGNED_CATALOG_ENABLED": flag_a,
                "HYPE_AUTO_SIGNED_DOWNLOADS_ENABLED": flag_b,
            }):
                self.assertEqual(_auto_client_distribution_enabled(), expected)


if __name__ == "__main__":
    unittest.main()
