import unittest
from functools import wraps
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask, abort, session

from modules.events_v26 import create_events_v26_blueprint


class FakeDB:
    def __init__(self):
        self.tables = {
            'torneios': [{'id': 7, 'titulo': 'HYPE Gen 9 OU',
                         'publicado': True, 'status_torneio': 'em_andamento'}],
            'partidas_torneio': [{
                'id': 22, 'torneio_id': 7, 'status': 'pendente',
                'jogador1_email': 'alpha@example.org', 'jogador1_nick': 'Alpha',
                'jogador2_email': 'beta@example.org', 'jogador2_nick': 'Beta'
            }],
            'hype_batalha_participantes': [],
            'usuarios_clan': [
                {'email': 'alpha@example.org', 'nick_jogo': 'Alpha', 'avatar_url': None},
                {'email': 'beta@example.org', 'nick_jogo': 'Beta', 'avatar_url': None},
            ]
        }
        self.operations = []

    def table(self, name):
        return FakeQuery(self, name)

    def safe(self, name, select='*', **filters):
        return [dict(x) for x in self.tables.get(name, [])
                if all(x.get(k) == v for k, v in filters.items())]


class FakeQuery:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.exclude = db, name, {}, {}
        self.action, self.payload = 'select', None

    def select(self, *_): return self
    def eq(self, key, value):
        self.filters[key] = value
        return self
    def neq(self, key, value):
        self.exclude[key] = value
        return self
    def limit(self, *_): return self
    def update(self, values):
        self.action, self.payload = 'update', values
        return self
    def upsert(self, values, on_conflict=None):
        self.action, self.payload = 'upsert', values
        return self

    def execute(self):
        rows = self.db.tables[self.name]
        matches = [x for x in rows if all(x.get(k) == v for k, v in self.filters.items())
                   and all(x.get(k) != v for k, v in self.exclude.items())]
        if self.action == 'upsert':
            target = next((x for x in rows if x['partida_id'] == self.payload['partida_id']
                          and x['usuario_email'] == self.payload['usuario_email']), None)
            if target is None:
                target = {}
                rows.append(target)
            target.update(self.payload)
            return SimpleNamespace(data=[dict(target)])
        if self.action == 'update':
            for x in matches:
                x.update(self.payload)
            self.db.operations.append((self.name, dict(self.payload), len(matches)))
        return SimpleNamespace(data=[dict(x) for x in matches])


class BattleRoomRoutesTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.app = Flask(__name__)
        self.app.secret_key = 'test-secret-key'
        self.logs = []
        self.notifications = []

        def login_required(func):
            @wraps(func)
            def decorated(*args, **kwargs):
                if not session.get('usuario_email'):
                    abort(401)
                return func(*args, **kwargs)
            return decorated

        self.app.add_url_rule('/torneios', 'torneios', lambda: 'Lista')
        self.app.register_blueprint(create_events_v26_blueprint(
            self.db, login_required, self.db.safe, lambda: False,
            lambda *a: self.logs.append(a),
            lambda *a: self.notifications.append(a)))
        self.client = self.app.test_client()

    def sign_in(self, email):
        with self.client.session_transaction() as sess:
            sess['usuario_email'] = email

    def test_match_page_uses_existing_bracket(self):
        with patch('modules.events_v26.render_template', return_value='Sala HYPE') as view:
            response = self.client.get('/torneios/7/batalha/22')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sala HYPE', response.data)
        self.assertEqual(view.call_args.kwargs['partida']['id'], 22)

    def test_cross_tournament_match_not_found(self):
        response = self.client.get('/torneios/8/batalha/22')
        self.assertEqual(response.status_code, 404)

    def test_only_player_can_mark_ready(self):
        self.sign_in('intruso@example.org')
        self.client.post('/torneios/batalha/22/pronto')
        self.assertEqual(self.db.tables['hype_batalha_participantes'], [])

    def test_anonymous_cannot_submit_result(self):
        response = self.client.post('/torneios/batalha/22/resultado',
                                    data={'vencedor_email': 'alpha@example.org'})
        self.assertEqual(response.status_code, 401)

    def test_both_agree_finalizes_once(self):
        for email in ('alpha@example.org', 'beta@example.org'):
            self.sign_in(email)
            self.client.post('/torneios/batalha/22/pronto')
        for email in ('alpha@example.org', 'beta@example.org'):
            self.sign_in(email)
            self.client.post('/torneios/batalha/22/resultado',
                             data={'vencedor_email': 'alpha@example.org'})
        match = self.db.tables['partidas_torneio'][0]
        self.assertEqual(match['status'], 'finalizada')
        self.assertEqual(match['vencedor_nick'], 'Alpha')
        self.assertEqual(len(self.logs), 1)
        self.assertEqual(len(self.notifications), 1)

    def test_disagreement_keeps_match_pending(self):
        for email in ('alpha@example.org', 'beta@example.org'):
            self.sign_in(email)
            self.client.post('/torneios/batalha/22/pronto')
            self.client.post('/torneios/batalha/22/resultado',
                             data={'vencedor_email': email})
        self.assertEqual(self.db.tables['partidas_torneio'][0]['status'], 'pendente')
        self.assertEqual(len(self.notifications), 0)

    def test_cannot_confirm_result_before_both_ready(self):
        self.sign_in('alpha@example.org')
        self.client.post('/torneios/batalha/22/pronto')
        self.client.post('/torneios/batalha/22/resultado',
                         data={'vencedor_email': 'alpha@example.org'})
        statuses = self.db.tables['hype_batalha_participantes']
        self.assertIsNone(statuses[0]['vencedor_reportado_email'])


if __name__ == '__main__':
    unittest.main()
