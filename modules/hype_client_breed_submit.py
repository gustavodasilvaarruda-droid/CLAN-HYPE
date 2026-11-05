"""Authenticated Breed order creation for HYPE Client.

The Minecraft client never receives a Supabase key and never decides the price.
Business rules and prices come from the same functions used by the website.
Requires migrations/20261105_hype_client_breed_request_id.sql before enabling.
"""
from datetime import datetime, timezone, timedelta
from uuid import UUID
from flask import request, jsonify, g
from modules.breed_regional import regional_form

STATS = ('hp', 'attack', 'defense', 'sp_attack', 'sp_defense', 'speed')
ACTIVE = ('pendente', 'aguardando_pagamento', 'em_producao', 'cancelamento_solicitado')


class InvalidOrder(ValueError):
    pass


def _boolean(value, name):
    if type(value) is not bool:
        raise InvalidOrder(name + ' deve ser verdadeiro ou falso.')
    return value


def _stats(value, *, cap, required):
    if not isinstance(value, dict) or set(value) - set(STATS):
        raise InvalidOrder('Atributos IV/EV invalidos.')
    if required and set(value) != set(STATS):
        raise InvalidOrder('Informe os seis IVs personalizados.')
    result = {}
    for key in (STATS if required else value):
        number = value[key]
        if type(number) is not int or not 0 <= number <= cap:
            raise InvalidOrder('IV/EV deve ser um numero inteiro dentro do limite.')
        result[key] = number
    return result


def install_breed_submit(api, db, secure, get_permissions, services):
    """Register POST /api/hype/v1/pedidos on the existing token API blueprint."""

    def error(message, code):
        return jsonify({'ok': False, 'erro': message}), code

    @api.post('/pedidos')
    @secure
    def submit_breed_order():
        if not request.is_json:
            return error('Envie JSON.', 415)
        if request.content_length is not None and request.content_length > 16384:
            return error('Pedido muito grande.', 413)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return error('JSON invalido.', 400)

        email = g.hype_user['email']
        player = str(g.hype_user.get('nick_jogo') or '').strip()
        if not player:
            return error('Cadastre seu nick do Minecraft no site.', 422)
        try:
            try:
                request_id = UUID(str(body['request_id']))
                if request_id.version != 4:
                    raise ValueError
            except (KeyError, TypeError, ValueError, AttributeError):
                raise InvalidOrder('request_id deve ser UUID v4.')
            request_id = str(request_id)
            pokemon_id = body.get('pokemon_id')
            if type(pokemon_id) is not int or not 1 <= pokemon_id <= 99999:
                raise InvalidOrder('ID do Pokemon invalido.')

            regional = regional_form(pokemon_id)
            if regional:
                pokemon = regional['name']  # canonical: e.g. rapidash-galar
                supplied_region = str(body.get('regiao') or regional['region']).strip().lower()
                if supplied_region != regional['region']:
                    raise InvalidOrder('A regiao nao corresponde ao ID da forma.')
            else:
                if body.get('regiao'):
                    raise InvalidOrder('Para formas regionais, envie o ID especifico da forma.')
                pokemon = str(body.get('pokemon') or '').strip()
                if not 1 <= len(pokemon) <= 80:
                    raise InvalidOrder('Nome do Pokemon invalido.')
                if any(x in pokemon.lower() for x in ('galar', 'alola', 'hisui', 'paldea')):
                    raise InvalidOrder('Use o ID da forma regional, nao o da especie base.')

            nature = str(body.get('nature') or '').strip()
            if nature in ('Sem Nature', 'sem nature'):
                nature = ''
            if nature and nature not in services['natures']:
                raise InvalidOrder('Nature invalida.')
            ha = _boolean(body.get('ha'), 'ha')
            genero = str(body.get('genero') or '').strip().lower()
            if genero not in ('macho', 'femea', 'indiferente'):
                raise InvalidOrder('Genero invalido.')
            mode = str(body.get('breed_tipo') or '').strip().upper()
            if mode not in ('F5', 'F6', 'PERSONALIZADO'):
                raise InvalidOrder('Modo de Breed invalido.')
            zero = _boolean(body.get('zero_speed', False), 'zero_speed')
            trained = _boolean(body.get('treinado', False), 'treinado')
            discarded = str(body.get('iv_descartado') or '').strip().lower() or None
            if mode == 'F5':
                if discarded not in services['f5_ivs']:
                    raise InvalidOrder('Escolha o IV descartado para F5.')
                if zero and discarded == 'velocidade':
                    raise InvalidOrder('Zero Speed nao permite descartar velocidade.')
            else:
                if discarded or zero:
                    raise InvalidOrder('IV descartado e Zero Speed sao exclusivos de F5.')
                discarded = None

            custom = _stats(body.get('ivs_personalizados') or {}, cap=31,
                            required=(mode == 'PERSONALIZADO'))
            if mode != 'PERSONALIZADO' and custom:
                raise InvalidOrder('IVs personalizados exigem modo PERSONALIZADO.')
            evs = _stats(body.get('evs_treinamento') or {}, cap=252, required=False)
            if trained and sum(evs.values()) > 510:
                raise InvalidOrder('Limite de 510 EVs ultrapassado.')
            if not trained and evs:
                raise InvalidOrder('EVs so podem ser enviados com treinamento.')
            coupon = str(body.get('cupom_breed') or '').strip().upper()
            if len(coupon) > 40 or (coupon and not all(x.isalnum() or x in '-_' for x in coupon)):
                raise InvalidOrder('Cupom invalido.')

        except InvalidOrder as exc:
            return error(str(exc), 422)

        try:
            perms = get_permissions(email) or {}
            if not perms.get('pode_fazer_pedido_breed'):
                return error('Conta sem permissao para solicitar Breed.', 403)

            # Idempotency check MUST precede cooldown. Retrying a successful POST
            # returns the existing order; a new UUID cannot duplicate that insert.
            previous = (db.table('pedidos_breed')
                        .select('id,usuario_email,pokemon_id,status,preco_total')
                        .eq('hype_client_request_id', request_id)
                        .limit(1).execute().data or [])
            if previous:
                old = previous[0]
                if old.get('usuario_email') != email or int(old.get('pokemon_id') or 0) != pokemon_id:
                    return error('Identificador de envio ja utilizado.', 409)
                return jsonify({'ok': True, 'repetido': True,
                                'pedido': {'id': old['id'], 'status': old['status'],
                                           'preco_total': old['preco_total']}}), 200

            rule = services['rule'](pokemon_id, pokemon)
            if not rule.get('breedavel'):
                return error(rule.get('motivo') or 'Pokemon nao disponivel para Breed.', 422)

            recent = (db.table('pedidos_breed').select('created_at')
                      .eq('usuario_email', email).order('created_at', desc=True)
                      .limit(1).execute().data or [])
            if recent:
                last = services['parse_date'](recent[0].get('created_at'))
                if last and datetime.now(timezone.utc) - last < timedelta(minutes=2):
                    return error('Aguarde 2 minutos antes de enviar outro pedido.', 429)

            active = (db.table('pedidos_breed').select(
                'pokemon_id,nature,ha,genero,breed_tipo,iv_descartado,zero_speed,treinado,'
                'evs_treinamento,ivs_personalizados')
                .eq('usuario_email', email).in_('status', list(ACTIVE))
                .limit(100).execute().data or [])
            for old in active:
                if (int(old.get('pokemon_id') or 0) == pokemon_id
                    and (old.get('nature') or '') == nature
                    and bool(old.get('ha')) == ha
                    and (old.get('genero') or '') == genero
                    and (old.get('breed_tipo') or '') == mode
                    and (old.get('iv_descartado') or '') == (discarded or '')
                    and bool(old.get('zero_speed')) == zero
                    and bool(old.get('treinado')) == trained
                    and (old.get('evs_treinamento') or {}) == evs
                    and (old.get('ivs_personalizados') or {}) == custom):
                    return error('Pedido identico ja esta pendente ou em producao.', 409)

            meta = services['classify'](pokemon_id)
            category = str(meta.get('categoria') or 'comum').lower()
            if category not in services['categories']:
                category = 'comum'
            uses_ditto = bool(rule.get('so_com_ditto'))
            if uses_ditto:
                category = 'ultra_raro'
            total, details = services['calculate'](
                mode, ha=ha, genero=genero, categoria=category,
                usa_ditto=uses_ditto, treinado=trained, nature=nature or None,
                zero_speed=zero, pokemon_id=pokemon_id, usuario_email=email,
                codigo_cupom=coupon
            )
            if coupon and details.get('pricing_v2') and details.get('cupom_valido') is False:
                return error('Cupom invalido ou indisponivel.', 422)
            if total <= 0:
                return error('Preco indisponivel. Tente novamente mais tarde.', 503)
            details['classificacao_raridade'] = {
                'categoria': category,
                'label': meta.get('categoria_label') or services['category_labels'].get(category, 'Comum'),
                'origem': meta.get('classificacao_origem'),
                'motivo': meta.get('classificacao_motivo'),
                'taxa_femea_percentual': meta.get('taxa_femea_percentual'),
                'so_com_ditto': uses_ditto,
            }
            pct, tax, breeder_value = services['split'](total)
            row = {
                'usuario_email': email, 'player': player,
                'pokemon': pokemon, 'pokemon_id': pokemon_id,
                'nature': nature or None, 'ha': ha, 'genero': genero,
                'breed_tipo': mode, 'modo_pedido': 'personalizado' if mode == 'PERSONALIZADO' else 'normal',
                'ivs_personalizados': custom, 'iv_descartado': discarded,
                'zero_speed': zero, 'categoria_preco': category,
                'usa_ditto': uses_ditto, 'breed_especial': uses_ditto, 'hpwr': False,
                'treinado': trained, 'evs_treinamento': evs,
                'preco_total': total, 'taxa_clan_percentual': pct,
                'taxa_clan_valor': tax, 'valor_breeder': breeder_value,
                'preco_original': int(details.get('preco_original') or total),
                'promocao_id': details.get('promocao_id'),
                'promocao_nome': details.get('promocao_nome'),
                'promocao_percentual': details.get('promocao_percentual') or 0,
                'tabela_preco_id': details.get('tabela_preco_id'),
                'cupom_codigo': details.get('cupom_codigo'),
                'preco_detalhes': details,
                'ability': 'HA' if ha else 'Sem HA',
                'nao_precisa': discarded if mode == 'F5' else None,
                'status': 'pendente', 'hype_client_request_id': request_id,
            }
            inserted = (db.table('pedidos_breed').insert(row).execute().data or [])
            if not inserted:
                return error('Pedido nao foi confirmado pelo banco. Consulte Meus Pedidos.', 503)
            order = inserted[0]
            try:
                services['activity']('breed_criado', email,
                                     'Pedido de Breed pelo HYPE Client: ' + pokemon, 'breed', order.get('id'))
            except Exception:
                pass  # Activity log must not undo a confirmed order.
            return jsonify({'ok': True, 'repetido': False,
                            'pedido': {'id': order['id'], 'status': 'pendente',
                                       'pokemon': pokemon, 'preco_total': total}}), 201

        except Exception as exc:
            # Duplicate UUID can race with another request; the unique index is
            # the final arbiter. Never blindly retry INSERT on transient errors.
            msg = str(exc).lower()
            if 'duplicate' in msg or '23505' in msg or 'unique constraint' in msg:
                try:
                    rows = (db.table('pedidos_breed')
                            .select('id,usuario_email,pokemon_id,status,preco_total')
                            .eq('hype_client_request_id', request_id).limit(1).execute().data or [])
                    if rows and rows[0].get('usuario_email') == email and int(rows[0].get('pokemon_id') or 0) == pokemon_id:
                        p = rows[0]
                        return jsonify({'ok': True, 'repetido': True,
                                        'pedido': {'id': p['id'], 'status': p['status'],
                                                   'preco_total': p['preco_total']}}), 200
                except Exception:
                    pass
            api.logger if False else None  # never expose Supabase internals to players
            return error('Nao foi possivel registrar o pedido. Confira Meus Pedidos antes de tentar novamente.', 503)
