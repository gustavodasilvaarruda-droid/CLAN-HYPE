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

    def rpc(self, name, args):
        return FakeRPC(self, name, args)

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


class FakeRPC:
    """Simula as funções atômicas Postgres, sem alterar o banco real."""
    def __init__(self, db, name, args):
        self.db, self.name, self.args = db, name, args

    def execute(self):
        a = self.args
        match = next((m for m in self.db.tables['partidas_torneio']
                      if m['id'] == a['p_partida_id']), None)
        event = next((t for t in self.db.tables['torneios']
                      if match and t['id'] == match['torneio_id']), None)
        email = a['p_usuario_email']
        if not match or not event or event['status_torneio'] != 'em_andamento' or match['status'] == 'finalizada':
            return SimpleNamespace(data=False if self.name.endswith('_pronto') else {'status': 'bloqueado'})
        players = [match['jogador1_email'], match['jogador2_email']]
        if not all(players) or players[0] == players[1] or email not in players:
            return SimpleNamespace(data=False if self.name.endswith('_pronto') else {'status': 'bloqueado'})
        state = self.db.tables['hype_batalha_participantes']
        mine = next((row for row in state
                     if row['partida_id'] == match['id'] and row['usuario_email'] == email), None)
        if self.name == 'hype_batalha_confirmar_pronto':
            if mine is None:
                state.append({'partida_id': match['id'], 'usuario_email': email,
                              'pronto': True, 'vencedor_reportado_email': None})
            else:
                mine['pronto'] = True
            return SimpleNamespace(data=True)
        if self.name != 'hype_batalha_confirmar_resultado':
            raise ValueError('RPC desconhecida')
        winner = a['p_vencedor_email']
        if winner not in players:
            return SimpleNamespace(data={'status': 'bloqueado'})
        records = [next((row for row in state
                         if row['partida_id'] == match['id'] and row['usuario_email'] == p), {})
                   for p in players]
        if not all(x.get('pronto') for x in records):
            return SimpleNamespace(data={'status': 'aguardando_pronto'})
        mine['vencedor_reportado_email'] = winner
        reported = [x.get('vencedor_reportado_email') for x in records]
        if reported[0] and reported[0] == reported[1]:
            match.update(status='finalizada', vencedor_email=winner,
                         vencedor_nick=match['jogador1_nick'] if winner == players[0]
                         else match['jogador2_nick'])
            return SimpleNamespace(data={'status': 'finalizada',
                                         'vencedor_email': winner,
                                         'vencedor_nick': match['vencedor_nick']})
        return SimpleNamespace(data={'status': 'divergencia' if all(reported)
                                     else 'aguardando_oponente'})


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
            lambda *a: self.notifications.append(a), battle_db=self.db))
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
                                    data={'vencedor_slot': '1'})
        self.assertEqual(response.status_code, 401)

    def test_both_agree_finalizes_once(self):
        for email in ('alpha@example.org', 'beta@example.org'):
            self.sign_in(email)
            self.client.post('/torneios/batalha/22/pronto')
        for email in ('alpha@example.org', 'beta@example.org'):
            self.sign_in(email)
            self.client.post('/torneios/batalha/22/resultado',
                             data={'vencedor_slot': '1'})
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
                             data={'vencedor_slot': '1' if email == 'alpha@example.org' else '2'})
        self.assertEqual(self.db.tables['partidas_torneio'][0]['status'], 'pendente')
        self.assertEqual(len(self.notifications), 0)

    def test_cannot_confirm_result_before_both_ready(self):
        self.sign_in('alpha@example.org')
        self.client.post('/torneios/batalha/22/pronto')
        self.client.post('/torneios/batalha/22/resultado',
                         data={'vencedor_slot': '1'})
        statuses = self.db.tables['hype_batalha_participantes']
        self.assertIsNone(statuses[0]['vencedor_reportado_email'])

    def test_cancelled_tournament_rejects_ready_and_results(self):
        self.db.tables['torneios'][0]['status_torneio'] = 'cancelado'
        self.sign_in('alpha@example.org')
        self.client.post('/torneios/batalha/22/pronto')
        self.client.post('/torneios/batalha/22/resultado', data={'vencedor_slot': '1'})
        self.assertEqual(self.db.tables['hype_batalha_participantes'], [])
        self.assertEqual(self.db.tables['partidas_torneio'][0]['status'], 'pendente')

    def test_invalid_winner_slot_does_not_write(self):
        for email in ('alpha@example.org', 'beta@example.org'):
            self.sign_in(email)
            self.client.post('/torneios/batalha/22/pronto')
        self.sign_in('alpha@example.org')
        self.client.post('/torneios/batalha/22/resultado',
                         data={'vencedor_slot': '3'})
        self.assertEqual(self.db.tables['partidas_torneio'][0]['status'], 'pendente')
        self.assertFalse(any(x.get('vencedor_reportado_email')
                             for x in self.db.tables['hype_batalha_participantes']))

    def test_already_finalized_cannot_register_twice(self):
        for email in ('alpha@example.org', 'beta@example.org'):
            self.sign_in(email)
            self.client.post('/torneios/batalha/22/pronto')
            self.client.post('/torneios/batalha/22/resultado',
                             data={'vencedor_slot': '1'})
        self.sign_in('beta@example.org')
        self.client.post('/torneios/batalha/22/resultado',
                         data={'vencedor_slot': '2'})
        self.assertEqual(self.db.tables['partidas_torneio'][0]['vencedor_email'],
                         'alpha@example.org')
        self.assertEqual(len(self.notifications), 1)
        self.assertEqual(len(self.logs), 1)

if __name__ == '__main__':
    unittest.main()
