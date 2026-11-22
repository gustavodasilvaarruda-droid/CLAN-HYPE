"""No-download permission tests for the planned HYPE multi-mod updater."""
import unittest
from datetime import datetime, timezone

from modules.hype_mod_update_access import (
    MOD_TO_SITE_MODULE, may_receive_mod_update,
)

NOW = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)


class MultiModAccessTests(unittest.TestCase):
    def access(self, *, mod="hype_pokedex", state="ativo", visible=True,
               roles=("membro_hype",), cargo="breeder", member=True,
               overrides=()):
        code = MOD_TO_SITE_MODULE.get(mod, "pokedex")
        return may_receive_mod_update(
            mod, [{"codigo": code, "estado": state, "visivel": visible}],
            [{"modulo_codigo": code, "cargo_id": role} for role in roles],
            list(overrides), cargo, member, now=NOW,
        )

    def test_all_four_runtime_mods_match_existing_site_codes(self):
        for mod, code in MOD_TO_SITE_MODULE.items():
            self.assertEqual(code, MOD_TO_SITE_MODULE[mod])
            with self.subTest(mod=mod):
                self.assertTrue(self.access(mod=mod))

    def test_maintenance_overrides_every_permission(self):
        grant = {"modulo_codigo": "pokedex", "decisao": "permitir",
                 "inicio_em": "2026-11-01T00:00:00Z"}
        self.assertFalse(self.access(state="manutencao", overrides=(grant,)))
        self.assertFalse(self.access(state="desativado", overrides=(grant,)))

    def test_hidden_or_missing_module_fails_closed(self):
        self.assertFalse(self.access(visible=False))
        self.assertFalse(may_receive_mod_update(
            "hype_pokedex", [], [], [], "breeder", True, now=NOW
        ))

    def test_role_and_membership_are_enforced(self):
        self.assertFalse(self.access(cargo="visitante", member=False))
        self.assertFalse(self.access(cargo="breeder", member=False))
        self.assertFalse(self.access(roles=(), cargo="breeder", member=True))
        self.assertTrue(self.access(roles=("breeder",), cargo="breeder", member=True))

    def test_individual_block_wins_and_time_window_expires(self):
        blocked = {"modulo_codigo": "pokedex", "decisao": "bloquear",
                   "inicio_em": "2026-11-01T00:00:00Z"}
        self.assertFalse(self.access(overrides=(blocked,)))
        expired = dict(blocked, fim_em="2026-11-20T00:00:00Z")
        self.assertTrue(self.access(overrides=(expired,)))

    def test_unknown_jar_and_bootstrap_do_not_gain_automatic_access(self):
        self.assertFalse(self.access(mod="hypeclient"))
        self.assertFalse(self.access(mod="unknown_fabric_jar"))


if __name__ == "__main__":
    unittest.main()
