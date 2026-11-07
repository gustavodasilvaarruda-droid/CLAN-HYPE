"""Isolated contract tests for the HYPE Client's owner-only order mutations.

No real Supabase tables or live orders are accessed.
"""
import unittest
from flask import Flask
from itsdangerous import URLSafeTimedSerializer

from modules.hype_client_api import create_hype_client_api_blueprint


class Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters = []
        self.operation, self.payload = 'select', None
        self.max_rows = None
        self.fields = '*'

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def select(self, fields):
        self.fields = fields
        return self

    def limit(self, n):
        self.max_rows = n
        return self

    def update(self, payload):
        self.operation, self.payload = 'update', payload
        return self

    def insert(self, payload):
        self.operation, self.payload = 'insert', payload
        return self

    def execute(self):
        rows = self.db.tables[self.table]
        if self.operation == 'insert':
            row = dict(self.payload)
            rows.append(row)
            return Result([dict(row)])
        selected = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
        if self.max_rows is not None:
            selected = selected[:self.max_rows]
        if self.operation == 'update':
            for row in selected:
                row.update(self.payload)
            return Result([dict(r) for r in selected])
        if self.fields != '*':
            fields = [k.strip() for k in self.fields.split(',')]
            selected = [{k: r.get(k) for k in fields} for r in selected]
        return Result([dict(r) for r in selected])


class FakeDB:
    def __init__(self):
        self.tables = {
            'usuarios_clan': [
                {'email': 'a@test.invalid', 'cargo': 'visitante', 'nick_jogo': 'A'},
                {'email': 'b@test.invalid', 'cargo': 'visitante', 'nick_jogo': 'B'},
            ],
            'pedidos_breed': [
                {'id': 1, 'usuario_email': 'a@test.invalid', 'status': 'pendente', 'breeder_responsavel': None},
                {'id': 2, 'usuario_email': 'b@test.invalid', 'status': 'pendente', 'breeder_responsavel': None},
                {'id': 3, 'usuario_email': 'a@test.invalid', 'status': 'aguardando_confirmacao', 'breeder_responsavel': 'breeder@test.invalid'},
                {'id': 4, 'usuario_email': 'a@test.invalid', 'status': 'em_producao', 'breeder_responsavel': 'breeder@test.invalid'},
                {'id': 5, 'usuario_email': 'a@test.invalid', 'status': 'entregue', 'breeder_responsavel': 'breeder@test.invalid'},
                {'id': 6, 'usuario_email': 'a@test.invalid', 'status': 'cancelamento_solicitado', 'breeder_responsavel': 'breeder@test.invalid'},
            ],
            'historico_pedidos': [], 'logs_admin': [], 'notificacoes': [],
            'mensagens_pedido': [], 'avaliacoes': [],
        }

    def table(self, name):
        return FakeQuery(self, name)


class OrderActionTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(create_hype_client_api_blueprint(
            self.db, 'test-key', lambda email: {}, lambda email: False,
            lambda email: False, lambda email: None, lambda email: None))
        self.client = app.test_client()
        tokens = URLSafeTimedSerializer('test-key', salt='hype-client-api-v1')
        self.mine = {'Authorization': 'Bearer ' + tokens.dumps({'email': 'a@test.invalid'})}
        self.other = {'Authorization': 'Bearer ' + tokens.dumps({'email': 'b@test.invalid'})}

    def post(self, order_id, action, payload=None, headers=None):
        return self.client.post('/api/hype/v1/meus-pedidos/%s/%s' % (order_id, action),
                                json=payload if payload is not None else {},
                                headers=self.mine if headers is None else headers)

    def test_anonymous_cannot_mutate_order(self):
        result = self.post(1, 'cancelamento', {'motivo': 'mudou de ideia'}, headers={})
        self.assertEqual(result.status_code, 401)
        self.assertEqual(self.db.tables['pedidos_breed'][0]['status'], 'pendente')

    def test_other_customer_cannot_cancel(self):
        result = self.post(2, 'cancelamento', {'motivo': 'teste'})
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.db.tables['pedidos_breed'][1]['status'], 'pendente')

    def test_pending_cancel_is_direct_and_audited(self):
        result = self.post(1, 'cancelamento', {'motivo': 'nao preciso mais'})
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(result.get_json()['status'], 'cancelado')
        self.assertEqual(self.db.tables['pedidos_breed'][0]['status'], 'cancelado')
        self.assertEqual(self.db.tables['historico_pedidos'][0]['usuario_email'], 'a@test.invalid')
        self.assertEqual(self.db.tables['logs_admin'][0]['acao'], 'cancelar')
        self.assertEqual(self.post(1, 'cancelamento').status_code, 409)

    def test_in_progress_cancel_needs_breeder_approval(self):
        response = self.post(4, 'cancelamento', {'motivo': 'preciso cancelar'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['status'], 'cancelamento_solicitado')
        self.assertEqual(self.db.tables['pedidos_breed'][3]['status_antes_cancelamento'], 'em_producao')
        self.assertEqual(len(self.db.tables['notificacoes']), 1)

    def test_receipt_only_after_breeder_reports_delivery(self):
        self.assertEqual(self.post(4, 'confirmar-recebimento').status_code, 409)
        result = self.post(3, 'confirmar-recebimento')
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(self.db.tables['pedidos_breed'][2]['status'], 'entregue')
        self.assertEqual(self.post(3, 'confirmar-recebimento').status_code, 409)

    def test_chat_and_readonly_after_delivery(self):
        self.assertEqual(self.post(1, 'mensagens', {'mensagem': 'Ola!'}).status_code, 409)
        self.assertEqual(self.post(5, 'mensagens', {'mensagem': 'Ola!'}).status_code, 409)
        result = self.post(4, 'mensagens', {'mensagem': 'Pode atualizar?'})
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertEqual(self.db.tables['mensagens_pedido'][0]['pedido_id'], 4)
        self.assertEqual(self.db.tables['mensagens_pedido'][0]['remetente_email'], 'a@test.invalid')

    def test_rating_is_only_for_delivered_order(self):
        self.assertEqual(self.post(4, 'avaliacao', {'nota': 5}).status_code, 409)
        self.assertEqual(self.post(5, 'avaliacao', {'nota': 6}).status_code, 422)
        result = self.post(5, 'avaliacao', {'nota': 5, 'comentario': 'Muito bom'})
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertEqual(self.db.tables['avaliacoes'][0]['avaliado_email'], 'breeder@test.invalid')
        self.assertEqual(self.post(5, 'avaliacao', {'nota': 4}).status_code, 409)

    def test_problem_only_for_completed_order(self):
        self.assertEqual(self.post(4, 'problema', {'motivo': 'falta algo'}).status_code, 409)
        self.assertEqual(self.post(3, 'problema', {'motivo': 'Pokemon incorreto'}).status_code, 200)
        self.assertEqual(self.db.tables['pedidos_breed'][2]['problema_status'], 'aberto')
        self.assertEqual(self.post(3, 'problema', {'motivo': 'novamente'}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
