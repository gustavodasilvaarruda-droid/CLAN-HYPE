import unittest
from datetime import datetime, timezone
from modules.hype_mod_access import evaluate_module, user_groups, visible_modules_for_user

NOW = datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc)

class TestPermissions(unittest.TestCase):
    def test_disabled_global_wins_override(self):
        self.assertEqual(evaluate_module({'estado':'desativado'}, {'membro_hype'}, {'membro_hype'}, {'decisao':'permitir', 'inicio_em':'2026-10-01T00:00:00Z'}, NOW)['motivo'], 'desativado_globalmente')
    def test_maintenance_global_wins_override(self):
        self.assertEqual(evaluate_module({'estado':'manutencao'}, {'membro_hype'}, {'membro_hype'}, {'decisao':'permitir', 'inicio_em':'2026-10-01T00:00:00Z'}, NOW)['motivo'], 'manutencao')
    def test_member_and_special_roles(self):
        self.assertEqual(user_groups('breeder', False), {'membro'})
        self.assertEqual(user_groups('breeder', True), {'membro','membro_hype','breeder'})
    def test_role_allowed(self):
        self.assertTrue(evaluate_module({'estado':'ativo'}, {'membro'}, {'membro'}, now=NOW)['permitido'])
    def test_nonmember_specialty_denied(self):
        self.assertFalse(evaluate_module({'estado':'ativo'}, user_groups('breeder', False), {'breeder'}, now=NOW)['permitido'])
    def test_manual_deny_wins_role(self):
        override={'decisao':'bloquear', 'inicio_em':'2026-10-10T00:00:00Z', 'fim_em':'2026-10-19T00:00:00Z'}
        self.assertFalse(evaluate_module({'estado':'ativo'}, {'membro'}, {'membro'}, override, NOW)['permitido'])
    def test_manual_allow(self):
        override={'decisao':'permitir', 'inicio_em':'2026-10-10T00:00:00Z', 'fim_em':'2026-10-19T00:00:00Z'}
        self.assertTrue(evaluate_module({'estado':'ativo'}, {'membro'}, {'membro_hype'}, override, NOW)['permitido'])
    def test_future_grant_not_yet(self):
        override={'decisao':'permitir', 'inicio_em':'2026-10-20T00:00:00Z'}
        self.assertFalse(evaluate_module({'estado':'ativo'}, {'membro'}, {'membro_hype'}, override, NOW)['permitido'])
    def test_expired_grant_not_active(self):
        override={'decisao':'permitir', 'inicio_em':'2026-10-01T00:00:00Z', 'fim_em':'2026-10-18T21:00:00Z'}
        self.assertFalse(evaluate_module({'estado':'ativo'}, {'membro'}, {'membro_hype'}, override, NOW)['permitido'])
    def test_no_start_fails_closed(self):
        override={'decisao':'permitir', 'fim_em':'2027-01-01T00:00:00Z'}
        self.assertFalse(evaluate_module({'estado':'ativo'}, {'membro'}, {'membro_hype'}, override, NOW)['permitido'])
    def test_malformed_date_fails_closed(self):
        override={'decisao':'permitir', 'inicio_em':'not a date'}
        self.assertFalse(evaluate_module({'estado':'ativo'}, {'membro'}, {'membro_hype'}, override, NOW)['permitido'])
    def test_hidden_module_not_listed(self):
        modules=[{'codigo':'a','nome':'Alpha','estado':'ativo','visivel':True}, {'codigo':'b','estado':'ativo','visivel':False}]
        rows=visible_modules_for_user(modules,[{'modulo_codigo':'a','cargo_id':'membro'}],[], 'visitante', False,NOW)
        self.assertEqual([m['codigo'] for m in rows], ['a'])
        self.assertNotIn('usuario_email', str(rows))
    def test_empty_group_list_denies(self):
        rows=visible_modules_for_user([{'codigo':'a','estado':'ativo'}],[],[], 'membro_hype',True,NOW)
        self.assertFalse(rows[0]['permitido'])
    def test_enabled_special_group(self):
        rows=visible_modules_for_user([{'codigo':'ai','estado':'ativo'}],[{'modulo_codigo':'ai','cargo_id':'membro_hype'}],[], 'membro',True,NOW)
        self.assertTrue(rows[0]['permitido'])

if __name__=='__main__': unittest.main()
