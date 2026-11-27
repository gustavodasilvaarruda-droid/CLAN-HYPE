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
    uploaded_client_binary, signed_catalog_for_uploaded_mods,
    uploaded_mod_binary, verify_auto_catalogue,
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
            "original_filename": "HYPE-CLIENT-1.4.jar",
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
        self.assertEqual(verify_auto_catalogue(signed_catalog_for_uploaded_mods(
            Db(self.row, self.data)))["mods"], [])
        self.row["status"] = "aguardando_protecao"
        self.row["meta"] = {"library_upload": False}
        self.assertEqual(verify_auto_catalogue(signed_catalog_for_uploaded_mods(
            Db(self.row, self.data)))["mods"], [])

    def test_admin_uploads_are_public_regardless_of_test_labels(self):
        from modules.hype_auto_signed_catalogue import _eligible
        filenames = (
            "HYPE-CLIENT-PILOTO-NAO-DISTRIBUIR.jar",
            "HYPE-POKEDEX-BETA8-TESTE.jar",
            "HYPE-BREED-PREVIEW03-VALIDACAO.jar",
            "HYPE-CAMPO-EXPERIMENTAL.jar",
            "HYPE-CLIENT-ALPHA7.jar",
            "HYPE-BATTLE-AI-3.0.0-rc.71.jar",
            "HYPE-CLIENT-NÃO DISTRIBUIR.jar",
        )
        for filename in filenames:
            with self.subTest(filename=filename):
                self.assertTrue(_eligible(dict(self.row, original_filename=filename)))
        for version in ("1.4-preview.3", "3.0.0-rc.71", "R7.19-ALPHA7-PREVIEW10.0.42"):
            with self.subTest(version=version):
                self.assertTrue(_eligible(dict(self.row, version=version)))
        for filename in (None, "../bad.jar", "folder/malicious.jar", "bad.txt"):
            with self.subTest(filename=filename):
                self.assertFalse(_eligible(dict(self.row, original_filename=filename)))

    def test_all_library_mods_are_included_even_experimental(self):
        from modules.hype_auto_signed_catalogue import latest_uploaded_mods
        rows = []
        for mod_id, version, filename in (
            ("hypeclient", "R7.19-ALPHA7-PREVIEW10.0.42", "PILOTO-NAO-DISTRIBUIR.jar"),
            ("hype_pokedex", "2.0.0-beta.8", "TESTE-POKEDEX.jar"),
            ("hype_breed_calculator", "2.0-preview.3", "BREED-VALIDACAO.jar"),
            ("hype_battlefield", "0.4.13-alpha.r5.3+3-terrains-v3", "CAMPO-EXPERIMENTAL.jar"),
            ("hype_battle_ai", "3.0.0-rc.71-v30.9q-forced-switch-repair", "BATTLE-AI.jar"),
            ("cobblemonextendedbattleui", "0.10.0", "BATTLE-UI.jar"),
        ):
            rows.append(dict(
                self.row, module_id=mod_id, version=version, original_filename=filename,
                storage_path=f"{mod_id}/{'a' * 32}/{self.sha}.jar",
            ))
        with patch("modules.hype_auto_signed_catalogue._uploaded_rows", return_value=rows):
            catalogue = verify_auto_catalogue(signed_catalog_for_uploaded_mods(self.db))
        self.assertEqual([item["id"] for item in catalogue["mods"]], [
            row["module_id"] for row in rows
        ])

    def test_external_hypeegg_never_enters_player_catalogue(self):
        from modules.hype_auto_signed_catalogue import _eligible, latest_uploaded_mods
        excluded = dict(
            self.row,
            module_id="hypeegg",
            version="1.5.1-preview66",
            original_filename="HYPE-EGG-TESTE.jar",
            storage_path=f"hypeegg/{'a' * 32}/{self.sha}.jar",
        )
        self.assertFalse(_eligible(excluded))
        with patch("modules.hype_auto_signed_catalogue._uploaded_rows",
                   return_value=[excluded, self.row]):
            document = verify_auto_catalogue(signed_catalog_for_uploaded_mods(self.db))
        self.assertEqual([item["id"] for item in document["mods"]], ["hypeclient"])

    def test_newest_admin_upload_wins_even_if_version_downgraded(self):
        from modules.hype_auto_signed_catalogue import latest_uploaded_mods
        latest = dict(self.row, version="0.5-alpha", original_filename="PILOTO.jar")
        older = dict(self.row, version="2.0", original_filename="PRODUCAO.jar")
        with patch("modules.hype_auto_signed_catalogue._uploaded_rows",
                   return_value=[latest, older]):
            self.assertEqual(latest_uploaded_mods(self.db)[0]["version"], "0.5-alpha")


    def test_other_fabric_mod_can_be_signed_and_downloaded(self):
        import copy
        row = copy.deepcopy(self.row)
        row["module_id"] = "hype_pokedex"
        row["storage_path"] = f"hype_pokedex/{'b' * 32}/{self.sha}.jar"
        # This JAR still carries hypeclient metadata so integrity checking fails.
        db = Db(row, self.data)
        signed_doc = verify_auto_catalogue(signed_catalog_for_uploaded_mods(db))
        self.assertEqual([x["id"] for x in signed_doc["mods"]], ["hype_pokedex"])
        with self.assertRaises(AutoCatalogUnavailable):
            uploaded_mod_binary(db, "hype_pokedex", self.sha)

    def test_different_public_key_rejected(self):
        with patch.object(signed, "PUBLIC_KEY_DER_B64", base64.b64encode(
            Ed25519PrivateKey.generate().public_key().public_bytes(
                Encoding.DER, PublicFormat.SubjectPublicKeyInfo,
            )).decode()):
            with self.assertRaises(AutoCatalogUnavailable):
                signed_catalog_for_uploaded_client(self.db)


    def test_protected_only_mode_does_not_list_unapproved_originals(self):
        with patch.dict(os.environ, {"HYPE_AUTO_REQUIRE_APPROVED_CANDIDATE": "1"}):
            doc = verify_auto_catalogue(signed_catalog_for_uploaded_mods(self.db))
            self.assertEqual(doc["mods"], [])
            with self.assertRaises(AutoCatalogUnavailable):
                uploaded_client_binary(self.db, self.sha)

    def test_protected_only_mode_serves_tested_candidate_not_original(self):
        buf = io.BytesIO()
        with ZipFile(buf, "w") as archive:
            archive.writestr("fabric.mod.json", json.dumps({
                "schemaVersion": 1, "id": "hypeclient", "version": "1.4",
                "name": "HYPE Client",
            }))
            archive.writestr("assets/padding.bin", b"Y" * 1400)
        candidate_bytes = buf.getvalue()
        candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
        draft_id = "a1b2c3d4-1234-4567-89ab-001122334455"
        path = f"hypeclient/{draft_id}/protected/{'b' * 32}/{candidate_sha}.jar"
        self.row.update(id=draft_id, status="pronto_para_aprovacao")
        self.row["meta"] = {
            "library_upload": True,
            "protected": {"storage_path": path, "sha256": candidate_sha,
                          "size_bytes": len(candidate_bytes)},
            "automatic_review": {"status": "passed", "candidate_sha256": candidate_sha},
            "manual_review": {"candidate_sha256": candidate_sha,
                              "checks": {"game_launch": True, "menus": True,
                                         "server_connection": True, "no_crashes": True}},
        }
        self.db.storage.blobs[path] = candidate_bytes
        with patch.dict(os.environ, {"HYPE_AUTO_REQUIRE_APPROVED_CANDIDATE": "1"}):
            cat = verify_auto_catalogue(signed_catalog_for_uploaded_mods(self.db))
            self.assertEqual(cat["mods"][0]["sha256"], candidate_sha)
            self.assertEqual(cat["mods"][0]["size"], len(candidate_bytes))
            self.assertEqual(uploaded_client_binary(self.db, candidate_sha), candidate_bytes)
            with self.assertRaises(AutoCatalogUnavailable):
                uploaded_client_binary(self.db, self.sha)
            self.row["meta"]["manual_review"]["candidate_sha256"] = self.sha
            self.assertEqual(
                verify_auto_catalogue(signed_catalog_for_uploaded_mods(self.db))["mods"], []
            )
            self.row["meta"]["manual_review"]["candidate_sha256"] = candidate_sha
            self.row["meta"]["protected"]["storage_path"] = "../not-a-private-candidate.jar"
            self.assertEqual(
                verify_auto_catalogue(signed_catalog_for_uploaded_mods(self.db))["mods"], []
            )

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
