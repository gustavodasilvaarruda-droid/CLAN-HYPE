"""HYPE Client R7 API: account data and revocable persistent login.

Never send Supabase keys to Minecraft. Only return public profile details.
"""
from datetime import datetime, timezone, timedelta
from functools import wraps
import hashlib
import logging
import secrets
from flask import Blueprint, jsonify, request, g
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import check_password_hash
from modules.hype_mod_access import visible_modules_for_user

SALT = 'hype-client-api-v1'
TOKEN_TTL = 60 * 60 * 4  # Tokens antigos do R7 continuam aceitos por 4 horas.
SESSION_IDLE_DAYS = 180  # Sessao persistente renovada enquanto o jogador usa o mod.
SESSION_RENEW_AFTER = timedelta(hours=24)
LOGGER = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _date_from_db(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _session_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def create_hype_client_api_blueprint(db, secret, get_permissions, is_member,
                                     login_blocked, login_fail, login_clear):
    api = Blueprint('hype_client_api', __name__, url_prefix='/api/hype/v1')
    serializer = URLSafeTimedSerializer(secret, salt=SALT)

    def fail(message, code):
        return jsonify({'ok': False, 'erro': message}), code

    def safe_profile(user):
        email = user['email']
        member = bool(is_member(email))
        perms = get_permissions(email) or {}
        return {'nick': user.get('nick_jogo') or '', 'cargo': user.get('cargo') or '',
                'avatar_url': user.get('avatar_url') or '', 'membro_hype': member,
                'permissoes': {k: bool(v) for k, v in perms.items() if k.startswith('pode_')}}

    def secure(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            header = request.headers.get('Authorization', '')
            if not header.startswith('Bearer '):
                return fail('Autenticacao necessaria.', 401)
            token = header[7:].strip()
            if not token or len(token) > 512:
                return fail('Token invalido.', 401)

            g.hype_session_id = None
            try:
                if token.startswith('hcs_'):
                    # Token aleatorio persistente: apenas SHA-256 fica no banco.
                    sessions = (db.table('hype_client_sessoes')
                                .select('id,usuario_email,ultimo_uso_em,expira_em')
                                .eq('token_hash', _session_hash(token))
                                .is_('revogado_em', 'null')
                                .limit(1).execute().data or [])
                    if not sessions:
                        return fail('Sessao encerrada ou invalida.', 401)
                    entry = sessions[0]
                    now = _utcnow()
                    if _date_from_db(entry['expira_em']) <= now:
                        return fail('Sessao expirada por inatividade. Entre novamente.', 401)
                    email = entry['usuario_email']
                    g.hype_session_id = entry['id']
                else:
                    # Compatibilidade com os .jar R7 antigos (4 horas).
                    identity = serializer.loads(token, max_age=TOKEN_TTL)
                    email = identity.get('email') if isinstance(identity, dict) else None
                    if not email:
                        return fail('Token invalido.', 401)

                users = (db.table('usuarios_clan')
                         .select('email,nick_jogo,cargo,avatar_url')
                         .eq('email', email).limit(1).execute().data or [])
                if not users:
                    return fail('Conta indisponivel.', 401)
                g.hype_user = users[0]

                if g.hype_session_id:
                    # Prorroga a sessao no servidor no maximo uma vez por dia.
                    last_used = _date_from_db(entry['ultimo_uso_em'])
                    if now - last_used >= SESSION_RENEW_AFTER:
                        try:
                            (db.table('hype_client_sessoes')
                             .update({'ultimo_uso_em': now.isoformat(),
                                      'expira_em': (now + timedelta(days=SESSION_IDLE_DAYS)).isoformat()})
                             .eq('id', g.hype_session_id).execute())
                        except Exception:
                            LOGGER.exception('Nao foi possivel renovar sessao do HYPE Client.')
            except (BadSignature, SignatureExpired):
                return fail('Sessao expirada ou invalida.', 401)
            except (ValueError, TypeError, KeyError):
                return fail('Sessao invalida.', 401)
            except Exception:
                LOGGER.exception('Erro de autenticacao na API HYPE Client.')
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
            rows = db.table('usuarios_clan').select('email,senha,nick_jogo,cargo,avatar_url').eq('email', email).limit(1).execute().data or []
            if not rows or not check_password_hash(rows[0]['senha'], password):
                login_fail(email)
                return fail('Email ou senha incorretos.', 401)
            login_clear(email)
            user = rows[0]
            token = serializer.dumps({'email': user['email']})
            session_token = None
            try:
                # Token persistente e revogavel para clientes novos.
                # Se a migracao ainda nao foi executada, o login R7 legado continua funcionando.
                generated = 'hcs_' + secrets.token_urlsafe(48)
                (db.table('hype_client_sessoes')
                 .insert({'usuario_email': user['email'],
                          'token_hash': _session_hash(generated),
                          'expira_em': (_utcnow() + timedelta(days=SESSION_IDLE_DAYS)).isoformat()})
                 .execute())
                session_token = generated
            except Exception:
                LOGGER.warning('Sessao persistente indisponivel; verificar migracao SQL HYPE Client R7.')
            return jsonify({'ok': True, 'token': token, 'expira_em_segundos': TOKEN_TTL,
                            'session_token': session_token,
                            'sessao_persistente': bool(session_token),
                            'expira_por_inatividade_em_dias': SESSION_IDLE_DAYS if session_token else None,
                            'usuario': safe_profile(user)})
        except Exception:
            return fail('Servico de autenticacao temporariamente indisponivel.', 503)

    @api.get('/me')
    @secure
    def me():
        return jsonify({'ok': True, 'usuario': safe_profile(g.hype_user),
                        'sessao_persistente': bool(g.hype_session_id)})

    @api.post('/logout')
    @secure
    def logout():
        # O logout revoga o token persistente no servidor.
        # Tokens legados de 4 horas nao possuem id revogavel.
        if not g.hype_session_id:
            return fail('Atualize o HYPE Client para encerrar a sessao persistente.', 400)
        try:
            (db.table('hype_client_sessoes')
             .update({'revogado_em': _utcnow().isoformat()})
             .eq('id', g.hype_session_id)
             .eq('usuario_email', g.hype_user['email']).execute())
            return jsonify({'ok': True, 'mensagem': 'Sessao encerrada.'})
        except Exception:
            LOGGER.exception('Falha ao revogar sessao HYPE Client.')
            return fail('Nao foi possivel sair da conta no momento.', 503)

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

    return api
