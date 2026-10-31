"""Regression tests for authenticated HYPE Client Breed preview APIs.

Run: python -m unittest discover -s tests -p 'test_hype_client_breed_api.py'
Requires Flask and the site's dependencies, but no live Supabase credentials.
"""
import unittest
from types import SimpleNamespace
from flask import Flask
from itsdangerous import URLSafeTimedSerializer

from modules.hype_client_api import create_hype_client_api_blueprint, SALT


class Query:
    def select(self, *args): return self
    def eq(self, *args): return self
    def limit(self, *args): return self
    def execute(self):
        return SimpleNamespace(data=[{
            'email': 'trainer@hype.test', 'nick_jogo': 'Trainer', 'cargo': 'membro'
        }])


class DB:
    def table(self, _): return Query()


class BreedApiTests(unittest.TestCase):
    def setUp(self):
        self.price_calls = []
        self.rules = {'breedavel': True, 'so_com_ditto': False}
        self.permission = True

        def calc(kind, **kwargs):
            self.price_calls.append((kind, kwargs))
            return 850000, {'pricing_v2': True, 'cupom_valido': True,
                            'promocao_ativa': True, 'desconto_valor': 150000}

        app = Flask(__name__)
        app.secret_key = 'test-secret-do-not-use-in-production'
        app.register_blueprint(create_hype_client_api_blueprint(
            DB(), app.secret_key,
            lambda email: {'pode_fazer_pedido_breed': self.permission},
            lambda email: True, lambda email: False,
            lambda email: None, lambda email: None,
            breed_services={
                'catalogo': lambda: [
                    {'id': 373, 'name': 'salamence'},
                    {'id': 1, 'name': 'bulbasaur'},
                ],
                'regra': lambda id, name: self.rules,
                'classificar': lambda id: {'categoria': 'raro', 'categoria_label': 'Raro'},
                'calcular': calc,
                'natures': {'Adamant', 'Timid'},
                'ivs_f5': {'hp', 'ataque', 'defesa', 'ataque_especial',
                            'defesa_especial', 'velocidade'},
            }))
        app.testing = True
        self.client = app.test_client()
        token = URLSafeTimedSerializer(app.secret_key, salt=SALT).dumps(
            {'email': 'trainer@hype.test'})
        self.headers = {'Authorization': 'Bearer ' + token}

    def test_bearer_required(self):
        response = self.client.get('/api/hype/v1/breed/pokemon/buscar?q=sal')
        self.assertEqual(response.status_code, 401)

    def test_catalog_search(self):
        response = self.client.get('/api/hype/v1/breed/pokemon/buscar?q=sal',
                                   headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['results'][0]['id'], 373)
        self.assertEqual(len(response.json['results']), 1)

    def test_permission_enforced(self):
        self.permission = False
        response = self.client.get('/api/hype/v1/breed/pokemon/373?nome=Salamence',
                                   headers=self.headers)
        self.assertEqual(response.status_code, 403)

    def test_invalid_f5_without_discard(self):
        response = self.client.post('/api/hype/v1/breed/preco-preview', json={
            'pokemon_id': 373, 'pokemon': 'Salamence', 'breed_tipo': 'F5',
            'ha': False, 'genero': 'indiferente', 'nature': 'Adamant'
        }, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.price_calls, [])

    def test_price_comes_from_server_with_promotions(self):
        response = self.client.post('/api/hype/v1/breed/preco-preview', json={
            'pokemon_id': 373, 'pokemon': 'Salamence', 'breed_tipo': 'F5',
            'iv_descartado': 'defesa', 'ha': True, 'genero': 'indiferente',
            'nature': 'Adamant', 'zero_speed': False, 'treinado': False,
            'cupom': 'HYPE'
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['preco_total'], 850000)
        self.assertEqual(response.json['detalhes']['desconto_valor'], 150000)
        self.assertEqual(self.price_calls[0][1]['codigo_cupom'], 'HYPE')

    def test_ditto_only_uses_ultra_rare_category(self):
        self.rules = {'breedavel': True, 'so_com_ditto': True}
        response = self.client.post('/api/hype/v1/breed/preco-preview', json={
            'pokemon_id': 373, 'pokemon': 'Salamence', 'breed_tipo': 'F6',
            'ha': False, 'genero': 'indiferente'
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.price_calls[0][1]['categoria'], 'ultra_raro')

    def test_submission_stays_blocked(self):
        response = self.client.post('/api/hype/v1/breed/pedidos', json={},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
