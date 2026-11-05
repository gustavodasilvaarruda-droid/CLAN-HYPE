"""HYPE Client API: authenticated reads and server-calculated Breed previews. Never expose DB keys."""
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Blueprint, jsonify, request, g
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import check_password_hash
from modules.hype_mod_access import visible_modules_for_user

SALT = 'hype-client-api-v1'
TOKEN_TTL = 60 * 60 * 4


def create_hype_client_api_blueprint(db, secret, get_permissions, is_member,
                                     login_blocked, login_fail, login_clear, breed_services=None):
    api = Blueprint('hype_client_api', __name__, url_prefix='/api/hype/v1')
    serializer = URLSafeTimedSerializer(secret, salt=SALT)

    def fail(message, code):
        return jsonify({'ok': False, 'erro': message}), code

    def safe_profile(user):
        email = user['email']
        member = bool(is_member(email))
        perms = get_permissions(email) or {}
        return {'nick': user.get('nick_jogo') or '', 'cargo': user.get('cargo') or '',
                'membro_hype': member,
                'permissoes': {k: bool(v) for k, v in perms.items() if k.startswith('pode_')}}

    def secure(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            header = request.headers.get('Authorization', '')
            if not header.startswith('Bearer '):
                return fail('Autenticacao necessaria.', 401)
            try:
                identity = serializer.loads(header[7:].strip(), max_age=TOKEN_TTL)
                email = identity.get('email') if isinstance(identity, dict) else None
                if not email:
                    return fail('Token invalido.', 401)
                users = db.table('usuarios_clan').select('email,nick_jogo,cargo').eq('email', email).limit(1).execute().data or []
                if not users:
                    return fail('Conta indisponivel.', 401)
                g.hype_user = users[0]
            except (BadSignature, SignatureExpired):
                return fail('Sessao expirada ou invalida.', 401)
            except Exception:
                return fail('Falha ao consultar conta.', 503)
            return fn(*args, **kwargs)
        return decorated

    def require_module(module_code):
        """Check access on the server for each protected read, never trust the GUI."""
        def decorator(fn):
            @wraps(fn)
            def decorated(*args, **kwargs):
                try:
                    modules = (db.table('hype_modulos')
                               .select('codigo,nome,estado,visivel')
                               .eq('codigo', module_code).limit(1).execute().data or [])
                    if not modules:
                        return fail('Modulo nao disponivel.', 403)
                    assignments = (db.table('hype_modulos_grupos')
                                   .select('modulo_codigo,cargo_id')
                                   .eq('modulo_codigo', module_code).limit(500).execute().data or [])
                    overrides = (db.table('hype_modulos_acessos')
                                 .select('modulo_codigo,decisao,inicio_em,fim_em')
                                 .eq('modulo_codigo', module_code)
                                 .eq('usuario_email', g.hype_user['email'])
                                 .limit(1).execute().data or [])
                    decisions = visible_modules_for_user(
                        modules, assignments, overrides,
                        g.hype_user.get('cargo'), bool(is_member(g.hype_user['email']))
                    )
                    if not decisions or not decisions[0]['permitido']:
                        return fail('Modulo bloqueado ou sem permissao.', 403)
                except Exception:
                    return fail('Nao foi possivel validar o acesso ao modulo.', 503)
                return fn(*args, **kwargs)
            return decorated
        return decorator

    @api.after_request
    def no_store(response):
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @api.get('/health')
    def health():
        return jsonify({'ok': True, 'api': 'hype-client', 'versao': '1', 'modo': 'leitura'})

    @api.post('/login')
    def login():
        if not request.is_json:
            return fail('Envie JSON.', 415)
        body = request.get_json(silent=True) or {}
        email = str(body.get('email') or '').strip().lower()
        password = str(body.get('senha') or '')
        if not email or '@' not in email or len(email) > 254 or not password or len(password) > 1024:
            return fail('Credenciais invalidas.', 400)
        try:
            if login_blocked(email):
                return fail('Muitas tentativas. Aguarde e tente novamente.', 429)
            rows = db.table('usuarios_clan').select('email,senha,nick_jogo,cargo').eq('email', email).limit(1).execute().data or []
            if not rows or not check_password_hash(rows[0]['senha'], password):
                login_fail(email)
                return fail('Email ou senha incorretos.', 401)
            login_clear(email)
            user = rows[0]
            token = serializer.dumps({'email': user['email']})
            return jsonify({'ok': True, 'token': token, 'expira_em_segundos': TOKEN_TTL,
                            'usuario': safe_profile(user)})
        except Exception:
            return fail('Servico de autenticacao temporariamente indisponivel.', 503)

    @api.get('/me')
    @secure
    def me():
        return jsonify({'ok': True, 'usuario': safe_profile(g.hype_user)})

    FIELDS = ('id','pokemon','pokemon_id','nature','ha','genero','breed_tipo','iv_descartado',
              'status','preco_total','created_at','assumido_em','concluido_em','entregue_em',
              'player','breeder_responsavel')
    def clean_order(p, *, show_breeder=True):
        r = {k: p.get(k) for k in FIELDS if k != 'breeder_responsavel'}
        if show_breeder:
            r['tem_breeder'] = bool(p.get('breeder_responsavel'))
        return r

    @api.get('/meus-pedidos')
    @secure
    def mine():
        try:
            rows = db.table('pedidos_breed').select(','.join(FIELDS)).eq('usuario_email',g.hype_user['email']).order('created_at',desc=True).limit(100).execute().data or []
            return jsonify({'ok': True,'pedidos':[clean_order(p) for p in rows]})
        except Exception:
            return fail('Nao foi possivel consultar os pedidos.',503)

    @api.get('/fila')
    @secure
    @require_module('breeder')
    def queue():
        perms = get_permissions(g.hype_user['email']) or {}
        if not (perms.get('pode_ver_fila_breed') or perms.get('pode_assumir_breed')):
            return fail('Sem permissao para consultar a fila.',403)
        try:
            rows = db.table('pedidos_breed').select(','.join(FIELDS)).eq('status','pendente').order('created_at',desc=False).limit(100).execute().data or []
            return jsonify({'ok':True,'pedidos':[clean_order(p) for p in rows]})
        except Exception:
            return fail('Nao foi possivel consultar a fila.',503)

    @api.get('/painel-breeder')
    @secure
    @require_module('breeder')
    def breeder():
        perms = get_permissions(g.hype_user['email']) or {}
        if not (perms.get('pode_assumir_breed') or perms.get('pode_concluir_breed')):
            return fail('Sem permissao para acessar o painel.',403)
        try:
            rows = db.table('pedidos_breed').select(','.join(FIELDS)).eq('breeder_responsavel',g.hype_user['email']).order('created_at',desc=True).limit(100).execute().data or []
            return jsonify({'ok': True,'pedidos':[clean_order(p) for p in rows]})
        except Exception:
            return fail('Nao foi possivel consultar o painel.',503)

    @api.get('/team-breeders')
    @secure
    def team():
        try:
            members = db.table('usuarios_funcoes').select('usuario_email').eq('funcao','breeder').limit(500).execute().data or []
            result=[]
            for entry in members:
                email=entry.get('usuario_email')
                if not email or not is_member(email):
                    continue
                u=db.table('usuarios_clan').select('nick_jogo').eq('email',email).limit(1).execute().data or []
                if u:
                    result.append({'nick':u[0].get('nick_jogo') or 'Breeder'})
            return jsonify({'ok':True,'breeders':result})
        except Exception:
            return fail('Nao foi possivel carregar o Team Breeders.',503)

    @api.get('/ranking')
    @secure
    def ranking():
        try:
            now=datetime.now(timezone.utc)
            month=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
            next_month=(month.replace(day=28)+timedelta(days=4)).replace(day=1)
            orders=db.table('pedidos_breed').select('breeder_responsavel,preco_total').in_('status',['concluido','entregue']).gte('concluido_em',month.isoformat()).lt('concluido_em',next_month.isoformat()).limit(2000).execute().data or []
            totals={}
            for p in orders:
                email=p.get('breeder_responsavel')
                if not email: continue
                row=totals.setdefault(email,{'total':0,'valor':0})
                row['total']+=1
                row['valor']+=int(p.get('preco_total') or 0)
            result=[]
            for email,summary in totals.items():
                users=db.table('usuarios_clan').select('nick_jogo').eq('email',email).limit(1).execute().data or []
                result.append({'nick':(users[0].get('nick_jogo') if users else None) or 'Breeder',**summary})
            result.sort(key=lambda x:(-x['total'],-x['valor']))
            return jsonify({'ok':True,'mes':month.strftime('%Y-%m'),'ranking':result[:50]})
        except Exception:
            return fail('Nao foi possivel calcular o ranking.',503)

    @api.get('/modulos')
    @secure
    def modulos():
        try:
            modules = (db.table('hype_modulos')
                       .select('codigo,nome,descricao,icone,categoria,versao,estado,visivel,ordem')
                       .order('ordem').limit(200).execute().data or [])
            groups = (db.table('hype_modulos_grupos')
                      .select('modulo_codigo,cargo_id').limit(2000).execute().data or [])
            overrides = (db.table('hype_modulos_acessos')
                         .select('modulo_codigo,decisao,inicio_em,fim_em')
                         .eq('usuario_email', g.hype_user['email'])
                         .limit(1000).execute().data or [])
            result = visible_modules_for_user(
                modules, groups, overrides,
                g.hype_user.get('cargo'), bool(is_member(g.hype_user['email']))
            )
            return jsonify({'ok': True, 'modulos': result})
        except Exception:
            return fail('Nao foi possivel validar o acesso aos modulos.', 503)


    # Breed - endpoints shared with the site, accessible with the existing 4-hour
    # Bearer token. These endpoints DO NOT create orders or write to Supabase.
    # Business rules and price calculation come from app.py, not client guesses.
    breed_services = breed_services or {}

    def can_request_breed():
        try:
            return bool((get_permissions(g.hype_user['email']) or {}).get('pode_fazer_pedido_breed'))
        except Exception:
            return False

    @api.get('/breed/pokemon/buscar')
    @secure
    def breed_search_pokemon():
        if not can_request_breed():
            return fail('Sem permissao para solicitar Breed.', 403)
        query = (request.args.get('q') or '').strip().casefold()
        if len(query) < 2:
            return jsonify({'ok': True, 'results': []})
        if len(query) > 80:
            return fail('Pesquisa muito longa.', 400)
        catalog = breed_services.get('catalogo')
        if not catalog:
            return fail('Catalogo indisponivel.', 503)
        try:
            matches = []
            for item in catalog():
                name = str(item.get('name') or '').strip()
                if query not in name.casefold():
                    continue
                pokemon_id = int(item.get('id') or 0)
                if pokemon_id <= 0:
                    continue
                matches.append({'id': pokemon_id, 'name': name,
                                'display_name': name.replace('-', ' ').title()})
                if len(matches) >= 24:
                    break
            return jsonify({'ok': True, 'results': matches})
        except Exception:
            return fail('Falha na pesquisa de Pokemon.', 503)

    @api.get('/breed/pokemon/<int:pokemon_id>')
    @secure
    def breed_pokemon_details(pokemon_id):
        if not can_request_breed():
            return fail('Sem permissao para solicitar Breed.', 403)
        name = (request.args.get('nome') or '').strip()
        if pokemon_id < 1 or pokemon_id > 100000 or not name or len(name) > 120:
            return fail('Pokemon invalido.', 400)
        rule_fn = breed_services.get('regra')
        classify_fn = breed_services.get('classificar')
        if not rule_fn or not classify_fn:
            return fail('Regras de Breed indisponiveis.', 503)
        try:
            rule = rule_fn(pokemon_id, name) or {}
            meta = classify_fn(pokemon_id) or {}
            return jsonify({'ok': True, 'pokemon': {
                'id': pokemon_id, 'name': name,
                'breedavel': bool(rule.get('breedavel')),
                'motivo': rule.get('motivo'),
                'so_com_ditto': bool(rule.get('so_com_ditto')),
                'egg_groups': rule.get('egg_groups') or [],
                'categoria': meta.get('categoria') or 'comum',
                'categoria_label': meta.get('categoria_label') or 'Comum',
                'taxa_femea_percentual': meta.get('taxa_femea_percentual'),
            }})
        except Exception:
            return fail('Falha ao verificar o Pokemon.', 503)

    @api.post('/breed/preco-preview')
    @secure
    def breed_price_preview():
        """Price and promotions always come from the same functions as web checkout."""
        if not can_request_breed():
            return fail('Sem permissao para solicitar Breed.', 403)
        if not request.is_json:
            return fail('Envie JSON.', 415)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return fail('JSON invalido.', 400)
        try:
            pokemon_id = int(body.get('pokemon_id', 0))
        except (TypeError, ValueError, OverflowError):
            return fail('Pokemon invalido.', 400)
        pokemon = str(body.get('pokemon') or '').strip()
        breed_type = str(body.get('breed_tipo') or '').strip().upper()
        nature = str(body.get('nature') or '').strip()
        gender = str(body.get('genero') or 'indiferente').strip().lower()
        ha = body.get('ha')
        trained = body.get('treinado', False)
        zero_speed = body.get('zero_speed', False)
        discard = str(body.get('iv_descartado') or '').strip().lower()
        coupon = str(body.get('cupom') or '').strip().upper()
        if (not 1 <= pokemon_id <= 100000 or not pokemon or len(pokemon) > 120
                or breed_type not in ('F5', 'F6', 'PERSONALIZADO')
                or gender not in ('macho', 'femea', 'indiferente')
                or type(ha) is not bool or type(trained) is not bool
                or type(zero_speed) is not bool or len(coupon) > 80):
            return fail('Caracteristicas invalidas.', 400)
        if nature and nature not in (breed_services.get('natures') or set()):
            return fail('Nature invalida.', 400)
        if breed_type == 'F5':
            if discard not in (breed_services.get('ivs_f5') or set()):
                return fail('Escolha o IV dispensavel no F5.', 400)
            if zero_speed and discard == 'velocidade':
                return fail('Zero Speed exige descartar outro IV.', 400)
        elif discard or zero_speed:
            return fail('IV dispensavel e Zero Speed sao exclusivos do F5.', 400)

        rule_fn = breed_services.get('regra')
        classify_fn = breed_services.get('classificar')
        price_fn = breed_services.get('calcular')
        if not all((rule_fn, classify_fn, price_fn)):
            return fail('Calculadora oficial indisponivel.', 503)
        try:
            rule = rule_fn(pokemon_id, pokemon) or {}
            if not rule.get('breedavel'):
                return fail(rule.get('motivo') or 'Pokemon indisponivel para Breed.', 400)
            meta = classify_fn(pokemon_id) or {}
            with_ditto = bool(rule.get('so_com_ditto'))
            category = 'ultra_raro' if with_ditto else (meta.get('categoria') or 'comum')
            if category not in ('comum', 'raro', 'ultra_raro'):
                category = 'comum'
            total, detail = price_fn(
                breed_type, ha=ha, genero=gender, categoria=category,
                usa_ditto=with_ditto, treinado=trained, nature=nature or None,
                zero_speed=zero_speed, pokemon_id=pokemon_id,
                usuario_email=g.hype_user['email'], codigo_cupom=coupon)
            total = int(total)
            if total <= 0:
                return fail('Tabela de precos nao configurada.', 422)
            if coupon and detail.get('cupom_valido') is False:
                return fail('Cupom invalido ou expirado.', 400)
            return jsonify({
                'ok': True, 'preco_total': total,
                'preco_formatado': (' + f'{total:,}').replace(',', '.'),
                'detalhes': detail,
                'categoria': category,
                'so_com_ditto': with_ditto,
                'observacao': 'Valor de previa. O site recalcula ao criar o pedido.'
            })
        except Exception:
            return fail('Falha temporaria ao calcular o preco.', 503)

    return api
