"""Carteira HYPE: rotas web autenticadas; nenhum dinheiro e movimentado no navegador.

REQUER: SUPABASE_SERVICE_ROLE_KEY no ambiente do servidor, nunca em HTML/JS.
Todas as escritas passam por RPCs transacionais. Nao ativa gastos de Breed ate
a integracao atomica com pedidos e repasses estar concluida.
"""
import os
import re
from functools import lru_cache
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from supabase import create_client


@lru_cache(maxsize=1)
def _service_client():
    url = os.environ.get('SUPABASE_URL', '').strip()
    key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not url or not key:
        return None
    # Separado do cliente existente para nunca depender da anon key.
    try:
        return create_client(url, key)
    except Exception:
        # Falha fechada: nenhum botao de deposito deve funcionar sem credencial valida.
        return None


def create_hype_wallet_blueprint(login_required, membro_ativo, is_admin):
    bp = Blueprint('hype_wallet', __name__)

    @bp.after_request
    def private_cache(response):
        response.headers['Cache-Control'] = 'no-store, private'
        return response

    def _member_email():
        email = session.get('usuario_email')
        if not email or not membro_ativo(email):
            abort(403)
        return email

    def _admin_email():
        email = session.get('usuario_email')
        if not email or not is_admin(email):
            abort(403)
        return email

    @bp.route('/carteira-hype', methods=['GET'])
    @login_required
    def carteira():
        email = _member_email()
        db = _service_client()
        saldo, movimentos, depositos = 0, [], []
        if db:
            try:
                contas = db.table('hype_wallet_accounts').select('balance').eq('owner_id',email).limit(1).execute().data or []
                saldo = int(contas[0]['balance']) if contas else 0
                movimentos = db.table('hype_wallet_entries').select('kind,delta,created_at').eq('owner_id',email).order('created_at',desc=True).limit(30).execute().data or []
                depositos = db.table('hype_wallet_deposit_requests').select('id,amount,status,created_at,note').eq('owner_id',email).order('created_at',desc=True).limit(15).execute().data or []
            except Exception:
                flash('A carteira está temporariamente indisponível. Tente mais tarde.', 'erro')
                db = None
        return render_template('hype_wallet.html', saldo=saldo, movimentos=movimentos,
                               depositos=depositos, carteira_ativa=bool(db), administrador=False)

    @bp.route('/carteira-hype/depositar', methods=['POST'])
    @login_required
    def solicitar_deposito():
        email = _member_email()
        db = _service_client()
        if not db:
            flash('Carteira ainda não habilitada no servidor.', 'erro')
            return redirect(url_for('hype_wallet.carteira'))
        entrada = (request.form.get('valor') or '').strip()
        if not re.fullmatch(r'[0-9]{1,13}', entrada):
            flash('Informe o valor inteiro em moedas do jogo, por exemplo 150000.', 'erro')
            return redirect(url_for('hype_wallet.carteira'))
        valor = int(entrada)
        if not 1 <= valor <= 1_000_000_000_000:
            flash('Valor fora do limite permitido.', 'erro')
            return redirect(url_for('hype_wallet.carteira'))
        try:
            db.rpc('hype_wallet_request_deposit',{'p_owner_id':email,'p_amount':valor}).execute()
            flash('Solicitação enviada. Pague no jogo e aguarde a confirmação do líder.', 'sucesso')
        except Exception:
            flash('Não foi possível solicitar o depósito. Confira se já existem pedidos pendentes.', 'erro')
        return redirect(url_for('hype_wallet.carteira'))

    @bp.route('/admin/carteira-hype', methods=['GET'])
    @login_required
    def admin_depositos():
        _admin_email()
        db = _service_client()
        pendentes = []
        if db:
            try:
                pendentes = db.table('hype_wallet_deposit_requests').select('id,owner_id,amount,created_at,status').eq('status','pending').order('created_at').limit(100).execute().data or []
            except Exception:
                flash('Não foi possível carregar os depósitos pendentes.', 'erro')
        return render_template('hype_wallet.html', administrador=True, carteira_ativa=bool(db),
                               pendentes=pendentes, saldo=0, depositos=[], movimentos=[])

    @bp.route('/admin/carteira-hype/<uuid:request_id>/<acao>', methods=['POST'])
    @login_required
    def admin_decidir_deposito(request_id, acao):
        actor = _admin_email()
        db = _service_client()
        if not db:
            flash('Configure a conexão administrativa da carteira.', 'erro')
            return redirect(url_for('hype_wallet.admin_depositos'))
        if acao not in ('confirmar','recusar'):
            abort(404)
        # A equipe confere a transferência no servidor de Minecraft antes de confirmar.
        try:
            if acao == 'confirmar':
                db.rpc('hype_wallet_confirm_deposit',{'p_request_id':str(request_id),'p_actor_id':actor}).execute()
                flash('Depósito confirmado e saldo creditado uma única vez.', 'sucesso')
            else:
                db.rpc('hype_wallet_reject_deposit',{'p_request_id':str(request_id),
                    'p_actor_id':actor,'p_note':(request.form.get('motivo') or '')[:500]}).execute()
                flash('Solicitação recusada, sem alterar o saldo.', 'sucesso')
        except Exception:
            flash('Operação não concluída. Recarregue a página e verifique o status do pedido.', 'erro')
        return redirect(url_for('hype_wallet.admin_depositos'))
    return bp
