"""Smoke tests for the HYPE Client API's server-side module gate."""
import unittest
from flask import Flask
from werkzeug.security import generate_password_hash

from modules.hype_client_api import create_hype_client_api_blueprint


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, rows):
        self.rows = [dict(x) for x in rows]
        self.fields = '*'

    def select(self, fields):
        self.fields = fields
        return self

    def eq(self, name, value):
        self.rows = [x for x in self.rows if x.get(name) == value]
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, number):
        self.rows = self.rows[:number]
        return self

    def execute(self):
        keys = None if self.fields == '*' else [x.strip() for x in self.fields.split(',')]
        return Result(self.rows if keys is None else [
            {k: row.get(k) for k in keys} for row in self.rows])


class Database:
    def __init__(self):
        pw = generate_password_hash('password-123')
        self.users = [
            {'email':'visitor@example.com', 'senha':pw, 'nick_jogo':'Visitor', 'cargo':'visitante'},
            {'email':'member@example.com', 'senha':pw, 'nick_jogo':'Member', 'cargo':'membro'},
            {'email':'hype@example.com', 'senha':pw, 'nick_jogo':'Hype', 'cargo':'membro'}
        ]
        self.grants = [{'modulo_codigo':'breeder','cargo_id':'membro'}]
        self.individual = []

    def table(self, name):
        tables = {
            'usuarios_clan': self.users,
            'hype_modulos': [{'codigo':'breeder','nome':'HYPE Breeder',
                              'estado':'ativo','visivel':True}],
            'hype_modulos_grupos': self.grants,
            'hype_modulos_acessos': self.individual,
            'pedidos_breed': []
        }
        return Query(tables[name])


class TestApiModuleGate(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.app = Flask(__name__)
        self.app.register_blueprint(create_hype_client_api_blueprint(
            self.db, 'test-secret', lambda email: {'pode_ver_fila_breed': email == 'hype@example.com',
                           'pode_assumir_breed': email == 'hype@example.com'},
            lambda email: email == 'hype@example.com',
            lambda _: False, lambda _: None, lambda _: None))
        self.client = self.app.test_client()

    def bearer(self, email):
        response = self.client.post('/api/hype/v1/login', json={
            'email':email,'senha':'password-123'})
        self.assertEqual(response.status_code, 200)
        return {'Authorization':'Bearer ' + response.get_json()['token']}

    def test_no_token_is_denied(self):
        response = self.client.get('/api/hype/v1/meus-pedidos')
        self.assertEqual(response.status_code, 401)

    def test_visitor_can_read_own_orders_even_without_module(self):
        response = self.client.get('/api/hype/v1/meus-pedidos',
                                   headers=self.bearer('visitor@example.com'))
        self.assertEqual(response.status_code, 200)

    def test_visitor_queue_is_denied(self):
        response = self.client.get('/api/hype/v1/fila',
                                   headers=self.bearer('visitor@example.com'))
        self.assertEqual(response.status_code, 403)

    def test_basic_member_can_access_basic_module(self):
        response = self.client.get('/api/hype/v1/meus-pedidos',
                                   headers=self.bearer('member@example.com'))
        self.assertEqual(response.status_code, 200)

    def test_basic_member_cannot_access_hype_exclusive_module(self):
        self.db.grants = [{'modulo_codigo':'breeder','cargo_id':'membro_hype'}]
        response = self.client.get('/api/hype/v1/fila',
                                   headers=self.bearer('member@example.com'))
        self.assertEqual(response.status_code, 403)

    def test_hype_member_can_access_hype_exclusive_module(self):
        self.db.grants = [{'modulo_codigo':'breeder','cargo_id':'membro_hype'}]
        response = self.client.get('/api/hype/v1/fila',
                                   headers=self.bearer('hype@example.com'))
        self.assertEqual(response.status_code, 200)

    def test_global_disabled_wins(self):
        # Global switches must be checked on the server even for HYPE members.
        original = self.db.table
        def disabled_table(name):
            if name == 'hype_modulos':
                return Query([{'codigo':'breeder','estado':'desativado','visivel':True}])
            return original(name)
        self.db.table = disabled_table
        response = self.client.get('/api/hype/v1/fila',
                                   headers=self.bearer('hype@example.com'))
        self.assertEqual(response.status_code, 403)

    def test_global_maintenance_wins(self):
        original = self.db.table
        def maintenance_table(name):
            if name == 'hype_modulos':
                return Query([{'codigo':'breeder','estado':'manutencao','visivel':True}])
            return original(name)
        self.db.table = maintenance_table
        response = self.client.get('/api/hype/v1/fila',
                                   headers=self.bearer('hype@example.com'))
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
