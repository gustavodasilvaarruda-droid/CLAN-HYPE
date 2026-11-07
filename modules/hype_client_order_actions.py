"""Authenticated client-side actions on *the same* pedidos_breed rows as the site.

No Supabase credentials in the JAR. Do not add breeder/admin actions here:
those need their own authorization and finance workflows.
"""
from datetime import datetime, timezone

from flask import g, jsonify, request


def install_order_actions(api, db, secure):
    def fail(message, status):
        return jsonify({'ok': False, 'erro': message}), status

    def body():
        if not request.is_json:
            return None
        value = request.get_json(silent=True)
        return value if isinstance(value, dict) else None

    def get_order(pedido_id):
        rows = (db.table('pedidos_breed').select('*')
                .eq('id', pedido_id)
                .eq('usuario_email', g.hype_user['email'])
                .limit(1).execute().data or [])
        return rows[0] if rows else None

    def change(pedido_id, old_status, updates):
        """Compare-and-set status so double clicks cannot repeat a transition."""
        rows = (db.table('pedidos_breed').update(updates)
                .eq('id', pedido_id).eq('usuario_email', g.hype_user['email'])
                .eq('status', old_status).execute().data or [])
        return bool(rows)

    def now():
        return datetime.now(timezone.utc).isoformat()

    def history(pedido_id, old, new, observation):
        # Follow the site's historico_pedidos schema with explicit token actor.
        try:
            db.table('historico_pedidos').insert({
                'tipo_pedido': 'breed', 'pedido_id': pedido_id,
                'usuario_email': g.hype_user['email'],
                'status_anterior': old, 'status_novo': new,
                'observacao': observation,
            }).execute()
        except Exception:
            api.logger.warning('Falha ao registrar historico do pedido %s', pedido_id) if hasattr(api, 'logger') else None

    def log(action, pedido_id, details):
        try:
            db.table('logs_admin').insert({
                'usuario_email': g.hype_user['email'], 'acao': action,
                'modulo': 'breed', 'alvo_tipo': 'pedido_breed',
                'alvo_id': str(pedido_id), 'detalhes': details,
            }).execute()
        except Exception:
            pass  # The site's logs are also best-effort.

    def notify(email, title, message, category='aviso', link=None):
        if not email:
            return
        try:
            db.table('notificacoes').insert({
                'usuario_email': email, 'titulo': title,
                'mensagem': message, 'tipo': category,
                'link': link, 'lida': False,
            }).execute()
        except Exception:
            pass

    @api.post('/meus-pedidos/<int:pedido_id>/cancelamento')
    @secure
    def client_cancel_order(pedido_id):
        data = body()
        if data is None:
            return fail('Envie um objeto JSON.', 415)
        if not isinstance(data.get('motivo', ''), str) or len(data.get('motivo', '')) > 500:
            return fail('Motivo invalido (maximo 500 caracteres).', 422)
        motivo = data.get('motivo', '').strip()
        try:
            p = get_order(pedido_id)
            if not p:
                return fail('Pedido nao encontrado.', 404)
            old = p.get('status')
            if old == 'pendente':
                # Direct cancellation happens before payment; never settle money in the client.
                if p.get('pagamento_confirmado_em'):
                    return fail('Cancelamento de pedido pago requer atendimento.', 409)
                updates = {'status': 'cancelado', 'cancelado_em': now(),
                           'cancelado_por': g.hype_user['email'],
                           'motivo_cancelamento': motivo or None}
                new = 'cancelado'
            elif old in ('aguardando_pagamento', 'em_producao'):
                updates = {'status': 'cancelamento_solicitado',
                           'status_antes_cancelamento': old,
                           'cancelamento_solicitado_em': now(),
                           'cancelamento_solicitado_por': g.hype_user['email'],
                           'motivo_cancelamento_solicitado': motivo or None,
                           'cancelamento_decisao': None,
                           'cancelamento_decidido_em': None,
                           'cancelamento_decidido_por': None}
                new = 'cancelamento_solicitado'
            else:
                return fail('Cancelamento indisponivel neste status.', 409)
            if not change(pedido_id, old, updates):
                return fail('O pedido mudou. Atualize os dados e tente novamente.', 409)
            history(pedido_id, old, new, motivo or ('Cancelamento direto' if new == 'cancelado' else 'Solicitacao de cancelamento'))
            log('cancelar' if new == 'cancelado' else 'solicitar_cancelamento', pedido_id,
                {'motivo': motivo, 'direto': new == 'cancelado'})
            if p.get('breeder_responsavel') and p.get('breeder_responsavel') != g.hype_user['email']:
                notify(p['breeder_responsavel'],
                       'Breed cancelado' if new == 'cancelado' else 'Solicitacao de cancelamento',
                       ('Pedido #%s cancelado.' if new == 'cancelado'
                        else 'Cliente solicitou cancelamento do pedido #%s. Revise no site HYPE.') % pedido_id,
                       link='/breed/fila')
            return jsonify({'ok': True, 'pedido_id': pedido_id, 'status': new,
                            'solicitacao': new == 'cancelamento_solicitado'})
        except Exception:
            return fail('Nao foi possivel solicitar o cancelamento.', 503)

    @api.post('/meus-pedidos/<int:pedido_id>/confirmar-recebimento')
    @secure
    def client_confirm_receipt(pedido_id):
        if body() is None:
            return fail('Envie um objeto JSON.', 415)
        try:
            p = get_order(pedido_id)
            if not p:
                return fail('Pedido nao encontrado.', 404)
            if p.get('status') != 'aguardando_confirmacao':
                return fail('A entrega ainda nao pode ser confirmada.', 409)
            timestamp = now()
            if not change(pedido_id, 'aguardando_confirmacao', {
                'status': 'entregue', 'entregue_em': timestamp,
                'recebimento_confirmado_em': timestamp,
                'recebimento_confirmado_por': g.hype_user['email'],
            }):
                return fail('Pedido alterado; atualize antes de confirmar.', 409)
            history(pedido_id, 'aguardando_confirmacao', 'entregue',
                    'Recebimento confirmado pelo cliente.')
            if p.get('breeder_responsavel'):
                notify(p['breeder_responsavel'], 'Entrega confirmada',
                       'O cliente confirmou o recebimento do Breed #%s.' % pedido_id,
                       'sucesso', '/breed/fila')
            return jsonify({'ok': True, 'pedido_id': pedido_id,
                            'status': 'entregue', 'avaliacao_liberada': True})
        except Exception:
            return fail('Nao foi possivel confirmar o recebimento.', 503)

    @api.post('/meus-pedidos/<int:pedido_id>/mensagens')
    @secure
    def client_send_message(pedido_id):
        data = body()
        if data is None:
            return fail('Envie um objeto JSON.', 415)
        message = data.get('mensagem')
        if not isinstance(message, str) or not message.strip() or len(message) > 1500:
            return fail('Mensagem invalida (1 a 1500 caracteres).', 422)
        try:
            p = get_order(pedido_id)
            if not p:
                return fail('Pedido nao encontrado.', 404)
            if not p.get('breeder_responsavel') or p.get('status') in ('entregue', 'cancelado'):
                return fail('Chat indisponivel ou arquivado.', 409)
            db.table('mensagens_pedido').insert({
                'tipo_pedido': 'breed', 'pedido_id': pedido_id,
                'remetente_email': g.hype_user['email'],
                'mensagem': message.strip(),
            }).execute()
            notify(p['breeder_responsavel'], 'Nova mensagem',
                   'Voce recebeu uma mensagem no pedido #%s.' % pedido_id,
                   'mensagem', '/pedido/breed/%s/chat' % pedido_id)
            return jsonify({'ok': True, 'pedido_id': pedido_id}), 201
        except Exception:
            return fail('Nao foi possivel enviar a mensagem.', 503)

    @api.post('/meus-pedidos/<int:pedido_id>/avaliacao')
    @secure
    def client_rate_breeder(pedido_id):
        data = body()
        if data is None:
            return fail('Envie um objeto JSON.', 415)
        score = data.get('nota')
        comment = data.get('comentario', '')
        if type(score) is not int or not 1 <= score <= 5:
            return fail('Nota deve ser de 1 a 5.', 422)
        if not isinstance(comment, str) or len(comment) > 700:
            return fail('Comentario invalido (maximo 700 caracteres).', 422)
        try:
            p = get_order(pedido_id)
            if not p:
                return fail('Pedido nao encontrado.', 404)
            if p.get('status') != 'entregue' or not p.get('breeder_responsavel'):
                return fail('Avaliacao indisponivel neste status.', 409)
            prior = (db.table('avaliacoes').select('pedido_id')
                     .eq('tipo_pedido', 'breed').eq('pedido_id', pedido_id)
                     .eq('avaliador_email', g.hype_user['email'])
                     .limit(1).execute().data or [])
            if prior:
                return fail('Pedido ja avaliado.', 409)
            try:
                db.table('avaliacoes').insert({
                    'tipo_pedido': 'breed', 'pedido_id': pedido_id,
                    'avaliador_email': g.hype_user['email'],
                    'avaliado_email': p['breeder_responsavel'],
                    'nota': score, 'comentario': comment.strip() or None,
                }).execute()
            except Exception:
                return fail('Avaliacao nao gravada; verifique se ja existe.', 409)
            notify(p['breeder_responsavel'], 'Nova avaliacao',
                   'Voce recebeu uma avaliacao de %s/5.' % score,
                   'sucesso', '/breeders')
            return jsonify({'ok': True, 'pedido_id': pedido_id, 'nota': score}), 201
        except Exception:
            return fail('Nao foi possivel enviar a avaliacao.', 503)

    @api.post('/meus-pedidos/<int:pedido_id>/problema')
    @secure
    def client_report_problem(pedido_id):
        data = body()
        if data is None:
            return fail('Envie um objeto JSON.', 415)
        reason = data.get('motivo')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 800:
            return fail('Descreva o problema em ate 800 caracteres.', 422)
        try:
            p = get_order(pedido_id)
            if not p:
                return fail('Pedido nao encontrado.', 404)
            if p.get('status') not in ('concluido', 'aguardando_confirmacao', 'entregue'):
                return fail('Nao e possivel relatar problema neste status.', 409)
            if p.get('problema_status') == 'aberto':
                return fail('Ja existe um problema aberto para este pedido.', 409)
            db.table('pedidos_breed').update({
                'problema_status': 'aberto', 'problema_motivo': reason.strip(),
                'problema_aberto_em': now(),
            }).eq('id', pedido_id).eq('usuario_email', g.hype_user['email']).eq('status', p['status']).execute()
            history(pedido_id, p['status'], p['status'],
                    'Cliente abriu um problema de entrega: ' + reason.strip())
            notify(p.get('breeder_responsavel'), 'Problema na entrega',
                   'O cliente abriu um problema no Breed #%s.' % pedido_id,
                   'aviso', '/pedido/breed/%s/chat' % pedido_id)
            return jsonify({'ok': True, 'pedido_id': pedido_id,
                            'problema_status': 'aberto'})
        except Exception:
            return fail('Nao foi possivel registrar o problema.', 503)
