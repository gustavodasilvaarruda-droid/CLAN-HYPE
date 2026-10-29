"""Integração real do Flask/CSRF usando Supabase inteiramente simulado.

Não usa credenciais reais, não cria contas e nunca chama o banco externo.
"""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class Query:
    def __init__(self, table, database):
        self.table_name = table
        self.db = database

    def select(self, *args, **kwargs): return self
    def eq(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self
    def order(self, *args, **kwargs): return self
    def in_(self, *args, **kwargs): return self
    def execute(self):
        rows = {
            'usuarios_clan': [{'cargo': 'lider'}],
            'membros_hype': [{'ativo': True}],
            'permissoes_cargos': [{'pode_gerenciar_cargos': True}],
        }
        return SimpleNamespace(data=rows.get(self.table_name, []))


class SafeFakeDB:
    def __init__(self): self.rpc_calls = []
    def table(self, name): return Query(name, self)
    def rpc(self, name, payload):
        self.rpc_calls.append((name, payload))
        if name == 'hype_wallet_integrity_report':
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=[{
                'ledger_sum': 0, 'balances_sum': 0,
                'mismatched_accounts': 0, 'confirmed_without_entry': 0,
                'entries_without_confirmation': 0
            }]))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))


class WalletFullFlaskIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = SafeFakeDB()
        app_file = Path(__file__).resolve().parents[1] / 'app.py'
        name = '_hype_wallet_full_flask_test'
        spec = importlib.util.spec_from_file_location(name, app_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        # Substitui a criação do cliente Supabase ANTES de importar o aplicativo.
        with patch.dict(os.environ, {
            'SECRET_KEY': 'wallet-integration-only-not-a-secret',
            'SUPABASE_URL': 'https://example.invalid',
            'SUPABASE_KEY': 'integration-fake',
            'SESSION_COOKIE_SECURE': '0',
            'HYPE_WALLET_ENABLED': '0',
            'HYPE_WALLET_DEPOSITS_ENABLED': '0',
        }):
            with patch('supabase.create_client', return_value=cls.db):
                spec.loader.exec_module(module)
        cls.flask_module = module
        cls.app = module.app
        cls.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)

    def setUp(self):
        self.client = self.app.test_client()
        self.db.rpc_calls.clear()
        self.env_patch = patch.dict(os.environ, {
            'HYPE_WALLET_ENABLED': '0',
            'HYPE_WALLET_DEPOSITS_ENABLED': '0',
            'SESSION_COOKIE_SECURE': '0',
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def login(self, email='leader@test.invalid', token='valid-csrf-token'):
        with self.client.session_transaction() as sess:
            sess['usuario_email'] = email
            sess['nick_jogo'] = 'HYPE-Test'
            sess['_csrf_token'] = token

    def test_global_csrf_blocks_deposit_without_token(self):
        self.login()
        with patch('modules.hype_wallet._service_client', return_value=self.db), \
             patch('modules.hype_wallet._flag_enabled', return_value=True):
            response = self.client.post('/carteira-hype/depositar', data={'valor': '1000'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.rpc_calls, [])

    def test_global_csrf_blocks_false_token(self):
        self.login()
        with patch('modules.hype_wallet._service_client', return_value=self.db), \
             patch('modules.hype_wallet._flag_enabled', return_value=True):
            response = self.client.post('/carteira-hype/depositar',
                data={'valor': '1000', 'csrf_token': 'wrong'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.rpc_calls, [])

    def test_valid_csrf_reaches_wallet_route_without_external_calls(self):
        self.login()
        with patch('modules.hype_wallet._service_client', return_value=self.db), \
             patch('modules.hype_wallet._flag_enabled', return_value=True):
            response = self.client.post('/carteira-hype/depositar',
                data={'valor': '1000', 'csrf_token': 'valid-csrf-token'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual([n for n,_ in self.db.rpc_calls],
                         ['hype_wallet_request_deposit'])

    def test_admin_confirmation_requires_csrf(self):
        self.login()
        with patch('modules.hype_wallet._service_client', return_value=self.db), \
             patch('modules.hype_wallet._flag_enabled', return_value=True):
            response = self.client.post(
              '/admin/carteira-hype/25f29cf8-8ff9-459d-80d0-e760e5e5edc0/confirmar')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.rpc_calls, [])

    def test_csrf_protected_admin_confirmation_checks_audit(self):
        self.login()
        with patch('modules.hype_wallet._service_client', return_value=self.db), \
             patch('modules.hype_wallet._flag_enabled', return_value=True):
            response = self.client.post(
              '/admin/carteira-hype/25f29cf8-8ff9-459d-80d0-e760e5e5edc0/confirmar',
              data={'csrf_token': 'valid-csrf-token'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual([n for n,_ in self.db.rpc_calls],
                         ['hype_wallet_integrity_report', 'hype_wallet_confirm_deposit'])


if __name__ == '__main__':
    unittest.main()
