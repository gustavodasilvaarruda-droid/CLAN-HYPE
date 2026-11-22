"""HYPE private rollout must stay fail-closed and cannot grant entitlements."""
import unittest

from modules.hype_mod_pilot_scope import (
    can_account_download_private_mods, pilot_scope_status,
)


class SingleTesterScopeTests(unittest.TestCase):
    def test_no_rollout_selected(self):
        self.assertEqual(pilot_scope_status({}), "off")
        self.assertFalse(can_account_download_private_mods("admin@example.org", {}))

    def test_single_requires_configured_valid_email(self):
        for value in ("", "without-at", "admin@example.org\nX-Admin: true", "admin@localhost"):
            config = {"HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                      "HYPE_PRIVATE_MOD_TESTER_EMAIL": value}
            self.assertEqual(pilot_scope_status(config), "single_missing_tester")
            self.assertFalse(can_account_download_private_mods("admin@example.org", config))

    def test_single_matches_only_server_authenticated_identity(self):
        config = {"HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                  "HYPE_PRIVATE_MOD_TESTER_EMAIL": " Pilot@Example.ORG "}
        self.assertTrue(can_account_download_private_mods("pilot@example.org", config))
        self.assertTrue(can_account_download_private_mods("PILOT@EXAMPLE.ORG", config))
        self.assertFalse(can_account_download_private_mods("other@example.org", config))
        self.assertFalse(can_account_download_private_mods(None, config))

    def test_single_does_not_fallback_to_everyone(self):
        config = {"HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
                  "HYPE_PRIVATE_MOD_TESTER_EMAIL": "pilot@example.org"}
        self.assertFalse(can_account_download_private_mods("pilot@example.org.evil", config))
        self.assertFalse(can_account_download_private_mods("", config))

    def test_clan_requires_extra_confirmation(self):
        config = {"HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "clan"}
        self.assertEqual(pilot_scope_status(config), "clan_unconfirmed")
        self.assertFalse(can_account_download_private_mods("player@example.org", config))
        config["HYPE_PRIVATE_MOD_CLAN_RELEASE_CONFIRMED"] = "yes"
        self.assertEqual(pilot_scope_status(config), "clan_ready")
        self.assertTrue(can_account_download_private_mods("player@example.org", config))

    def test_typo_and_unrecognized_scope_denied(self):
        config = {"HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "singel",
                  "HYPE_PRIVATE_MOD_TESTER_EMAIL": "pilot@example.org"}
        self.assertEqual(pilot_scope_status(config), "off")
        self.assertFalse(can_account_download_private_mods("pilot@example.org", config))


if __name__ == "__main__":
    unittest.main()
