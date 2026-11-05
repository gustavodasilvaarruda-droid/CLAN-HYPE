"""Unit tests for HYPE Client -> Site Breed order contract.

Run after installing requirements.txt:
    python -m unittest discover -s tests -p 'test_hype_client_breed_submit.py'
No real Supabase project, token or network connection is used.
"""
import unittest
from uuid import uuid4
from datetime import datetime, timezone
from flask import Flask
from itsdangerous import URLSafeTimedSerializer

from modules.hype_client_api import create_hype_client_api_blueprint


class Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.predicates = []
        self.action = 'select'
        self.new = None
        self.reverse = False
        self.sort_field = None
        self.n = None

    def select(self, _fields): return self
    def eq(self, key, value):
        self.predicates.append(lambda row, k=key, v=value: row.get(k) == v)
        return self
    def in_(self, key, values):
        self.predicates.append(lambda row, k=key, v=values: row.get(k) in v)
        return self
    def limit(self, n): self.n = n; return self
    def order(self, field, desc=False): self.sort_field = field; self.reverse = desc; return self
    def insert(self, payload): self.action = 'insert'; self.new = payload; return self

    def execute(self):
        if self.action == 'insert':
            if self.table != 'pedidos_breed':
                raise AssertionError('Unexpected write to ' + self.table)
            if any(p.get('hype_client_request_id') == self.new.get('hype_client_request_id')
                   for p in self.db.orders):
                raise Exception('23505 unique constraint')
            row = dict(self.new)
            row['id'] = len(self.db.orders) + 1
            row['created_at'] = datetime.now(timezone.utc).isoformat()
            self.db.orders.append(row)
            return type('Result', (), {'data': [row]})()
        data = self.db.users if self.table == 'usuarios_clan' else self.db.orders
        selected = [dict(row) for row in data if all(p(row) for p in self.predicates)]
        if self.sort_field:
            selected.sort(key=lambda x: x.get(self.sort_field) or '', reverse=self.reverse)
        if self.n is not None:
            selected = selected[:self.n]
        return type('Result', (), {'data': selected})()


class FakeDB:
    def __init__(self):
        self.users = [{'email': 'cliente@example.com', 'nick_jogo': 'Treinador', 'cargo': 'visitante'}]
        self.orders = []
    def table(self, name):
        assert name in ('usuarios_clan', 'pedidos_breed'), name
        return Query(self, name)


class ClientOrderTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        services = {
            'rule': lambda pid, name: {'breedavel': pid != 132, 'so_com_ditto': False,
                                       'motivo': 'Ditto bloqueado'},
            'classify': lambda pid: {'categoria': 'comum'},
            'calculate': lambda *args, **kwargs: (500000, {'preco_original': 500000, 'pricing_v2': True}),
            'split': lambda total: (25, 125000, total - 125000),
            'parse_date': lambda value: datetime.fromisoformat(value),
            'activity': lambda *args: None,
            'natures': {'Jolly', 'Adamant'},
            'f5_ivs': {'hp', 'ataque', 'defesa', 'ataque_especial', 'defesa_especial', 'velocidade'},
            'categories': ('comum', 'raro', 'ultra_raro'),
            'category_labels': {'comum': 'Comum'},
        }
        bp = create_hype_client_api_blueprint(
            self.db, 'segredo-de-teste', lambda email: {'pode_fazer_pedido_breed': True},
            lambda email: False, lambda email: False, lambda email: None,
            lambda email: None, breed_services=services
        )
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()
        token = URLSafeTimedSerializer('segredo-de-teste', salt='hype-client-api-v1').dumps(
            {'email': 'cliente@example.com'})
        self.headers = {'Authorization': 'Bearer ' + token}
        self.body = {
            'request_id': str(uuid4()), 'pokemon': 'Bulbasaur', 'pokemon_id': 1,
            'nature': 'Jolly', 'ha': False, 'genero': 'indiferente',
            'breed_tipo': 'F5', 'iv_descartado': 'ataque_especial',
            'zero_speed': False, 'treinado': False,
            'ivs_personalizados': {}, 'evs_treinamento': {}
        }

    def send(self, body=None, headers=None):
        return self.client.post('/api/hype/v1/pedidos', json=self.body if body is None else body,
                                headers=self.headers if headers is None else headers)

    def test_login_required(self):
        result = self.send(headers={})
        self.assertEqual(result.status_code, 401)
        self.assertEqual(len(self.db.orders), 0)

    def test_order_is_pending_and_price_is_server_computed(self):
        payload = dict(self.body, preco_total=1, usuario_email='outro@example.com', status='entregue')
        result = self.send(payload)
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertEqual(result.get_json()['pedido']['preco_total'], 500000)
        self.assertEqual(self.db.orders[0]['usuario_email'], 'cliente@example.com')
        self.assertEqual(self.db.orders[0]['player'], 'Treinador')
        self.assertEqual(self.db.orders[0]['status'], 'pendente')

    def test_same_request_is_idempotent(self):
        self.assertEqual(self.send().status_code, 201)
        result = self.send()
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertTrue(result.get_json()['repetido'])
        self.assertEqual(len(self.db.orders), 1)

    def test_ditto_blocked(self):
        payload = dict(self.body, pokemon='Ditto', pokemon_id=132)
        result = self.send(payload)
        self.assertEqual(result.status_code, 422)
        self.assertEqual(len(self.db.orders), 0)

    def test_invalid_evs(self):
        payload = dict(self.body, treinado=True, evs_treinamento={
            'hp': 252, 'attack': 252, 'speed': 252})
        self.assertEqual(self.send(payload).status_code, 422)

    def test_requires_regional_id(self):
        payload = dict(self.body, pokemon='Rapidash Galar', pokemon_id=78, regiao='galar')
        self.assertEqual(self.send(payload).status_code, 422)

    def test_missing_confirmation_uuid(self):
        payload = dict(self.body)
        del payload['request_id']
        self.assertEqual(self.send(payload).status_code, 422)

    def test_two_new_orders_trigger_cooldown(self):
        self.assertEqual(self.send().status_code, 201)
        payload = dict(self.body, request_id=str(uuid4()), pokemon='Pikachu', pokemon_id=25)
        self.assertEqual(self.send(payload).status_code, 429)
        self.assertEqual(len(self.db.orders), 1)


if __name__ == '__main__':
    unittest.main()
