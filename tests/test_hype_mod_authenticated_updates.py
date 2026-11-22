"""Regression tests for authenticated HYPE update entitlements (no JAR transfer)."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from itsdangerous import URLSafeTimedSerializer

from modules.hype_client_api import (
    SALT, create_hype_client_api_blueprint,
)
from modules.hype_mod_authenticated_updates import (
    ModEntitlementUnavailable, may_account_receive_update,
)


class Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters = db, name, {}

    def select(self, *args):
        return self

    def eq(self, name, value):
        self.filters[name] = value
        return self

    def limit(self, amount):
        return self

    def execute(self):
        if self.db.fail == self.name:
            raise RuntimeError("database unavailable")
        rows = [dict(row) for row in self.db.rows.get(self.name, [])
                if all(row.get(key) == value for key, value in self.filters.items())]
        return SimpleNamespace(data=rows)


class FakeDB:
    def __init__(self):
        self.fail = None
        self.rows = {
            "usuarios_clan": [
                {"email": "trainer@example.com", "nick_jogo": "Trainer",
                 "cargo": "breeder"}
            ],
            "hype_modulos": [
                {"codigo": code, "estado": "ativo", "visivel": True}
                for code in ("pokedex", "breed_calculator", "campo_batalha", "battle_ai")
            ],
            "hype_modulos_grupos": [
                {"modulo_codigo": code, "cargo_id": "membro_hype"}
                for code in ("pokedex", "breed_calculator", "campo_batalha", "battle_ai")
            ],
            "hype_modulos_acessos": [],
        }

    def table(self, name):
        return Query(self, name)


class AuthenticatedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.member = True
        self.secret = "tests-only-secret"
        app = Flask(__name__)
        app.config["TESTING"] = True
        api = create_hype_client_api_blueprint(
            self.db, self.secret, lambda email: {},
            lambda email: self.member,
            lambda email: False,
            lambda email: None,
            lambda email: None,
        )
        app.register_blueprint(api)
        self.client = app.test_client()
        token = URLSafeTimedSerializer(self.secret, salt=SALT).dumps(
            {"email": "trainer@example.com"}
        )
        self.auth = {"Authorization": "Bearer " + token}
        self.path = "/api/hype/v1/updates/authorized-mods"

    def test_default_off_and_login_required(self):
        with patch.dict(os.environ, {"HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED": ""}):
            self.assertEqual(self.client.get(self.path, headers=self.auth).status_code, 404)
        with patch.dict(os.environ, {"HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED": "1",
                                    "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                                    "HYPE_PRIVATE_MOD_TESTER_EMAIL": "trainer@example.com"}):
            self.assertEqual(self.client.get(self.path).status_code, 401)
            self.assertEqual(self.client.get(self.path, headers={
                "Authorization": "Bearer forged"
            }).status_code, 401)

    def test_four_allowed_ids_without_file_urls_or_private_user_data(self):
        with patch.dict(os.environ, {"HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED": "1",
                                    "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                                    "HYPE_PRIVATE_MOD_TESTER_EMAIL": "trainer@example.com"}):
            response = self.client.get(self.path, headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json["mods"]), {
            "hype_pokedex", "hype_breed_calculator",
            "hype_battlefield", "hype_battle_ai"
        })
        self.assertNotIn("email", str(response.json))
        self.assertNotIn("url", str(response.json).lower())
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_maintenance_overrides_cargo_and_individual_grant(self):
        self.db.rows["hype_modulos"][0]["estado"] = "manutencao"
        self.db.rows["hype_modulos_acessos"].append({
            "modulo_codigo": "pokedex", "usuario_email": "trainer@example.com",
            "decisao": "permitir", "inicio_em": "2020-01-01T00:00:00Z",
            "fim_em": None
        })
        with patch.dict(os.environ, {"HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED": "1",
                                    "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                                    "HYPE_PRIVATE_MOD_TESTER_EMAIL": "trainer@example.com"}):
            response = self.client.get(self.path, headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("hype_pokedex", response.json["mods"])

    def test_individual_block_and_cargo_or_membership_change_are_live(self):
        self.db.rows["hype_modulos_acessos"].append({
            "modulo_codigo": "pokedex", "usuario_email": "trainer@example.com",
            "decisao": "bloquear", "inicio_em": "2020-01-01T00:00:00Z",
            "fim_em": None
        })
        with patch.dict(os.environ, {"HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED": "1",
                                    "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                                    "HYPE_PRIVATE_MOD_TESTER_EMAIL": "trainer@example.com"}):
            response = self.client.get(self.path, headers=self.auth)
            self.assertNotIn("hype_pokedex", response.json["mods"])
            self.member = False
            response = self.client.get(self.path, headers=self.auth)
        self.assertEqual(response.json["mods"], [])

    def test_hidden_unknown_and_missing_access_are_denied(self):
        self.db.rows["hype_modulos"][0]["visivel"] = False
        self.assertFalse(may_account_receive_update(
            self.db, "hype_pokedex", "trainer@example.com", "breeder", True
        ))
        self.assertFalse(may_account_receive_update(
            self.db, "unrecognized_mod", "trainer@example.com", "breeder", True
        ))
        self.assertFalse(may_account_receive_update(
            self.db, "hypeclient", "trainer@example.com", "breeder", True
        ))

    def test_database_failure_does_not_return_partial_entitlements(self):
        self.db.fail = "hype_modulos_grupos"
        with self.assertRaises(ModEntitlementUnavailable):
            may_account_receive_update(
                self.db, "hype_pokedex", "trainer@example.com", "breeder", True
            )
        with patch.dict(os.environ, {"HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED": "1",
                                    "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                                    "HYPE_PRIVATE_MOD_TESTER_EMAIL": "trainer@example.com"}):
            response = self.client.get(self.path, headers=self.auth)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("mods", response.json)


if __name__ == "__main__":
    unittest.main()
