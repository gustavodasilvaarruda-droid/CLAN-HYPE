"""Testes das rotas de carteira sem conectar ao banco de produção."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from jinja2 import DictLoader

from modules.hype_wallet import create_hype_wallet_blueprint


class FakeQuery:
    def __init__(self, data):
        self.data = data

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)


class FakeDB:
    def __init__(self):
        self.data = {
            'hype_wallet_accounts': [{'balance': 150000}],
            'hype_wallet_entries': [{'kind': 'deposit', 'delta': 150000, 'created_at': '2026-10-28T10:00:00'}],
            'hype_wallet_deposit_requests': []
        }
        self.calls = []

    def table(self, name):
        return FakeQuery(self.data[name])

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return FakeQuery([])


class WalletRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'only-for-unit-tests'
        self.app.testing = True
        self.app.jinja_loader = DictLoader({
            'hype_wallet.html': 'Saldo={{saldo}},Ativa={{carteira_ativa}},Depositos={{depositos_ativos}},Admin={{administrador}}'
        })
        self.app.register_blueprint(create_hype_wallet_blueprint(
            login_required=lambda f: f,
            membro_ativo=lambda email: email in ('member@test.invalid','leader@test.invalid'),
            is_admin=lambda email: email == 'leader@test.invalid'
        ))
        self.client = self.app.test_client()
        self.db = FakeDB()

    def login(self, email):
        with self.client.session_transaction() as session:
            session['usuario_email'] = email

    def test_member_reads_only_their_wallet(self):
        self.login('member@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=False):
                response = self.client.get('/carteira-hype')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Saldo=150000', response.data)
        self.assertIn(b'Depositos=False', response.data)
        self.assertEqual(response.headers['Cache-Control'], 'no-store, private')

    def test_non_member_is_forbidden(self):
        self.login('guest@test.invalid')
        response = self.client.get('/carteira-hype')
        self.assertEqual(response.status_code, 403)

    def test_deposit_disabled_does_not_call_rpc(self):
        self.login('member@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=False):
                response = self.client.post('/carteira-hype/depositar', data={'valor': '150000'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.calls, [])

    def test_valid_deposit_creates_pending_request_not_credit(self):
        self.login('member@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=True):
                response = self.client.post('/carteira-hype/depositar', data={'valor': '150000'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.calls, [('hype_wallet_request_deposit',
                          {'p_owner_id':'member@test.invalid','p_amount':150000})])

    def test_invalid_deposit_never_calls_database(self):
        self.login('member@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=True):
                response = self.client.post('/carteira-hype/depositar', data={'valor': '-20'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.calls, [])

    def test_non_admin_cannot_confirm(self):
        self.login('member@test.invalid')
        response = self.client.post('/admin/carteira-hype/25f29cf8-8ff9-459d-80d0-e760e5e5edc0/confirmar')
        self.assertEqual(response.status_code, 403)

    def test_admin_confirmation_uses_rpc(self):
        self.login('leader@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=True):
                response = self.client.post('/admin/carteira-hype/25f29cf8-8ff9-459d-80d0-e760e5e5edc0/confirmar')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.calls[0][0], 'hype_wallet_confirm_deposit')
        self.assertEqual(self.db.calls[0][1]['p_actor_id'], 'leader@test.invalid')

    def test_admin_disabled_confirmation_does_not_call_rpc(self):
        self.login('leader@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=False):
                response = self.client.post('/admin/carteira-hype/25f29cf8-8ff9-459d-80d0-e760e5e5edc0/confirmar')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.calls, [])


    def test_member_reported_payment_calls_rpc(self):
        self.login('member@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=True):
                response = self.client.post(
                    '/carteira-hype/deposito/25f29cf8-8ff9-459d-80d0-e760e5e5edc0/informar-pagamento',
                    data={'referencia': 'Pagamento enviado no Minecraft'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.calls[0][0], 'hype_wallet_report_deposit')
        self.assertEqual(self.db.calls[0][1]['p_owner_id'], 'member@test.invalid')

    def test_disabled_member_report_never_calls_rpc(self):
        self.login('member@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=False):
                response = self.client.post(
                    '/carteira-hype/deposito/25f29cf8-8ff9-459d-80d0-e760e5e5edc0/informar-pagamento')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.calls, [])

    def test_unauthorized_member_cannot_report_payment(self):
        self.login('guest@test.invalid')
        response = self.client.post(
            '/carteira-hype/deposito/25f29cf8-8ff9-459d-80d0-e760e5e5edc0/informar-pagamento')
        self.assertEqual(response.status_code, 403)

    def test_admin_queue_is_readable(self):
        self.login('leader@test.invalid')
        with patch('modules.hype_wallet._service_client', return_value=self.db):
            with patch('modules.hype_wallet._flag_enabled', return_value=False):
                response = self.client.get('/admin/carteira-hype')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Admin=True', response.data)

if __name__ == '__main__':
    unittest.main()
