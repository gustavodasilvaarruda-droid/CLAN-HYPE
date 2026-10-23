"""Regressions for member/HYPE Breed ordering rights without loading Flask/Supabase.

The authorization function is extracted from the real app.py using Python AST.
This avoids importing the whole Flask app, which needs production configuration.
"""
import ast
import unittest
from pathlib import Path


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.rows = [r for r in self.rows if r.get(column) == value]
        return self

    def execute(self):
        return Response(list(self.rows))


class Database:
    def __init__(self, users, permissions):
        self.tables = {'usuarios_clan': users, 'permissoes_cargos': permissions}

    def table(self, name):
        return Query(self.tables[name])


def permissions_function(db, active_clan):
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'app.py').read_text(encoding='utf-8'))
    fn = next(node for node in tree.body
              if isinstance(node, ast.FunctionDef)
              and node.name == 'obter_permissoes_usuario')
    namespace = {'supabase': db, 'membro_hype_ativo': active_clan}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 str(root / 'app.py'), 'exec'), namespace)
    return namespace['obter_permissoes_usuario']


class MemberBreedOrdersTest(unittest.TestCase):
    def get_for(self, cargo, *, member=False, saved_order_flag=False):
        db = Database(
            [{'email': 'test@example.com', 'cargo': cargo}],
            [{'cargo_id': cargo,
              'pode_fazer_pedido_breed': saved_order_flag,
              'pode_assumir_breed': False,
              'pode_ver_fila_breed': False}])
        return permissions_function(db, lambda _email: member)('test@example.com')

    def test_registered_visitor_can_order(self):
        self.assertTrue(self.get_for('visitante')['pode_fazer_pedido_breed'])

    def test_registered_basic_member_can_order(self):
        self.assertTrue(self.get_for('membro')['pode_fazer_pedido_breed'])

    def test_hype_member_can_order_even_when_old_permission_is_false(self):
        result = self.get_for('membro_hype', member=True)
        self.assertTrue(result['pode_fazer_pedido_breed'])
        self.assertFalse(result['pode_assumir_breed'])
        self.assertFalse(result['pode_ver_fila_breed'])

    def test_clan_member_with_specialty_role_can_order(self):
        result = self.get_for('breeder', member=True)
        self.assertTrue(result['pode_fazer_pedido_breed'])
        self.assertFalse(result['pode_assumir_breed'])

    def test_unknown_account_does_not_receive_permission(self):
        db = Database([], [])
        self.assertEqual(permissions_function(db, lambda _email: False)(
            'missing@example.com'), {})


if __name__ == '__main__':
    unittest.main()
