"""Contract and route tests for the opt-in multi-mod HYPE signed catalogue."""
import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from flask import Flask

from modules import hype_signed_release as signed
from modules.hype_mod_catalog import InvalidCatalogue, verify_signed_catalogue
from modules.hype_updates import hype_updates_bp


def mod(mod_id, *, depends_on=(), required=True):
    sha = hashlib.sha256(mod_id.encode()).hexdigest()
    return {
        "id": mod_id, "version": "2.0.1", "sha256": sha, "size": 2048,
        "url": f"https://clan-hype.onrender.com/hype-updates/mods/{mod_id}/{sha}.jar",
        "required": required, "depends_on": list(depends_on),
    }


class SignedCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        der = self.key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        key_patch = patch.object(
            signed, "PUBLIC_KEY_DER_B64", base64.b64encode(der).decode("ascii")
        )
        key_patch.start()
        self.addCleanup(key_patch.stop)
        self.unsigned = {
            "schema": 1,
            "minecraft": "1.21.1",
            "channel": "stable",
            "mods": [
                mod("hypeclient"),
                mod("hype_pokedex", depends_on=("hypeclient",)),
            ],
        }

    def signed_document(self, unsigned=None):
        data = self.unsigned if unsigned is None else unsigned
        canonical = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        envelope = dict(data)
        envelope["signature"] = base64.b64encode(
            self.key.sign(canonical)
        ).decode("ascii")
        return json.dumps(envelope, ensure_ascii=False).encode("utf-8")

    def test_two_mods_signed_catalogue_is_valid(self):
        parsed = verify_signed_catalogue(self.signed_document())
        self.assertEqual(len(parsed["mods"]), 2)
        self.assertEqual(parsed["mods"][1]["depends_on"], ["hypeclient"])

    def test_modified_data_is_rejected_even_when_signature_is_well_formed(self):
        raw = self.signed_document()
        tampered = raw.replace(b"2.0.1", b"2.0.2", 1)
        with self.assertRaises(InvalidCatalogue):
            verify_signed_catalogue(tampered)

    def test_nonofficial_url_duplicate_id_and_missing_dependency_rejected(self):
        for change in ("url", "duplicate", "dependency", "cycle", "unrequired_client"):
            unsigned = json.loads(json.dumps(self.unsigned))
            if change == "url":
                unsigned["mods"][1]["url"] = "https://example.com/malicious.jar"
            elif change == "duplicate":
                unsigned["mods"][1] = unsigned["mods"][0]
            elif change == "dependency":
                unsigned["mods"] = unsigned["mods"][:1]
                unsigned["mods"][0]["depends_on"] = ["hype_pokedex"]
            elif change == "cycle":
                unsigned["mods"][0]["depends_on"] = ["hype_pokedex"]
            else:
                unsigned["mods"][0]["required"] = False
            with self.subTest(change=change), self.assertRaises(InvalidCatalogue):
                verify_signed_catalogue(self.signed_document(unsigned))

    def test_duplicate_json_keys_and_bad_type_rejected(self):
        raw = self.signed_document()
        duplicated = raw.replace(b'"schema": 1', b'"schema": 1, "schema": 1', 1)
        with self.assertRaises(InvalidCatalogue):
            verify_signed_catalogue(duplicated)
        unsigned = json.loads(json.dumps(self.unsigned))
        unsigned["mods"][1]["size"] = True
        with self.assertRaises(InvalidCatalogue):
            verify_signed_catalogue(self.signed_document(unsigned))

    def test_read_only_route_is_disabled_by_default_and_requires_signed_file(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name) / "mods"
        folder.mkdir()
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(hype_updates_bp)
        client = app.test_client()

        with patch.dict(os.environ, {
            "HYPE_UPDATES_DIR": temp.name, "HYPE_MULTI_MOD_CATALOG_ENABLED": ""
        }):
            self.assertEqual(client.get("/hype-updates/mods/catalog.json").status_code, 404)
            self.assertEqual(client.post("/hype-updates/mods/catalog.json").status_code, 405)

        with patch.dict(os.environ, {
            "HYPE_UPDATES_DIR": temp.name, "HYPE_MULTI_MOD_CATALOG_ENABLED": "1"
        }):
            self.assertEqual(client.get("/hype-updates/mods/catalog.json").status_code, 404)
            (folder / "catalog.json").write_bytes(self.signed_document())
            response = client.get("/hype-updates/mods/catalog.json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["mods"][0]["id"], "hypeclient")
            self.assertIn("no-store", response.headers["Cache-Control"])
            (folder / "catalog.json").write_bytes(b"unsigned")
            self.assertEqual(client.get("/hype-updates/mods/catalog.json").status_code, 503)


    def test_binary_download_is_opt_in_and_requires_signed_listing_and_hash(self):
        import io
        from zipfile import ZipFile

        with tempfile.TemporaryDirectory() as home:
            mods = Path(home) / "mods"
            mods.mkdir()
            payload = io.BytesIO()
            with ZipFile(payload, "w") as zf:
                zf.writestr("fabric.mod.json", '{"schemaVersion":1,"id":"hype_pokedex"}')
                zf.writestr("test.bin", b"x" * 3000)
            jar = payload.getvalue()
            sha = hashlib.sha256(jar).hexdigest()
            entry = mod("hype_pokedex", depends_on=("hypeclient",))
            entry.update({
                "sha256": sha, "size": len(jar),
                "url": f"https://clan-hype.onrender.com/hype-updates/mods/hype_pokedex/{sha}.jar"
            })
            unsigned = dict(self.unsigned, mods=[mod("hypeclient"), entry])
            (mods / "catalog.json").write_bytes(self.signed_document(unsigned))
            target = mods / "hype_pokedex"
            target.mkdir()
            (target / f"{sha}.jar").write_bytes(jar)
            app = Flask(__name__)
            app.config["TESTING"] = True
            app.register_blueprint(hype_updates_bp)
            client = app.test_client()
            endpoint = f"/hype-updates/mods/hype_pokedex/{sha}.jar"

            with patch.dict(os.environ, {
                "HYPE_UPDATES_DIR": home,
                "HYPE_MULTI_MOD_CATALOG_ENABLED": "1",
                "HYPE_MULTI_MOD_DOWNLOADS_ENABLED": ""
            }):
                self.assertEqual(client.get(endpoint).status_code, 404)
            with patch.dict(os.environ, {
                "HYPE_UPDATES_DIR": home,
                "HYPE_MULTI_MOD_CATALOG_ENABLED": "1",
                "HYPE_MULTI_MOD_DOWNLOADS_ENABLED": "1"
            }):
                res = client.get(endpoint)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.data, jar)
                self.assertIn("immutable", res.headers["Cache-Control"])
                self.assertEqual(client.get(
                    f"/hype-updates/mods/hype_pokedex/{'0' * 64}.jar"
                ).status_code, 404)
                (target / f"{sha}.jar").write_bytes(b"corrupt")
                self.assertEqual(client.get(endpoint).status_code, 503)
                (target / f"{sha}.jar").write_bytes(jar)
                (mods / "catalog.json").write_bytes(b"not signed")
                self.assertEqual(client.get(endpoint).status_code, 503)


if __name__ == "__main__":
    unittest.main()
