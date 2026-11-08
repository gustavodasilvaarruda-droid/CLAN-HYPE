"""Regression tests: game-client actions share the site's server authority."""
from functools import wraps
from types import SimpleNamespace
from flask import Blueprint, Flask, flash, g, jsonify, session

from modules.hype_client_breeder_actions import install_breeder_actions


class Table:
    def __init__(self, db):
        self.db = db
        self.pedido = None

    def select(self, *_):
        return self

    def eq(self, col, value):
        if col == 'id':
            self.pedido = value
        return self

    def limit(self, *_):
        return self

    def execute(self):
        p = self.db.orders.get(self.pedido)
        return SimpleNamespace(data=[dict(p)] if p else [])


class DB:
    def __init__(self):
        self.orders = {184: {
            'id': 184, 'status': 'pendente', 'breeder_responsavel': None,
        }}

    def table(self, name):
        assert name == 'pedidos_breed'
        return Table(self)


def context(order_id, permission=True, failing=False):
    db = DB()
    bp = Blueprint('hype_client_api', __name__, url_prefix='/api/hype/v1')

    def secure(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            g.hype_user = {'email': 'breeder@example.com', 'nick_jogo': 'TestBreeder'}
            return fn(*args, **kwargs)
        return wrapped

    def require_module(_code):
        return lambda fn: fn

    def site_handler(pedido_id):
        assert session.get('usuario_email') == 'breeder@example.com'
        assert session.get('nick_jogo') == 'TestBreeder'
        if failing:
            flash('Regra do site recusou este pedido.', 'erro')
            return
        db.orders[pedido_id]['status'] = 'aguardando_pagamento'
        db.orders[pedido_id]['breeder_responsavel'] = session['usuario_email']
        flash('Pedido assumido.', 'sucesso')

    perms = {'pode_assumir_breed': permission, 'pode_concluir_breed': permission}
    install_breeder_actions(
        bp, db, secure, require_module, lambda _: perms,
        {'assumir': site_handler},
    )
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.secret_key = 'test-secret'
    app.register_blueprint(bp)
    return app, db


def test_assume_calls_real_site_workflow_without_browser_cookie():
    app, db = context(184)
    result = app.test_client().post('/api/hype/v1/fila/184/acao', json={'acao': 'assumir'})
    assert result.status_code == 200
    assert result.json['ok'] is True
    assert result.json['status'] == 'aguardando_pagamento'
    assert db.orders[184]['breeder_responsavel'] == 'breeder@example.com'
    assert not result.headers.get('Set-Cookie')


def test_invalid_or_unauthorized_does_not_touch_order():
    app, db = context(184, permission=False)
    result = app.test_client().post('/api/hype/v1/fila/184/acao', json={'acao': 'assumir'})
    assert result.status_code == 403
    assert db.orders[184]['status'] == 'pendente'
    result = app.test_client().post('/api/hype/v1/fila/184/acao', json={'acao': 'devolver', 'motivo': ''})
    assert result.status_code == 422


def test_site_rejection_stays_rejection_and_no_false_success():
    app, db = context(184, failing=True)
    result = app.test_client().post('/api/hype/v1/fila/184/acao', json={'acao': 'assumir'})
    assert result.status_code == 409
    assert result.json['ok'] is False
    assert db.orders[184]['status'] == 'pendente'


def test_stale_status_cannot_repeat_action():
    app, db = context(184)
    db.orders[184]['status'] = 'concluido'
    result = app.test_client().post('/api/hype/v1/fila/184/acao', json={'acao': 'assumir'})
    assert result.status_code == 409
    assert db.orders[184]['status'] == 'concluido'


def test_cannot_act_on_other_breeders_order_without_admin():
    app, db = context(184)
    db.orders[184] = {'id': 184, 'status': 'em_producao',
                      'breeder_responsavel': 'someone-else@example.com'}
    result = app.test_client().post('/api/hype/v1/fila/184/acao', json={'acao': 'concluir'})
    assert result.status_code == 403
    assert db.orders[184]['status'] == 'em_producao'
