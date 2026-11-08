"""Bearer-authenticated HYPE Client bridge to existing website Breed workflows.

Never duplicate payment, commission, cancellation, notifications or role logic
in a second implementation. The website handlers are the sole write authority.

The isolated internal request context exists only during a previously
authenticated /api/hype/v1/ POST, and does not set a browser-login cookie.
"""
from flask import current_app, g, get_flashed_messages, jsonify, request, session


HANDLERS = {
    'assumir': ('pendente', 'aguardando_pagamento'),
    'confirmar_pagamento': ('aguardando_pagamento', 'em_producao'),
    'concluir': ('em_producao', 'concluido'),
    'devolver': (('aguardando_pagamento', 'em_producao', 'cancelamento_solicitado'), 'pendente'),
    'entregar': ('concluido', 'aguardando_confirmacao'),
    'cancelamento_aprovar': ('cancelamento_solicitado', 'cancelado'),
    'cancelamento_recusar': ('cancelamento_solicitado', ('aguardando_pagamento', 'em_producao')),
}


def install_breeder_actions(api, db, secure, require_module, get_permissions, handlers):
    """Install authorized JSON wrappers around *existing* website functions."""

    def fail(message, code):
        return jsonify({'ok': False, 'erro': message}), code

    @api.post('/fila/<int:pedido_id>/acao')
    @secure
    @require_module('breeder')
    def breeder_action(pedido_id):
        if not request.is_json:
            return fail('Envie JSON.', 415)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return fail('JSON invalido.', 400)

        action = body.get('acao')
        if not isinstance(action, str) or action not in HANDLERS:
            return fail('Acao invalida.', 422)
        motive = body.get('motivo', '')
        if not isinstance(motive, str) or len(motive) > 500:
            return fail('Motivo invalido.', 422)
        motive = motive.strip()
        if action == 'devolver' and len(motive) < 3:
            return fail('Informe um motivo para devolver o pedido.', 422)
        handler = handlers.get(action)
        if not callable(handler):
            return fail('Operacao ainda nao publicada.', 503)

        actor = dict(g.hype_user)
        email = actor.get('email')
        try:
            perms = get_permissions(email) or {}
            if action == 'assumir' and not perms.get('pode_assumir_breed'):
                return fail('Sem permissao para assumir pedidos.', 403)
            if action == 'concluir' and not perms.get('pode_concluir_breed'):
                return fail('Sem permissao para concluir pedidos.', 403)

            found = (db.table('pedidos_breed').select('*')
                     .eq('id', pedido_id).limit(1).execute().data or [])
            if not found:
                return fail('Pedido nao encontrado.', 404)
            order = found[0]
            previous = order.get('status')
            expected_before, expected_after = HANDLERS[action]
            if (previous not in expected_before if isinstance(expected_before, tuple)
                    else previous != expected_before):
                return fail('Estado do pedido mudou. Atualize a fila.', 409)

            owner = order.get('breeder_responsavel') == email
            admin = bool(perms.get('pode_gerenciar_cargos'))
            if action == 'assumir':
                if order.get('breeder_responsavel'):
                    return fail('Pedido ja pertence a outro breeder.', 409)
            elif not (owner or admin):
                return fail('Somente breeder responsavel ou administrador.', 403)

            # Keep the site's exact business rules, accounting and notifications.
            # Execute the existing decorated handler under an isolated web session
            # populated ONLY with the identity just verified by @secure.
            app = current_app._get_current_object()
            with app.test_request_context(
                '/breed/_internal_client_action',
                method='POST',
                data={'motivo': motive},
            ):
                session['usuario_email'] = email
                session['nick_jogo'] = actor.get('nick_jogo') or ''
                handler(pedido_id)
                messages = get_flashed_messages(with_categories=True)

            errors = [str(msg) for cat, msg in messages if cat in ('erro', 'error', 'danger')]
            if errors:
                # One of the site's handlers may have partially changed data
                # before a financial failure. Never retry automatically.
                return fail(errors[0][:450] + ' Confira no site antes de tentar novamente.', 409)

            success = any(cat in ('sucesso', 'success') for cat, _ in messages)
            if not success:
                return fail('Operacao sem confirmacao do servidor.', 503)

            after_rows = (db.table('pedidos_breed').select('status,breeder_responsavel')
                          .eq('id', pedido_id).limit(1).execute().data or [])
            if not after_rows:
                return fail('Verificacao do pedido indisponivel.', 503)
            after = after_rows[0]
            status = after.get('status')
            valid = (status in expected_after if isinstance(expected_after, tuple)
                     else status == expected_after)
            if action == 'devolver' and after.get('breeder_responsavel'):
                valid = False
            if action == 'assumir' and after.get('breeder_responsavel') != email:
                valid = False
            if not valid:
                return fail('Estado nao confirmado. Atualize antes de tentar novamente.', 409)
            return jsonify({'ok': True, 'pedido_id': pedido_id, 'status': status,
                            'mensagem': 'Acao registrada e sincronizada.'})
        except Exception:
            current_app.logger.exception(
                'HYPE Client breeder action failed: %s order=%s', action, pedido_id)
            return fail('Falha no processamento. Confira o status antes de repetir.', 503)
