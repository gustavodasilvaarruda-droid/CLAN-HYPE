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

    def test_unbounded_registry_accepts_new_hype_mod_ids(self):
        unsigned = dict(self.unsigned, mods=[
            mod("hypeclient"),
            mod("hype_new_arena", depends_on=("hypeclient",)),
            mod("my_future_mod", depends_on=("hype_new_arena",)),
        ])
        self.assertEqual(
            len(verify_signed_catalogue(self.signed_document(unsigned))["mods"]), 3
        )

    def test_bad_module_id_path_is_rejected(self):
        for mod_id in ("../private", "a/b", "UPPER", "x" * 100, "hypebootstrap"):
            unsigned = dict(self.unsigned, mods=[mod("hypeclient"), mod(mod_id)])
            with self.subTest(mod_id=mod_id), self.assertRaises(InvalidCatalogue):
                verify_signed_catalogue(self.signed_document(unsigned))

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
            # A signed catalogue can contain any eligible publicly approved ID.
            response = client.get("/hype-updates/mods/catalog.json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json["mods"]), 2)
            only_client = dict(self.unsigned, mods=[mod("hypeclient")])
            (folder / "catalog.json").write_bytes(self.signed_document(only_client))
            response = client.get("/hype-updates/mods/catalog.json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["mods"][0]["id"], "hypeclient")
            self.assertIn("no-store", response.headers["Cache-Control"])
            (folder / "catalog.json").write_bytes(b"unsigned")
            self.assertEqual(client.get("/hype-updates/mods/catalog.json").status_code, 503)


    def test_binary_download_is_opt_in_and_never_serves_unlisted_mods(self):
        import io
        from zipfile import ZipFile

        with tempfile.TemporaryDirectory() as home:
            mods = Path(home) / "mods"
            mods.mkdir()
            payload = io.BytesIO()
            with ZipFile(payload, "w") as zf:
                zf.writestr("fabric.mod.json", '{"schemaVersion":1,"id":"hypeclient"}')
                zf.writestr("test.bin", b"x" * 3000)
            jar = payload.getvalue()
            sha = hashlib.sha256(jar).hexdigest()
            entry = mod("hypeclient")
            entry.update({
                "sha256": sha, "size": len(jar),
                "url": f"https://clan-hype.onrender.com/hype-updates/mods/hypeclient/{sha}.jar"
            })
            unsigned = dict(self.unsigned, mods=[
                entry, mod("hype_pokedex", depends_on=("hypeclient",))
            ])
            (mods / "catalog.json").write_bytes(self.signed_document(unsigned))
            target = mods / "hypeclient"
            target.mkdir()
            (target / f"{sha}.jar").write_bytes(jar)
            app = Flask(__name__)
            app.config["TESTING"] = True
            app.register_blueprint(hype_updates_bp)
            client = app.test_client()
            endpoint = f"/hype-updates/mods/hypeclient/{sha}.jar"

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
                # A private file not named in the signed catalogue is invisible.
                restricted = "/hype-updates/mods/hype_pokedex/" + "0" * 64 + ".jar"
                self.assertEqual(client.get(restricted).status_code, 404)
                res = client.get(endpoint)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.data, jar)
                self.assertIn("immutable", res.headers["Cache-Control"])
                self.assertEqual(client.get(
                    f"/hype-updates/mods/hypeclient/{'0' * 64}.jar"
                ).status_code, 404)
                (target / f"{sha}.jar").write_bytes(b"corrupt")
                self.assertEqual(client.get(endpoint).status_code, 503)
                (target / f"{sha}.jar").write_bytes(jar)
                (mods / "catalog.json").write_bytes(b"not signed")
                self.assertEqual(client.get(endpoint).status_code, 503)


    def test_public_signed_new_mod_binary_can_be_downloaded(self):
        import io
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory() as home:
            mods_dir = Path(home) / "mods"
            mods_dir.mkdir()
            items = []
            for mod_id in ("hypeclient", "hype_future_module"):
                output = io.BytesIO()
                with ZipFile(output, "w") as archive:
                    archive.writestr("fabric.mod.json", json.dumps({
                        "schemaVersion": 1, "id": mod_id, "version": "2.0.1"
                    }))
                    archive.writestr("content.bin", b"x" * 3000)
                data = output.getvalue()
                sha = hashlib.sha256(data).hexdigest()
                (mods_dir / mod_id).mkdir()
                (mods_dir / mod_id / f"{sha}.jar").write_bytes(data)
                item = mod(mod_id, depends_on=("hypeclient",) if mod_id != "hypeclient" else ())
                item.update({
                    "sha256": sha, "size": len(data),
                    "url": f"https://clan-hype.onrender.com/hype-updates/mods/{mod_id}/{sha}.jar"
                })
                items.append(item)
            (mods_dir / "catalog.json").write_bytes(
                self.signed_document(dict(self.unsigned, mods=items))
            )
            app = Flask(__name__)
            app.config["TESTING"] = True
            app.register_blueprint(hype_updates_bp)
            with patch.dict(os.environ, {
                "HYPE_UPDATES_DIR": home,
                "HYPE_MULTI_MOD_CATALOG_ENABLED": "1",
                "HYPE_MULTI_MOD_DOWNLOADS_ENABLED": "1",
            }):
                res = app.test_client().get("/hype-updates/mods/hype_future_module/" +
                    items[1]["sha256"] + ".jar")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(hashlib.sha256(res.data).hexdigest(), items[1]["sha256"])


    def test_persistent_supabase_bucket_serves_only_signed_approved_artifacts(self):
        import io
        from types import SimpleNamespace
        from zipfile import ZipFile

        class FakePrivateStorage:
            public = False

            def __init__(self, objects):
                self.objects = objects
                self.used_buckets = []

            def get_bucket(self, name):
                self.used_buckets.append(name)
                if name != "hype-mod-distribution":
                    raise AssertionError("Private originals MUST NOT be accessed")
                return {"public": self.public}

            def from_(self, name):
                self.used_buckets.append(name)
                if name != "hype-mod-distribution":
                    raise AssertionError("Unexpected storage bucket")
                return self

            def download(self, path):
                return self.objects[path]

        entries, files = [], {}
        for mid in ("hypeclient", "hype_new_module_2027"):
            output = io.BytesIO()
            with ZipFile(output, "w") as archive:
                archive.writestr("fabric.mod.json", json.dumps({
                    "schemaVersion": 1, "id": mid, "version": "2.0.1"
                }))
                archive.writestr("content.bin", b"x" * 3000)
            content = output.getvalue()
            sha = hashlib.sha256(content).hexdigest()
            item = mod(mid, depends_on=("hypeclient",) if mid != "hypeclient" else ())
            item.update({
                "sha256": sha, "size": len(content),
                "url": f"https://clan-hype.onrender.com/hype-updates/mods/{mid}/{sha}.jar"
            })
            entries.append(item)
            files[f"stable/1.21.1/mods/{mid}/{sha}.jar"] = content
        cat_path = "stable/1.21.1/catalog.json"
        files[cat_path] = self.signed_document(dict(self.unsigned, mods=entries))
        store = FakePrivateStorage(files)

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(hype_updates_bp)
        app.extensions["hype_release_db"] = SimpleNamespace(storage=store)
        client = app.test_client()
        allowed = {
            "HYPE_MULTI_MOD_PUBLIC_STORAGE_ENABLED": "1",
            "HYPE_MULTI_MOD_CATALOG_ENABLED": "1",
            "HYPE_MULTI_MOD_DOWNLOADS_ENABLED": "1",
        }
        with patch.dict(os.environ, allowed):
            catalog_response = client.get("/hype-updates/mods/catalog.json")
            self.assertEqual(catalog_response.status_code, 200)
            self.assertEqual(catalog_response.data, files[cat_path])
            self.assertEqual(len(catalog_response.json["mods"]), 2)
            path = "/hype-updates/mods/" + entries[1]["id"] + "/" + entries[1]["sha256"] + ".jar"
            self.assertEqual(client.get(path).data,
                             files["stable/1.21.1/mods/" + entries[1]["id"] +
                                   "/" + entries[1]["sha256"] + ".jar"])
            self.assertEqual(client.get(
                "/hype-updates/mods/hype_new_module_2027/" + "0" * 64 + ".jar"
            ).status_code, 404)

            # Invalid data in the distribution bucket can never reach players.
            key = "stable/1.21.1/mods/" + entries[1]["id"] + "/" + entries[1]["sha256"] + ".jar"
            original = files[key]
            files[key] = b"unapproved"
            self.assertEqual(client.get(path).status_code, 503)
            files[key] = original

            # An accidentally public storage bucket must fail closed.
            store.public = True
            self.assertEqual(client.get(path).status_code, 503)
            self.assertEqual(client.get("/hype-updates/mods/catalog.json").status_code, 503)
            store.public = False

            # Never return an unsigned or modified catalogue from storage.
            files[cat_path] = b"unsigned"
            self.assertEqual(client.get("/hype-updates/mods/catalog.json").status_code, 503)

        self.assertNotIn("hype-mod-originals", store.used_buckets)



if __name__ == "__main__":
    unittest.main()
