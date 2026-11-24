"""Regression for the isolated owner-only unsigned *developer* pilot."""
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules.hype_mod_owner_pilot import (
    owner_pilot_enabled, _valid_original, _record, publish_owner_pilot,
    find_owner_pilot, InvalidPrivateRelease,
)

OWNER = "test-owner@example.com"
UUID = "c957d4c1-15e4-4b43-af6d-5d5cc4dc6d97"
SHA = "a" * 64


def row(module_id="hypeclient"):
    return dict(
        id=UUID, module_id=module_id, version="R7.19-ALPHA7-PREVIEW10.0.42",
        status="aguardando_protecao", sha256=SHA, size_bytes=3500,
        storage_path=f"{module_id}/{'b'*32}/{SHA}.jar", meta={},
    )


class Table:
    def __init__(self, db):
        self.db, self.filters, self.patch = db, [], None

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_):
        return self

    def update(self, fields):
        self.patch = fields
        return self

    def execute(self):
        allowed = all(self.db.record.get(key) == val for key, val in self.filters)
        if not allowed:
            return SimpleNamespace(data=[])
        if self.patch:
            self.db.record.update(self.patch)
        return SimpleNamespace(data=[dict(self.db.record)])


class DB:
    def __init__(self):
        self.record = row()

    def table(self, table):
        assert table == "hype_mod_release_drafts"
        return Table(self)


class OwnerPilotTests(unittest.TestCase):
    def test_feature_fails_closed_and_requires_exact_owner(self):
        env = {
            "HYPE_MOD_OWNER_PILOT_ENABLED": "1",
            "HYPE_MOD_PILOT_ORIGINAL_ENABLED": "1",
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
            "HYPE_PRIVATE_MOD_TESTER_EMAIL": OWNER,
        }
        with patch.dict(os.environ, env):
            self.assertTrue(owner_pilot_enabled(OWNER))
            self.assertFalse(owner_pilot_enabled("other@example.com"))
            with patch.dict(os.environ, {"HYPE_MOD_OWNER_PILOT_ENABLED": "0"}):
                self.assertFalse(owner_pilot_enabled(OWNER))

    def test_hypeclient_original_supported_with_no_signature(self):
        source = row()
        self.assertEqual(_valid_original(source), UUID)
        source["meta"]["owner_pilot"] = {"release": 12, "published_by": OWNER}
        rec = _record(source)
        self.assertEqual(rec["id"], "hypeclient")
        self.assertEqual(rec["release"], 12)
        self.assertNotIn("manifest", rec)
        self.assertIn("/owner-pilot/mods/hypeclient/", rec["url"])

    def test_unsafe_original_rejected(self):
        for field, value in (("storage_path", "../original.jar"),
                             ("sha256", "not-a-sha"),
                             ("module_id", "evil"),
                             ("status", "rejeitado"),
                             ("size_bytes", -1)):
            with self.subTest(field=field):
                candidate = row()
                candidate[field] = value
                with self.assertRaises(InvalidPrivateRelease):
                    _valid_original(candidate)

    def test_publication_increments_and_never_publishes_to_player_table(self):
        db = DB()
        with patch("modules.hype_mod_owner_pilot.owner_pilot_enabled", return_value=True), \
             patch("modules.hype_mod_owner_pilot.download_owner_pilot", return_value=None):
            result = publish_owner_pilot(db, draft_id=UUID, published_by=OWNER)
            self.assertEqual(result["release"], 1)
            self.assertEqual(db.record["meta"]["owner_pilot"]["release"], 1)
            with self.assertRaises(InvalidPrivateRelease):
                publish_owner_pilot(db, draft_id=UUID, published_by=OWNER)
            self.assertEqual(find_owner_pilot(db, "hypeclient")[1]["release"], 1)

    def test_client_api_requires_authenticated_lider_and_owner_gate(self):
        api = (Path(__file__).resolve().parents[1] / "modules" /
               "hype_client_api.py").read_text(encoding="utf-8")
        route = api.split("def owner_pilot_binary(mod_id, sha256):", 1)[1].split(
            "    @api.get('/updates/releases')", 1
        )[0]
        self.assertIn("@secure", api)
        self.assertIn('owner_pilot_enabled(email)', route)
        self.assertIn('g.hype_user.get("cargo") != "lider"', route)
        self.assertIn('download_owner_pilot(db, original)', route)
        self.assertIn('fresh[0].get("cargo") != "lider"', route)
        self.assertNotIn('public=True', route)

    def test_signed_player_paths_stay_separate(self):
        template = (Path(__file__).resolve().parents[1] / "templates" /
                    "admin_hype_mod_releases.html").read_text(encoding="utf-8")
        self.assertIn("mod_release_publish_owner_pilot", template)
        self.assertIn("{% if not owner_pilot_enabled %}", template)
        self.assertIn("mod_release_publish_private", template)
        self.assertIn("mod_release_publish", template)


if __name__ == "__main__":
    unittest.main()
