"""Owner-only read API for one HYPE Breed order in the Minecraft client.

State-changing endpoints must reuse the site's business rules rather than
replicating financial, audit, and notification logic in the client.
"""
from flask import g, jsonify


def install_order_details(api, db, secure, clean_order):
    @api.get('/meus-pedidos/<int:pedido_id>')
    @secure
    def order_details(pedido_id):
        email = g.hype_user['email']
        try:
            found = (db.table('pedidos_breed').select('*')
                     .eq('id', pedido_id).eq('usuario_email', email)
                     .limit(1).execute().data or [])
            if not found:
                # Keep another customer's order indistinguishable from an absent ID.
                return jsonify({'ok': False, 'erro': 'Pedido nao encontrado.'}), 404

            p = found[0]
            status = p.get('status') or ''
            breeder = p.get('breeder_responsavel')
            history = (db.table('historico_pedidos')
                       .select('status_anterior,status_novo,observacao,created_at')
                       .eq('tipo_pedido', 'breed').eq('pedido_id', pedido_id)
                       .order('created_at').limit(200).execute().data or [])
            recent = (db.table('mensagens_pedido')
                      .select('remetente_email,mensagem,created_at,lida')
                      .eq('tipo_pedido', 'breed').eq('pedido_id', pedido_id)
                      .order('created_at', desc=True).limit(20).execute().data or [])
            reviewed = (db.table('avaliacoes')
                        .select('nota,comentario,created_at')
                        .eq('tipo_pedido', 'breed').eq('pedido_id', pedido_id)
                        .eq('avaliador_email', email).limit(1).execute().data or [])
            order = clean_order(p)
            # Order owner's details only; never expose internal commission or emails.
            for key in ('ability', 'zero_speed', 'ivs_personalizados',
                        'treinado', 'evs_treinamento', 'preco_original',
                        'promocao_nome', 'promocao_percentual',
                        'pagamento_confirmado_em', 'recebimento_confirmado_em',
                        'cancelamento_solicitado_em',
                        'motivo_cancelamento_solicitado', 'motivo_cancelamento'):
                if key in p:
                    order[key] = p[key]

            actions = {
                'cancelar_ou_solicitar': status in ('pendente', 'aguardando_pagamento', 'em_producao'),
                'confirmar_recebimento': status == 'aguardando_confirmacao',
                'avaliar': status == 'entregue' and not bool(reviewed),
                'abrir_chat': bool(breeder),
                'enviar_chat': bool(breeder) and status not in ('entregue', 'cancelado'),
                'relatar_problema': status in ('concluido', 'aguardando_confirmacao', 'entregue'),
            }
            return jsonify({
                'ok': True,
                'pedido': order,
                'historico': history,
                'mensagens_recentes': [
                    {'meu': m.get('remetente_email') == email,
                     'mensagem': m.get('mensagem'), 'created_at': m.get('created_at')}
                    for m in reversed(recent)
                ],
                'mensagens_nao_lidas_recentes': sum(
                    1 for m in recent if m.get('remetente_email') != email and not m.get('lida')),
                'avaliacao': reviewed[0] if reviewed else None,
                'acoes': actions,
            })
        except Exception:
            return jsonify({'ok': False, 'erro': 'Nao foi possivel consultar os detalhes.'}), 503
