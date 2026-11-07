"""Read-only Breeder queue contract for HYPE Client.

No network or Supabase account is needed. Run:
    python -m unittest discover -s tests -p 'test_hype_client_queue_complete.py'
"""
import unittest
from flask import Flask
from itsdangerous import URLSafeTimedSerializer

from modules.hype_client_api import create_hype_client_api_blueprint


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, rows):
        self.rows = [dict(x) for x in rows]
        self.columns = None

    def select(self, fields):
        self.columns = [part.strip() for part in fields.split(',')]
        return self

    def eq(self, column, value):
        self.rows = [r for r in self.rows if r.get(column) == value]
        return self

    def in_(self, column, values):
        self.rows = [r for r in self.rows if r.get(column) in values]
        return self

    def order(self, column, desc=False):
        self.rows.sort(key=lambda r: str(r.get(column) or ''), reverse=desc)
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def execute(self):
        data = self.rows
        if self.columns is not None:
            data = [{k: r.get(k) for k in self.columns} for r in data]
        return Result(data)


class FakeDB:
    def __init__(self):
        self.tables = {
            'usuarios_clan': [
                {'email': 'breeder@example.com', 'cargo': 'breeder', 'nick_jogo': 'Breeder'},
                {'email': 'other@example.com', 'cargo': 'breeder', 'nick_jogo': 'Outro'},
                {'email': 'cliente@example.com', 'cargo': 'membro', 'nick_jogo': 'Cliente'},
            ],
            'hype_modulos': [
                {'codigo': 'breeder', 'nome': 'Breeder', 'estado': 'ativo', 'visivel': True}
            ],
            'hype_modulos_grupos': [
                {'modulo_codigo': 'breeder', 'cargo_id': 'breeder'}
            ],
            'hype_modulos_acessos': [],
            'pedidos_breed': [
                {'id': 1, 'pokemon': 'Bulbasaur', 'pokemon_id': 1,
                 'status': 'pendente', 'player': 'Cliente',
                 'usuario_email': 'cliente@example.com',
                 'preco_total': 500000, 'breeder_responsavel': None, 'created_at': '2026-11-01'},
                {'id': 2, 'pokemon': 'Charmander', 'pokemon_id': 4,
                 'status': 'em_producao', 'player': 'Cliente',
                 'usuario_email': 'cliente@example.com',
                 'preco_total': 600000, 'breeder_responsavel': 'other@example.com', 'created_at': '2026-11-02'},
                {'id': 3, 'pokemon': 'Squirtle', 'pokemon_id': 7,
                 'status': 'concluido', 'player': 'Cliente',
                 'usuario_email': 'cliente@example.com',
                 'preco_total': 700000, 'breeder_responsavel': 'breeder@example.com', 'created_at': '2026-11-03'},
                {'id': 4, 'pokemon': 'Pikachu', 'pokemon_id': 25,
                 'status': 'entregue', 'player': 'Cliente',
                 'usuario_email': 'cliente@example.com',
                 'preco_total': 100000, 'breeder_responsavel': 'breeder@example.com', 'created_at': '2026-11-04'},
            ],
        }
        self.reads = []

    def table(self, name):
        self.reads.append(name)
        return Query(self.tables[name])


class FullQueueTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.can_view = True
        self.app = Flask(__name__)
        self.app.register_blueprint(create_hype_client_api_blueprint(
            self.db, 'queue-test-secret',
            lambda email: {'pode_ver_fila_breed': self.can_view},
            lambda email: True,
            lambda email: False,
            lambda email: None,
            lambda email: None
        ))
        self.client = self.app.test_client()

    def auth(self, email='breeder@example.com'):
        token = URLSafeTimedSerializer(
            'queue-test-secret', salt='hype-client-api-v1'
        ).dumps({'email': email})
        return {'Authorization': 'Bearer ' + token}

    def test_login_is_required(self):
        result = self.client.get('/api/hype/v1/fila-completa')
        self.assertEqual(result.status_code, 401)

    def test_non_breeder_is_denied_by_module(self):
        result = self.client.get('/api/hype/v1/fila-completa',
                                 headers=self.auth('cliente@example.com'))
        self.assertEqual(result.status_code, 403)

    def test_permission_can_be_revoked(self):
        self.can_view = False
        result = self.client.get('/api/hype/v1/fila-completa', headers=self.auth())
        self.assertEqual(result.status_code, 403)

    def test_full_queue_contains_active_statuses_but_not_delivered(self):
        result = self.client.get('/api/hype/v1/fila-completa', headers=self.auth())
        self.assertEqual(result.status_code, 200, result.get_json())
        orders = result.get_json()['pedidos']
        self.assertEqual([x['id'] for x in orders], [1, 2, 3])
        self.assertTrue(result.get_json()['fila_completa'])
        self.assertEqual(orders[1]['breeder_nick'], 'Outro')
        self.assertFalse(orders[1]['meu_breed'])
        self.assertTrue(orders[2]['meu_breed'])

    def test_private_emails_are_not_returned(self):
        result = self.client.get('/api/hype/v1/fila-completa', headers=self.auth())
        text = result.get_data(as_text=True)
        self.assertNotIn('breeder@example.com', text)
        self.assertNotIn('other@example.com', text)
        self.assertNotIn('cliente@example.com', text)

    def test_queue_is_read_only(self):
        before = [dict(row) for row in self.db.tables['pedidos_breed']]
        result = self.client.get('/api/hype/v1/fila-completa', headers=self.auth())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.db.tables['pedidos_breed'], before)


if __name__ == '__main__':
    unittest.main()
