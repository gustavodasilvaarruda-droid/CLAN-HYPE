"""Contract tests: owner-only order details in the Minecraft API."""
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

    def eq(self, key, value):
        self.rows = [x for x in self.rows if x.get(key) == value]
        return self

    def order(self, key, desc=False):
        self.rows.sort(key=lambda x: str(x.get(key) or ''), reverse=desc)
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def execute(self):
        cols = None if self.fields == '*' else self.fields.split(',')
        return Result(self.rows if cols is None else [
            {k: row.get(k) for k in cols} for row in self.rows])


class Database:
    def __init__(self):
        pw = generate_password_hash('password-123')
        self.users = [
            {'email': email, 'senha': pw, 'nick_jogo': email, 'cargo': 'visitante'}
            for email in ('a@example.com', 'b@example.com')
        ]
        self.orders = [
            {'id': 1, 'usuario_email': 'a@example.com', 'status': 'pendente',
             'pokemon': 'Pikachu', 'preco_total': 100, 'breeder_responsavel': None},
            {'id': 2, 'usuario_email': 'b@example.com', 'status': 'entregue',
             'pokemon': 'Eevee', 'preco_total': 200,
             'breeder_responsavel': 'breeder@example.com'},
            {'id': 3, 'usuario_email': 'a@example.com',
             'status': 'aguardando_confirmacao', 'pokemon': 'Bulbasaur',
             'preco_total': 300, 'breeder_responsavel': 'breeder@example.com'},
        ]
        self.history = [{'tipo_pedido': 'breed', 'pedido_id': 3,
                         'status_anterior': 'concluido',
                         'status_novo': 'aguardando_confirmacao',
                         'created_at': '2026-11-07T11:00:00',
                         'observacao': 'Breeder informou entrega'}]
        self.messages = [{'tipo_pedido': 'breed', 'pedido_id': 3,
                          'remetente_email': 'breeder@example.com',
                          'mensagem': 'Pokemon pronto!', 'lida': False,
                          'created_at': '2026-11-07T12:00:00'}]
        self.ratings = []

    def table(self, name):
        return Query({
            'usuarios_clan': self.users,
            'pedidos_breed': self.orders,
            'historico_pedidos': self.history,
            'mensagens_pedido': self.messages,
            'avaliacoes': self.ratings,
        }[name])


class OrderDetailTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.app = Flask(__name__)
        self.app.register_blueprint(create_hype_client_api_blueprint(
            self.db, 'test-secret', lambda _: {}, lambda _: False,
            lambda _: False, lambda _: None, lambda _: None))
        self.client = self.app.test_client()

    def headers(self, email):
        login = self.client.post('/api/hype/v1/login', json={
            'email': email, 'senha': 'password-123'})
        self.assertEqual(login.status_code, 200)
        return {'Authorization': 'Bearer ' + login.get_json()['token']}

    def test_unauthenticated_denied(self):
        self.assertEqual(self.client.get('/api/hype/v1/meus-pedidos/1').status_code, 401)

    def test_cannot_view_another_customer_order(self):
        result = self.client.get('/api/hype/v1/meus-pedidos/2',
                                 headers=self.headers('a@example.com'))
        self.assertEqual(result.status_code, 404)

    def test_pending_order_can_cancel_but_not_confirm(self):
        result = self.client.get('/api/hype/v1/meus-pedidos/1',
                                 headers=self.headers('a@example.com'))
        self.assertEqual(result.status_code, 200)
        actions = result.get_json()['acoes']
        self.assertTrue(actions['cancelar_ou_solicitar'])
        self.assertFalse(actions['confirmar_recebimento'])
        self.assertFalse(actions['abrir_chat'])

    def test_delivery_confirmation_history_and_private_messages(self):
        result = self.client.get('/api/hype/v1/meus-pedidos/3',
                                 headers=self.headers('a@example.com'))
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertTrue(data['acoes']['confirmar_recebimento'])
        self.assertEqual(data['historico'][0]['status_novo'], 'aguardando_confirmacao')
        self.assertEqual(data['mensagens_nao_lidas_recentes'], 1)
        self.assertEqual(data['mensagens_recentes'][0]['mensagem'], 'Pokemon pronto!')
        self.assertNotIn('remetente_email', str(data))
        self.assertNotIn('breeder@example.com', str(data))

    def test_not_found(self):
        result = self.client.get('/api/hype/v1/meus-pedidos/99',
                                 headers=self.headers('a@example.com'))
        self.assertEqual(result.status_code, 404)


if __name__ == '__main__':
    unittest.main()
