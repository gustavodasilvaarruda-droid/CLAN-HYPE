"""Regression coverage: private HYPE JARs must remain signed and permission-gated."""
import base64
import hashlib
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from flask import Flask
from itsdangerous import URLSafeTimedSerializer

from modules import hype_signed_release as signed
from modules.hype_client_api import SALT, create_hype_client_api_blueprint


EMAIL = "player@example.org"
MOD = "hype_pokedex"
CODE = "pokedex"
DRAFT_ID = "0f9af0ba-37ee-4a30-a8f1-73a451d30982"


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.sort = db, table, {}, None

    def select(self, *args):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, key, desc=False):
        self.sort = (key, desc)
        return self

    def limit(self, size):
        self.limit_size = size
        return self

    def execute(self):
        if self.db.fail == self.table:
            raise OSError("storage backend unavailable")
        rows = [dict(row) for row in self.db.rows.get(self.table, [])
                if all(row.get(key) == value for key, value in self.filters.items())]
        if self.sort:
            key, desc = self.sort
            rows.sort(key=lambda x: x.get(key), reverse=desc)
        return SimpleNamespace(data=rows[:getattr(self, "limit_size", len(rows))])


class PrivateStorage:
    def __init__(self, db):
        self.db = db
        self.on_download = None
        self.public = False

    def get_bucket(self, name):
        return {"public": self.public}

    def from_(self, name):
        return self

    def download(self, path):
        if self.on_download:
            self.on_download()
        return self.db.blobs[path]


class FakeDB:
    def __init__(self):
        self.rows = {}
        self.blobs = {}
        self.fail = None
        self.storage = PrivateStorage(self)

    def table(self, name):
        return Query(self, name)


def make_jar():
    buf = io.BytesIO()
    with ZipFile(buf, "w") as zipfile:
        zipfile.writestr("fabric.mod.json", '{"schemaVersion":1,"id":"hype_pokedex","version":"2.0.0-test"}')
        zipfile.writestr("br/clanhype/pokedex/Test.class", b"not executable" * 300)
    return buf.getvalue()


class PrivateModDownloadTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        pub_der = self.key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        key_patch = patch.object(signed, "PUBLIC_KEY_DER_B64", base64.b64encode(pub_der).decode("ascii"))
        key_patch.start()
        self.addCleanup(key_patch.stop)

        flags = patch.dict(os.environ, {
            "HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED": "1",
            "HYPE_PRIVATE_MOD_DOWNLOADS_ENABLED": "1",
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "clan",
            "HYPE_PRIVATE_MOD_CLAN_RELEASE_CONFIRMED": "yes",
        })
        flags.start()
        self.addCleanup(flags.stop)

        self.member = True
        self.db = FakeDB()
        self.jar = make_jar()
        self.sha = hashlib.sha256(self.jar).hexdigest()
        self.path = f"{MOD}/{DRAFT_ID}/protected/{'e' * 32}/{self.sha}.jar"
        self.db.blobs[self.path] = self.jar
        self.db.rows = {
            "usuarios_clan": [{"email": EMAIL, "cargo": "breeder", "nick_jogo": "Player"}],
            "hype_modulos": [{"codigo": CODE, "estado": "ativo", "visivel": True}],
            "hype_modulos_grupos": [{"modulo_codigo": CODE, "cargo_id": "membro_hype"}],
            "hype_modulos_acessos": [],
            "hype_mod_release_drafts": [{
                "id": DRAFT_ID, "module_id": MOD, "version": "2.0.0-test",
                "status": "pronto_para_aprovacao",
                "meta": {
                    "protected": {"sha256": self.sha, "size_bytes": len(self.jar),
                                  "storage_path": self.path},
                    "automatic_review": {"status": "passed", "candidate_sha256": self.sha},
                    "manual_review": {
                        "candidate_sha256": self.sha,
                        "checks": {"game_launch": True, "menus": True,
                                   "server_connection": True, "no_crashes": True}
                    },
                },
            }],
            "hype_mod_restricted_releases": [],
        }
        self.record = {
            "module_id": MOD, "release": 1, "draft_id": DRAFT_ID,
            "version": "2.0.0-test", "sha256": self.sha,
            "size_bytes": len(self.jar), "storage_path": self.path,
            "status": "published",
        }
        self.record["manifest"] = self.signed_manifest()
        self.db.rows["hype_mod_restricted_releases"].append(self.record)
        app = Flask(__name__)
        app.config["TESTING"] = True
        secret = "private-tests-only-not-a-production-secret"
        api = create_hype_client_api_blueprint(
            self.db, secret, lambda email: {}, lambda email: self.member,
            lambda email: False, lambda email: None, lambda email: None)
        app.register_blueprint(api)
        self.client = app.test_client()
        self.token = URLSafeTimedSerializer(secret, salt=SALT).dumps({"email": EMAIL})
        self.auth = {"Authorization": f"Bearer {self.token}"}
        self.url = f"/api/hype/v1/updates/mods/{MOD}/{self.sha}.jar"
        self.catalogue = "/api/hype/v1/updates/releases"

    def signed_manifest(self):
        fields = {
            "release": "1", "version": "2.0.0-test",
            "url": f"https://clan-hype.onrender.com/api/hype/v1/updates/mods/{MOD}/{self.sha}.jar",
            "sha256": self.sha, "size": str(len(self.jar)),
            "minecraft": "1.21.1", "mod_id": MOD, "channel": "stable",
        }
        canonical = "".join(f"{k}={fields[k]}\n" for k in signed.FIELDS)
        return canonical + "signature=" + base64.b64encode(
            self.key.sign(canonical.encode("ascii"))
        ).decode("ascii") + "\n"

    def test_flags_off_even_for_valid_token(self):
        with patch.dict(os.environ, {"HYPE_PRIVATE_MOD_DOWNLOADS_ENABLED": ""}):
            self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 404)
            self.assertEqual(self.client.get(self.catalogue, headers=self.auth).status_code, 404)

    def test_login_required_for_catalogue_and_file(self):
        for path in (self.url, self.catalogue):
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, headers={
                "Authorization": "Bearer forged"
            }).status_code, 401)

    def test_catalogue_lists_only_signed_approved_authorized_mod(self):
        res = self.client.get(self.catalogue, headers=self.auth)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json["releases"]), 1)
        item = res.json["releases"][0]
        self.assertEqual(item["sha256"], self.sha)
        self.assertIn("signature=", item["manifest"])
        self.assertNotIn("storage_path", str(res.json))
        self.assertNotIn(EMAIL, str(res.json))
        self.assertIn("no-store", res.headers["Cache-Control"])

    def test_rollout_defaults_off_even_with_legacy_feature_flags(self):
        with patch.dict(os.environ, {"HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": ""}):
            self.assertEqual(self.client.get(self.catalogue, headers=self.auth).status_code, 404)
            self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 404)

    def test_single_tester_only_even_when_both_accounts_have_role(self):
        self.db.rows["usuarios_clan"].append({
            "email": "other@example.org", "cargo": "breeder", "nick_jogo": "Other"})
        stranger = URLSafeTimedSerializer(
            "private-tests-only-not-a-production-secret", salt=SALT
        ).dumps({"email": "other@example.org"})
        outsider_auth = {"Authorization": f"Bearer {stranger}"}
        with patch.dict(os.environ, {
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
            "HYPE_PRIVATE_MOD_TESTER_EMAIL": EMAIL.upper(),
        }):
            self.assertEqual(self.client.get(self.catalogue, headers=self.auth).status_code, 200)
            self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 200)
            for path in (self.catalogue, self.url):
                self.assertEqual(self.client.get(
                    path, headers=outsider_auth).status_code, 404)

    def test_single_tester_unconfigured_or_malformed_denies_everyone(self):
        for target in ("", "not-an-email", "name@example.org\nBcc:someone@example.org"):
            with self.subTest(target=target), patch.dict(os.environ, {
                "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                "HYPE_PRIVATE_MOD_TESTER_EMAIL": target,
            }):
                self.assertEqual(self.client.get(self.catalogue, headers=self.auth).status_code, 404)

    def test_clan_scope_requires_separate_release_confirmation(self):
        with patch.dict(os.environ, {
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "clan",
            "HYPE_PRIVATE_MOD_CLAN_RELEASE_CONFIRMED": "",
        }):
            self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 404)

    def test_single_tester_revoked_while_binary_is_loading(self):
        scope = {
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
            "HYPE_PRIVATE_MOD_TESTER_EMAIL": EMAIL,
        }
        def revoke_during_download():
            os.environ["HYPE_PRIVATE_MOD_TESTER_EMAIL"] = "other@example.org"
        with patch.dict(os.environ, scope):
            self.db.storage.on_download = revoke_during_download
            self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 403)

    def test_binary_integrity_and_no_public_cache(self):
        res = self.client.get(self.url, headers=self.auth)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, self.jar)
        self.assertIn("no-store", res.headers["Cache-Control"])
        self.assertIn("private", res.headers["Cache-Control"])
        self.assertEqual(self.client.get(
            "/api/hype/v1/updates/mods/unknown/" + self.sha + ".jar", headers=self.auth
        ).status_code, 404)

    def test_denied_when_maintenance_or_individual_block(self):
        self.db.rows["hype_modulos"][0]["estado"] = "manutencao"
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 403)
        self.assertEqual(self.client.get(self.catalogue, headers=self.auth).json["releases"], [])
        self.db.rows["hype_modulos"][0]["estado"] = "ativo"
        self.db.rows["hype_modulos_acessos"].append({
            "modulo_codigo": CODE, "usuario_email": EMAIL,
            "decisao": "bloquear", "inicio_em": "2020-01-01T00:00:00Z", "fim_em": None
        })
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 403)

    def test_revocation_during_storage_read_denies_delivery(self):
        self.db.storage.on_download = lambda: setattr(self, "member", False)
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 403)

    def test_corrupt_jar_or_public_bucket_denied(self):
        self.db.blobs[self.path] = b"tampered"
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 503)
        self.db.blobs[self.path] = self.jar
        self.db.storage.public = True
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 503)

    def test_signature_and_review_must_match_exact_candidate(self):
        self.record["manifest"] = self.record["manifest"].replace("stable", "beta")
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 503)
        self.record["manifest"] = self.signed_manifest()
        self.db.rows["hype_mod_release_drafts"][0]["meta"]["manual_review"]["candidate_sha256"] = "0" * 64
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 503)

    def test_missing_release_and_database_error_fail_closed(self):
        self.db.rows["hype_mod_restricted_releases"].clear()
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 404)
        self.db.fail = "hype_modulos_grupos"
        self.assertEqual(self.client.get(self.url, headers=self.auth).status_code, 503)


if __name__ == "__main__":
    unittest.main()
