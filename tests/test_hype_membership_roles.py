"""Regressões: Membro, filiação HYPE, Breed, torneios e mods."""
import ast
import unittest
from pathlib import Path
from modules.hype_membership_rules import (
    BASIC_ROLE, role_requires_active_clan, selectable_roles, membership_status,
)

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'app.py').read_text(encoding='utf-8')
TREE = ast.parse(APP)


def get_function(name):
    return next(node for node in TREE.body
                if isinstance(node, ast.FunctionDef) and node.name == name)


class TestHypeMembership(unittest.TestCase):
    def test_basic_role_and_specialty(self):
        self.assertEqual(BASIC_ROLE, 'membro')
        self.assertFalse(role_requires_active_clan('membro'))
        for special in ('breeder', 'lider', 'sub_lider', 'sub_breeder'):
            self.assertTrue(role_requires_active_clan(special))
        self.assertEqual(membership_status(True), 'Membro HYPE')
        self.assertEqual(membership_status(False), 'Membro do servidor')

    def test_hide_duplicates_from_role_selection(self):
        roles = [{'id': name} for name in
                 ('visitante', 'membro', 'membro_hype', 'pedri', 'breeder', 'lider')]
        self.assertEqual([x['id'] for x in selectable_roles(roles)],
                         ['membro', 'breeder', 'lider'])

    def test_public_signup_is_basic_not_hype(self):
        code = ast.get_source_segment(APP, get_function('login_membro'))
        self.assertIn("'cargo': BASIC_ROLE", code)
        self.assertIn("session['cargo'] = BASIC_ROLE", code)
        self.assertIn("'ativo': False", code)

    def test_changing_role_does_not_change_membership(self):
        code = ast.get_source_segment(APP, get_function('alterar_cargo'))
        self.assertIn('role_requires_active_clan(novo_cargo) and not hype_ativo', code)
        self.assertNotIn("table('membros_hype').upsert", code)
        self.assertNotIn("'ativo': True", code)
        self.assertNotIn('contratos_casas', code)

    def test_tournament_remains_all_registered_accounts(self):
        func = get_function('inscrever_torneio')
        decorators = [d.id for d in func.decorator_list if isinstance(d, ast.Name)]
        self.assertIn('login_required', decorators)
        self.assertNotIn('membro_hype_required', decorators)

    def test_member_removed_from_clan_downgrades_only_function(self):
        code = ast.get_source_segment(APP, get_function('admin_membros_hype'))
        self.assertIn("if usuarios[0].get('cargo') != BASIC_ROLE:", code)
        self.assertIn("supabase.table('contratos_casas').update", code)

    def test_module_virtual_group_preserved(self):
        mod = (ROOT / 'modules' / 'hype_mod_access.py').read_text(encoding='utf-8')
        self.assertIn("groups.add('membro_hype')", mod)

    def test_safe_sql_does_not_approve_clan(self):
        sql = (ROOT / 'sql' / '20261108_membros_servidor_hype_migracao.sql').read_text().lower()
        self.assertIn("set cargo = 'membro'", sql)
        self.assertIn('drop trigger if exists trg_hype_sincronizar_membro_cargo', sql)
        self.assertIn('alter column ativo set default false', sql)
        self.assertNotIn('set ativo = true', sql)


if __name__ == '__main__':
    unittest.main()
