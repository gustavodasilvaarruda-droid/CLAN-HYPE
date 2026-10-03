import os
import json
import csv
import io
import hashlib
import hmac
import secrets
from functools import wraps, lru_cache
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from uuid import uuid4
from urllib.request import urlopen
from urllib.parse import quote, urlencode, urlparse
from supabase import create_client, Client
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

app = Flask(__name__)
try:
    HYPE_TZ = ZoneInfo('America/Sao_Paulo')
except Exception:
    HYPE_TZ = timezone(timedelta(hours=-3))


def _env_bool(nome, padrao=False):
    valor = str(os.environ.get(nome, '')).strip().lower()
    if not valor:
        return bool(padrao)
    return valor in ('1', 'true', 'on', 'sim', 'yes')


# V29: endurecimento de sessão e uploads. Em produção no Render, cookie HTTPS é
# ativado automaticamente; no desenvolvimento local HTTP ele continua utilizável.
app.config.update(
    SESSION_COOKIE_NAME='hype_session',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=_env_bool('SESSION_COOKIE_SECURE', bool(os.environ.get('RENDER'))),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    SESSION_REFRESH_EACH_REQUEST=True,
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
)

# V31.1: proteção CSRF nativa, sem dependência de Flask-WTF.
# O token fica vinculado à sessão e é exigido em toda requisição que altera dados.
def csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


app.jinja_env.globals['csrf_token'] = csrf_token


def _destino_seguro_csrf():
    destino = request.referrer or url_for('pagina_inicial')
    try:
        ref = urlparse(destino)
        if ref.netloc and ref.netloc != request.host:
            destino = url_for('pagina_inicial')
    except Exception:
        destino = url_for('pagina_inicial')
    return destino


@app.before_request
def proteger_csrf_global():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return None

    esperado = session.get('_csrf_token')
    recebido = (
        request.form.get('csrf_token')
        or request.headers.get('X-CSRFToken')
        or request.headers.get('X-CSRF-Token')
    )

    if not esperado or not recebido or not hmac.compare_digest(str(esperado), str(recebido)):
        flash('Sua sessão de segurança expirou. Atualize a página e tente novamente.', 'erro')
        return redirect(_destino_seguro_csrf())

    return None


@app.template_filter('preco')
def filtro_preco(valor):
    """Formata valores do jogo: 500000 -> 500k, 1500000 -> 1.5kk."""
    try:
        valor = int(valor or 0)

        if valor >= 1_000_000:
            numero = valor / 1_000_000
            if numero.is_integer():
                return f"{int(numero)}kk"
            return f"{numero:g}kk"

        if valor >= 1_000:
            numero = valor / 1_000
            if numero.is_integer():
                return f"{int(numero)}k"
            return f"{numero:g}k"

        return str(valor)
    except (ValueError, TypeError):
        return str(valor)

# Configurações de Segurança e Conexão Supabase
app.secret_key = os.environ.get("SECRET_KEY", "")
if not app.secret_key:
    raise RuntimeError("A variável de ambiente SECRET_KEY não foi configurada.")

# AJUSTADO: Agora com o ID do seu projeto correto antes do '.supabase.co'
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL:
    raise RuntimeError("A variável de ambiente SUPABASE_URL não foi configurada.")
if not SUPABASE_KEY:
    raise RuntimeError("A variável de ambiente SUPABASE_KEY não foi configurada.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.errorhandler(413)
def tratar_upload_grande(_erro):
    flash('O arquivo enviado é muito grande. O limite do site é 10 MB.', 'erro')
    return redirect(request.referrer or url_for('painel'))


@app.after_request
def cabecalhos_seguranca(response):
    # Cabeçalhos seguros que não quebram os embeds/JS atuais do HYPE.
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    if os.environ.get('RENDER') or request.is_secure:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    if session.get('usuario_email') and (request.path.startswith('/admin') or request.path.startswith('/conta') or request.path.startswith('/perfil/midia')):
        response.headers.setdefault('Cache-Control', 'no-store, private')
    return response


# ============================================================================
# HELPER FUNCTIONS & DECORATORS
# ============================================================================

def obter_permissoes_usuario(email):
    """Busca as permissões do cargo atual do usuário logado."""
    if not email:
        return {}
    
    try:
        # CORREÇÃO: Removeu .single() para evitar quebra estrutural do código
        res_usr = supabase.table('usuarios_clan').select('cargo').eq('email', email).execute()
        if not res_usr.data:
            return {}
        
        # Coleta o cargo com segurança do primeiro registro da lista
        cargo_id = res_usr.data[0].get('cargo')
        
        # CORREÇÃO: Removeu .single() para evitar falhas de cache
        res_perm = supabase.table('permissoes_cargos').select('*').eq('cargo_id', cargo_id).execute()
        return res_perm.data[0] if res_perm.data else {}
    except Exception as e:
        print(f"Erro ao buscar permissões: {e}")
        return {}


def login_required(f):
    """Garante que o usuário está autenticado na sessão."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_email' not in session:
            flash('Por favor, faça login para acessar esta página.', 'erro')
            return redirect(url_for('pagina_inicial'))
        return f(*args, **kwargs)
    return decorated_function


def membro_hype_ativo(email=None):
    """Retorna True somente para usuário confirmado e ativo no Clã HYPE."""
    email = email or session.get('usuario_email')
    if not email:
        return False
    try:
        rows = supabase.table('membros_hype').select('ativo').eq('usuario_email', email).limit(1).execute().data or []
        return bool(rows and rows[0].get('ativo'))
    except Exception as e:
        print(f'[membros_hype] {e}')
        return False


def membro_hype_required(f):
    """Protege áreas internas exclusivas dos membros ativos do Clã HYPE."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_email' not in session:
            flash('Faça login para acessar esta área.', 'erro')
            return redirect(url_for('pagina_inicial'))
        if not membro_hype_ativo(session.get('usuario_email')):
            flash('O Tesouro do Clã é exclusivo para membros ativos da HYPE.', 'erro')
            return redirect(url_for('painel'))
        return f(*args, **kwargs)
    return decorated_function



def parse_valor_moeda(valor):
    """Aceita 500k, 1.5m, 1,5m, 1.5kk, 1,5kk ou números inteiros."""
    t = str(valor or '0').strip().lower().replace(' ', '')
    mult = 1
    for sufixo, fator in (('kk', 1_000_000), ('m', 1_000_000), ('k', 1_000)):
        if t.endswith(sufixo):
            mult = fator
            t = t[:-len(sufixo)]
            break

    # Com sufixo, ponto/vírgula podem ser decimais: 1.5m / 1,5m.
    if mult > 1:
        t = t.replace(',', '.')
        if t.count('.') > 1:
            partes = t.split('.')
            t = ''.join(partes[:-1]) + '.' + partes[-1]
    else:
        # Sem sufixo, aceita separadores de milhar comuns.
        if ',' in t and '.' in t:
            if t.rfind(',') > t.rfind('.'):
                t = t.replace('.', '').replace(',', '.')
            else:
                t = t.replace(',', '')
        elif ',' in t:
            partes = t.split(',')
            t = ''.join(partes) if len(partes[-1]) == 3 else t.replace(',', '.')
        elif '.' in t:
            partes = t.split('.')
            if len(partes) > 1 and len(partes[-1]) == 3:
                t = ''.join(partes)

    try:
        return max(0, int(float(t or 0) * mult))
    except (ValueError, TypeError):
        return 0


def agora_iso():
    """Retorna o horário atual em UTC no formato aceito pelo Supabase."""
    return datetime.now(timezone.utc).isoformat()


def parse_data_supabase(valor):
    if not valor:
        return None
    try:
        texto = str(valor)
        if texto.endswith('Z'):
            texto = texto[:-1] + '+00:00'
        data = datetime.fromisoformat(texto)
        if data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)
        return data
    except Exception:
        return None


def _login_guard_chave(email):
    # Nunca grava IP/e-mail em texto puro na tabela de tentativas.
    origem = f"{str(email or '').strip().lower()}|{request.remote_addr or 'sem-ip'}".encode('utf-8')
    return hmac.new(app.secret_key.encode('utf-8'), origem, hashlib.sha256).hexdigest()


def _login_guard_bloqueado(email):
    """Retorna minutos restantes do bloqueio ou 0. Falha aberta se a migração ainda não rodou."""
    try:
        chave = _login_guard_chave(email)
        rows = supabase.table('hype_login_seguranca').select('bloqueado_ate').eq('chave', chave).limit(1).execute().data or []
        if not rows or not rows[0].get('bloqueado_ate'):
            return 0
        bloqueado = parse_data_supabase(rows[0].get('bloqueado_ate'))
        if not bloqueado:
            return 0
        restante = bloqueado - datetime.now(timezone.utc)
        if restante.total_seconds() <= 0:
            return 0
        return max(1, int((restante.total_seconds() + 59) // 60))
    except Exception as e:
        print(f'[login guard consultar] {e}')
        return 0


def _login_guard_falha(email):
    """Registra falha e bloqueia por 15 min após 5 erros na mesma origem/e-mail."""
    try:
        chave = _login_guard_chave(email)
        rows = supabase.table('hype_login_seguranca').select('*').eq('chave', chave).limit(1).execute().data or []
        row = rows[0] if rows else {}
        agora = datetime.now(timezone.utc)
        ultima = parse_data_supabase(row.get('ultima_falha_em'))
        falhas = int(row.get('falhas') or 0)
        if not ultima or (agora - ultima) > timedelta(minutes=30):
            falhas = 0
        falhas += 1
        bloqueado_ate = None
        if falhas >= 5:
            bloqueado_ate = (agora + timedelta(minutes=15)).isoformat()
        supabase.table('hype_login_seguranca').upsert({
            'chave': chave,
            'falhas': min(falhas, 20),
            'ultima_falha_em': agora.isoformat(),
            'bloqueado_ate': bloqueado_ate,
        }, on_conflict='chave').execute()
        return 15 if bloqueado_ate else 0
    except Exception as e:
        print(f'[login guard falha] {e}')
        return 0


def _login_guard_limpar(email):
    try:
        supabase.table('hype_login_seguranca').delete().eq('chave', _login_guard_chave(email)).execute()
    except Exception as e:
        print(f'[login guard limpar] {e}')


@app.template_filter('data_br')
def filtro_data_br(valor, formato='%d/%m/%Y %H:%M'):
    """Formata datas do Supabase no horário do HYPE (Brasília).

    Aceita datetime ou string ISO/TIMESTAMPTZ. Se o valor não puder ser
    interpretado, devolve o texto original para a página nunca quebrar.
    """
    if not valor:
        return ''
    try:
        if isinstance(valor, datetime):
            data = valor
            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)
        else:
            data = parse_data_supabase(valor)
            if data is None:
                return str(valor)
        return data.astimezone(HYPE_TZ).strftime(formato)
    except Exception:
        return str(valor)


def mapa_nicks_por_email():
    """Mapa leve de perfis usado nas telas do Breed sem expor e-mail na interface."""
    try:
        res = supabase.table('usuarios_clan').select(
            'email,nick_jogo,nome_exibicao,avatar_url,discord_avatar_url,cargo'
        ).execute()
        return {
            u.get('email'): {
                'nick': u.get('nick_jogo') or u.get('email'),
                'nome': u.get('nome_exibicao') or u.get('nick_jogo') or u.get('email'),
                'avatar_url': u.get('avatar_url') or u.get('discord_avatar_url'),
                'cargo': u.get('cargo') or 'membro'
            }
            for u in (res.data or [])
            if u.get('email')
        }
    except Exception as e:
        print(f"Erro ao montar mapa de nicks: {e}")
        return {}


def enriquecer_pedidos_com_nicks(pedidos):
    mapa = mapa_nicks_por_email()
    for p in pedidos:
        email_breeder = p.get('breeder_responsavel')
        breeder = mapa.get(email_breeder, {}) if email_breeder else {}
        cliente = mapa.get(p.get('usuario_email'), {})
        p['breeder_nick'] = breeder.get('nick') if email_breeder else None
        p['breeder_avatar_url'] = breeder.get('avatar_url') if email_breeder else None
        p['player_nick'] = cliente.get('nick') or p.get('player') or 'Jogador'
        p['player_nome'] = cliente.get('nome') or p.get('player') or 'Jogador'
        p['player_avatar_url'] = cliente.get('avatar_url')
    return pedidos



def _safe_table(table, select='*', **eqs):
    """Consulta auxiliar: retorna [] se um módulo opcional ainda não existir no banco."""
    try:
        q = supabase.table(table).select(select)
        for k, v in eqs.items():
            q = q.eq(k, v)
        return q.execute().data or []
    except Exception as e:
        print(f"[{table}] {e}")
        return []


def tem_permissao(chave, fallback_gerenciar=True):
    p = obter_permissoes_usuario(session.get('usuario_email'))
    if chave in p:
        return bool(p.get(chave))
    return bool(p.get('pode_gerenciar_cargos')) if fallback_gerenciar else False


PRECO_BREED_FALLBACK = {
    'comum_f5_naturado': 200000, 'comum_f5_sem_nature': 200000,
    'comum_f6_sem_nature': 400000, 'comum_f6_naturado': 500000,
    'raro_f5_naturado': 800000, 'raro_f5_sem_nature': 800000,
    'raro_f6_sem_nature': 1200000, 'raro_f6_naturado': 1500000,
    'ditto_f5_naturado': 800000, 'ditto_f6_sem_nature': 1200000,
    'ditto_f6_naturado': 1500000,
    'ha_com_ditto_f5': 1800000, 'ha_com_ditto_f5_naturado': 1800000,
    'ha_com_ditto_f5_sem_nature': 1800000,
    'ha_com_ditto_f6_sem_nature': 2500000, 'ha_com_ditto_f6_naturado': 3000000,
    'ha_sem_ditto_f5': 1200000, 'ha_sem_ditto_f5_naturado': 1200000,
    'ha_sem_ditto_f5_sem_nature': 1200000,
    'ha_sem_ditto_f6_sem_nature': 1500000, 'ha_sem_ditto_f6_naturado': 1800000,
    'comum_genero': 100000, 'escolher_genero': 100000,
    'ha_sem_ditto_genero': 200000, 'femea_rara': 200000,
    'zero_speed': 200000,
    'treinado': 200000,
}

# Códigos legados que representam o mesmo componente de preço.
# Mantemos compatibilidade porque versões anteriores do HYPE gravaram nomes
# diferentes para o mesmo item na tabela de preços e nas promoções.
PROMO_CODIGO_EQUIVALENCIAS = {
    'comum_genero': {'comum_genero', 'escolher_genero'},
    'escolher_genero': {'comum_genero', 'escolher_genero'},
    'ha_sem_ditto_genero': {'ha_sem_ditto_genero', 'escolher_genero_raro'},
    'escolher_genero_raro': {'ha_sem_ditto_genero', 'escolher_genero_raro'},
    'ha_com_ditto_f5': {'ha_com_ditto_f5', 'ha_com_ditto_f5_naturado', 'ha_com_ditto_f5_sem_nature'},
    'ha_com_ditto_f5_naturado': {'ha_com_ditto_f5', 'ha_com_ditto_f5_naturado'},
    'ha_com_ditto_f5_sem_nature': {'ha_com_ditto_f5', 'ha_com_ditto_f5_sem_nature'},
    'ha_sem_ditto_f5': {'ha_sem_ditto_f5', 'ha_sem_ditto_f5_naturado', 'ha_sem_ditto_f5_sem_nature'},
    'ha_sem_ditto_f5_naturado': {'ha_sem_ditto_f5', 'ha_sem_ditto_f5_naturado'},
    'ha_sem_ditto_f5_sem_nature': {'ha_sem_ditto_f5', 'ha_sem_ditto_f5_sem_nature'},
}

# V31.2: aliases entre a antiga tabela por combinação e os novos componentes.
# Uma promoção antiga de HA+Ditto, por exemplo, continua incidindo sobre base + HA + Ditto.
PROMO_CODIGO_EQUIVALENCIAS.update({
    'base_comum_f5': {'base_comum_f5','comum_f5_naturado','comum_f5_sem_nature','ditto_f5_naturado','ha_sem_ditto_f5','ha_sem_ditto_f5_naturado','ha_sem_ditto_f5_sem_nature','ha_com_ditto_f5','ha_com_ditto_f5_naturado','ha_com_ditto_f5_sem_nature'},
    'base_comum_f6': {'base_comum_f6','comum_f6_naturado','comum_f6_sem_nature','ditto_f6_naturado','ditto_f6_sem_nature','ha_sem_ditto_f6_naturado','ha_sem_ditto_f6_sem_nature','ha_com_ditto_f6_naturado','ha_com_ditto_f6_sem_nature'},
    'base_raro_f5': {'base_raro_f5','raro_f5_naturado','raro_f5_sem_nature'},
    'base_raro_f6': {'base_raro_f6','raro_f6_naturado','raro_f6_sem_nature'},
    'adicional_ha_comum_f5': {'adicional_ha_comum_f5','ha_sem_ditto_f5','ha_sem_ditto_f5_naturado','ha_sem_ditto_f5_sem_nature','ha_com_ditto_f5','ha_com_ditto_f5_naturado','ha_com_ditto_f5_sem_nature'},
    'adicional_ha_raro_f5': {'adicional_ha_raro_f5','ha_sem_ditto_f5','ha_sem_ditto_f5_naturado','ha_sem_ditto_f5_sem_nature','ha_com_ditto_f5','ha_com_ditto_f5_naturado','ha_com_ditto_f5_sem_nature'},
    'adicional_ha_comum_f6': {'adicional_ha_comum_f6','ha_sem_ditto_f6_naturado','ha_sem_ditto_f6_sem_nature','ha_com_ditto_f6_naturado','ha_com_ditto_f6_sem_nature'},
    'adicional_ha_raro_f6': {'adicional_ha_raro_f6','ha_sem_ditto_f6_naturado','ha_sem_ditto_f6_sem_nature','ha_com_ditto_f6_naturado','ha_com_ditto_f6_sem_nature'},
    'adicional_ditto_comum_f5': {'adicional_ditto_comum_f5','ditto_f5_naturado','ha_com_ditto_f5','ha_com_ditto_f5_naturado','ha_com_ditto_f5_sem_nature'},
    'adicional_ditto_raro_f5': {'adicional_ditto_raro_f5','ditto_f5_naturado','ha_com_ditto_f5','ha_com_ditto_f5_naturado','ha_com_ditto_f5_sem_nature'},
    'adicional_ditto_comum_f6': {'adicional_ditto_comum_f6','ditto_f6_naturado','ditto_f6_sem_nature','ha_com_ditto_f6_naturado','ha_com_ditto_f6_sem_nature'},
    'adicional_ditto_raro_f6': {'adicional_ditto_raro_f6','ditto_f6_naturado','ditto_f6_sem_nature','ha_com_ditto_f6_naturado','ha_com_ditto_f6_sem_nature'},
    'adicional_zero_speed_comum': {'adicional_zero_speed_comum','zero_speed'},
    'adicional_zero_speed_raro': {'adicional_zero_speed_raro','zero_speed'},
    'adicional_genero_comum': {'adicional_genero_comum','comum_genero','escolher_genero'},
    'adicional_genero_raro': {'adicional_genero_raro','ha_sem_ditto_genero','escolher_genero_raro','femea_rara'},
    'adicional_treinado': {'adicional_treinado','treinado'},
})


def _promo_codigos_equivalentes(codigo):
    codigo = str(codigo or '').strip()
    return PROMO_CODIGO_EQUIVALENCIAS.get(codigo, {codigo})


def _parse_promo_datetime(valor):
    """Normaliza TIMESTAMPTZ do Supabase para UTC.

    Datetimes sem fuso vindos de dados antigos são interpretados no fuso HYPE
    (America/Sao_Paulo), e não em UTC. Isso evita promoções começarem/terminarem
    três horas fora do horário escolhido no painel.
    """
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HYPE_TZ)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _promo_datetime_form_para_utc(valor):
    """Converte o datetime-local do navegador (horário de Brasília) para UTC."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HYPE_TZ)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception as exc:
        raise ValueError('Data/horário da promoção inválido.') from exc


def _status_promocao(p, agora=None):
    agora = agora or datetime.now(timezone.utc)
    if p.get('ativo') is False:
        return 'pausada'
    inicio = _parse_promo_datetime(p.get('inicio_em'))
    fim = _parse_promo_datetime(p.get('fim_em'))
    if inicio and agora < inicio:
        return 'agendada'
    if fim and agora > fim:
        return 'expirada'
    return 'ativa'


def promocoes_breed_ativas(codigo_cupom=None, usuario_email=None, forcar_membro_hype=False):
    """Promoções válidas agora, incluindo cupons e regras exclusivas de membro.

    Promoções antigas continuam automáticas. Promoções com ``codigo_cupom`` só
    entram no cálculo quando o código informado confere. Falha fechada: sem
    tabela/migração = sem desconto.
    """
    agora = datetime.now(timezone.utc)
    cupom = str(codigo_cupom or '').strip().upper()
    rows = _safe_table('promocoes_breed', '*')
    validas = []
    eh_membro = bool(forcar_membro_hype) or (membro_hype_ativo(usuario_email) if usuario_email else False)
    for p in rows:
        if p.get('ativo') is False:
            continue
        inicio = _parse_promo_datetime(p.get('inicio_em'))
        fim = _parse_promo_datetime(p.get('fim_em'))
        if inicio and agora < inicio:
            continue
        if fim and agora > fim:
            continue
        try:
            pct = float(p.get('percentual') or 0)
        except (TypeError, ValueError):
            continue
        if pct <= 0 or pct > 100:
            continue
        codigo = str(p.get('codigo_cupom') or '').strip().upper()
        if codigo:
            if not cupom or cupom != codigo:
                continue
        elif p.get('aplicar_automaticamente', True) is False:
            continue
        if p.get('somente_membros_hype') and not eh_membro:
            continue
        limite = p.get('limite_usos')
        if limite not in (None, ''):
            try:
                if int(p.get('usos') or 0) >= int(limite):
                    continue
            except (TypeError, ValueError):
                pass
        p = dict(p)
        p['percentual'] = pct
        p['codigo_cupom_normalizado'] = codigo or None
        validas.append(p)
    validas.sort(key=lambda x: float(x.get('percentual') or 0), reverse=True)
    return validas


def _promocao_para_codigo(codigo, promocoes=None):
    """Retorna a melhor promoção aplicável ao código de preço.

    Além do match exato, entende aliases das versões antigas do HYPE. Assim uma
    promoção criada para `ha_com_ditto_f5` também alcança a variante naturada
    usada pelo cálculo atual, sem precisar recriar a promoção.
    """
    alvo_equivalentes = _promo_codigos_equivalentes(codigo)
    for p in (promocoes if promocoes is not None else promocoes_breed_ativas()):
        codigos = p.get('codigos_preco') or []
        if isinstance(codigos, str):
            try:
                codigos = json.loads(codigos)
            except Exception:
                # Postgres pode devolver arrays em forma textual em integrações antigas.
                texto = codigos.strip().strip('{}[]')
                codigos = [x.strip().strip('\"\'') for x in texto.split(',') if x.strip()]
        codigos = {str(x).strip() for x in (codigos or []) if str(x).strip()}
        if p.get('aplicar_todos'):
            return p
        if codigo in codigos:
            return p
        for selecionado in codigos:
            if alvo_equivalentes & _promo_codigos_equivalentes(selecionado):
                return p
    return None


def _aplicar_promocao_componente(codigo, valor, promocoes):
    promo = _promocao_para_codigo(codigo, promocoes)
    valor = int(valor or 0)
    if not promo:
        return valor, None
    pct = float(promo.get('percentual') or 0)
    final = max(0, int(round(valor * (100.0 - pct) / 100.0)))
    return final, promo


def _calcular_preco_breed_legacy(breed_tipo, ha=False, genero='indiferente', categoria='comum',
                                 usa_ditto=False, treinado=False, nature=None, zero_speed=False):
    """Calcula o preço no servidor. Ditto é automático; HPWR foi removido do formulário."""
    # Compatibilidade com bancos HYPE antigos e novos: versões anteriores de
    # precos_breed podem não ter a coluna `ativo`. Primeiro usamos apenas preços
    # ativos; se o filtro não retornar nada, consultamos a tabela sem esse filtro.
    # A tabela do Admin é sempre a fonte principal. O fallback abaixo evita
    # quebrar Revisão/Envio se o Supabase estiver momentaneamente sem leitura.
    linhas = _safe_table('precos_breed', '*')
    ativos = [x for x in linhas if x.get('ativo', True) is not False]
    precos = dict(PRECO_BREED_FALLBACK)
    precos.update({
        x.get('codigo'): int(x.get('valor') or 0)
        for x in ativos if x.get('codigo')
    })
    bt = (breed_tipo or '').lower()
    naturado = bool(nature)
    sufixo = 'naturado' if naturado else 'sem_nature'

    candidatos = []
    if ha:
        candidatos.append(f"ha_{'com' if usa_ditto else 'sem'}_ditto_{bt}_{sufixo}")
        candidatos.append(f"ha_{'com' if usa_ditto else 'sem'}_ditto_{bt}")
    elif usa_ditto:
        candidatos.append(f"ditto_{bt}_{sufixo}")
        candidatos.append(f"ditto_{bt}")
    elif categoria == 'raro':
        candidatos.append(f"raro_{bt}_{sufixo}")
        candidatos.append(f"raro_{bt}")
        candidatos.append(f"comum_{bt}_{sufixo}")
        candidatos.append(f"comum_{bt}")
    else:
        candidatos.append(f"comum_{bt}_{sufixo}")
        candidatos.append(f"comum_{bt}")

    # O cadastro atual usa F5 naturado; este fallback evita pedido zerado se Nature vier vazia.
    if bt == 'f5':
        if ha:
            candidatos.append(f"ha_{'com' if usa_ditto else 'sem'}_ditto_f5")
        elif usa_ditto:
            candidatos.append("ditto_f5_naturado")
        elif categoria == 'raro':
            candidatos.extend(["raro_f5_naturado", "comum_f5_naturado"])
        else:
            candidatos.append("comum_f5_naturado")

    codigo = next((c for c in candidatos if c in precos), candidatos[0] if candidatos else '')
    promocoes = promocoes_breed_ativas()
    base_original = int(precos.get(codigo, 0) or 0)
    base, promo_base = _aplicar_promocao_componente(codigo, base_original, promocoes)
    total_original = base_original
    total = base
    extras = []
    promos_usadas = []
    if promo_base: promos_usadas.append(promo_base)

    if genero in ('macho', 'femea'):
        if ha and not usa_ditto:
            extra_key = 'ha_sem_ditto_genero'
        else:
            extra_key = 'comum_genero'
        original = int(precos.get(extra_key, precos.get('escolher_genero', 0)) or 0)
        v, promo = _aplicar_promocao_componente(extra_key, original, promocoes)
        total_original += original; total += v
        extras.append({'codigo': extra_key, 'valor_original': original, 'valor': v, 'promocao': promo.get('nome') if promo else None})
        if promo: promos_usadas.append(promo)

        if categoria == 'raro' and genero == 'femea':
            original = int(precos.get('femea_rara', 0) or 0)
            v, promo = _aplicar_promocao_componente('femea_rara', original, promocoes)
            total_original += original; total += v
            extras.append({'codigo': 'femea_rara', 'valor_original': original, 'valor': v, 'promocao': promo.get('nome') if promo else None})
            if promo: promos_usadas.append(promo)

    if zero_speed:
        original = int(precos.get('zero_speed', 0) or 0)
        v, promo = _aplicar_promocao_componente('zero_speed', original, promocoes)
        total_original += original; total += v
        extras.append({'codigo': 'zero_speed', 'valor_original': original, 'valor': v, 'promocao': promo.get('nome') if promo else None})
        if promo: promos_usadas.append(promo)

    if treinado:
        original = int(precos.get('treinado', 0) or 0)
        v, promo = _aplicar_promocao_componente('treinado', original, promocoes)
        total_original += original; total += v
        extras.append({'codigo': 'treinado', 'valor_original': original, 'valor': v, 'promocao': promo.get('nome') if promo else None})
        if promo: promos_usadas.append(promo)

    promo_principal = max(promos_usadas, key=lambda x: float(x.get('percentual') or 0), default=None)
    desconto = max(0, total_original - total)
    return total, {
        'base_codigo': codigo, 'base_valor_original': base_original, 'base_valor': base,
        'breed_especial_ditto': bool(usa_ditto), 'extras': extras,
        'preco_original': total_original, 'desconto_valor': desconto, 'total': total,
        'promocao_ativa': bool(desconto),
        'promocao_id': promo_principal.get('id') if promo_principal else None,
        'promocao_nome': promo_principal.get('nome') if promo_principal else None,
        'promocao_percentual': float(promo_principal.get('percentual') or 0) if promo_principal else 0,
    }


def _precos_breed_interface_legacy():
    """Valores legados dos adicionais enviados junto com o HTML."""
    linhas = _safe_table('precos_breed', '*')
    ativos = [x for x in linhas if x.get('ativo', True) is not False]
    precos = dict(PRECO_BREED_FALLBACK)
    precos.update({x.get('codigo'): int(x.get('valor') or 0) for x in ativos if x.get('codigo')})
    promocoes = promocoes_breed_ativas()
    codigos = ('zero_speed', 'comum_genero', 'escolher_genero', 'ha_sem_ditto_genero', 'femea_rara', 'treinado')
    saida = {}
    for codigo in codigos:
        original = int(precos.get(codigo, 0) or 0)
        valor, promo = _aplicar_promocao_componente(codigo, original, promocoes)
        saida[codigo] = {
            'valor_original': original,
            'valor': int(valor or 0),
            'promocao_nome': promo.get('nome') if promo else None,
            'promocao_percentual': float(promo.get('percentual') or 0) if promo else 0,
        }
    return saida



# ============================================================================
# HYPE V33 - CENTRAL DE PRECOS BREED 3.0 (base V31.2/V31.3/V32)
# Tabelas versionadas, raridade automática, HA, Zero Speed, exceções por espécie,
# desconto de membro, margem mínima e simulador administrativo.
# ============================================================================
BREED_V312_COMPONENTES_META = {
    'base_comum_f5': ('Base Comum F5', 'base', 10),
    'base_comum_f6': ('Base Comum F6', 'base', 20),
    'base_raro_f5': ('Base Raro F5', 'base', 30),
    'base_raro_f6': ('Base Raro F6', 'base', 40),
    'base_ultra_raro_f5': ('Base Ultra Raro F5', 'base', 50),
    'base_ultra_raro_f6': ('Base Ultra Raro F6', 'base', 60),
    'desconto_sem_nature_comum_f5': ('Desconto sem Nature · Comum F5', 'nature', 70),
    'desconto_sem_nature_comum_f6': ('Desconto sem Nature · Comum F6', 'nature', 80),
    'desconto_sem_nature_raro_f5': ('Desconto sem Nature · Raro F5', 'nature', 90),
    'desconto_sem_nature_raro_f6': ('Desconto sem Nature · Raro F6', 'nature', 100),
    'desconto_sem_nature_ultra_raro_f5': ('Desconto sem Nature · Ultra Raro F5', 'nature', 110),
    'desconto_sem_nature_ultra_raro_f6': ('Desconto sem Nature · Ultra Raro F6', 'nature', 120),
    'adicional_ha_comum_f5': ('HA · Comum F5', 'ha', 130),
    'adicional_ha_comum_f6': ('HA · Comum F6', 'ha', 140),
    'adicional_ha_raro_f5': ('HA · Raro F5', 'ha', 150),
    'adicional_ha_raro_f6': ('HA · Raro F6', 'ha', 160),
    'adicional_ha_ultra_raro_f5': ('HA · Ultra Raro F5', 'ha', 170),
    'adicional_ha_ultra_raro_f6': ('HA · Ultra Raro F6', 'ha', 180),
    'adicional_zero_speed_comum': ('Zero Speed · Comum', 'zero_speed', 190),
    'adicional_zero_speed_raro': ('Zero Speed · Raro', 'zero_speed', 200),
    'adicional_zero_speed_ultra_raro': ('Zero Speed · Ultra Raro', 'zero_speed', 210),
    # V31.3: Ditto deixa de ser adicional para espécies Ultra Raras; a dificuldade já está no preço-base.
    # Os componentes antigos de Ditto continuam no banco apenas por compatibilidade/histórico.
    'adicional_genero_comum': ('Escolher gênero · Comum', 'extras', 220),
    'adicional_genero_raro': ('Escolher gênero · Raro', 'extras', 230),
    'adicional_genero_ultra_raro': ('Escolher gênero · Ultra Raro', 'extras', 240),
    'adicional_treinado': ('Pokémon treinado', 'extras', 250),
    # V32: Hidden Power Ability = pedido totalmente personalizado por IV.
    'base_comum_personalizado': ('Personalizado · Comum', 'personalizado', 300),
    'base_raro_personalizado': ('Personalizado · Raro', 'personalizado', 310),
    'base_ultra_raro_personalizado': ('Personalizado · Ultra Raro', 'personalizado', 320),
    'desconto_sem_nature_comum_personalizado': ('Sem Nature · Personalizado Comum', 'personalizado', 330),
    'desconto_sem_nature_raro_personalizado': ('Sem Nature · Personalizado Raro', 'personalizado', 340),
    'desconto_sem_nature_ultra_raro_personalizado': ('Sem Nature · Personalizado Ultra Raro', 'personalizado', 350),
    'adicional_ha_comum_personalizado': ('HA · Personalizado Comum', 'personalizado', 360),
    'adicional_ha_raro_personalizado': ('HA · Personalizado Raro', 'personalizado', 370),
    'adicional_ha_ultra_raro_personalizado': ('HA · Personalizado Ultra Raro', 'personalizado', 380),
}

BREED_V312_PACOTES = [
    {'codigo':'economico_f5','nome':'F5 Econômico','breed_tipo':'F5','ha':False,'zero_speed':False,'categoria':'comum','usa_ditto':False},
    {'codigo':'f5_ha','nome':'F5 + HA','breed_tipo':'F5','ha':True,'zero_speed':False,'categoria':'comum','usa_ditto':False},
    {'codigo':'f5_zero','nome':'F5 Zero Speed','breed_tipo':'F5','ha':False,'zero_speed':True,'categoria':'comum','usa_ditto':False},
    {'codigo':'raro_comp','nome':'Raro Competitivo','breed_tipo':'F5','ha':True,'zero_speed':True,'categoria':'raro','usa_ditto':False},
    {'codigo':'ultra_comp','nome':'Ultra Raro Competitivo','breed_tipo':'F5','ha':True,'zero_speed':True,'categoria':'ultra_raro','usa_ditto':True},
    {'codigo':'personalizado','nome':'Hidden Power Ability','breed_tipo':'PERSONALIZADO','ha':False,'zero_speed':False,'categoria':'comum','usa_ditto':False},
]

BREED_CATEGORIAS_PRECO = ('comum', 'raro', 'ultra_raro')
BREED_CATEGORIA_LABELS = {
    'comum': 'Comum',
    'raro': 'Raro',
    'ultra_raro': 'Ultra Raro',
}



def _breed_v312_tabelas():
    return _safe_table('breed_tabelas_preco', '*')


def _breed_v312_tabela_por_id(tabela_id):
    try:
        alvo = int(tabela_id)
    except (TypeError, ValueError):
        return None
    rows = _safe_table('breed_tabelas_preco', '*', id=alvo)
    return rows[0] if rows else None


def _breed_v312_tabela_atual():
    """Resolve a tabela em vigor. Uma tabela agendada sobrepõe a ativa só na janela."""
    agora = datetime.now(timezone.utc)
    rows = _breed_v312_tabelas()
    agendadas = []
    ativas = []
    for row in rows:
        status = str(row.get('status') or '').lower()
        inicio = parse_data_supabase(row.get('inicio_em'))
        fim = parse_data_supabase(row.get('fim_em'))
        dentro = (not inicio or inicio <= agora) and (not fim or agora < fim)
        if status == 'agendada' and dentro:
            agendadas.append(row)
        elif status == 'ativa' and dentro:
            ativas.append(row)
    def chave(row):
        dt = parse_data_supabase(row.get('inicio_em')) or parse_data_supabase(row.get('publicado_em')) or parse_data_supabase(row.get('created_at'))
        return (dt or datetime.min.replace(tzinfo=timezone.utc), int(row.get('id') or 0))
    if agendadas:
        return sorted(agendadas, key=chave, reverse=True)[0]
    if ativas:
        return sorted(ativas, key=chave, reverse=True)[0]
    return None


def _breed_v312_componentes(tabela_id):
    if not tabela_id:
        return {}
    rows = _safe_table('breed_tabela_componentes', '*', tabela_id=tabela_id)
    return {str(x.get('codigo')): x for x in rows if x.get('codigo') and x.get('ativo', True) is not False}


def _breed_v312_excecao(tabela_id, pokemon_id):
    if not tabela_id or not pokemon_id:
        return None
    rows = _safe_table('breed_preco_especie_excecoes', '*', tabela_id=tabela_id, pokemon_id=int(pokemon_id))
    return rows[0] if rows else None


def _breed_v312_valor(componentes, codigo, padrao=0):
    row = componentes.get(codigo) or {}
    try:
        return max(0, int(row.get('valor') if row else padrao))
    except (TypeError, ValueError):
        return max(0, int(padrao or 0))


def _breed_v312_registrar_historico(tabela_id, acao, codigo=None, anterior=None, novo=None, detalhes=None):
    try:
        supabase.table('breed_preco_historico').insert({
            'tabela_id': tabela_id, 'acao': acao, 'codigo': codigo,
            'valor_anterior': anterior, 'valor_novo': novo,
            'usuario_email': session.get('usuario_email'), 'detalhes': detalhes or {}
        }).execute()
    except Exception as exc:
        print(f'[V31.2 historico preco] {exc}')


def _breed_v312_validar_tabela(tabela_id):
    """Valida apenas a integridade da tabela de preços.

    V31.3.1: o Admin tem liberdade para definir a relação de preços entre
    Comum, Raro e Ultra Raro. Não bloqueamos mais a publicação por hierarquia
    entre categorias, por F5/F6 ou pela diferença dos adicionais entre elas.
    """
    c = _breed_v312_componentes(tabela_id)
    erros = []
    def v(k): return _breed_v312_valor(c, k)

    obrigatorios = [
        k for k in BREED_V312_COMPONENTES_META
        if k.startswith('base_') or k.startswith('adicional_ha_') or k.startswith('adicional_zero_speed_')
    ]
    faltando = [k for k in obrigatorios if k not in c]
    if faltando:
        erros.append('Existem componentes obrigatórios ausentes: ' + ', '.join(faltando[:4]) + ('…' if len(faltando) > 4 else ''))

    # Mantém somente proteções de integridade: o desconto sem Nature não pode
    # transformar o preço-base em um valor negativo.
    for cat in BREED_CATEGORIAS_PRECO:
        for bt in ('f5','f6'):
            if v(f'desconto_sem_nature_{cat}_{bt}') > v(f'base_{cat}_{bt}'):
                erros.append(f'O desconto sem Nature de {BREED_CATEGORIA_LABELS[cat]} {bt.upper()} não pode superar o preço-base.')

    # HA e Zero Speed continuam sendo serviços adicionais do Pricing 2.0,
    # mas seus valores podem ser diferentes livremente entre as categorias.
    for cat in BREED_CATEGORIAS_PRECO:
        for bt in ('f5','f6'):
            if v(f'adicional_ha_{cat}_{bt}') < 0:
                erros.append(f'O adicional HA de {BREED_CATEGORIA_LABELS[cat]} {bt.upper()} não pode ser negativo.')
        if v(f'adicional_zero_speed_{cat}') < 0:
            erros.append(f'O adicional Zero Speed de {BREED_CATEGORIA_LABELS[cat]} não pode ser negativo.')
    return erros


def _breed_v312_promo_aplicada(codigo, valor, promocoes, max_pct=100):
    promo = _promocao_para_codigo(codigo, promocoes)
    original = max(0, int(valor or 0))
    if not promo:
        return original, None
    pct = min(float(promo.get('percentual') or 0), max(0.0, min(100.0, float(max_pct or 100))))
    final = max(0, int(round(original * (100.0 - pct) / 100.0)))
    promo = dict(promo); promo['percentual_aplicado'] = pct
    return final, promo


def _calcular_preco_breed_v312(breed_tipo, ha=False, genero='indiferente', categoria='comum',
                                usa_ditto=False, treinado=False, nature=None, zero_speed=False,
                                pokemon_id=None, usuario_email=None, codigo_cupom=None, tabela_id_override=None, forcar_membro_hype=False):
    tabela = _breed_v312_tabela_por_id(tabela_id_override) if tabela_id_override else _breed_v312_tabela_atual()
    if not tabela:
        return None
    componentes = _breed_v312_componentes(tabela.get('id'))
    if not componentes:
        return None

    bt = str(breed_tipo or '').lower()
    if bt not in ('f5','f6','personalizado'):
        return 0, {'erro':'Breed inválido.'}
    categoria = str(categoria or 'comum').lower()
    if categoria not in BREED_CATEGORIAS_PRECO:
        categoria = 'comum'

    excecao = _breed_v312_excecao(tabela.get('id'), pokemon_id)
    if excecao and excecao.get('categoria_override') in BREED_CATEGORIAS_PRECO:
        categoria = excecao.get('categoria_override')

    # V31.3: se a espécie realmente depende de Ditto, ela pertence à categoria Ultra Raro.
    # O Ditto já está embutido no preço-base Ultra Raro e não é somado novamente.
    if usa_ditto:
        categoria = 'ultra_raro'

    # Compatibilidade de deploy: se o código V31.3 subir antes da migração SQL,
    # usa temporariamente a antiga estrutura Raro + adicional Ditto em vez de zerar o preço.
    ultra_fallback_legado = False
    if categoria == 'ultra_raro' and f'base_ultra_raro_{bt}' not in componentes:
        categoria = 'raro'
        ultra_fallback_legado = True

    max_pct = float(tabela.get('desconto_maximo_percentual') or 100)
    promocoes = promocoes_breed_ativas(codigo_cupom=codigo_cupom, usuario_email=usuario_email, forcar_membro_hype=forcar_membro_hype)
    cupom_digitado = str(codigo_cupom or '').strip().upper()
    cupom_promo = next((p for p in promocoes if str(p.get('codigo_cupom') or '').strip().upper() == cupom_digitado), None) if cupom_digitado else None

    itens = []
    promos_usadas = []
    def adicionar(codigo, valor=None, tipo='adicional'):
        if valor is None:
            valor = _breed_v312_valor(componentes, codigo)
        valor = max(0, int(valor or 0))
        final, promo = _breed_v312_promo_aplicada(codigo, valor, promocoes, max_pct=max_pct)
        meta = BREED_V312_COMPONENTES_META.get(codigo, (codigo.replace('_',' ').title(), 'outros', 999))
        itens.append({'codigo':codigo,'nome':meta[0],'tipo':tipo,'valor_original':valor,'valor':final,
                      'promocao': promo.get('nome') if promo else None})
        if promo: promos_usadas.append(promo)
        return valor, final

    base_codigo = f'base_{categoria}_{bt}'
    base_original = _breed_v312_valor(componentes, base_codigo)
    if excecao and excecao.get('valor_base_override') is not None:
        try: base_original = max(0, int(excecao.get('valor_base_override') or 0))
        except (TypeError, ValueError): pass
    _, base_final = adicionar(base_codigo, base_original, 'base')
    estrutural_original = base_original
    subtotal = base_final

    # Sem Nature é uma regra estrutural da tabela, não uma promoção.
    if not nature:
        desconto_codigo = f'desconto_sem_nature_{categoria}_{bt}'
        desconto_nature = min(_breed_v312_valor(componentes, desconto_codigo), estrutural_original)
        if desconto_nature:
            estrutural_original -= desconto_nature
            subtotal = max(0, subtotal - desconto_nature)
            meta = BREED_V312_COMPONENTES_META.get(desconto_codigo, (desconto_codigo, 'nature', 0))
            itens.append({'codigo':desconto_codigo,'nome':meta[0],'tipo':'desconto_tabela','valor_original':-desconto_nature,'valor':-desconto_nature,'promocao':None})

    codigos_extras = []
    if ha: codigos_extras.append(f'adicional_ha_{categoria}_{bt}')
    if zero_speed and bt in ('f5','f6'): codigos_extras.append(f'adicional_zero_speed_{categoria}')
    if usa_ditto and ultra_fallback_legado:
        codigos_extras.append(f'adicional_ditto_{categoria}_{bt}')
    if genero in ('macho','femea'): codigos_extras.append(f'adicional_genero_{categoria}')
    if treinado: codigos_extras.append('adicional_treinado')
    for codigo in codigos_extras:
        o, f = adicionar(codigo)
        estrutural_original += o
        subtotal += f

    if excecao:
        adicional = max(0, int(excecao.get('adicional_fixo') or 0))
        if adicional:
            o, f = adicionar('especie_adicional', adicional)
            estrutural_original += o; subtotal += f
        try: multiplicador = float(excecao.get('multiplicador') or 1)
        except (TypeError, ValueError): multiplicador = 1.0
        multiplicador = max(.1, min(10.0, multiplicador))
        if abs(multiplicador - 1.0) > 0.0001:
            estrutural_original = int(round(estrutural_original * multiplicador))
            subtotal = int(round(subtotal * multiplicador))
            itens.append({'codigo':'especie_multiplicador','nome':f'Multiplicador da espécie ×{multiplicador:g}','tipo':'regra_especie','valor_original':0,'valor':0,'promocao':None})

    desconto_membro_pct = 0.0
    desconto_membro_valor = 0
    if forcar_membro_hype or (usuario_email and membro_hype_ativo(usuario_email)):
        try: desconto_membro_pct = max(0.0, min(100.0, float(tabela.get('desconto_membro_hype_percentual') or 0)))
        except (TypeError, ValueError): desconto_membro_pct = 0
        if desconto_membro_pct:
            desconto_membro_valor = int(round(subtotal * desconto_membro_pct / 100.0))
            subtotal = max(0, subtotal - desconto_membro_valor)

    # Proteção de desconto máximo considerando promoções + desconto de membro.
    piso_desconto = int(round(estrutural_original * (100.0 - max_pct) / 100.0))
    total = max(subtotal, piso_desconto)

    # Proteção de margem: garante o líquido mínimo configurado para o Breeder.
    minimo_breeder = max(0, int(tabela.get('minimo_breeder_liquido') or 0))
    margem_protegida = False
    if minimo_breeder:
        taxa_pct = obter_taxa_clan_breed()
        fator = max(0.0001, 1.0 - taxa_pct / 100.0)
        piso_total = int((minimo_breeder / fator) + 0.999999)
        if total < piso_total:
            total = piso_total
            margem_protegida = True

    promo_principal = max(promos_usadas, key=lambda x: float(x.get('percentual_aplicado', x.get('percentual') or 0)), default=None)
    cupom_aplicado = bool(cupom_promo and any(str(p.get('id')) == str(cupom_promo.get('id')) for p in promos_usadas))
    desconto_total = max(0, estrutural_original - total)
    return total, {
        'pricing_v2': True, 'pricing_v3_raridade': not ultra_fallback_legado,
        'tabela_preco_id': tabela.get('id'), 'tabela_preco_nome': tabela.get('nome'),
        'categoria': categoria, 'base_codigo': base_codigo, 'base_valor_original': base_original,
        'base_valor': next((x.get('valor') for x in itens if x.get('codigo') == base_codigo), base_final),
        'breed_especial_ditto': bool(usa_ditto), 'extras': [x for x in itens if x.get('tipo') != 'base'],
        'componentes': itens, 'preco_original': estrutural_original, 'desconto_valor': desconto_total, 'total': total,
        'promocao_ativa': bool(desconto_total),
        'promocao_id': promo_principal.get('id') if promo_principal else None,
        'promocao_nome': promo_principal.get('nome') if promo_principal else None,
        'promocao_percentual': float(promo_principal.get('percentual_aplicado', promo_principal.get('percentual') or 0)) if promo_principal else 0,
        'cupom_codigo': cupom_digitado or None, 'cupom_valido': bool(cupom_promo) if cupom_digitado else None,
        'cupom_aplicado': cupom_aplicado if cupom_digitado else None,
        'cupom_id': cupom_promo.get('id') if (cupom_promo and cupom_aplicado) else None,
        'desconto_membro_hype_percentual': desconto_membro_pct,
        'desconto_membro_hype_valor': desconto_membro_valor,
        'margem_protegida': margem_protegida, 'minimo_breeder_liquido': minimo_breeder,
        'regra_especie': excecao or None,
    }


def calcular_preco_breed(breed_tipo, ha=False, genero='indiferente', categoria='comum',
                         usa_ditto=False, treinado=False, nature=None, zero_speed=False,
                         pokemon_id=None, usuario_email=None, codigo_cupom=None):
    """Preço oficial do Breed. V31.3 usa três raridades; mantém fallback legado para deploy seguro."""
    v2 = _calcular_preco_breed_v312(
        breed_tipo, ha=ha, genero=genero, categoria=categoria, usa_ditto=usa_ditto,
        treinado=treinado, nature=nature, zero_speed=zero_speed, pokemon_id=pokemon_id,
        usuario_email=usuario_email, codigo_cupom=codigo_cupom
    )
    if v2 is not None:
        return v2
    total, detalhes = _calcular_preco_breed_legacy(
        breed_tipo, ha=ha, genero=genero, categoria=categoria, usa_ditto=usa_ditto,
        treinado=treinado, nature=nature, zero_speed=zero_speed
    )
    detalhes['pricing_v2'] = False
    detalhes['cupom_codigo'] = str(codigo_cupom or '').strip().upper() or None
    detalhes['cupom_valido'] = None
    detalhes['tabela_preco_id'] = None
    return total, detalhes


def precos_breed_interface():
    """Valores usados nos avisos instantâneos do formulário; o servidor recalcula no envio."""
    tabela = _breed_v312_tabela_atual()
    if not tabela:
        return _precos_breed_interface_legacy()
    c = _breed_v312_componentes(tabela.get('id'))
    promocoes = promocoes_breed_ativas(usuario_email=session.get('usuario_email'))
    mapa = {
        'zero_speed':'adicional_zero_speed_comum', 'zero_speed_raro':'adicional_zero_speed_raro',
        'zero_speed_ultra_raro':'adicional_zero_speed_ultra_raro',
        'comum_genero':'adicional_genero_comum', 'escolher_genero':'adicional_genero_comum',
        'ha_sem_ditto_genero':'adicional_genero_comum', 'femea_rara':'adicional_genero_raro',
        'genero_raro':'adicional_genero_raro', 'genero_ultra_raro':'adicional_genero_ultra_raro', 'treinado':'adicional_treinado',
    }
    saida = {}
    max_pct = float(tabela.get('desconto_maximo_percentual') or 100)
    for alias, codigo in mapa.items():
        original = _breed_v312_valor(c, codigo)
        valor, promo = _breed_v312_promo_aplicada(codigo, original, promocoes, max_pct=max_pct)
        saida[alias] = {'valor_original':original,'valor':valor,'promocao_nome':promo.get('nome') if promo else None,
                        'promocao_percentual':float(promo.get('percentual_aplicado', promo.get('percentual') or 0)) if promo else 0}
    saida['_meta'] = {'pricing_v2':True,'tabela_id':tabela.get('id'),'tabela_nome':tabela.get('nome')}
    return saida

def obter_taxa_clan_breed():
    """Percentual de comissão do clã configurado no banco (padrão 30%)."""
    try:
        rows = _safe_table('configuracoes_site', '*', chave='breed_taxa_clan_percentual')
        valor = rows[0].get('valor') if rows else 30
        taxa = float(str(valor).replace(',', '.'))
    except Exception:
        taxa = 30.0
    return max(0.0, min(100.0, taxa))


def calcular_divisao_breed(valor_total, percentual=None):
    total = max(0, int(valor_total or 0))
    pct = obter_taxa_clan_breed() if percentual is None else max(0.0, min(100.0, float(percentual)))
    taxa = max(0, min(total, int(round(total * pct / 100.0))))
    return pct, taxa, total - taxa


def registrar_caixa_clan(tipo, categoria, descricao, valor, origem_tipo=None, origem_id=None, chave_unica=None):
    if tipo not in ('entrada', 'saida'):
        return False
    try:
        supabase.table('hype_caixa_clan').insert({
            'tipo': tipo, 'categoria': categoria or 'geral', 'descricao': descricao or 'Movimentação do Clã HYPE',
            'valor': max(0, int(valor or 0)), 'origem_tipo': origem_tipo, 'origem_id': origem_id,
            'criado_por': session.get('usuario_email'), 'chave_unica': chave_unica
        }).execute()
        return True
    except Exception as e:
        if chave_unica and ('duplicate' in str(e).lower() or 'unique' in str(e).lower()):
            return False
        print(f"Movimentação do caixa HYPE não registrada: {e}")
        return False



# ============================================================================
# HYPE V28 - FINANCEIRO BREED 2.0 / COMISSOES DO CLA
# A taxa vira divida somente quando o Pokemon e marcado como pronto.
# ============================================================================
def obter_comissao_breed(pedido_id):
    try:
        rows = supabase.table('hype_breed_comissoes').select('*').eq('pedido_id', pedido_id).limit(1).execute().data or []
        return rows[0] if rows else None
    except Exception:
        return None


def gerar_comissao_breed_pendente(pedido):
    """Cria, de forma idempotente, a divida do Breeder quando o Breed fica pronto."""
    if not pedido or not pedido.get('id') or not pedido.get('breeder_responsavel'):
        return None
    existente = obter_comissao_breed(pedido.get('id'))
    if existente:
        return existente
    valor = int(pedido.get('taxa_clan_valor') or 0)
    pct = float(pedido.get('taxa_clan_percentual') or 0)
    if valor <= 0:
        return None
    payload = {
        'pedido_id': pedido.get('id'),
        'breeder_email': pedido.get('breeder_responsavel'),
        'percentual': pct,
        'valor': valor,
        'status': 'pendente',
        'origem_fluxo': 'v28',
        'gerada_em': agora_iso(),
    }
    try:
        res = supabase.table('hype_breed_comissoes').insert(payload).execute()
        comissao = (res.data or [payload])[0]
        criar_notificacao(
            pedido.get('breeder_responsavel'),
            'Comissao HYPE pendente',
            f"O Breed #{pedido.get('id')} de {pedido.get('pokemon')} ficou pronto. Sua comissao com o Cla e de {formatar_preco(valor)}.",
            'aviso',
            url_for('painel_breeder_hype')
        )
        registrar_log('gerar_comissao', 'financeiro_breed', 'pedido_breed', pedido.get('id'), {
            'breeder': pedido.get('breeder_responsavel'), 'valor': valor, 'percentual': pct
        })
        return comissao
    except Exception as e:
        # UNIQUE(pedido_id) protege contra clique duplo/race condition.
        print(f'[V28 comissao] Nao foi possivel gerar comissao do pedido #{pedido.get("id")}: {e}')
        return obter_comissao_breed(pedido.get('id'))


def cancelar_comissao_breed(pedido_id, motivo='Pedido cancelado/estornado'):
    """Cancela a divida. Se ja estava paga, estorna o caixa do cla uma unica vez."""
    comissao = obter_comissao_breed(pedido_id)
    if not comissao or comissao.get('status') == 'cancelado':
        return comissao
    status_anterior = comissao.get('status')
    if status_anterior == 'pago' and int(comissao.get('valor') or 0) > 0:
        registrar_caixa_clan(
            'saida', 'estorno_taxa_breed', f"Estorno da comissao do Breed #{pedido_id}", int(comissao.get('valor') or 0),
            origem_tipo='breed_comissao', origem_id=comissao.get('id'),
            chave_unica=f'breed:comissao:{comissao.get("id")}:estorno'
        )
    try:
        supabase.table('hype_breed_comissoes').update({
            'status':'cancelado', 'cancelado_em':agora_iso(), 'motivo_cancelamento':motivo,
            'updated_at':agora_iso()
        }).eq('id', comissao.get('id')).execute()
    except Exception as e:
        print(f'[V28 comissao] Falha ao cancelar comissao #{comissao.get("id")}: {e}')
    return comissao


def formatar_preco(valor):
    try:
        return f"{int(valor or 0):,}".replace(',', '.')
    except Exception:
        return str(valor or 0)


def notificar_admins_financeiro(titulo, mensagem):
    """Envia aviso aos Lideres/Sub-Lideres quando um Breeder informa pagamento."""
    try:
        usuarios = _safe_table('usuarios_clan', 'email,cargo')
        for u in usuarios:
            if u.get('cargo') in ('lider','sub_lider') and u.get('email'):
                criar_notificacao(u.get('email'), titulo, mensagem, 'aviso', url_for('final.financeiro'))
    except Exception as e:
        print(f'[V28 comissao] Falha ao notificar administracao: {e}')


def classificar_pokemon_preco(pokemon_id):
    """V31.3: classificação automática por regra objetiva de breeding.

    Prioridade automática: Ultra Raro (só com Ditto) > Raro (12,5% fêmea) > Comum.
    O Admin pode criar override explícito para a economia/regra do servidor.
    """
    rows = _safe_table('pokemon_precificacao', '*', pokemon_id=pokemon_id)
    meta_db = dict(rows[0]) if rows else {}
    externa = _pokeapi_species_rule(pokemon_id)

    gender_rate = meta_db.get('gender_rate')
    try:
        gender_rate = int(gender_rate) if gender_rate is not None else None
    except (TypeError, ValueError):
        gender_rate = None
    so_com_ditto_auto = bool(meta_db.get('usa_ditto_padrao'))
    if externa:
        if externa.get('gender_rate') is not None:
            gender_rate = externa.get('gender_rate')
        so_com_ditto_auto = bool(externa.get('so_com_ditto')) or so_com_ditto_auto

    override = str(meta_db.get('categoria_override') or '').strip().lower()
    ditto_override = meta_db.get('usa_ditto_override')
    if isinstance(ditto_override, bool):
        so_com_ditto = ditto_override
        ditto_origem = 'manual'
    elif override == 'ultra_raro':
        # Forçar Ultra Raro também força a regra de Ditto, preservando a definição da categoria.
        so_com_ditto = True
        ditto_origem = 'manual'
    else:
        so_com_ditto = so_com_ditto_auto
        ditto_origem = 'automatico'

    if so_com_ditto:
        categoria_auto = 'ultra_raro'
        motivo_auto = 'Reprodução dependente de Ditto.'
    elif gender_rate == 1:
        categoria_auto = 'raro'
        motivo_auto = 'Taxa de fêmea de 12,5% (1/8).'
    else:
        categoria_auto = 'comum'
        motivo_auto = 'Reprodução padrão: não depende de Ditto e não possui taxa de fêmea de 12,5%.'

    # Ultra Raro tem prioridade sempre que a regra efetiva exigir Ditto. Para rebaixar
    # uma espécie que no jogo padrão depende de Ditto, o Admin precisa forçar "não depende".
    if so_com_ditto:
        categoria = 'ultra_raro'
        origem = 'manual' if ditto_origem == 'manual' else 'automatico'
        motivo = (meta_db.get('motivo_override') or '').strip() if origem == 'manual' else motivo_auto
        motivo = motivo or motivo_auto
    elif override in BREED_CATEGORIAS_PRECO:
        categoria = override
        origem = 'manual'
        motivo = (meta_db.get('motivo_override') or '').strip() or f'Categoria definida manualmente como {BREED_CATEGORIA_LABELS[override]}.'
    else:
        categoria = categoria_auto
        origem = 'automatico'
        motivo = motivo_auto

    taxa_femea = None
    if isinstance(gender_rate, int) and gender_rate >= 0:
        taxa_femea = round((gender_rate / 8) * 100, 2)

    return {
        **meta_db,
        'categoria': categoria,
        'categoria_automatica': categoria_auto,
        'categoria_label': BREED_CATEGORIA_LABELS.get(categoria, 'Comum'),
        'classificacao_origem': origem,
        'classificacao_motivo': motivo,
        'gender_rate': gender_rate,
        'taxa_femea_percentual': taxa_femea,
        'so_com_ditto': so_com_ditto,
        'usa_ditto_padrao': so_com_ditto,
        'ditto_origem': ditto_origem,
    }


@lru_cache(maxsize=2048)
def _pokeapi_species_rule(pokemon_id):
    """Valida se a espécie pode ser alvo de Breed. PokéAPI + fallback CSV oficial."""
    try:
        with urlopen(f"https://pokeapi.co/api/v2/pokemon-species/{int(pokemon_id)}/", timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        egg_groups = [g.get("name") for g in (data.get("egg_groups") or []) if g.get("name")]
        is_baby = bool(data.get("is_baby"))
        is_legendary = bool(data.get("is_legendary"))
        is_mythical = bool(data.get("is_mythical"))
        no_eggs = "no-eggs" in egg_groups
        breedavel = not (is_baby or is_legendary or is_mythical or no_eggs)
        so_com_ditto = breedavel and data.get("gender_rate") == -1
        return {
            "breedavel": breedavel,
            "so_com_ditto": so_com_ditto,
            "gender_rate": data.get("gender_rate"),
            "egg_groups": egg_groups,
            "nome": data.get("name"),
            "is_baby": is_baby,
            "is_legendary": is_legendary,
            "is_mythical": is_mythical,
            "no_eggs": no_eggs,
        }
    except Exception as e:
        print(f"PokeAPI indisponível para regra de Breed #{pokemon_id}: {e}")

    # Fallback oficial do projeto PokéAPI. Evita que uma indisponibilidade da API
    # transforme a validação em permissiva.
    try:
        pid = str(int(pokemon_id))
        species = next((r for r in _pokeapi_csv('pokemon_species.csv') if r.get('id') == pid), None)
        if not species:
            return None
        egg_names = {r.get('id'): r.get('identifier') for r in _pokeapi_csv('egg_groups.csv')}
        egg_rows = [r for r in _pokeapi_csv('pokemon_egg_groups.csv') if r.get('species_id') == pid]
        egg_groups = [egg_names.get(r.get('egg_group_id')) for r in egg_rows if egg_names.get(r.get('egg_group_id'))]
        is_baby = species.get('is_baby') == '1'
        is_legendary = species.get('is_legendary') == '1'
        is_mythical = species.get('is_mythical') == '1'
        no_eggs = 'no-eggs' in egg_groups
        breedavel = not (is_baby or is_legendary or is_mythical or no_eggs)
        try:
            gender_rate = int(species.get('gender_rate', '0'))
        except (TypeError, ValueError):
            gender_rate = 0
        return {
            'breedavel': breedavel,
            'so_com_ditto': breedavel and gender_rate == -1,
            'gender_rate': gender_rate,
            'egg_groups': egg_groups,
            'nome': species.get('identifier'),
            'is_baby': is_baby,
            'is_legendary': is_legendary,
            'is_mythical': is_mythical,
            'no_eggs': no_eggs,
        }
    except Exception as e:
        print(f"Fallback de regra Breed indisponível para #{pokemon_id}: {e}")
        return None


def regra_breed_pokemon(pokemon_id, pokemon_nome):
    nome = (pokemon_nome or "").strip().lower()
    if nome == "ditto":
        return {
            "breedavel": False, "so_com_ditto": False, "breed_especial": False,
            "motivo": "Ditto é parceiro de Breed e não pode ser solicitado como Pokémon alvo.",
            "egg_groups": ["ditto"], "categoria_bloqueio": "ditto"
        }

    bloqueados = _safe_table("pokemon_bloqueados", "*", ativo=True)
    bloqueio = next((x for x in bloqueados if (x.get("pokemon") or "").strip().lower() == nome), None)
    if bloqueio:
        return {
            "breedavel": False, "so_com_ditto": False, "breed_especial": False,
            "motivo": bloqueio.get("motivo") or "Este Pokémon não está disponível para Breed.",
            "egg_groups": [], "categoria_bloqueio": "manual"
        }

    meta = classificar_pokemon_preco(pokemon_id)
    externa = _pokeapi_species_rule(pokemon_id)
    if not externa:
        # Fail closed: um pedido nunca passa sem a espécie ter sido validada.
        return {
            "breedavel": False, "so_com_ditto": False, "breed_especial": False,
            "motivo": "Não foi possível validar esta espécie agora. Tente novamente em instantes.",
            "egg_groups": [], "categoria_bloqueio": "validacao_indisponivel"
        }

    motivo = None
    categoria = None
    if externa.get('is_baby'):
        motivo, categoria = "Pokémon bebê não pode ser solicitado no Breed.", "baby"
    elif externa.get('is_legendary'):
        motivo, categoria = "Pokémon Lendário não pode ser solicitado no Breed.", "legendary"
    elif externa.get('is_mythical'):
        motivo, categoria = "Pokémon Mítico não pode ser solicitado no Breed.", "mythical"
    elif externa.get('no_eggs') or not externa.get('breedavel'):
        motivo, categoria = "Esta espécie pertence ao Egg Group No Eggs Discovered e não pode breedar.", "no-eggs"

    if motivo:
        return {
            "breedavel": False, "so_com_ditto": False, "breed_especial": False,
            "motivo": motivo, "egg_groups": externa.get("egg_groups") or [],
            "categoria_bloqueio": categoria,
            "is_baby": bool(externa.get('is_baby')),
            "is_legendary": bool(externa.get('is_legendary')),
            "is_mythical": bool(externa.get('is_mythical')),
        }

    so_com_ditto = bool(meta.get("so_com_ditto"))
    return {
        "breedavel": True, "so_com_ditto": so_com_ditto,
        "breed_especial": so_com_ditto, "motivo": None,
        "egg_groups": externa.get("egg_groups", []), "categoria_bloqueio": None,
        "is_baby": False, "is_legendary": False, "is_mythical": False,
        "categoria_preco": meta.get('categoria') or 'comum',
        "categoria_label": meta.get('categoria_label') or 'Comum',
        "classificacao_motivo": meta.get('classificacao_motivo'),
        "classificacao_origem": meta.get('classificacao_origem'),
        "taxa_femea_percentual": meta.get('taxa_femea_percentual'),
    }



def conceder_conquista_se_ausente(usuario_email, titulo, descricao, icone='🏅'):
    if not usuario_email:
        return
    try:
        existente = supabase.table('conquistas_usuario').select('id').eq(
            'usuario_email', usuario_email
        ).eq('titulo', titulo).limit(1).execute().data or []
        if not existente:
            supabase.table('conquistas_usuario').insert({
                'usuario_email': usuario_email,
                'titulo': titulo,
                'descricao': descricao,
                'icone': icone
            }).execute()
    except Exception as e:
        print(f"Conquista não registrada: {e}")


def atualizar_conquistas_breeder(usuario_email):
    try:
        total = len(
            supabase.table('pedidos_breed').select('id').eq(
                'breeder_responsavel', usuario_email
            ).in_('status', ['concluido','entregue']).execute().data or []
        )
        for marco, titulo in [(10,'Breeder Bronze'), (50,'Breeder Prata'), (100,'Breeder Ouro')]:
            if total >= marco:
                conceder_conquista_se_ausente(
                    usuario_email, titulo, f'{marco} Breeds concluídos no Clã HYPE.', '🥚'
                )
    except Exception as e:
        print(f"Falha ao atualizar conquistas do Breeder: {e}")


def criar_notificacao(usuario_email, titulo, mensagem, tipo='info', link=None, discord_dados=None):
    try:
        supabase.table('notificacoes').insert({
            'usuario_email': usuario_email, 'titulo': titulo, 'mensagem': mensagem,
            'tipo': tipo, 'link': link, 'lida': False
        }).execute()
    except Exception as e:
        print(f"Notificação não registrada: {e}")

    # Canal opcional: envia a mesma informação por DM quando o membro vinculou
    # o Discord, habilitou avisos e o servidor possui DISCORD_BOT_TOKEN.
    try:
        bot_token = os.environ.get('DISCORD_BOT_TOKEN', '').strip()
        if not bot_token or not usuario_email:
            return
        rows = supabase.table('usuarios_clan').select('discord_id,discord_notificacoes').eq('email', usuario_email).limit(1).execute().data or []
        if not rows or not rows[0].get('discord_id') or not rows[0].get('discord_notificacoes'):
            return
        discord_id = str(rows[0]['discord_id'])
        headers = {'Authorization': f'Bot {bot_token}', 'Content-Type':'application/json', 'User-Agent':'HYPE-Site/1.0'}
        dm_req = __import__('urllib.request', fromlist=['Request']).Request('https://discord.com/api/v10/users/@me/channels', data=json.dumps({'recipient_id': discord_id}).encode(), headers=headers, method='POST')
        dm = json.loads(urlopen(dm_req, timeout=10).read().decode())
        channel_id = dm.get('id')
        if channel_id:
            # Notificações HYPE em Embed: mantém o conteúdo original, mas com
            # apresentação visual consistente no Discord.
            cores = {
                'success': 0x57F287,
                'sucesso': 0x57F287,
                'warning': 0xFEE75C,
                'aviso': 0xFEE75C,
                'danger': 0xED4245,
                'erro': 0xED4245,
                'error': 0xED4245,
                'info': 0xD4AF37,
            }
            cor = cores.get(str(tipo or 'info').lower(), 0xD4AF37)
            titulo_embed = str(titulo or 'Notificação HYPE')[:256]
            descricao_embed = str(mensagem or 'Você recebeu uma nova notificação no HYPE.')[:4000]

            embed = {
                'title': titulo_embed,
                'description': descricao_embed,
                'color': cor,
                'thumbnail': {'url': 'attachment://emblema_hype_novo.png'},
                'footer': {'text': 'HYPE • Central do Membro'},
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }

            # Cards especiais do HYPE Breed. O Discord não aceita HTML/CSS dentro
            # do Embed, então reproduzimos a referência com cabeçalho, campos,
            # status, Pokémon, preço e instrução operacional organizados.
            if isinstance(discord_dados, dict) and discord_dados.get('categoria') == 'breed':
                status = str(discord_dados.get('status') or '').strip()
                pedido_num = discord_dados.get('pedido_id')
                pokemon = str(discord_dados.get('pokemon') or 'Pokémon').strip()
                breeder = str(discord_dados.get('breeder') or '—').strip()
                valor_breed = discord_dados.get('valor')
                pokemon_id = discord_dados.get('pokemon_id')
                instrucao = str(discord_dados.get('instrucao') or '').strip()

                visuais = {
                    'aguardando_pagamento': ('🟡', 'HYPE BREED • AGUARDANDO PAGAMENTO', 0xF1C40F),
                    'em_producao': ('🥚', 'HYPE BREED • EM PRODUÇÃO', 0x3498DB),
                    'concluido': ('✨', 'HYPE BREED • POKÉMON PRONTO', 0x57F287),
                    'aguardando_confirmacao': ('🤝', 'HYPE BREED • AGUARDANDO CONFIRMAÇÃO', 0x5865F2),
                    'entregue': ('✅', 'HYPE BREED • PEDIDO ENTREGUE', 0x57F287),
                    'cancelado': ('❌', 'HYPE BREED • PEDIDO CANCELADO', 0xED4245),
                }
                icone_status, cabecalho, cor_status = visuais.get(status, ('🥚', 'HYPE BREED', cor))
                embed['author'] = {'name': '🥚 HYPE BREED • Central de Breed'}
                embed['title'] = f"{icone_status} {titulo_embed}"
                embed['color'] = cor_status
                embed['description'] = descricao_embed
                campos = []
                if pedido_num is not None:
                    campos.append({'name': '📋 Pedido', 'value': f'`#{pedido_num}`', 'inline': True})
                campos.append({'name': '🧬 Pokémon', 'value': f'**{pokemon}**', 'inline': True})
                if valor_breed not in (None, ''):
                    campos.append({'name': '🪙 Valor', 'value': f'**{filtro_preco(valor_breed)}**', 'inline': True})
                if breeder and breeder != '—':
                    campos.append({'name': '👤 Breeder', 'value': f'**{breeder}**', 'inline': True})
                campos.append({'name': '📡 Status', 'value': f'**{cabecalho.replace("HYPE BREED • ", "").title()}**', 'inline': True})
                if instrucao:
                    campos.append({'name': '⚡ Próximo passo', 'value': instrucao[:1024], 'inline': False})
                embed['fields'] = campos[:25]
                embed['footer'] = {'text': 'HYPE • Central do Membro • Breed System'}

                # Quando há ID da Pokédex, usa o sprite oficial como imagem do
                # Pokémon e mantém o emblema HYPE anexado no corpo do card.
                try:
                    pid = int(pokemon_id or 0)
                except (TypeError, ValueError):
                    pid = 0
                if pid > 0:
                    embed['thumbnail'] = {'url': f'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{pid}.png'}
                    embed['image'] = {'url': 'attachment://emblema_hype_novo.png'}

                payload_content = f'🥚 **{cabecalho}**'
            else:
                payload_content = '🔔 **Nova atualização HYPE**'

            # Quando a notificação possui destino no site, transforma o título
            # do Embed em um atalho clicável. Links relativos usam a URL atual.
            if link:
                try:
                    destino = str(link).strip()
                    if destino.startswith('/') and has_request_context():
                        destino = request.url_root.rstrip('/') + destino
                    elif destino.startswith('/'):
                        base = os.environ.get('SITE_URL', '').strip().rstrip('/')
                        if base:
                            destino = base + destino
                    if destino.startswith(('http://', 'https://')):
                        embed['url'] = destino
                except Exception:
                    pass

            payload = {
                'content': payload_content,
                'embeds': [embed],
                'allowed_mentions': {'parse': []},
            }
            # Anexa o emblema diretamente à DM. Assim o Discord consegue
            # exibi-lo inclusive quando o HYPE está sendo testado em localhost,
            # sem depender de uma URL pública para a imagem.
            emblema_path = os.path.join(app.root_path, 'static', 'imagens', 'emblema_hype_novo.png')
            if os.path.isfile(emblema_path):
                boundary = '----HYPEDiscordEmbedBoundary7MA4YWxkTrZu0gW'
                payload_json = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                with open(emblema_path, 'rb') as img_file:
                    imagem_bytes = img_file.read()
                partes = [
                    f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json; charset=utf-8\r\n\r\n'.encode('utf-8'),
                    payload_json,
                    b'\r\n',
                    f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="emblema_hype_novo.png"\r\nContent-Type: image/png\r\n\r\n'.encode('utf-8'),
                    imagem_bytes,
                    b'\r\n',
                    f'--{boundary}--\r\n'.encode('utf-8'),
                ]
                multipart_headers = dict(headers)
                multipart_headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
                msg_req = __import__('urllib.request', fromlist=['Request']).Request(
                    f'https://discord.com/api/v10/channels/{channel_id}/messages',
                    data=b''.join(partes),
                    headers=multipart_headers,
                    method='POST'
                )
            else:
                # Fallback seguro: envia o Embed mesmo que a imagem tenha sido
                # removida da pasta static por engano.
                embed.pop('thumbnail', None)
                msg_req = __import__('urllib.request', fromlist=['Request']).Request(
                    f'https://discord.com/api/v10/channels/{channel_id}/messages',
                    data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                    headers=headers,
                    method='POST'
                )
            urlopen(msg_req, timeout=10).read()
    except Exception as e:
        print(f"Aviso Discord não enviado: {e}")


def registrar_transacao_hype(usuario_email, tipo, categoria, descricao, valor, origem_tipo=None, origem_id=None, contraparte_email=None, chave_unica=None):
    """Registra movimentação no extrato HYPE sem bloquear o fluxo principal em caso de falha."""
    if not usuario_email or tipo not in ('entrada', 'saida'):
        return False
    try:
        supabase.table('transacoes_hype').insert({
            'usuario_email': usuario_email,
            'tipo': tipo,
            'categoria': categoria or 'geral',
            'descricao': descricao or 'Movimentação HYPE',
            'valor': max(0, int(valor or 0)),
            'origem_tipo': origem_tipo,
            'origem_id': origem_id,
            'contraparte_email': contraparte_email,
            'criado_por': session.get('usuario_email'),
            'chave_unica': chave_unica
        }).execute()
        return True
    except Exception as e:
        if chave_unica and ('duplicate' in str(e).lower() or 'unique' in str(e).lower()):
            return False
        print(f"Transação HYPE não registrada: {e}")
        return False


# ============================================================================
# ROTAS PRINCIPAIS
# ============================================================================

@app.route('/')
def pagina_inicial():
    """Home pública do Clã Hype com dados reais do Supabase."""
    resumo = {'membros': 0, 'breeds': 0, 'breeders': 0}
    destaques = []
    top_breeders = []
    eventos_home = []
    torneios_home = []

    try:
        usuarios = supabase.table('usuarios_clan').select('email,nick_jogo,cargo').execute().data or []
        membros_hype = _safe_table('membros_hype', 'usuario_email,ativo')
        resumo['membros'] = sum(bool(x.get('ativo')) for x in membros_hype) if membros_hype else len(usuarios)
        resumo['breeders'] = sum(
            1 for u in usuarios
            if u.get('cargo') in ['breeder', 'sub_lider', 'lider']
        )

        pedidos = supabase.table('pedidos_breed').select(
            'pokemon,pokemon_id,status,breeder_responsavel'
        ).in_('status', ['concluido', 'entregue']).execute().data or []
        resumo['breeds'] = len(pedidos)

        contagem = {}
        for pedido in pedidos:
            nome = (pedido.get('pokemon') or '').strip()
            if nome:
                contagem[nome] = contagem.get(nome, 0) + 1

        destaques = sorted(
            contagem.items(),
            key=lambda item: (-item[1], item[0].lower())
        )[:3]

        contagem_breeders = {}
        for pedido in pedidos:
            breeder = pedido.get('breeder_responsavel')
            if breeder:
                contagem_breeders[breeder] = contagem_breeders.get(breeder, 0) + 1
        mapa = {u.get('email'): (u.get('nick_jogo') or u.get('email')) for u in usuarios}
        top_breeders = [
            (mapa.get(email, email), total)
            for email, total in sorted(
                contagem_breeders.items(),
                key=lambda item: (-item[1], (mapa.get(item[0], item[0]) or '').lower())
            )[:5]
        ]
    except Exception as e:
        print(f'Erro ao carregar resumo da Home: {e}')

    try:
        eventos_home = (
            supabase.table('eventos').select('*')
            .eq('publicado', True)
            .order('data_evento')
            .limit(3)
            .execute().data or []
        )
    except Exception as e:
        print(f'Erro ao carregar eventos da Home: {e}')

    try:
        torneios_home = (
            supabase.table('torneios').select('*')
            .eq('publicado', True)
            .order('data_torneio')
            .limit(3)
            .execute().data or []
        )
    except Exception as e:
        print(f'Erro ao carregar torneios da Home: {e}')

    # V18: vitrine dinâmica da Home. Todos os blocos usam dados reais do banco.
    # Se uma área ainda não tiver dados, o template mostra um estado vazio elegante.
    ranking_competitivo_home = []
    try:
        temporadas = _safe_table('temporadas')
        temporada_ativa = next((t for t in temporadas if t.get('ativa')), None)
        if temporada_ativa:
            rows = _safe_table('ranking_temporada', '*', temporada_id=temporada_ativa.get('id'))
            usuarios_rank = {u.get('email'): u for u in _safe_table('usuarios_clan', 'email,nick_jogo,avatar_url')}
            rows = sorted(rows, key=lambda r: (-int(r.get('pontos') or 0), -int(r.get('vitorias') or 0), -int(r.get('podios') or 0)))[:5]
            for r in rows:
                u = usuarios_rank.get(r.get('usuario_email'), {})
                ranking_competitivo_home.append({
                    'nick': u.get('nick_jogo') or r.get('usuario_email'),
                    'avatar_url': u.get('avatar_url'),
                    'pontos': int(r.get('pontos') or 0),
                    'vitorias': int(r.get('vitorias') or 0),
                    'podios': int(r.get('podios') or 0),
                    'temporada': temporada_ativa.get('nome') or 'Temporada atual'
                })
    except Exception as e:
        print(f'Erro ao carregar ranking competitivo da Home: {e}')

    eventos_populares_home = []
    try:
        for evento in eventos_home:
            total = len(_safe_table('inscricoes_evento', 'id', evento_id=evento.get('id')))
            item = dict(evento); item['total_inscritos'] = total
            eventos_populares_home.append(item)
        eventos_populares_home.sort(key=lambda x: -int(x.get('total_inscritos') or 0))
    except Exception as e:
        print(f'Erro ao montar ranking de eventos da Home: {e}')

    torneios_destaques_home = []
    try:
        for torneio in torneios_home:
            item = dict(torneio)
            item['total_inscritos'] = len(_safe_table('inscricoes_torneio', 'id', torneio_id=torneio.get('id')))
            torneios_destaques_home.append(item)
    except Exception as e:
        print(f'Erro ao montar destaques de torneios da Home: {e}')

    noticias_home = [x for x in _safe_table('noticias') if x.get('publicado', True)][:6]
    videos_home = [x for x in _safe_table('videos') if x.get('publicado', True)][:6]
    galeria_home = [x for x in _safe_table('galeria') if x.get('publicado', True)][:8]

    return render_template(
        'index.html',
        resumo=resumo, destaques=destaques, top_breeders=top_breeders,
        eventos_home=eventos_home, torneios_home=torneios_home,
        eventos_populares_home=eventos_populares_home,
        torneios_destaques_home=torneios_destaques_home,
        ranking_competitivo_home=ranking_competitivo_home,
        noticias_home=noticias_home, videos_home=videos_home, galeria_home=galeria_home
    )


@app.route('/login', methods=['POST'])
def login_membro():
    """Processa tanto Login quanto Cadastro do modal da Home."""
    acao = request.form.get('acao')
    email = request.form.get('email', '').strip().lower()
    senha = request.form.get('senha', '').strip()
    nick_jogo = request.form.get('nick_jogo', '').strip()

    if not email or not senha:
        flash('Preencha todos os campos obrigatórios!', 'erro')
        return redirect(url_for('pagina_inicial'))
    if '@' not in email or len(email) > 254:
        flash('Informe um e-mail válido.', 'erro')
        return redirect(url_for('pagina_inicial'))

    # CADASTRO DE NOVO GUERREIRO
    if acao == 'cadastro':
        if not nick_jogo:
            flash('Informe seu Nick no Jogo para se cadastrar.', 'erro')
            return redirect(url_for('pagina_inicial'))
        if len(nick_jogo) < 2 or len(nick_jogo) > 80:
            flash('O Nick deve ter entre 2 e 80 caracteres.', 'erro')
            return redirect(url_for('pagina_inicial'))
        if len(senha) < 8:
            flash('Para novas contas, use uma senha com pelo menos 8 caracteres.', 'erro')
            return redirect(url_for('pagina_inicial'))

        # Verificar se e-mail já existe
        checar_email = supabase.table('usuarios_clan').select('email').eq('email', email).execute()
        if checar_email.data:
            flash('Este e-mail já está cadastrado no Clã!', 'erro')
            return redirect(url_for('pagina_inicial'))

        senha_hash = generate_password_hash(senha)
        
        try:
            supabase.table('usuarios_clan').insert({
                'email': email,
                'senha': senha_hash,
                'nick_jogo': nick_jogo,
                'cargo': 'membro'
            }).execute()

            session.clear()
            session.permanent = True
            session['usuario_email'] = email
            session['nick_jogo'] = nick_jogo
            session['cargo'] = 'membro'

            flash(f'Bem-vindo ao Clã, {nick_jogo}!', 'sucesso')
            return redirect(url_for('painel'))
        except Exception as e:
            print(f'[cadastro] {e}')
            flash('Não foi possível concluir o cadastro agora. Tente novamente.', 'erro')
            return redirect(url_for('pagina_inicial'))

    # LOGIN DE GUERREIRO EXISTENTE
    else:
        minutos = _login_guard_bloqueado(email)
        if minutos:
            flash(f'Muitas tentativas de login. Tente novamente em cerca de {minutos} minuto(s).', 'erro')
            return redirect(url_for('pagina_inicial'))

        res = supabase.table('usuarios_clan').select('*').eq('email', email).execute()
        if not res.data or not check_password_hash(res.data[0]['senha'], senha):
            bloqueio = _login_guard_falha(email)
            if bloqueio:
                flash('Muitas tentativas incorretas. O login nesta origem foi bloqueado por 15 minutos.', 'erro')
            else:
                flash('E-mail ou senha incorretos.', 'erro')
            return redirect(url_for('pagina_inicial'))

        _login_guard_limpar(email)
        usuario = res.data[0]
        session.clear()
        session.permanent = True
        session['usuario_email'] = usuario['email']
        session['nick_jogo'] = usuario['nick_jogo']
        session['cargo'] = usuario['cargo']

        flash(f'Olá novamente, {usuario["nick_jogo"]}!', 'sucesso')
        return redirect(url_for('painel'))


@app.route('/logout', methods=['POST'])
def logout():
    """Encerra a sessão do usuário."""
    session.clear()
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('pagina_inicial'))


@app.route('/painel')
@login_required
def painel():
    email = session.get('usuario_email')
    usr = {}
    try:
        dados = supabase.table('usuarios_clan').select('*').eq('email', email).limit(1).execute().data or []
        usr = dados[0] if dados else {}
    except Exception as e:
        print(f"Erro usuário painel: {e}")

    permissoes = obter_permissoes_usuario(email)
    pode_gerenciar = bool(permissoes.get('pode_gerenciar_cargos', False))
    pedidos = _safe_table('pedidos_breed', '*', usuario_email=email)
    resumo = {
        'pedidos': len(pedidos),
        'pendentes': sum(p.get('status') == 'pendente' for p in pedidos),
        'aguardando_pagamento': sum(p.get('status') == 'aguardando_pagamento' for p in pedidos),
        'andamento': sum(p.get('status') in ('em_producao', 'em_andamento') for p in pedidos),
        'prontos': sum(p.get('status') == 'concluido' for p in pedidos),
        'entregues': sum(p.get('status') == 'entregue' for p in pedidos),
    }
    notificacoes = _safe_table('notificacoes', '*', usuario_email=email)
    notificacoes = sorted(notificacoes, key=lambda x: x.get('created_at') or '', reverse=True)[:8]
    eventos_proximos = _safe_table('eventos', '*', publicado=True)[:4]
    torneios_proximos = _safe_table('torneios', '*', publicado=True)[:4]
    minhas_inscricoes = _safe_table('inscricoes_torneio', '*', usuario_email=email)
    conquistas = sorted(_safe_table('conquistas_usuario', '*', usuario_email=email), key=lambda x: x.get('created_at') or '', reverse=True)
    atividades_perfil = sorted(_safe_table('atividades_perfil', '*', usuario_email=email), key=lambda x: x.get('created_at') or '', reverse=True)[:8]
    xp = int(usr.get('xp') or 0)
    nivel = max(1, int(usr.get('nivel') or 1))
    xp_faixa = xp % 1000
    progresso_xp = min(100, round((xp_faixa / 1000) * 100))
    notificacoes_nao_lidas = sum(not bool(n.get('lida')) for n in _safe_table('notificacoes', '*', usuario_email=email))

    membro_hype_rows = _safe_table('membros_hype', '*', usuario_email=email)
    membro_hype = membro_hype_rows[0] if membro_hype_rows and membro_hype_rows[0].get('ativo') else None

    return render_template('painel.html', usuario=usr, nick_jogo=usr.get('nick_jogo', session.get('nick_jogo')),
        cargo=usr.get('cargo','membro'), pode_gerenciar=pode_gerenciar, permissoes=permissoes,
        resumo=resumo, pedidos=pedidos[:6], notificacoes=notificacoes, eventos_proximos=eventos_proximos,
        torneios_proximos=torneios_proximos, minhas_inscricoes=minhas_inscricoes, membro_hype=membro_hype,
        conquistas=conquistas[:6], atividades_perfil=atividades_perfil, nivel=nivel, xp=xp,
        progresso_xp=progresso_xp, notificacoes_nao_lidas=notificacoes_nao_lidas)


@app.route('/perfil/editar', methods=['POST'])
@login_required
def editar_perfil():
    time_pokemon = [x.strip()[:80] for x in request.form.getlist('pokemon_time') if x.strip()][:6]
    dados = {
        'nome_exibicao': request.form.get('nome_exibicao','').strip()[:80] or None,
        'bio': request.form.get('bio','').strip()[:500] or None,
        'pokemon_favorito': request.form.get('pokemon_favorito','').strip()[:80] or None,
        'pokemon_time': time_pokemon,
        'links_perfil': {
            'discord': request.form.get('discord','').strip()[:120],
            'youtube': request.form.get('youtube','').strip()[:250]
        },
        'privacidade_perfil': {
            'mostrar_atividade': request.form.get('mostrar_atividade') == '1',
            'mostrar_times': request.form.get('mostrar_times') == '1'
        }
    }
    try:
        supabase.table('usuarios_clan').update(dados).eq('email', session['usuario_email']).execute()
        flash('Perfil atualizado!', 'sucesso')
    except Exception as e: flash(f'Erro ao atualizar perfil: {e}', 'erro')
    return redirect(url_for('conta_hype'))


@app.route('/notificacoes/ler', methods=['POST'])
@login_required
def ler_notificacoes():
    try:
        supabase.table('notificacoes').update({'lida': True}).eq('usuario_email', session['usuario_email']).execute()
    except Exception as e: print(e)
    return redirect(url_for('painel'))


@app.route('/perfil/<nick>')
def perfil_publico(nick):
    try:
        dados = supabase.table('usuarios_clan').select('*').ilike('nick_jogo', nick).limit(1).execute().data or []
        if not dados:
            flash('Membro não encontrado.', 'erro')
            return redirect(url_for('pagina_inicial'))
        u = dados[0]
        email = u.get('email')
        # Mantém XP/nível do perfil visitado atualizado, não apenas do usuário logado.
        progressao = _hype_recalcular_progressao(email) if '_hype_recalcular_progressao' in globals() else None
        if progressao:
            u['xp'] = progressao.get('xp', u.get('xp') or 0)
            u['nivel'] = progressao.get('nivel', u.get('nivel') or 1)
        pedidos = _safe_table('pedidos_breed', '*')
        membro = dict(u)
        membro['pedidos_feitos'] = sum(p.get('usuario_email') == email for p in pedidos)
        membro['breeds_concluidos'] = sum(
            p.get('breeder_responsavel') == email and p.get('status') in ('concluido','entregue')
            for p in pedidos
        )
        membro['conquistas'] = sorted(_safe_table('conquistas_usuario', '*', usuario_email=email), key=lambda x: x.get('created_at') or '', reverse=True)
        priv = membro.get('privacidade_perfil') or {}
        membro['mostrar_atividade'] = bool(priv.get('mostrar_atividade', True))
        membro['mostrar_times'] = bool(priv.get('mostrar_times', True))
        membro['atividades'] = sorted(_safe_table('atividades_perfil', '*', usuario_email=email), key=lambda x: x.get('created_at') or '', reverse=True)[:20] if membro['mostrar_atividade'] else []
        viewer_is_owner = session.get('usuario_email') == email
        times_perfil = _safe_table('times_pokemon', '*', usuario_email=email) if membro['mostrar_times'] else []
        # Em perfil público, só times marcados como públicos são expostos. O dono
        # continua vendo os próprios times para conferir como o perfil está montado.
        if not viewer_is_owner:
            times_perfil = [t for t in times_perfil if bool(t.get('publico')) and str(t.get('moderacao_status') or 'visivel') != 'oculto']
        membro['times_salvos'] = sorted(times_perfil, key=lambda x: x.get('updated_at') or x.get('created_at') or '', reverse=True)[:6]
        membro['viewer_is_owner'] = viewer_is_owner
        xp_atual = int(membro.get('xp') or 0)
        membro['xp_progresso'] = min(100, round((xp_atual % 1000) / 10, 1))
        membro['xp_para_proximo'] = 1000 - (xp_atual % 1000) if xp_atual % 1000 else 1000
        links = membro.get('links_perfil') or {}
        youtube = str(links.get('youtube') or '').strip()
        if youtube and not youtube.lower().startswith(('http://','https://')):
            links['youtube'] = ''
        membro['links_perfil'] = links
        mh = _safe_table('membros_hype', '*', usuario_email=email)
        membro['membro_hype'] = bool(mh and mh[0].get('ativo'))
        membro['membro_hype_desde'] = mh[0].get('entrou_em') if membro['membro_hype'] else None
        seguidores = _safe_table('comunidade_seguidores', 'seguidor_email', seguido_email=email)
        seguindo = _safe_table('comunidade_seguidores', 'seguido_email', seguidor_email=email)
        membro['seguidores_total'] = len(seguidores)
        membro['seguindo_total'] = len(seguindo)
        viewer_email = session.get('usuario_email')
        membro['viewer_seguindo'] = bool(viewer_email and viewer_email != email and _safe_table('comunidade_seguidores', 'seguido_email', seguidor_email=viewer_email, seguido_email=email))
        return render_template('perfil.html', membro=membro)
    except Exception as e:
        print(f'Erro perfil: {e}')
        flash('Não foi possível abrir este perfil.', 'erro')
        return redirect(url_for('pagina_inicial'))



@app.context_processor
def hype_account_context():
    """Dados leves da conta usados no cabeçalho HYPE."""
    if not session.get('usuario_email'):
        return {'hype_header_user': {}, 'hype_notificacoes_nao_lidas': 0, 'hype_permissoes': {}, 'hype_membro_hype': False}
    email = session.get('usuario_email')
    usuario = {}
    try:
        rows = supabase.table('usuarios_clan').select('nick_jogo,nome_exibicao,avatar_url,cargo').eq('email', email).limit(1).execute().data or []
        usuario = rows[0] if rows else {}
    except Exception:
        usuario = {'nick_jogo': session.get('nick_jogo'), 'cargo': session.get('cargo')}
    try:
        rows = supabase.table('notificacoes').select('id').eq('usuario_email', email).eq('lida', False).execute().data or []
        unread = len(rows)
    except Exception:
        unread = 0
    try:
        hype_permissoes = obter_permissoes_usuario(email)
    except Exception:
        hype_permissoes = {}
    try:
        hype_membro_hype = membro_hype_ativo(email)
    except Exception:
        hype_membro_hype = False
    return {
        'hype_header_user': usuario,
        'hype_notificacoes_nao_lidas': unread,
        'hype_permissoes': hype_permissoes,
        'hype_membro_hype': hype_membro_hype
    }


@app.route('/conta')
@login_required
def conta_hype():
    email = session['usuario_email']
    rows = _safe_table('usuarios_clan', '*', email=email)
    usuario = rows[0] if rows else {}
    mh = _safe_table('membros_hype', '*', usuario_email=email)
    membro_hype = mh[0] if mh and mh[0].get('ativo') else None
    conquistas = sorted(_safe_table('conquistas_usuario', '*', usuario_email=email), key=lambda x: x.get('created_at') or '', reverse=True)[:6]
    return render_template('conta.html', usuario=usuario, membro_hype=membro_hype, conquistas=conquistas)


@app.route('/notificacoes')
@login_required
def central_notificacoes():
    email = session['usuario_email']
    notificacoes = sorted(_safe_table('notificacoes', '*', usuario_email=email), key=lambda x: x.get('created_at') or '', reverse=True)
    return render_template('notificacoes.html', notificacoes=notificacoes)


@app.route('/notificacoes/<int:notificacao_id>/ler', methods=['POST'])
@login_required
def ler_notificacao(notificacao_id):
    try:
        supabase.table('notificacoes').update({'lida': True}).eq('id', notificacao_id).eq('usuario_email', session['usuario_email']).execute()
    except Exception as e:
        print(f'Erro ao ler notificacao: {e}')
    destino = request.form.get('destino', '').strip()
    return redirect(destino if destino.startswith('/') else url_for('central_notificacoes'))


@app.route('/discord/conectar')
@login_required
def discord_conectar():
    client_id = os.environ.get('DISCORD_CLIENT_ID', '').strip()
    redirect_uri = os.environ.get('DISCORD_REDIRECT_URI', '').strip() or url_for('discord_callback', _external=True)
    if not client_id:
        flash('Integração Discord ainda não foi configurada pelo administrador.', 'info')
        return redirect(url_for('conta_hype') + '#discord')
    state = uuid4().hex
    session['discord_oauth_state'] = state
    params = urlencode({'client_id': client_id, 'response_type': 'code', 'redirect_uri': redirect_uri, 'scope': 'identify', 'state': state, 'prompt': 'consent'})
    return redirect('https://discord.com/oauth2/authorize?' + params)


@app.route('/discord/callback')
@login_required
def discord_callback():
    if request.args.get('state') != session.pop('discord_oauth_state', None):
        flash('Não foi possível validar a conexão com o Discord.', 'erro')
        return redirect(url_for('conta_hype') + '#discord')
    code = request.args.get('code', '').strip()
    client_id = os.environ.get('DISCORD_CLIENT_ID', '').strip()
    client_secret = os.environ.get('DISCORD_CLIENT_SECRET', '').strip()
    redirect_uri = os.environ.get('DISCORD_REDIRECT_URI', '').strip() or url_for('discord_callback', _external=True)
    if not code or not client_id or not client_secret:
        flash('Configuração do Discord incompleta.', 'erro')
        return redirect(url_for('conta_hype') + '#discord')
    try:
        token_body = urlencode({'client_id': client_id, 'client_secret': client_secret, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri}).encode()
        req = __import__('urllib.request', fromlist=['Request']).Request('https://discord.com/api/oauth2/token', data=token_body, headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'HYPE-Site/1.0'})
        token = json.loads(urlopen(req, timeout=12).read().decode())
        access_token = token.get('access_token')
        req_user = __import__('urllib.request', fromlist=['Request']).Request('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {access_token}', 'User-Agent':'HYPE-Site/1.0'})
        du = json.loads(urlopen(req_user, timeout=12).read().decode())
        did = str(du.get('id') or '')
        if not did:
            raise ValueError('Discord não retornou o ID do usuário.')
        avatar = du.get('avatar')
        avatar_url = f'https://cdn.discordapp.com/avatars/{did}/{avatar}.png?size=128' if avatar else None
        supabase.table('usuarios_clan').update({'discord_id': did, 'discord_username': du.get('global_name') or du.get('username'), 'discord_avatar_url': avatar_url, 'discord_conectado_em': agora_iso()}).eq('email', session['usuario_email']).execute()
        flash('Discord conectado à sua conta HYPE!', 'sucesso')
    except Exception as e:
        print(f'Erro Discord OAuth: {e}')
        flash('Não foi possível conectar o Discord. Verifique a configuração do aplicativo Discord.', 'erro')
    return redirect(url_for('conta_hype') + '#discord')


@app.route('/discord/desconectar', methods=['POST'])
@login_required
def discord_desconectar():
    try:
        supabase.table('usuarios_clan').update({'discord_id': None, 'discord_username': None, 'discord_avatar_url': None, 'discord_conectado_em': None, 'discord_notificacoes': False}).eq('email', session['usuario_email']).execute()
        flash('Discord desconectado da conta HYPE.', 'sucesso')
    except Exception as e:
        flash(f'Não foi possível desconectar o Discord: {e}', 'erro')
    return redirect(url_for('conta_hype') + '#discord')


@app.route('/discord/notificacoes', methods=['POST'])
@login_required
def discord_notificacoes():
    ativo = request.form.get('ativo') == '1'
    try:
        supabase.table('usuarios_clan').update({'discord_notificacoes': ativo}).eq('email', session['usuario_email']).execute()
        flash('Preferência de notificações do Discord atualizada.', 'sucesso')
    except Exception as e:
        flash(f'Não foi possível atualizar a preferência: {e}', 'erro')
    return redirect(url_for('conta_hype') + '#discord')

# ============================================================================
# ROTAS DO BERÇÁRIO (SISTEMA DE BREED UPGRADED) 🌟
# ============================================================================

NATURES_VALIDAS = {
    'Hardy', 'Lonely', 'Brave', 'Adamant', 'Naughty',
    'Bold', 'Docile', 'Relaxed', 'Impish', 'Lax',
    'Timid', 'Hasty', 'Serious', 'Jolly', 'Naive',
    'Modest', 'Mild', 'Quiet', 'Bashful', 'Rash',
    'Calm', 'Gentle', 'Sassy', 'Careful', 'Quirky'
}

IVS_F5_VALIDOS = {
    'hp', 'ataque', 'defesa', 'ataque_especial',
    'defesa_especial', 'velocidade'
}


def montar_ranking_breed(pedidos):
    """Agrupa os pedidos por Pokémon e calcula os dados mais pedidos."""
    from collections import Counter, defaultdict

    grupos = defaultdict(list)
    for pedido in pedidos:
        pokemon = (pedido.get('pokemon') or '').strip()
        if pokemon:
            grupos[pokemon.lower()].append(pedido)

    ranking = []
    for _, itens in grupos.items():
        primeiro = itens[0]
        nome = primeiro.get('pokemon') or 'Pokémon'

        def mais_comum(campo, padrao='—'):
            valores = [
                str(p.get(campo)).strip()
                for p in itens
                if p.get(campo) not in (None, '', 'None')
            ]
            return Counter(valores).most_common(1)[0][0] if valores else padrao

        ha_val = mais_comum('ha', '—')
        if ha_val == 'True':
            ha_val = 'Sim'
        elif ha_val == 'False':
            ha_val = 'Não'

        ranking.append({
            'pokemon': nome,
            'pokemon_id': primeiro.get('pokemon_id'),
            'total': len(itens),
            'nature': mais_comum('nature'),
            'breed_tipo': mais_comum('breed_tipo'),
            'iv_descartado': mais_comum('iv_descartado'),
            'ha': ha_val,
            'genero': mais_comum('genero')
        })

    ranking.sort(key=lambda item: (-item['total'], item['pokemon'].lower()))
    return ranking


@app.route('/breed', methods=['GET', 'POST'])
@login_required
def breed():
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if request.method == 'POST':
        if not permissoes or not permissoes.get('pode_fazer_pedido_breed', False):
            flash('Seu cargo não possui permissão para solicitar breeds.', 'erro')
            return redirect(url_for('breed'))

        pokemon = request.form.get('pokemon', '').strip()
        pokemon_id_raw = request.form.get('pokemon_id', '').strip()
        nature = request.form.get('nature', '').strip()
        ha = request.form.get('ha', '').strip().lower()
        genero = request.form.get('genero', '').strip().lower()
        breed_tipo = request.form.get('breed_tipo', '').strip().upper()
        iv_descartado = request.form.get('iv_descartado', '').strip().lower()
        zero_speed = request.form.get('zero_speed') == 'sim'
        treinado = request.form.get('treinado') == 'sim'
        cupom_breed = request.form.get('cupom_breed', '').strip().upper()
        modo_pedido = 'personalizado' if breed_tipo == 'PERSONALIZADO' else 'normal'
        ivs_personalizados = {}
        if modo_pedido == 'personalizado':
            iv_map = {
                'hp':'custom_iv_hp','attack':'custom_iv_attack','defense':'custom_iv_defense',
                'sp_attack':'custom_iv_sp_attack','sp_defense':'custom_iv_sp_defense','speed':'custom_iv_speed'
            }
            try:
                for iv_key, field in iv_map.items():
                    raw = (request.form.get(field, '') or '').strip()
                    if raw == '':
                        raise ValueError
                    value = int(raw)
                    if value < 0 or value > 31:
                        raise ValueError
                    ivs_personalizados[iv_key] = value
            except (TypeError, ValueError):
                flash('No modo Hidden Power Ability, informe todos os 6 IVs entre 0 e 31.', 'erro')
                return redirect(url_for('breed'))

        ev_keys = ('hp', 'attack', 'defense', 'sp_attack', 'sp_defense', 'speed')
        evs_treinamento = {}
        if treinado:
            try:
                for ev_key in ev_keys:
                    raw = (request.form.get(f'ev_{ev_key}', '0') or '0').strip()
                    value = int(raw)
                    if value < 0 or value > 252:
                        raise ValueError
                    evs_treinamento[ev_key] = value
                if sum(evs_treinamento.values()) > 510:
                    flash('O treinamento ultrapassa o limite de 510 EVs.', 'erro')
                    return redirect(url_for('breed'))
            except (TypeError, ValueError):
                flash('EVs inválidos. Cada atributo deve ficar entre 0 e 252.', 'erro')
                return redirect(url_for('breed'))

        if not pokemon or not pokemon_id_raw or not ha or not genero or not breed_tipo:
            flash('Preencha Pokémon, HA, Gênero e Breed.', 'erro')
            return redirect(url_for('breed'))

        try:
            pokemon_id = int(pokemon_id_raw)
            if pokemon_id <= 0:
                raise ValueError
        except ValueError:
            flash('Selecione um Pokémon válido pela caixa de pesquisa.', 'erro')
            return redirect(url_for('breed'))

        if nature and nature not in NATURES_VALIDAS:
            flash('Selecione uma Nature válida ou deixe Sem Nature.', 'erro')
            return redirect(url_for('breed'))

        if ha not in ('sim', 'nao'):
            flash('Selecione HA: Sim ou Não.', 'erro')
            return redirect(url_for('breed'))

        if genero not in ('macho', 'femea', 'indiferente'):
            flash('Selecione Macho, Fêmea ou Indiferente.', 'erro')
            return redirect(url_for('breed'))

        if breed_tipo not in ('F5', 'F6', 'PERSONALIZADO'):
            flash('Selecione F5, F6 ou Hidden Power Ability.', 'erro')
            return redirect(url_for('breed'))

        if breed_tipo == 'F5':
            if iv_descartado not in IVS_F5_VALIDOS:
                flash('No F5, escolha qual IV não precisa.', 'erro')
                return redirect(url_for('breed'))
            if zero_speed and iv_descartado == 'velocidade':
                flash('Com Zero Speed, a Velocidade já ficará em 0 IV. Escolha outro IV que pode ficar menor.', 'erro')
                return redirect(url_for('breed'))
        elif breed_tipo == 'PERSONALIZADO':
            iv_descartado = None
            zero_speed = False
        else:
            iv_descartado = None
            zero_speed = False

        # Validação real do Pokémon + anti-spam.
        regra = regra_breed_pokemon(pokemon_id, pokemon)
        if not regra.get('breedavel'):
            flash(regra.get('motivo') or 'Este Pokémon não está disponível para Breed.', 'erro')
            return redirect(url_for('breed'))

        recentes = supabase.table('pedidos_breed').select('created_at').eq(
            'usuario_email', email
        ).order('created_at', desc=True).limit(1).execute().data or []
        if recentes:
            ultima = parse_data_supabase(recentes[0].get('created_at'))
            if ultima and datetime.now(timezone.utc) - ultima < timedelta(minutes=2):
                flash('Aguarde 2 minutos antes de enviar outro pedido de Breed.', 'erro')
                return redirect(url_for('breed'))

        # Impede duplicação de pedido ativo, mesmo com refresh/duplo clique.
        try:
            ativos_usuario = supabase.table('pedidos_breed').select('*').eq(
                'usuario_email', email
            ).in_('status', [
                'pendente','aguardando_pagamento','em_producao','cancelamento_solicitado'
            ]).execute().data or []
        except Exception as e:
            print(f'[breed] Não foi possível verificar duplicados: {type(e).__name__}: {e}')
            ativos_usuario = []
        duplicado = any(
            int(x.get('pokemon_id') or 0) == pokemon_id
            and (x.get('nature') or '') == (nature or '')
            and bool(x.get('ha')) == (ha == 'sim')
            and (x.get('genero') or '') == genero
            and (x.get('breed_tipo') or '') == breed_tipo
            and (x.get('iv_descartado') or '') == (iv_descartado or '')
            and bool(x.get('zero_speed')) == bool(zero_speed)
            and bool(x.get('treinado')) == bool(treinado)
            and (x.get('evs_treinamento') or {}) == (evs_treinamento if treinado else {})
            and (x.get('ivs_personalizados') or {}) == (ivs_personalizados if modo_pedido == 'personalizado' else {})
            for x in ativos_usuario
        )
        if duplicado:
            flash('Você já possui um pedido idêntico pendente ou em andamento.', 'erro')
            return redirect(url_for('breed'))

        meta = classificar_pokemon_preco(pokemon_id)
        categoria = (meta.get('categoria') or 'comum').lower()
        if categoria not in BREED_CATEGORIAS_PRECO:
            categoria = 'comum'

        # Ditto nunca é escolha do cliente. Pela regra V31.3, toda espécie que
        # depende efetivamente de Ditto é Ultra Rara e não recebe dupla cobrança.
        usa_ditto = bool(regra.get('so_com_ditto'))
        if usa_ditto:
            categoria = 'ultra_raro'
        preco_total, preco_detalhes = calcular_preco_breed(
            breed_tipo,
            ha=(ha == 'sim'),
            genero=genero,
            categoria=categoria,
            usa_ditto=usa_ditto,
            treinado=treinado,
            nature=nature or None,
            zero_speed=zero_speed,
            pokemon_id=pokemon_id,
            usuario_email=email,
            codigo_cupom=cupom_breed
        )
        # Congela também o motivo da classificação V31.3 dentro do pedido.
        preco_detalhes['classificacao_raridade'] = {
            'categoria': categoria,
            'label': meta.get('categoria_label') or BREED_CATEGORIA_LABELS.get(categoria, 'Comum'),
            'origem': meta.get('classificacao_origem'),
            'motivo': meta.get('classificacao_motivo'),
            'taxa_femea_percentual': meta.get('taxa_femea_percentual'),
            'so_com_ditto': bool(usa_ditto),
        }
        if cupom_breed and preco_detalhes.get('pricing_v2') and preco_detalhes.get('cupom_valido') is False:
            flash('Cupom inválido, expirado ou indisponível para sua conta.', 'erro')
            return redirect(url_for('breed'))
        if preco_total <= 0:
            flash('Não foi possível calcular o preço. Verifique a tabela de preços no painel administrativo.', 'erro')
            return redirect(url_for('breed'))

        try:
            taxa_pct, taxa_valor, valor_breeder = calcular_divisao_breed(preco_total)
            dados_pedido = {
                'usuario_email': email,
                'player': session.get('nick_jogo'),
                'pokemon': pokemon,
                'pokemon_id': pokemon_id,
                'nature': nature or None,
                'ha': ha == 'sim',
                'genero': genero,
                'breed_tipo': breed_tipo,
                'modo_pedido': modo_pedido,
                'ivs_personalizados': ivs_personalizados if modo_pedido == 'personalizado' else {},
                'iv_descartado': iv_descartado,
                'zero_speed': zero_speed,
                'categoria_preco': categoria,
                'usa_ditto': usa_ditto,
                'breed_especial': bool(usa_ditto),
                'hpwr': False,
                'treinado': treinado,
                'evs_treinamento': evs_treinamento if treinado else {},
                'preco_total': preco_total,
                'taxa_clan_percentual': taxa_pct,
                'taxa_clan_valor': taxa_valor,
                'valor_breeder': valor_breeder,
                'preco_original': int(preco_detalhes.get('preco_original') or preco_total),
                'promocao_id': preco_detalhes.get('promocao_id'),
                'promocao_nome': preco_detalhes.get('promocao_nome'),
                'promocao_percentual': preco_detalhes.get('promocao_percentual') or 0,
                'tabela_preco_id': preco_detalhes.get('tabela_preco_id'),
                'cupom_codigo': preco_detalhes.get('cupom_codigo'),
                'preco_detalhes': preco_detalhes,
                # Mantidos por compatibilidade com pedidos/estrutura antigos.
                'ability': 'HA' if ha == 'sim' else 'Sem HA',
                'nao_precisa': iv_descartado if breed_tipo == 'F5' else None,
                'status': 'pendente'
            }

            # V14.7.2: compatibilidade com bancos que ainda não receberam a coluna
            # evs_treinamento. O pedido não pode deixar de ser criado por causa de
            # uma migração opcional/atrasada. Quando a coluna existir, os EVs são
            # persistidos normalmente; em schema antigo, repete o INSERT sem ela.
            try:
                resultado_insert = supabase.table('pedidos_breed').insert(dados_pedido).execute()
            except Exception as insert_error:
                erro_txt = str(insert_error)
                opcionais = ('evs_treinamento','tabela_preco_id','cupom_codigo','modo_pedido','ivs_personalizados')
                if ('PGRST204' in erro_txt or 'schema cache' in erro_txt.lower()) and any(c in erro_txt for c in opcionais):
                    dados_compat = dict(dados_pedido)
                    for coluna in opcionais:
                        if coluna in erro_txt:
                            dados_compat.pop(coluna, None)
                    resultado_insert = supabase.table('pedidos_breed').insert(dados_compat).execute()
                else:
                    raise

            # Uso de cupom é contabilizado somente depois de o pedido existir.
            if preco_detalhes.get('cupom_aplicado') and preco_detalhes.get('cupom_id'):
                try:
                    cupom_id = preco_detalhes.get('cupom_id')
                    promo_rows = _safe_table('promocoes_breed','*',id=cupom_id)
                    if promo_rows and promo_rows[0].get('codigo_cupom'):
                        atual = int(promo_rows[0].get('usos') or 0)
                        limite = promo_rows[0].get('limite_usos')
                        if limite in (None, '') or atual < int(limite):
                            supabase.table('promocoes_breed').update({'usos':atual+1,'updated_at':agora_iso()}).eq('id',cupom_id).execute()
                except Exception as exc:
                    print(f'[V31.2 cupom] Falha ao contabilizar uso: {exc}')

            registrar_atividade_reino('breed_criado', email, f"Pedido de Breed: {pokemon}", 'breed')
            especial_txt = ' • BREED ESPECIAL COM DITTO' if usa_ditto else ''
            flash((f'Pedido enviado! Valor calculado: ${preco_total:,}{especial_txt}. Acompanhe o progresso em Meus Pedidos. ⏳').replace(',', '.'), 'sucesso')
        except Exception as e:
            flash(f'Erro ao registrar pedido: {e}', 'erro')

        return redirect(url_for('breed'))

    # V21: Fazer Pedido é uma experiência independente. Nesta rota não carregamos
    # mais a fila geral nem o histórico; isso reduz consultas e evita misturar as
    # três áreas oficiais do Breed: Fazer Pedido / Meus Pedidos / Fila dos Breeders.
    try:
        # Mantém somente a verificação operacional de prazo. O pedido permanece com
        # o mesmo Breeder e recebe sinalização de atraso depois de 3 dias em produção.
        res_verificacao = supabase.table('pedidos_breed').select('*').eq('status', 'em_producao').execute()
        if res_verificacao and res_verificacao.data:
            agora = datetime.now(timezone.utc)
            for pedido in res_verificacao.data:
                data_referencia = parse_data_supabase(
                    pedido.get('pagamento_confirmado_em') or pedido.get('assumido_em') or pedido.get('created_at')
                )
                try:
                    if data_referencia and agora - data_referencia > timedelta(days=3) and not pedido.get('prazo_notificado'):
                        supabase.table('pedidos_breed').update({'prazo_notificado': True}).eq('id', pedido['id']).execute()
                        criar_notificacao(
                            pedido.get('breeder_responsavel'), 'Prazo do Breed excedido',
                            f"O pedido #{pedido.get('id')} de {pedido.get('pokemon')} passou de 3 dias.",
                            'aviso', url_for('breed_fila_breeders')
                        )
                        criar_notificacao(
                            pedido.get('usuario_email'), 'Atualização do seu Breed',
                            f"Seu pedido #{pedido.get('id')} passou do prazo de 3 dias e a equipe foi avisada.",
                            'aviso', url_for('breed_meus_pedidos')
                        )
                except Exception as err_date:
                    print(f"Erro ao processar data do pedido {pedido.get('id')}: {err_date}")
    except Exception as e:
        print(f"Erro ao verificar prazos do Breed: {e}")

    return render_template(
        'breed.html',
        permissoes=permissoes,
        precos_ui=precos_breed_interface()
    )



@app.route('/breed/meus-pedidos')
@login_required
def breed_meus_pedidos():
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    try:
        pedidos = supabase.table('pedidos_breed').select('*').eq(
            'usuario_email', email
        ).order('created_at', desc=True).execute().data or []
    except Exception as e:
        print(f'Erro ao buscar meus pedidos de Breed: {e}')
        pedidos = []
    pedidos = enriquecer_pedidos_com_nicks(pedidos)
    # V14.8: indicadores de chat e avaliação diretamente em Meus Pedidos.
    ids = [p.get('id') for p in pedidos if p.get('id') is not None]
    nao_lidas = {}
    avaliados = set()
    if ids:
        try:
            msgs = supabase.table('mensagens_pedido').select('pedido_id,remetente_email,lida').eq('tipo_pedido','breed').in_('pedido_id', ids).execute().data or []
            for m in msgs:
                if not m.get('lida') and m.get('remetente_email') != email:
                    pid = m.get('pedido_id'); nao_lidas[pid] = nao_lidas.get(pid, 0) + 1
        except Exception as e:
            print(f'Erro ao contar mensagens Breed: {e}')
        try:
            avs = supabase.table('avaliacoes').select('pedido_id').eq('tipo_pedido','breed').eq('avaliador_email',email).in_('pedido_id', ids).execute().data or []
            avaliados = {a.get('pedido_id') for a in avs}
        except Exception as e:
            print(f'Erro ao buscar avaliações Breed: {e}')
    historicos = {}
    if ids:
        try:
            hs = supabase.table('historico_pedidos').select('*').eq('tipo_pedido','breed').in_('pedido_id', ids).order('created_at', desc=False).execute().data or []
            for h in hs: historicos.setdefault(h.get('pedido_id'), []).append(h)
        except Exception as e: print(f'Erro ao buscar histórico Breed: {e}')
    for pedido in pedidos:
        pedido['mensagens_nao_lidas'] = nao_lidas.get(pedido.get('id'), 0)
        pedido['ja_avaliado'] = pedido.get('id') in avaliados
        pedido['historico_status'] = historicos.get(pedido.get('id'), [])
        base = pedido.get('entregue_em') or pedido.get('concluido_em') or pedido.get('pagamento_confirmado_em') or pedido.get('assumido_em') or pedido.get('created_at')
        pedido['atualizado_em'] = base
    ativos = [p for p in pedidos if p.get('status') in ('pendente','aguardando_pagamento','em_producao','cancelamento_solicitado','concluido','aguardando_confirmacao')]
    historico = [p for p in pedidos if p.get('status') in ('entregue','cancelado')]
    resumo = {
        'ativos': len(ativos),
        'pagamento': sum(1 for p in ativos if p.get('status') == 'aguardando_pagamento'),
        'producao': sum(1 for p in ativos if p.get('status') in ('em_producao','cancelamento_solicitado')),
        'prontos': sum(1 for p in ativos if p.get('status') in ('concluido','aguardando_confirmacao')),
        'historico': len(historico),
        'total': len(pedidos),
    }
    return render_template('breed_meus_pedidos.html', pedidos_ativos=ativos, historico=historico, permissoes=permissoes, resumo=resumo)


@app.route('/breed/historico')
@login_required
def breed_historico_geral():
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    try:
        pedidos = supabase.table('pedidos_breed').select('*').eq('status','entregue').order('entregue_em', desc=True).limit(300).execute().data or []
    except Exception as e:
        print(f'Erro ao buscar histórico geral do Breed: {e}')
        pedidos = []
    pedidos = enriquecer_pedidos_com_nicks(pedidos)
    return render_template('breed_historico.html', pedidos=pedidos, permissoes=permissoes, usuario_email=email)


def listar_breeders_transferencia():
    """Usuários que podem receber transferência administrativa de pedidos Breed."""
    usuarios = _safe_table('usuarios_clan', 'email,nick_jogo,cargo')
    funcoes = _safe_table('usuarios_funcoes', 'usuario_email,funcao')
    extras = {x.get('usuario_email') for x in funcoes if x.get('funcao') == 'breeder'}
    perfis = {x.get('usuario_email'): x for x in _safe_table('breeders_perfil', '*')}
    saida = []
    for u in usuarios:
        email = u.get('email')
        if not email:
            continue
        if u.get('cargo') not in ('breeder','sub_lider','lider') and email not in extras:
            continue
        perfil = perfis.get(email) or {}
        saida.append({
            'email': email, 'nick': u.get('nick_jogo') or email, 'cargo': u.get('cargo') or 'membro',
            'status': perfil.get('status') or 'disponivel', 'max_ativos': int(perfil.get('max_ativos') or 4)
        })
    saida.sort(key=lambda x: (x.get('nick') or '').lower())
    return saida


@app.route('/breed/fila')
@login_required
def breed_fila_breeders():
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    if not permissoes.get('pode_ver_fila_breed', False):
        flash('A Fila dos Breeders é exclusiva para usuários autorizados.', 'erro')
        return redirect(url_for('breed_meus_pedidos'))

    # Estados exibidos na fila. Mantemos os dois nomes legados para que
    # instalações antigas continuem filtrando corretamente.
    status_fila = [
        'pendente','em_andamento','aguardando_pagamento','em_producao',
        'cancelamento_solicitado','concluido','aguardando_confirmacao',
        'aguardando_confirmacao_cliente'
    ]
    try:
        pedidos = supabase.table('pedidos_breed').select('*').in_(
            'status', status_fila
        ).order('created_at', desc=False).execute().data or []
    except Exception as e:
        print(f'Erro ao buscar fila dos Breeders: {e}')
        pedidos = []
    pedidos = enriquecer_pedidos_com_nicks(pedidos)

    # Indicadores usados pelo layout oficial da Fila dos Breeders.
    contagens_fila = {s: 0 for s in status_fila}
    for p in pedidos:
        st = p.get('status')
        if st in contagens_fila:
            contagens_fila[st] += 1
    contagens_fila['todos'] = len(pedidos)
    contagens_fila['meus'] = sum(1 for p in pedidos if p.get('breeder_responsavel') == email)

    resumo_fila = {
        'total': len(pedidos),
        'pendentes': contagens_fila.get('pendente', 0),
        'em_andamento': sum(contagens_fila.get(x, 0) for x in (
            'em_andamento','aguardando_pagamento','em_producao','cancelamento_solicitado'
        )),
        'concluidos': sum(contagens_fila.get(x, 0) for x in (
            'concluido','aguardando_confirmacao','aguardando_confirmacao_cliente'
        )),
        'entregues': 0,
    }
    try:
        status_rows = supabase.table('pedidos_breed').select('status').execute().data or []
        resumo_fila['entregues'] = sum(1 for x in status_rows if x.get('status') == 'entregue')
    except Exception as e:
        print(f'Erro ao montar resumo geral da fila: {e}')

    # Mensagens não lidas e sinalização de atraso também na fila operacional.
    ids = [p.get('id') for p in pedidos if p.get('id') is not None]
    nao_lidas = {}
    if ids:
        try:
            msgs = supabase.table('mensagens_pedido').select(
                'pedido_id,remetente_email,lida'
            ).eq('tipo_pedido','breed').in_('pedido_id',ids).execute().data or []
            for m in msgs:
                if not m.get('lida') and m.get('remetente_email') != email:
                    pid = m.get('pedido_id')
                    nao_lidas[pid] = nao_lidas.get(pid,0) + 1
        except Exception as e:
            print(f'Erro ao contar mensagens da fila: {e}')
    for p in pedidos:
        p['mensagens_nao_lidas'] = nao_lidas.get(p.get('id'),0)
        inicio = parse_data_supabase(p.get('pagamento_confirmado_em') or p.get('assumido_em'))
        p['atrasado'] = bool(
            inicio
            and p.get('status') in ('aguardando_pagamento','em_producao','cancelamento_solicitado')
            and (datetime.now(timezone.utc)-inicio).total_seconds() > 3*86400
        )

    meus_ativos = sum(
        1 for p in pedidos
        if p.get('breeder_responsavel') == email
        and p.get('status') in ('aguardando_pagamento','em_producao','cancelamento_solicitado')
    )
    max_ativos = 4
    status_breeder = 'disponivel'
    try:
        perfil = supabase.table('breeders_perfil').select(
            'max_ativos,status'
        ).eq('usuario_email', email).limit(1).execute().data or []
        if perfil and perfil[0].get('max_ativos') is not None:
            max_ativos = int(perfil[0]['max_ativos'])
        # disponibilidade_funcoes é a fonte operacional principal; breeders_perfil
        # continua sincronizado por compatibilidade com versões anteriores.
        disp = supabase.table('disponibilidade_funcoes').select('status').eq(
            'usuario_email', email
        ).eq('funcao','breeder').limit(1).execute().data or []
        status_breeder = (
            (disp[0].get('status') if disp else None)
            or (perfil[0].get('status') if perfil else None)
            or 'disponivel'
        )
        if status_breeder == 'ausente':
            status_breeder = 'indisponivel'
    except Exception as e:
        print(f'Erro ao buscar limite/status do Breeder: {e}')

    # V23: todos os pedidos operacionais são enviados para a página e os filtros
    # atuam instantaneamente no navegador. O parâmetro ?filtro= continua sendo
    # aceito para abrir a tela já posicionada no filtro escolhido.
    filtro_atual = (request.args.get('filtro') or 'todos').strip().lower()
    filtros_validos = {'todos','pendente','em_andamento','concluido','meus'}
    if filtro_atual not in filtros_validos:
        filtro_atual = 'todos'

    # Histórico cancelado continua disponível, porém recolhido no fim da página.
    try:
        historico_cancelados = supabase.table('pedidos_breed').select('*').eq(
            'status','cancelado'
        ).order('created_at', desc=True).limit(100).execute().data or []
    except Exception as e:
        print(f'Erro ao buscar histórico cancelado da fila: {e}')
        historico_cancelados = []
    historico_cancelados = enriquecer_pedidos_com_nicks(historico_cancelados)

    return render_template(
        'breed_fila.html',
        fila_ativa=pedidos,
        filtro_atual=filtro_atual,
        historico_cancelados=historico_cancelados,
        permissoes=permissoes,
        breeder_email=email,
        meus_ativos=meus_ativos,
        max_ativos=max_ativos,
        status_breeder=status_breeder,
        resumo_fila=resumo_fila,
        contagens_fila=contagens_fila,
        breeders_transferencia=listar_breeders_transferencia()
    )



def _breed_payload(pedidos, email):
    saida=[]
    for p in pedidos:
        saida.append({
            'id':p.get('id'),'status':p.get('status'),'breeder_responsavel':p.get('breeder_responsavel'),
            'assumido_em':p.get('assumido_em'),'pagamento_confirmado_em':p.get('pagamento_confirmado_em'),
            'concluido_em':p.get('concluido_em'),'entregue_em':p.get('entregue_em'),
            'prazo_estimado_em':p.get('prazo_estimado_em'),'prioridade':p.get('prioridade') or 'normal',
            'problema_status':p.get('problema_status'),'updated_at':p.get('updated_at') or p.get('created_at')
        })
    return saida

@app.route('/api/breed/meus-pedidos-status')
@login_required
def api_breed_meus_pedidos_status():
    email=session.get('usuario_email')
    try:
        pedidos=supabase.table('pedidos_breed').select('*').eq('usuario_email',email).order('created_at',desc=True).execute().data or []
        return jsonify({'ok':True,'pedidos':_breed_payload(pedidos,email),'server_time':agora_iso()})
    except Exception as e:
        return jsonify({'ok':False,'error':str(e)}),500

@app.route('/api/breed/fila-status')
@login_required
def api_breed_fila_status():
    email=session.get('usuario_email'); perm=obter_permissoes_usuario(email)
    if not perm.get('pode_ver_fila_breed'): return jsonify({'ok':False}),403
    try:
        pedidos=supabase.table('pedidos_breed').select('*').in_('status',['pendente','em_andamento','aguardando_pagamento','em_producao','cancelamento_solicitado','concluido','aguardando_confirmacao','aguardando_confirmacao_cliente']).order('created_at',desc=False).execute().data or []
        return jsonify({'ok':True,'pedidos':_breed_payload(pedidos,email),'server_time':agora_iso()})
    except Exception as e: return jsonify({'ok':False,'error':str(e)}),500

@app.route('/breed/confirmar-recebimento/<int:pedido_id>',methods=['POST'])
@login_required
def confirmar_recebimento_breed(pedido_id):
    email=session.get('usuario_email')
    try:
        rows=supabase.table('pedidos_breed').select('*').eq('id',pedido_id).limit(1).execute().data or []
        if not rows or rows[0].get('usuario_email')!=email:
            flash('Pedido não encontrado.','erro'); return redirect(url_for('breed_meus_pedidos'))
        p=rows[0]
        if p.get('status') != 'aguardando_confirmacao':
            flash('A confirmação só é liberada depois que o Breeder informar a entrega.','erro'); return redirect(url_for('breed_meus_pedidos'))
        supabase.table('pedidos_breed').update({'status':'entregue','entregue_em':agora_iso(),'recebimento_confirmado_em':agora_iso(),'recebimento_confirmado_por':email}).eq('id',pedido_id).eq('status','aguardando_confirmacao').execute()
        registrar_historico('breed',pedido_id,p.get('status'),'entregue','Recebimento confirmado pelo cliente.')
        if p.get('breeder_responsavel'): criar_notificacao(p.get('breeder_responsavel'),'Entrega confirmada',f"O cliente confirmou o recebimento do Breed #{pedido_id}.",'sucesso',url_for('breed_fila_breeders'))
        flash('Recebimento confirmado. Agora você pode avaliar o Breeder.','sucesso')
        return redirect(url_for('breed_meus_pedidos', avaliar=pedido_id))
    except Exception as e:
        flash(f'Erro ao confirmar recebimento: {e}','erro')
        return redirect(url_for('breed_meus_pedidos'))

@app.route('/breed/problema/<int:pedido_id>',methods=['POST'])
@login_required
def relatar_problema_breed(pedido_id):
    email=session.get('usuario_email'); motivo=request.form.get('motivo','').strip()[:800]
    try:
        rows=supabase.table('pedidos_breed').select('*').eq('id',pedido_id).limit(1).execute().data or []
        if not rows or rows[0].get('usuario_email')!=email: flash('Pedido não encontrado.','erro'); return redirect(url_for('breed_meus_pedidos'))
        p=rows[0]
        if p.get('status') not in ('concluido','aguardando_confirmacao','entregue'): flash('Problemas de entrega só podem ser abertos quando o Pokémon estiver pronto ou entregue.','erro'); return redirect(url_for('breed_meus_pedidos'))
        supabase.table('pedidos_breed').update({'problema_status':'aberto','problema_motivo':motivo or 'Problema informado pelo cliente','problema_aberto_em':agora_iso()}).eq('id',pedido_id).execute()
        registrar_historico('breed',pedido_id,'entregue','entregue','Cliente abriu um problema de entrega: '+(motivo or 'sem detalhes'))
        if p.get('breeder_responsavel'): criar_notificacao(p.get('breeder_responsavel'),'Problema na entrega',f"O cliente abriu um problema no Breed #{pedido_id}.",'aviso',url_for('chat_pedido',tipo='breed',pedido_id=pedido_id))
        flash('Problema registrado. Use o chat do pedido para acompanhar.','sucesso')
    except Exception as e: flash(f'Erro ao registrar problema: {e}','erro')
    return redirect(url_for('breed_meus_pedidos'))

@app.route('/breed/breeder-status',methods=['POST'])
@login_required
def alterar_status_breeder():
    email=session.get('usuario_email'); perm=obter_permissoes_usuario(email)
    if not perm.get('pode_assumir_breed'): return redirect(url_for('breed_meus_pedidos'))
    status=request.form.get('status','disponivel')
    if status not in ('disponivel','ocupado','indisponivel','ausente'): status='disponivel'
    if status == 'ausente': status = 'indisponivel'
    filtro=(request.form.get('filtro') or 'todos').strip().lower()
    if filtro not in {'todos','pendente','em_andamento','concluido','meus'}: filtro='todos'
    try:
        agora=agora_iso()
        supabase.table('breeders_perfil').upsert(
            {'usuario_email':email,'status':status,'updated_at':agora},on_conflict='usuario_email'
        ).execute()
        supabase.table('disponibilidade_funcoes').upsert(
            {'usuario_email':email,'funcao':'breeder','status':status,'updated_at':agora},
            on_conflict='usuario_email,funcao'
        ).execute()
        flash('Disponibilidade atualizada.','sucesso')
    except Exception as e: flash(f'Erro ao atualizar disponibilidade: {e}','erro')
    return redirect(url_for('breed_fila_breeders', filtro=filtro) if filtro!='todos' else url_for('breed_fila_breeders'))

@app.route('/breed/admin/prioridade/<int:pedido_id>',methods=['POST'])
@login_required
def admin_prioridade_breed(pedido_id):
    email=session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'): return redirect(url_for('breed_fila_breeders'))
    prioridade=request.form.get('prioridade','normal')
    if prioridade not in ('normal','alta','urgente'): prioridade='normal'
    try:
        supabase.table('pedidos_breed').update({'prioridade':prioridade}).eq('id',pedido_id).execute(); registrar_log('prioridade','breed','pedido_breed',pedido_id,{'prioridade':prioridade}); flash('Prioridade atualizada.','sucesso')
    except Exception as e: flash(f'Erro ao atualizar prioridade: {e}','erro')
    return redirect(url_for('breed_fila_breeders'))

@lru_cache(maxsize=1)
def _pokeapi_species_index():
    """Índice central do catálogo. O navegador nunca depende diretamente da PokéAPI."""
    try:
        with urlopen("https://pokeapi.co/api/v2/pokemon-species?limit=2000", timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        itens = []
        for item in data.get("results") or []:
            partes = (item.get("url") or "").rstrip("/").split("/")
            try:
                pid = int(partes[-1])
            except (TypeError, ValueError):
                continue
            itens.append({"id": pid, "name": item.get("name") or ""})
        return itens
    except Exception as e:
        print(f"PokeAPI indisponível ao carregar catálogo Breed: {e}")
        return []


@app.route('/api/breed/preco')
@app.route('/api/breed/preco-preview')
@app.route('/breed/preco-preview')
def api_breed_preco():
    """Prévia do preço: sempre devolve JSON; nunca uma página HTML de erro."""
    try:
        if 'usuario_email' not in session:
            return jsonify({'ok': False, 'error': 'Sua sessão expirou. Faça login novamente.'}), 401
        try:
            pokemon_id = int(request.args.get('pokemon_id', '0'))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Pokémon inválido.'}), 400
        pokemon = request.args.get('pokemon', '').strip()
        breed_tipo = request.args.get('breed_tipo', '').strip().upper()
        ha = request.args.get('ha', '').strip().lower()
        genero = request.args.get('genero', 'indiferente').strip().lower()
        treinado = request.args.get('treinado', 'nao').strip().lower() == 'sim'
        zero_speed = request.args.get('zero_speed', 'nao').strip().lower() == 'sim'
        nature = request.args.get('nature', '').strip()
        cupom_breed = request.args.get('cupom', '').strip().upper()
        if pokemon_id <= 0 or not pokemon or breed_tipo not in ('F5','F6','PERSONALIZADO') or ha not in ('sim','nao') or genero not in ('macho','femea','indiferente'):
            return jsonify({'ok': False, 'error': 'Complete as características para calcular o preço.'}), 400
        if nature and nature not in NATURES_VALIDAS:
            return jsonify({'ok': False, 'error': 'Nature inválida.'}), 400
        regra = regra_breed_pokemon(pokemon_id, pokemon)
        if not regra.get('breedavel'):
            return jsonify({'ok': False, 'error': regra.get('motivo') or 'Pokémon indisponível para Breed.'}), 400
        meta = classificar_pokemon_preco(pokemon_id)
        categoria = (meta.get('categoria') or 'comum').lower()
        if categoria not in BREED_CATEGORIAS_PRECO:
            categoria = 'comum'
        total, detalhes = calcular_preco_breed(
            breed_tipo, ha=(ha=='sim'), genero=genero, categoria=categoria,
            usa_ditto=bool(regra.get('so_com_ditto')), treinado=treinado,
            nature=nature or None, zero_speed=(zero_speed and breed_tipo == 'F5'),
            pokemon_id=pokemon_id, usuario_email=session.get('usuario_email'), codigo_cupom=cupom_breed
        )
        if total <= 0:
            return jsonify({'ok': False, 'error': 'Tabela de preços ainda não configurada para esta combinação.'}), 422
        preco_formatado = ('$' + f'{int(total):,}').replace(',', '.')
        return jsonify({'ok': True, 'total': int(total), 'preco_total': int(total),
                        'preco_formatado': preco_formatado, **detalhes})
    except Exception as e:
        print(f'[api/breed/preco] {type(e).__name__}: {e}')
        return jsonify({'ok': False, 'error': 'Falha temporária ao calcular o preço.'}), 500


@app.route('/api/breed/pokemon/catalogo')
@login_required
def api_breed_catalogo_pokemon():
    itens = _pokeapi_species_index()
    return {'results': [
        {
            'id': x['id'],
            'name': x['name'],
            'display_name': (x['name'] or '').replace('-', ' ').title(),
            'sprite': f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{x['id']}.png"
        } for x in itens if x.get('id') and x.get('name')
    ]}


@app.route('/api/breed/pokemon/buscar')
@login_required
def api_breed_buscar_pokemon():
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return {'results': []}

    # Catálogo remoto centralizado no Flask. Se estiver fora do ar, a interface
    # ainda mantém os cards HYPE locais e o pedido continua utilizável.
    encontrados = []
    for item in _pokeapi_species_index():
        nome = (item.get('name') or '').lower()
        if q in nome:
            encontrados.append({
                'id': item['id'],
                'name': nome,
                'display_name': nome.replace('-', ' ').title(),
                'sprite': f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{item['id']}.png"
            })
            if len(encontrados) >= 24:
                break

    # Se o índice completo estiver temporariamente indisponível, uma busca pelo
    # nome exato ainda funciona e devolve o card com sprite.
    if not encontrados and len(q) >= 3:
        try:
            with urlopen(f"https://pokeapi.co/api/v2/pokemon-species/{quote(q)}/", timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            pid = int(data.get('id'))
            nome = data.get('name') or q
            encontrados.append({
                'id': pid, 'name': nome,
                'display_name': nome.replace('-', ' ').title(),
                'sprite': f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{pid}.png"
            })
        except Exception:
            pass
    return {'results': encontrados}


@lru_cache(maxsize=16)
def _pokeapi_csv(nome_arquivo):
    """Fallback leve usando os CSVs oficiais do projeto PokéAPI no GitHub."""
    url = f"https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/{nome_arquivo}"
    try:
        with urlopen(url, timeout=8) as resp:
            texto = resp.read().decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(texto)))
    except Exception as e:
        print(f"CSV PokéAPI {nome_arquivo} indisponível: {e}")
        return []


def _pokeapi_github_details(pokemon_id):
    """Monta os dados visuais do painel mesmo quando pokeapi.co estiver indisponível."""
    pid = str(int(pokemon_id))
    out = {'types': [], 'abilities': [], 'stats': [], 'height': None, 'weight': None,
           'generation': None, 'egg_groups': []}
    try:
        pokemon = next((r for r in _pokeapi_csv('pokemon.csv') if r.get('id') == pid), None)
        if pokemon:
            out['height'] = int(pokemon['height']) if pokemon.get('height') else None
            out['weight'] = int(pokemon['weight']) if pokemon.get('weight') else None
            species_id = pokemon.get('species_id') or pid
        else:
            species_id = pid

        species = next((r for r in _pokeapi_csv('pokemon_species.csv') if r.get('id') == species_id), None)
        if species and species.get('generation_id'):
            out['generation'] = 'generation-' + str(species['generation_id'])

        type_names = {r.get('id'): r.get('identifier') for r in _pokeapi_csv('types.csv')}
        type_rows = [r for r in _pokeapi_csv('pokemon_types.csv') if r.get('pokemon_id') == pid]
        type_rows.sort(key=lambda r: int(r.get('slot') or 0))
        out['types'] = [type_names.get(r.get('type_id')) for r in type_rows if type_names.get(r.get('type_id'))]

        ability_names = {r.get('id'): r.get('identifier') for r in _pokeapi_csv('abilities.csv')}
        ability_rows = [r for r in _pokeapi_csv('pokemon_abilities.csv') if r.get('pokemon_id') == pid]
        ability_rows.sort(key=lambda r: int(r.get('slot') or 0))
        out['abilities'] = [
            {'name': ability_names.get(r.get('ability_id')), 'hidden': str(r.get('is_hidden')).lower() in ('1','true')}
            for r in ability_rows if ability_names.get(r.get('ability_id'))
        ]

        stat_names = {'1':'hp','2':'attack','3':'defense','4':'special-attack','5':'special-defense','6':'speed'}
        stat_rows = [r for r in _pokeapi_csv('pokemon_stats.csv') if r.get('pokemon_id') == pid]
        stat_rows.sort(key=lambda r: int(r.get('stat_id') or 0))
        out['stats'] = [
            {'name': stat_names.get(r.get('stat_id')), 'value': int(r.get('base_stat') or 0)}
            for r in stat_rows if stat_names.get(r.get('stat_id'))
        ]

        egg_names = {r.get('id'): r.get('identifier') for r in _pokeapi_csv('egg_groups.csv')}
        egg_rows = [r for r in _pokeapi_csv('pokemon_egg_groups.csv') if r.get('species_id') == species_id]
        out['egg_groups'] = [egg_names.get(r.get('egg_group_id')) for r in egg_rows if egg_names.get(r.get('egg_group_id'))]
    except Exception as e:
        print(f"Fallback GitHub PokéAPI #{pokemon_id} incompleto: {e}")
    return out


@app.route('/api/breed/pokemon/<int:pokemon_id>')
@login_required
def api_breed_pokemon(pokemon_id):
    nome = request.args.get('nome', '').strip()
    regra = regra_breed_pokemon(pokemon_id, nome)
    meta = classificar_pokemon_preco(pokemon_id)

    resposta = {
        'id': pokemon_id,
        'name': nome,
        'breedavel': bool(regra.get('breedavel')),
        'so_com_ditto': bool(regra.get('so_com_ditto')),
        'breed_especial': bool(regra.get('breed_especial')),
        'motivo': regra.get('motivo'),
        'categoria_bloqueio': regra.get('categoria_bloqueio'),
        'is_baby': bool(regra.get('is_baby')),
        'is_legendary': bool(regra.get('is_legendary')),
        'is_mythical': bool(regra.get('is_mythical')),
        'egg_groups': regra.get('egg_groups') or [],
        'categoria': (meta.get('categoria') or 'comum'),
        'categoria_label': meta.get('categoria_label') or 'Comum',
        'classificacao_motivo': meta.get('classificacao_motivo'),
        'classificacao_origem': meta.get('classificacao_origem'),
        'taxa_femea_percentual': meta.get('taxa_femea_percentual'),
        'sprite': f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{pokemon_id}.png",
        'types': [], 'abilities': [], 'stats': [], 'height': None, 'weight': None,
        'generation': None
    }

    # Metadados enriquecem a tela, mas nunca são requisito para criar o pedido.
    try:
        with urlopen(f"https://pokeapi.co/api/v2/pokemon/{pokemon_id}/", timeout=4) as resp:
            pdata = json.loads(resp.read().decode('utf-8'))
        resposta['name'] = resposta['name'] or pdata.get('name') or ''
        resposta['types'] = [x.get('type', {}).get('name') for x in pdata.get('types', []) if x.get('type', {}).get('name')]
        resposta['abilities'] = [
            {'name': x.get('ability', {}).get('name'), 'hidden': bool(x.get('is_hidden'))}
            for x in pdata.get('abilities', []) if x.get('ability', {}).get('name')
        ]
        resposta['stats'] = [
            {'name': x.get('stat', {}).get('name'), 'value': x.get('base_stat')}
            for x in pdata.get('stats', []) if x.get('stat', {}).get('name')
        ]
        resposta['height'] = pdata.get('height')
        resposta['weight'] = pdata.get('weight')
    except Exception as e:
        print(f"Metadados Pokémon #{pokemon_id} indisponíveis: {e}")

    try:
        with urlopen(f"https://pokeapi.co/api/v2/pokemon-species/{pokemon_id}/", timeout=4) as resp:
            sdata = json.loads(resp.read().decode('utf-8'))
        resposta['generation'] = (sdata.get('generation') or {}).get('name')
        if not resposta['egg_groups']:
            resposta['egg_groups'] = [x.get('name') for x in sdata.get('egg_groups', []) if x.get('name')]
    except Exception as e:
        print(f"Metadados de espécie #{pokemon_id} indisponíveis: {e}")

    # Se pokeapi.co falhar no host, completa o painel pelos CSVs oficiais no GitHub.
    if not resposta['stats'] or not resposta['types'] or resposta['height'] is None:
        fallback = _pokeapi_github_details(pokemon_id)
        for campo in ('types', 'abilities', 'stats', 'egg_groups'):
            if not resposta.get(campo) and fallback.get(campo):
                resposta[campo] = fallback[campo]
        for campo in ('height', 'weight', 'generation'):
            if resposta.get(campo) is None and fallback.get(campo) is not None:
                resposta[campo] = fallback[campo]

    return resposta


@app.route('/breed/ranking')
@login_required
def ranking_breed():
    try:
        res = supabase.table('pedidos_breed').select(
            'pokemon,pokemon_id,nature,ha,genero,breed_tipo,iv_descartado,status'
        ).execute()
        pedidos = res.data if res and res.data else []
    except Exception as e:
        print(f"Erro ao montar ranking: {e}")
        pedidos = []

    ranking = montar_ranking_breed(pedidos)
    return render_template('ranking_breed.html', ranking=ranking)


@app.route('/breed/assumir/<int:pedido_id>', methods=['POST'])
@login_required
def assumir_breed(pedido_id):
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes or not permissoes.get('pode_assumir_breed', False):
        flash('Você não tem permissão para assumir pedidos de breed.', 'erro')
        return redirect(url_for('breed'))

    try:
        checar_pedido = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute()
        if not checar_pedido.data:
            flash('Pedido de breed não encontrado.', 'erro')
            return redirect(url_for('breed'))

        pedido = checar_pedido.data[0]
        try:
            disp = supabase.table('breeders_perfil').select('status').eq('usuario_email',email).limit(1).execute().data or []
            if disp and disp[0].get('status') in ('ausente','indisponivel') and not permissoes.get('pode_gerenciar_cargos'):
                flash('Seu perfil de Breeder está pausado. Marque-se como disponível antes de assumir novos pedidos.','erro')
                return redirect(url_for('breed_fila_breeders'))
        except Exception as e: print(f'Erro ao validar disponibilidade: {e}')
        if pedido.get('status') != 'pendente':
            flash('Este pedido não está mais disponível para ser assumido.', 'erro')
            return redirect(url_for('breed_fila_breeders'))

        # Um pedido já atribuído é exclusivo do Breeder responsável. Mesmo que um
        # registro legado esteja como pendente por engano, outro Breeder não pode
        # assumir por cima do responsável atual; somente a administração transfere.
        if pedido.get('breeder_responsavel'):
            flash('Este pedido já está atribuído a outro Breeder. Somente a administração pode transferi-lo.', 'erro')
            return redirect(url_for('breed_fila_breeders'))

        pedidos_ativos = supabase.table('pedidos_breed').select('id').eq(
            'breeder_responsavel', email
        ).in_('status', ['aguardando_pagamento','em_producao','cancelamento_solicitado']).execute()

        limite_ativos = 4
        try:
            perfil_breeder = supabase.table('breeders_perfil').select('max_ativos').eq('usuario_email', email).limit(1).execute().data or []
            if perfil_breeder and perfil_breeder[0].get('max_ativos') is not None:
                limite_ativos = max(1, int(perfil_breeder[0]['max_ativos']))
        except Exception as e:
            print(f'Erro ao buscar limite do Breeder; usando 4: {e}')
        if pedidos_ativos.data and len(pedidos_ativos.data) >= limite_ativos:
            flash(f'Você já atingiu o limite máximo de {limite_ativos} pedidos ativos por vez!', 'erro')
            return redirect(url_for('breed_fila_breeders'))

        resultado = supabase.table('pedidos_breed').update({
            'status': 'aguardando_pagamento',
            'breeder_responsavel': email,
            'assumido_em': agora_iso(),
            'prazo_notificado': False
        }).eq('id', pedido_id).eq('status', 'pendente').is_('breeder_responsavel', 'null').execute()

        if not resultado.data:
            flash('Este pedido acabou de ser assumido por outro Breeder.', 'erro')
            return redirect(url_for('breed'))

        valor = filtro_preco(pedido.get('preco_total') or 0)
        criar_notificacao(
            pedido.get('usuario_email'),
            'Aguardando pagamento',
            f"Seu pedido de {pedido.get('pokemon')} foi assumido por {session.get('nick_jogo')}. Valor: {valor}. A produção só começa após o Breeder confirmar o pagamento.",
            'aviso', url_for('breed'),
            {'categoria':'breed','status':'aguardando_pagamento','pedido_id':pedido_id,
             'pokemon':pedido.get('pokemon'),'pokemon_id':pedido.get('pokemon_id'),
             'valor':pedido.get('preco_total'),'breeder':session.get('nick_jogo'),
             'instrucao':'Aguarde a confirmação do pagamento para que a produção seja iniciada.'}
        )
        criar_notificacao(
            email,
            'Não inicie a produção ainda',
            f"O pedido #{pedido_id} está aguardando pagamento. Confirme o recebimento antes de começar a breedar/chocar.",
            'aviso', url_for('breed'),
            {'categoria':'breed','status':'aguardando_pagamento','pedido_id':pedido_id,
             'pokemon':pedido.get('pokemon'),'pokemon_id':pedido.get('pokemon_id'),
             'valor':pedido.get('preco_total'),'breeder':session.get('nick_jogo'),
             'instrucao':'Confirme o recebimento do pagamento antes de começar a breedar/chocar.'}
        )
        registrar_historico('breed', pedido_id, 'pendente', 'aguardando_pagamento', 'Pedido assumido; aguardando confirmação do pagamento.')
        registrar_log('assumir', 'breed', 'pedido_breed', pedido_id, {'status_novo':'aguardando_pagamento'})
        flash('Pedido assumido. Aguarde o pagamento e confirme o recebimento antes de iniciar a produção.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao assumir pedido: {e}', 'erro')

    return redirect(url_for('breed'))


@app.route('/breed/devolver/<int:pedido_id>', methods=['POST'])
@login_required
def devolver_breed_fila(pedido_id):
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    motivo = (request.form.get('motivo') or '').strip()[:500]
    if len(motivo) < 3:
        flash('Informe o motivo da devolução para a fila.', 'erro')
        return redirect(url_for('breed_fila_breeders'))
    try:
        rows = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute().data or []
        if not rows:
            flash('Pedido não encontrado.', 'erro'); return redirect(url_for('breed_fila_breeders'))
        p = rows[0]
        admin = bool(permissoes.get('pode_gerenciar_cargos'))
        if p.get('breeder_responsavel') != email and not admin:
            flash('Somente o Breeder responsável ou um administrador pode devolver este pedido.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        if p.get('status') not in ('aguardando_pagamento','em_producao','cancelamento_solicitado'):
            flash('Este pedido não pode ser devolvido para a fila neste status.', 'erro')
            return redirect(url_for('breed_fila_breeders'))

        status_anterior = p.get('status')
        antigo_breeder = p.get('breeder_responsavel')
        # Se o pagamento já havia sido confirmado, desfaz o extrato antes de liberar o pedido.
        if p.get('pagamento_confirmado_em'):
            valor_mov = int(p.get('preco_total') or 0)
            taxa_clan = int(p.get('taxa_clan_valor') or 0)
            valor_breeder = int(p.get('valor_breeder') or max(0, valor_mov - taxa_clan))
            ciclo = str(p.get('pagamento_confirmado_em') or 'sem_pagamento')
            registrar_transacao_hype(p.get('usuario_email'),'entrada','estorno_breed',f"Estorno por devolução do Breed #{pedido_id}",valor_mov,origem_tipo='breed',origem_id=pedido_id,contraparte_email=antigo_breeder,chave_unica=f'breed:{pedido_id}:devolucao_cliente:{ciclo}')
            registrar_transacao_hype(antigo_breeder,'saida','estorno_breed',f"Estorno por devolução do Breed #{pedido_id}",valor_breeder,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('usuario_email'),chave_unica=f'breed:{pedido_id}:devolucao_breeder:{ciclo}')
            cancelar_comissao_breed(pedido_id, 'Pedido devolvido pelo Breeder')

        updates = {
            'status':'pendente','breeder_responsavel':None,'assumido_em':None,
            'pagamento_confirmado_em':None,'pagamento_confirmado_por':None,'prazo_notificado':False,
            'cancelamento_solicitado_em':None,'cancelamento_solicitado_por':None,
            'motivo_cancelamento_solicitado':None,'status_antes_cancelamento':None,
            'cancelamento_decidido_em':None,'cancelamento_decidido_por':None,'cancelamento_decisao':None
        }
        res = supabase.table('pedidos_breed').update(updates).eq('id',pedido_id).eq('status',status_anterior).execute()
        if not res.data:
            flash('O pedido mudou de estado. Atualize a fila e tente novamente.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        registrar_historico('breed',pedido_id,status_anterior,'pendente',f'Devolvido à fila por {email}. Motivo: {motivo}')
        registrar_log('devolver_fila','breed','pedido_breed',pedido_id,{'breeder_anterior':antigo_breeder,'motivo':motivo})
        criar_notificacao(p.get('usuario_email'),'Breed devolvido à fila',f"Seu pedido #{pedido_id} de {p.get('pokemon')} voltou para a fila. Motivo informado: {motivo}",'aviso',url_for('breed_meus_pedidos'))
        flash('Pedido devolvido para a fila e Breeder liberado.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao devolver pedido: {e}', 'erro')
    return redirect(url_for('breed_fila_breeders'))


@app.route('/breed/admin/transferir/<int:pedido_id>', methods=['POST'])
@login_required
def admin_transferir_breed(pedido_id):
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    if not permissoes.get('pode_gerenciar_cargos'):
        flash('Você não tem permissão para transferir pedidos.', 'erro')
        return redirect(url_for('breed_fila_breeders'))
    destino = (request.form.get('breeder_destino') or '').strip().lower()
    motivo = (request.form.get('motivo') or '').strip()[:500]
    forcar = request.form.get('forcar_limite') == '1'
    if not destino or len(motivo) < 3:
        flash('Selecione o Breeder de destino e informe o motivo da transferência.', 'erro')
        return redirect(url_for('breed_fila_breeders'))
    try:
        rows = supabase.table('pedidos_breed').select('*').eq('id',pedido_id).limit(1).execute().data or []
        if not rows:
            flash('Pedido não encontrado.', 'erro'); return redirect(url_for('breed_fila_breeders'))
        p = rows[0]
        if p.get('status') not in ('aguardando_pagamento','em_producao','cancelamento_solicitado','concluido'):
            flash('Somente pedidos já atribuídos e ainda não entregues podem ser transferidos.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        candidatos = {x['email']: x for x in listar_breeders_transferencia()}
        if destino not in candidatos:
            flash('O usuário selecionado não está autorizado como Breeder.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        if destino == p.get('breeder_responsavel'):
            flash('O pedido já está atribuído a este Breeder.', 'info')
            return redirect(url_for('breed_fila_breeders'))
        perfil = candidatos[destino]
        ativos = supabase.table('pedidos_breed').select('id').eq('breeder_responsavel',destino).in_('status',['aguardando_pagamento','em_producao','cancelamento_solicitado']).execute().data or []
        limite = max(1, int(perfil.get('max_ativos') or 4))
        if len(ativos) >= limite and not forcar:
            flash(f"{perfil.get('nick')} já atingiu o limite de {limite} pedidos ativos. Marque a exceção administrativa para forçar.", 'erro')
            return redirect(url_for('breed_fila_breeders'))
        anterior = p.get('breeder_responsavel')
        res = supabase.table('pedidos_breed').update({'breeder_responsavel':destino}).eq('id',pedido_id).eq('breeder_responsavel',anterior).execute()
        if not res.data:
            flash('O responsável mudou antes da transferência. Atualize a fila.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        # Se o pagamento já ocorreu, transfere também o repasse líquido do Breeder.
        if p.get('pagamento_confirmado_em') and anterior:
            valor_liquido = int(p.get('valor_breeder') or 0)
            if valor_liquido <= 0:
                _, _, valor_liquido = calcular_divisao_breed(int(p.get('preco_total') or 0), p.get('taxa_clan_percentual') or None)
            tag = agora_iso()
            registrar_transacao_hype(anterior,'saida','transferencia_breed',f"Transferência financeira do Breed #{pedido_id}",valor_liquido,origem_tipo='breed',origem_id=pedido_id,contraparte_email=destino,chave_unica=f'breed:{pedido_id}:transfer_saida:{tag}')
            registrar_transacao_hype(destino,'entrada','transferencia_breed',f"Repasse transferido do Breed #{pedido_id}",valor_liquido,origem_tipo='breed',origem_id=pedido_id,contraparte_email=anterior,chave_unica=f'breed:{pedido_id}:transfer_entrada:{tag}')
        registrar_historico('breed',pedido_id,p.get('status'),p.get('status'),f'Transferido de {anterior or "sem breeder"} para {destino}. Motivo: {motivo}')
        registrar_log('transferir_breeder','breed','pedido_breed',pedido_id,{'de':anterior,'para':destino,'motivo':motivo,'excecao_limite':forcar})
        if anterior:
            criar_notificacao(anterior,'Breed transferido',f"O pedido #{pedido_id} foi transferido para {perfil.get('nick')}. Motivo: {motivo}",'aviso',url_for('breed_fila_breeders'))
        criar_notificacao(destino,'Novo Breed transferido',f"O pedido #{pedido_id} de {p.get('pokemon')} foi transferido para você.",'aviso',url_for('breed_fila_breeders'))
        criar_notificacao(p.get('usuario_email'),'Breeder atualizado',f"Seu pedido #{pedido_id} agora está com {perfil.get('nick')}.",'info',url_for('breed_meus_pedidos'))
        flash('Pedido transferido com sucesso.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao transferir pedido: {e}', 'erro')
    return redirect(url_for('breed_fila_breeders'))


@app.route('/breed/confirmar-pagamento/<int:pedido_id>', methods=['POST'])
@login_required
def confirmar_pagamento_breed(pedido_id):
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    try:
        rows = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute().data or []
        if not rows:
            flash('Pedido não encontrado.', 'erro')
            return redirect(url_for('breed'))
        pedido = rows[0]
        admin = bool(permissoes.get('pode_gerenciar_cargos'))
        if pedido.get('breeder_responsavel') != email and not admin:
            flash('Somente o Breeder responsável pode confirmar o pagamento.', 'erro')
            return redirect(url_for('breed'))
        if pedido.get('status') != 'aguardando_pagamento':
            flash('Este pedido não está aguardando pagamento.', 'erro')
            return redirect(url_for('breed'))

        agora = agora_iso()
        resultado = supabase.table('pedidos_breed').update({
            'status': 'em_producao',
            'pagamento_confirmado_em': agora,
            'pagamento_confirmado_por': email,
            'prazo_notificado': False
        }).eq('id', pedido_id).eq('status', 'aguardando_pagamento').execute()
        if not resultado.data:
            flash('Não foi possível confirmar o pagamento.', 'erro')
            return redirect(url_for('breed'))

        criar_notificacao(
            pedido.get('usuario_email'), 'Pagamento confirmado',
            f"Pagamento do pedido de {pedido.get('pokemon')} confirmado. Seu pedido entrou em produção.",
            'sucesso', url_for('breed'),
            {'categoria':'breed','status':'em_producao','pedido_id':pedido_id,
             'pokemon':pedido.get('pokemon'),'pokemon_id':pedido.get('pokemon_id'),
             'valor':pedido.get('preco_total'),'breeder':session.get('nick_jogo'),
             'instrucao':'Pagamento confirmado. Seu Pokémon já está em produção.'}
        )
        registrar_historico('breed', pedido_id, 'aguardando_pagamento', 'em_producao', 'Pagamento confirmado pelo Breeder; produção liberada.')
        registrar_log('confirmar_pagamento', 'breed', 'pedido_breed', pedido_id, {'valor': pedido.get('preco_total') or 0})
        registrar_atividade_reino('breed_pagamento_confirmado', email, f"Pagamento confirmado: {pedido.get('pokemon')}", 'breed', pedido_id)
        valor_mov = int(pedido.get('preco_total') or 0)
        pct_salvo = pedido.get('taxa_clan_percentual')
        try:
            pct_taxa, taxa_clan, valor_breeder = calcular_divisao_breed(valor_mov, pct_salvo if pct_salvo is not None else None)
        except Exception:
            pct_taxa, taxa_clan, valor_breeder = calcular_divisao_breed(valor_mov)
        # Congela a divisão financeira no próprio pedido para auditoria futura.
        supabase.table('pedidos_breed').update({
            'taxa_clan_percentual': pct_taxa, 'taxa_clan_valor': taxa_clan, 'valor_breeder': valor_breeder
        }).eq('id', pedido_id).execute()
        registrar_transacao_hype(
            pedido.get('usuario_email'), 'saida', 'breed',
            f"Pagamento do Breed #{pedido_id} - {pedido.get('pokemon')}", valor_mov,
            origem_tipo='breed', origem_id=pedido_id, contraparte_email=pedido.get('breeder_responsavel'),
            chave_unica=f'breed:{pedido_id}:cliente:{agora}'
        )
        registrar_transacao_hype(
            pedido.get('breeder_responsavel'), 'entrada', 'breed',
            f"Repasse do Breed #{pedido_id} - {pedido.get('pokemon')}", valor_breeder,
            origem_tipo='breed', origem_id=pedido_id, contraparte_email=pedido.get('usuario_email'),
            chave_unica=f'breed:{pedido_id}:breeder:{agora}'
        )
        # V28: a taxa NAO entra mais no caixa aqui. O Breeder apenas recebeu o
        # pagamento do cliente. A divida com o Cla nasce quando o Pokemon fica pronto
        # e o caixa so recebe quando um Admin confirmar o pagamento da comissao.
        flash('Pagamento confirmado. Agora a produção pode começar.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao confirmar pagamento: {e}', 'erro')
    return redirect(url_for('breed'))


@app.route('/breed/concluir/<int:pedido_id>', methods=['POST'])
@login_required
def concluir_breed(pedido_id):
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes or not permissoes.get('pode_concluir_breed', False):
        flash('Você não tem permissão para concluir pedidos de breed.', 'erro')
        return redirect(url_for('breed'))

    try:
        res = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute()
        if not res.data:
            flash('Pedido de breed não encontrado.', 'erro')
            return redirect(url_for('breed'))

        pedido = res.data[0]
        if pedido.get('status') != 'em_producao':
            flash('Somente pedidos em produção e com pagamento confirmado podem ser concluídos.', 'erro')
            return redirect(url_for('breed'))

        # Regra principal: Breeder comum nunca conclui trabalho de outro Breeder.
        pode_gerenciar = permissoes.get('pode_gerenciar_cargos', False)
        if pedido.get('breeder_responsavel') != email and not pode_gerenciar:
            flash('Somente o Breeder responsável pode concluir este pedido.', 'erro')
            return redirect(url_for('breed'))

        resultado = supabase.table('pedidos_breed').update({
            'status': 'concluido',
            'concluido_em': agora_iso()
        }).eq('id', pedido_id).eq('status', 'em_producao').execute()

        if not resultado.data:
            flash('Não foi possível concluir este pedido.', 'erro')
            return redirect(url_for('breed'))

        pedido_pronto = dict(pedido)
        pedido_pronto['status'] = 'concluido'
        pedido_pronto['concluido_em'] = agora_iso()
        gerar_comissao_breed_pendente(pedido_pronto)

        criar_notificacao(pedido.get('usuario_email'), 'Pokémon pronto!', f"Seu {pedido.get('pokemon')} foi concluído e está pronto para entrega.", 'sucesso', url_for('breed'), {'categoria':'breed','status':'concluido','pedido_id':pedido_id,'pokemon':pedido.get('pokemon'),'pokemon_id':pedido.get('pokemon_id'),'valor':pedido.get('preco_total'),'breeder':session.get('nick_jogo'),'instrucao':'Seu Pokémon está pronto. Combine a entrega com o Breeder.'})
        atualizar_conquistas_breeder(pedido.get('breeder_responsavel') or email)
        registrar_atividade_reino('breed_concluido', email, f"Breed concluído: {pedido.get('pokemon')}", 'breed', pedido_id)
        flash('Pedido marcado como concluído! O jogador foi notificado. 🎉', 'sucesso')
    except Exception as e:
        flash(f'Erro ao concluir pedido: {e}', 'erro')

    return redirect(url_for('breed'))



@app.route('/breed/comissao/<int:comissao_id>/informar-pagamento', methods=['POST'])
@login_required
def informar_pagamento_comissao_breed(comissao_id):
    email = session.get('usuario_email')
    observacao = (request.form.get('observacao') or '').strip()[:500] or None
    try:
        rows = supabase.table('hype_breed_comissoes').select('*').eq('id', comissao_id).limit(1).execute().data or []
        if not rows:
            flash('Comissao nao encontrada.', 'erro')
            return redirect(url_for('painel_breeder_hype'))
        c = rows[0]
        if c.get('breeder_email') != email:
            flash('Esta comissao pertence a outro Breeder.', 'erro')
            return redirect(url_for('painel_breeder_hype'))
        if c.get('status') == 'pago':
            flash('Esta comissao ja foi confirmada como paga.', 'info')
            return redirect(url_for('painel_breeder_hype'))
        if c.get('status') != 'pendente':
            flash('Esta comissao nao pode ser informada neste estado.', 'erro')
            return redirect(url_for('painel_breeder_hype'))
        agora = agora_iso()
        supabase.table('hype_breed_comissoes').update({
            'status':'informado', 'informado_pagamento_em':agora,
            'informado_pagamento_por':email, 'observacao_pagamento':observacao,
            'recusado_em':None, 'recusado_por':None, 'motivo_recusa':None,
            'updated_at':agora
        }).eq('id',comissao_id).eq('status','pendente').execute()
        registrar_log('informar_pagamento_comissao','financeiro_breed','comissao_breed',comissao_id,{'valor':c.get('valor')})
        notificar_admins_financeiro('Pagamento de comissao informado', f"{session.get('nick_jogo') or email} informou o pagamento de {formatar_preco(c.get('valor'))} da comissao do Breed #{c.get('pedido_id')}.")
        flash('Pagamento informado. Agora aguarde a confirmacao da administracao.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao informar pagamento da comissao: {e}', 'erro')
    return redirect(url_for('painel_breeder_hype'))


@app.route('/breed/comissoes/informar-pagamento-total', methods=['POST'])
@login_required
def informar_pagamento_total_comissoes_breed():
    email = session.get('usuario_email')
    observacao = (request.form.get('observacao') or '').strip()[:500] or None
    try:
        rows = supabase.table('hype_breed_comissoes').select('*').eq('breeder_email',email).eq('status','pendente').execute().data or []
        if not rows:
            flash('Voce nao possui comissoes pendentes para informar.', 'info')
            return redirect(url_for('painel_breeder_hype'))
        agora = agora_iso()
        ids=[]; total=0
        for c in rows:
            supabase.table('hype_breed_comissoes').update({
                'status':'informado','informado_pagamento_em':agora,'informado_pagamento_por':email,
                'observacao_pagamento':observacao,'updated_at':agora
            }).eq('id',c.get('id')).eq('status','pendente').execute()
            ids.append(c.get('id')); total += int(c.get('valor') or 0)
        registrar_log('informar_pagamento_total_comissoes','financeiro_breed','breeder',email,{'comissoes':ids,'valor':total})
        notificar_admins_financeiro('Pagamento total de comissoes informado', f"{session.get('nick_jogo') or email} informou o pagamento total de {formatar_preco(total)} em {len(ids)} comissao(oes).")
        flash(f'Pagamento de {formatar_preco(total)} informado. Aguarde a confirmacao da administracao.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao informar pagamento: {e}', 'erro')
    return redirect(url_for('painel_breeder_hype'))


@app.route('/admin/financeiro/comissao/<int:comissao_id>/confirmar', methods=['POST'])
@login_required
def admin_confirmar_comissao_breed(comissao_id):
    if not _is_admin():
        flash('Apenas a administracao pode confirmar comissoes.', 'erro')
        return redirect(url_for('painel'))
    try:
        rows = supabase.table('hype_breed_comissoes').select('*').eq('id',comissao_id).limit(1).execute().data or []
        if not rows:
            flash('Comissao nao encontrada.', 'erro')
            return redirect(url_for('final.financeiro'))
        c=rows[0]
        if c.get('status') == 'pago':
            flash('Esta comissao ja esta paga.', 'info')
            return redirect(url_for('final.financeiro'))
        if c.get('status') not in ('pendente','informado'):
            flash('Esta comissao nao pode ser confirmada neste estado.', 'erro')
            return redirect(url_for('final.financeiro'))
        agora=agora_iso()
        supabase.table('hype_breed_comissoes').update({
            'status':'pago','confirmado_em':agora,'confirmado_por':session.get('usuario_email'),'updated_at':agora
        }).eq('id',comissao_id).in_('status',['pendente','informado']).execute()
        pedido = _pedido('breed', c.get('pedido_id')) or {}
        registrar_caixa_clan(
            'entrada','taxa_breed',f"Comissao recebida do Breed #{c.get('pedido_id')} - {pedido.get('pokemon') or 'Pokemon'}",int(c.get('valor') or 0),
            origem_tipo='breed_comissao', origem_id=comissao_id,
            chave_unica=f'breed:comissao:{comissao_id}:recebida'
        )
        registrar_log('confirmar_comissao','financeiro_breed','comissao_breed',comissao_id,{'valor':c.get('valor'),'breeder':c.get('breeder_email')})
        criar_notificacao(c.get('breeder_email'),'Comissao HYPE confirmada',f"A administracao confirmou o recebimento de {formatar_preco(c.get('valor'))} referente ao Breed #{c.get('pedido_id')}.",'sucesso',url_for('painel_breeder_hype'))
        flash('Recebimento confirmado e valor lancado no Caixa do Cla.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao confirmar comissao: {e}', 'erro')
    return redirect(url_for('final.financeiro'))


@app.route('/admin/financeiro/comissao/<int:comissao_id>/rejeitar', methods=['POST'])
@login_required
def admin_rejeitar_comissao_breed(comissao_id):
    if not _is_admin():
        return redirect(url_for('painel'))
    motivo=(request.form.get('motivo') or '').strip()[:500] or 'Pagamento nao localizado pela administracao.'
    try:
        rows=supabase.table('hype_breed_comissoes').select('*').eq('id',comissao_id).limit(1).execute().data or []
        if not rows:
            flash('Comissao nao encontrada.','erro'); return redirect(url_for('final.financeiro'))
        c=rows[0]
        if c.get('status')!='informado':
            flash('Somente pagamentos informados podem ser devolvidos para pendente.','erro'); return redirect(url_for('final.financeiro'))
        agora=agora_iso()
        supabase.table('hype_breed_comissoes').update({
            'status':'pendente','recusado_em':agora,'recusado_por':session.get('usuario_email'),
            'motivo_recusa':motivo,'updated_at':agora
        }).eq('id',comissao_id).eq('status','informado').execute()
        registrar_log('rejeitar_pagamento_comissao','financeiro_breed','comissao_breed',comissao_id,{'motivo':motivo})
        criar_notificacao(c.get('breeder_email'),'Pagamento da comissao nao confirmado',f"A administracao nao confirmou o pagamento do Breed #{c.get('pedido_id')}. Motivo: {motivo}",'aviso',url_for('painel_breeder_hype'))
        flash('Pagamento devolvido para Pendente.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao rejeitar informacao: {e}','erro')
    return redirect(url_for('final.financeiro'))


@app.route('/breed/entregar/<int:pedido_id>', methods=['POST'])
@login_required
def entregar_breed(pedido_id):
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    try:
        res = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute()
        if not res.data:
            flash('Pedido de breed não encontrado.', 'erro')
            return redirect(url_for('breed'))

        pedido = res.data[0]
        if pedido.get('status') != 'concluido':
            flash('Somente pedidos concluídos podem ser entregues.', 'erro')
            return redirect(url_for('breed'))

        pode_gerenciar = permissoes.get('pode_gerenciar_cargos', False)
        if pedido.get('breeder_responsavel') != email and not pode_gerenciar:
            flash('Você não tem permissão para entregar este pedido.', 'erro')
            return redirect(url_for('breed'))

        resultado = supabase.table('pedidos_breed').update({
            'status': 'aguardando_confirmacao'
        }).eq('id', pedido_id).eq('status', 'concluido').execute()

        if not resultado.data:
            flash('Não foi possível entregar este pedido.', 'erro')
            return redirect(url_for('breed'))

        registrar_historico('breed', pedido_id, 'concluido', 'aguardando_confirmacao', 'Breeder informou a entrega; aguardando confirmação do cliente.')
        criar_notificacao(pedido.get('usuario_email'),'Confirme o recebimento',f"O Breeder informou a entrega do pedido #{pedido_id}. Confirme em Meus Pedidos.",'aviso',url_for('breed_meus_pedidos'), {'categoria':'breed','status':'aguardando_confirmacao','pedido_id':pedido_id,'pokemon':pedido.get('pokemon'),'pokemon_id':pedido.get('pokemon_id'),'valor':pedido.get('preco_total'),'breeder':session.get('nick_jogo'),'instrucao':'Abra Meus Pedidos e confirme que recebeu o Pokémon.'})
        flash('Entrega informada. Agora aguardamos a confirmação do cliente.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao entregar pedido: {e}', 'erro')

    return redirect(url_for('breed'))




@app.route('/breeders')
@login_required
def team_breeders():
    """Vitrine operacional do Team HYPE Breeders."""
    usuarios = _safe_table('usuarios_clan', '*')
    funcoes = _safe_table('usuarios_funcoes', '*')
    disp = _safe_table('disponibilidade_funcoes', '*')
    perfis = _safe_table('breeders_perfil', '*')
    pedidos = _safe_table('pedidos_breed', '*')
    avaliacoes = _safe_table('avaliacoes', '*')
    emails = {x.get('usuario_email') for x in funcoes if x.get('funcao') == 'breeder'}
    emails.update(u.get('email') for u in usuarios if u.get('cargo') in ('breeder','sub_lider','lider'))
    dmap = {x.get('usuario_email'): x for x in disp if x.get('funcao') == 'breeder'}
    pmap = {x.get('usuario_email'): x for x in perfis}
    cards=[]
    for u in usuarios:
        email=u.get('email')
        if email not in emails: continue
        feitos=[x for x in pedidos if x.get('breeder_responsavel')==email]
        ativos=[x for x in feitos if x.get('status') in ('aguardando_pagamento','em_producao','cancelamento_solicitado')]
        concluidos=[x for x in feitos if x.get('status') in ('concluido','entregue')]
        notas=[int(x.get('nota') or 0) for x in avaliacoes if x.get('avaliado_email')==email and x.get('tipo_pedido')=='breed' and x.get('nota')]
        perfil=pmap.get(email,{})
        status=(dmap.get(email,{}).get('status') or perfil.get('status') or 'disponivel')
        if status == 'indisponivel': status='ausente'
        cards.append({'email':email,'nick':u.get('nome_exibicao') or u.get('nick_jogo') or email,'nick_url':u.get('nick_jogo') or email,
          'avatar_url':u.get('avatar_url'),'cargo':u.get('cargo'),'status':status,'ativos':len(ativos),'concluidos':len(concluidos),
          'avaliacao':round(sum(notas)/len(notas),1) if notas else None,'max_ativos':int(perfil.get('max_ativos') or 4),
          'especialidades':perfil.get('especialidades') or [],'bio':perfil.get('bio_breeder'), **_hype_breeder_metricas(email,pedidos,avaliacoes)})
    ordem={'disponivel':0,'ocupado':1,'ausente':2}
    cards.sort(key=lambda x:(ordem.get(x['status'],9),x['ativos'],x['nick'].casefold()))
    return render_template('team_breeders.html', breeders=cards, permissoes=obter_permissoes_usuario(session.get('usuario_email')))

@app.route('/breed/painel-breeder', endpoint='painel_breeder_hype')
@login_required
def painel_breeder_hype():
    """Central pessoal do Breeder: operação, capacidade, avaliações e repasses."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    if not (usuario_tem_funcao(email, 'breeder') or permissoes.get('pode_assumir_breed') or _is_admin(email)):
        flash('A Central do Breeder é exclusiva para Breeders autorizados.', 'erro')
        return redirect(url_for('painel'))

    pedidos = _safe_table('pedidos_breed', '*')
    meus = [p for p in pedidos if p.get('breeder_responsavel') == email]
    meus.sort(key=lambda x: str(x.get('updated_at') or x.get('created_at') or ''), reverse=True)
    avaliacoes = [a for a in _safe_table('avaliacoes', '*') if a.get('tipo_pedido') == 'breed' and a.get('avaliado_email') == email]
    metricas = _hype_breeder_metricas(email, pedidos, avaliacoes)

    perfil = next(iter(_safe_table('breeders_perfil', '*', usuario_email=email)), {})
    disponibilidade = next((d for d in _safe_table('disponibilidade_funcoes', '*', usuario_email=email) if d.get('funcao') == 'breeder'), {})
    usuario = next(iter(_safe_table('usuarios_clan', '*', email=email)), {})
    max_ativos = int(perfil.get('max_ativos') or 4)

    ativos_status = ('aguardando_pagamento', 'em_producao', 'cancelamento_solicitado')
    ativos = [p for p in meus if p.get('status') in ativos_status]
    aguardando_pagamento = [p for p in meus if p.get('status') == 'aguardando_pagamento']
    em_producao = [p for p in meus if p.get('status') in ('em_producao', 'cancelamento_solicitado')]
    prontos = [p for p in meus if p.get('status') in ('concluido', 'aguardando_confirmacao')]
    entregues = [p for p in meus if p.get('status') == 'entregue']

    ids = [p.get('id') for p in meus if p.get('id') is not None]
    nao_lidas = {}
    if ids:
        try:
            msgs = supabase.table('mensagens_pedido').select('pedido_id,remetente_email,lida').eq('tipo_pedido','breed').in_('pedido_id', ids).execute().data or []
            for m in msgs:
                if not m.get('lida') and m.get('remetente_email') != email:
                    pid = m.get('pedido_id')
                    nao_lidas[pid] = nao_lidas.get(pid, 0) + 1
        except Exception as e:
            print(f'Erro ao contar mensagens no painel Breeder: {e}')

    mapa = mapa_nicks_por_email()
    for p in meus:
        p['cliente_nick'] = mapa.get(p.get('usuario_email'), {}).get('nick') or p.get('player') or 'Membro HYPE'
        p['mensagens_nao_lidas'] = nao_lidas.get(p.get('id'), 0)

    repasse_total = sum(int(p.get('valor_breeder') or p.get('preco_total') or 0) for p in entregues)
    agora = datetime.now(HYPE_TZ)
    repasse_mes = 0
    entregues_mes = 0
    for p in entregues:
        dt = parse_data_supabase(p.get('entregue_em'))
        if dt and dt.astimezone(HYPE_TZ).year == agora.year and dt.astimezone(HYPE_TZ).month == agora.month:
            repasse_mes += int(p.get('valor_breeder') or p.get('preco_total') or 0)
            entregues_mes += 1

    comissoes = []
    try:
        comissoes = supabase.table('hype_breed_comissoes').select('*').eq('breeder_email', email).order('gerada_em', desc=True).execute().data or []
    except Exception as e:
        print(f'Erro ao carregar comissoes do Breeder: {e}')
    comissoes_abertas = [c for c in comissoes if c.get('status') in ('pendente','informado')]
    comissoes_pendentes = [c for c in comissoes if c.get('status') == 'pendente']
    comissoes_informadas = [c for c in comissoes if c.get('status') == 'informado']
    comissao_devida = sum(int(c.get('valor') or 0) for c in comissoes_abertas)
    comissao_pendente = sum(int(c.get('valor') or 0) for c in comissoes_pendentes)
    comissao_aguardando = sum(int(c.get('valor') or 0) for c in comissoes_informadas)
    pedidos_por_id = {p.get('id'): p for p in meus}
    for c in comissoes:
        p = pedidos_por_id.get(c.get('pedido_id')) or {}
        c['pokemon'] = p.get('pokemon') or 'Pokemon'
        c['pokemon_id'] = p.get('pokemon_id')

    avaliacoes.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    for a in avaliacoes[:8]:
        a['avaliador_nick'] = mapa.get(a.get('avaliador_email'), {}).get('nick') or 'Membro HYPE'

    return render_template(
        'painel_breeder_hype.html', usuario=usuario, perfil=perfil, disponibilidade=disponibilidade,
        metricas=metricas, max_ativos=max_ativos, ativos=ativos, aguardando_pagamento=aguardando_pagamento,
        em_producao=em_producao, prontos=prontos, entregues=entregues[:8], repasse_total=repasse_total,
        repasse_mes=repasse_mes, entregues_mes=entregues_mes, avaliacoes=avaliacoes[:8], permissoes=permissoes,
        comissoes=comissoes[:12], comissoes_abertas=comissoes_abertas, comissao_devida=comissao_devida,
        comissao_pendente=comissao_pendente, comissao_aguardando=comissao_aguardando
    )


@app.route('/breed/pedido/<int:pedido_id>')
@login_required
def breed_pedido_detalhe(pedido_id):
    """Detalhes completos de um pedido Breed com acesso por cliente, responsável ou equipe autorizada."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    pedido = _pedido('breed', pedido_id)
    if not pedido:
        flash('Pedido de Breed não encontrado.', 'erro')
        return redirect(url_for('breed_meus_pedidos'))
    pode_ver = email in (pedido.get('usuario_email'), pedido.get('breeder_responsavel')) or permissoes.get('pode_ver_fila_breed') or _is_admin(email)
    if not pode_ver:
        flash('Você não tem acesso a este pedido.', 'erro')
        return redirect(url_for('breed_meus_pedidos'))

    mapa = mapa_nicks_por_email()
    pedido['cliente_nick'] = mapa.get(pedido.get('usuario_email'), {}).get('nick') or pedido.get('player') or 'Membro HYPE'
    pedido['breeder_nick'] = mapa.get(pedido.get('breeder_responsavel'), {}).get('nick') if pedido.get('breeder_responsavel') else None

    historico = []
    mensagens = []
    avaliacao = None
    try:
        historico = supabase.table('historico_pedidos').select('*').eq('tipo_pedido','breed').eq('pedido_id',pedido_id).order('created_at').execute().data or []
    except Exception as e:
        print(f'Erro ao carregar histórico do pedido #{pedido_id}: {e}')
    try:
        mensagens = supabase.table('mensagens_pedido').select('*').eq('tipo_pedido','breed').eq('pedido_id',pedido_id).order('created_at', desc=True).limit(6).execute().data or []
        mensagens.reverse()
    except Exception as e:
        print(f'Erro ao carregar mensagens do pedido #{pedido_id}: {e}')
    try:
        avs = supabase.table('avaliacoes').select('*').eq('tipo_pedido','breed').eq('pedido_id',pedido_id).limit(1).execute().data or []
        avaliacao = avs[0] if avs else None
    except Exception as e:
        print(f'Erro ao carregar avaliação do pedido #{pedido_id}: {e}')

    for m in mensagens:
        m['autor_nick'] = 'Você' if m.get('remetente_email') == email else (mapa.get(m.get('remetente_email'), {}).get('nick') or 'Equipe HYPE')

    comissao = obter_comissao_breed(pedido_id)
    return render_template('breed_pedido_detalhe.html', pedido=pedido, historico=historico, mensagens=mensagens,
                           avaliacao=avaliacao, permissoes=permissoes, usuario_email=email, comissao=comissao)


@app.route('/admin/breeders')
@login_required
def gestao_breeders():
    """Painel de produção e valor gerado pelos Breeders."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes or not (permissoes.get('pode_ver_gestao_breed', False) or (permissoes.get('pode_ver_gestao_breed', permissoes.get('pode_gerenciar_cargos', False)))):
        flash('Você não tem permissão para acessar a Gestão do Berçário.', 'erro')
        return redirect(url_for('painel'))

    periodo = request.args.get('periodo', 'semana').strip().lower()
    agora = datetime.now(timezone.utc)

    if periodo == 'hoje':
        inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        titulo_periodo = 'Hoje'
    elif periodo == 'mes':
        inicio = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        titulo_periodo = 'Este mês'
    else:
        periodo = 'semana'
        inicio = (agora - timedelta(days=agora.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        titulo_periodo = 'Esta semana'

    try:
        res_pedidos = supabase.table('pedidos_breed').select(
            'id,pokemon,pokemon_id,breed_tipo,status,breeder_responsavel,preco_total,concluido_em,entregue_em'
        ).in_('status', ['concluido', 'entregue']).execute()
        pedidos = res_pedidos.data or []
    except Exception as e:
        print(f"Erro ao carregar estatísticas de breeders: {e}")
        pedidos = []

    mapa = mapa_nicks_por_email()
    stats = {}
    total_pokemons = 0
    total_valor = 0

    for p in pedidos:
        # Produção conta pela data em que o Pokémon ficou pronto.
        data = parse_data_supabase(p.get('concluido_em'))
        if not data or data < inicio or data > agora:
            continue

        breeder_email = p.get('breeder_responsavel')
        if not breeder_email:
            continue

        valor = int(p.get('preco_total') or 0)
        info = mapa.get(breeder_email, {})
        item = stats.setdefault(breeder_email, {
            'email': breeder_email,
            'nick': info.get('nick') or breeder_email,
            'cargo': info.get('cargo') or 'breeder',
            'quantidade': 0,
            'valor': 0,
            'pedidos': []
        })
        item['quantidade'] += 1
        item['valor'] += valor
        item['pedidos'].append({
            'pokemon': p.get('pokemon') or 'Pokémon',
            'breed_tipo': p.get('breed_tipo') or '—',
            'valor': valor,
            'data': data
        })
        total_pokemons += 1
        total_valor += valor

    breeders = sorted(stats.values(), key=lambda x: (-x['quantidade'], -x['valor'], x['nick'].lower()))

    # Série diária para o gráfico (últimos 7 dias, independente do filtro)
    grafico = []
    for dias_atras in range(6, -1, -1):
        dia = (agora - timedelta(days=dias_atras)).date()
        quantidade = 0
        valor = 0
        for p in pedidos:
            data = parse_data_supabase(p.get('concluido_em'))
            if data and data.date() == dia:
                quantidade += 1
                valor += int(p.get('preco_total') or 0)
        grafico.append({'dia': dia.strftime('%d/%m'), 'quantidade': quantidade, 'valor': valor})

    return render_template(
        'gestao_breeders.html',
        breeders=breeders,
        periodo=periodo,
        titulo_periodo=titulo_periodo,
        total_pokemons=total_pokemons,
        total_valor=total_valor,
        breeders_ativos=len(breeders),
        grafico=grafico
    )


# ============================================================================
# ROTAS ADMINISTRATIVAS (GESTÃO DE CARGOS)
# ============================================================================

@app.route('/admin/cargos', methods=['GET'])
@login_required
def admin_cargos():
    """Página principal de gerenciamento de cargos do clã (Lista membros e cargos)."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes or not permissoes.get('pode_gerenciar_cargos', False):
        flash('Você não tem permissão para acessar a área administrativa.', 'erro')
        return redirect(url_for('painel'))

    try:
        res_usuarios = supabase.table('usuarios_clan').select('*').order('nick_jogo').execute()
        res_cargos = supabase.table('cargos').select('*').execute()
        
        usuarios = res_usuarios.data if res_usuarios.data else []
        cargos = res_cargos.data if res_cargos.data else []
    except Exception as e:
        print(f"Erro ao carregar dados administrativos: {e}")
        usuarios = []
        cargos = []

    return render_template('admin_cargos.html', usuarios=usuarios, cargos=cargos)


@app.route('/admin/criar-cargo', methods=['POST'])
@login_required
def criar_novo_cargo():
    """Cria um novo cargo e define suas permissões no Supabase."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes or not permissoes.get('pode_gerenciar_cargos', False):
        flash('Acesso negado.', 'erro')
        return redirect(url_for('painel'))

    nome_cargo = request.form.get('nome_cargo', '').strip()
    id_cargo = request.form.get('id_cargo', '').strip().lower().replace(' ', '_')

    if not nome_cargo or not id_cargo:
        flash('Preencha o nome e o ID do cargo.', 'erro')
        return redirect(url_for('admin_cargos'))

    try:
        supabase.table('cargos').insert({
            'id': id_cargo,
            'nome_cargo': nome_cargo
        }).execute()

        supabase.table('permissoes_cargos').upsert({
            'cargo_id': id_cargo,
            'pode_ver_fila_breed': request.form.get('pode_ver_fila_breed') is not None,
            'pode_fazer_pedido_breed': request.form.get('pode_fazer_pedido_breed') is not None,
            'pode_assumir_breed': request.form.get('pode_assumir_breed') is not None,
            'pode_concluir_breed': request.form.get('pode_concluir_breed') is not None,
            'pode_ver_gestao_breed': request.form.get('pode_ver_gestao_breed') is not None,
            'pode_gerenciar_cargos': request.form.get('pode_gerenciar_cargos') is not None,
            'pode_gerenciar_eventos': request.form.get('pode_gerenciar_eventos') is not None,
            'pode_gerenciar_torneios': request.form.get('pode_gerenciar_torneios') is not None,
            'pode_gerenciar_precos': request.form.get('pode_gerenciar_precos') is not None,
            'pode_gerenciar_midias': request.form.get('pode_gerenciar_midias') is not None,
            'pode_gerenciar_conquistas': request.form.get('pode_gerenciar_conquistas') is not None,
            'pode_revisar_builds': request.form.get('pode_revisar_builds') is not None,
            'pode_gerenciar_economia': request.form.get('pode_gerenciar_economia') is not None,
            'pode_gerenciar_reino': request.form.get('pode_gerenciar_reino') is not None
        }).execute()

        flash(f'Cargo "{nome_cargo}" criado com sucesso!', 'sucesso')
    except Exception as e:
        flash(f'Erro ao criar cargo: {e}', 'erro')

    return redirect(url_for('admin_cargos'))


@app.route('/alterar-cargo/<path:email_usuario>', methods=['POST'])
@login_required
def alterar_cargo(email_usuario):
    """Altera o cargo de um determinado membro do clã."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes or not permissoes.get('pode_gerenciar_cargos', False):
        flash('Acesso negado.', 'erro')
        return redirect(url_for('painel'))

    novo_cargo = request.form.get('novo_cargo')

    try:
        supabase.table('usuarios_clan').update({
            'cargo': novo_cargo
        }).eq('email', email_usuario).execute()

        flash(f'Cargo do usuário atualizado para {novo_cargo.upper()}!', 'sucesso')
    except Exception as e:
        flash(f'Erro ao atualizar cargo: {e}', 'erro')

    return redirect(url_for('admin_cargos'))



# ============================================================================
# EVENTOS E TORNEIOS
# ============================================================================

def _pode_administrar_conteudo():
    return tem_permissao('pode_gerenciar_eventos') or tem_permissao('pode_gerenciar_torneios')


@app.route('/eventos')
def eventos():
    try:
        dados = supabase.table('eventos').select('*').eq('publicado', True).order('data_evento').execute().data or []
    except Exception as e:
        print(f'Erro ao carregar eventos: {e}')
        dados = []
    email=session.get('usuario_email')
    for e in dados:
        ins=_safe_table('inscricoes_evento','*',evento_id=e.get('id'))
        e['participantes']=ins
        e['total_inscritos']=len(ins)
        e['usuario_inscrito']=bool(email and any(x.get('usuario_email')==email for x in ins))

    # V7: a tela de Eventos também exibe uma prévia dos torneios, como no
    # conceito visual consolidado. A rota /torneios continua sendo a tela
    # completa e mantém todas as ações já existentes.
    torneios_resumo = []
    try:
        torneios_resumo = supabase.table('torneios').select('*').eq('publicado', True).order('data_torneio').limit(6).execute().data or []
        for t in torneios_resumo:
            inscr = _safe_table('inscricoes_torneio', '*', torneio_id=t.get('id'))
            t['total_inscritos'] = len(inscr)
    except Exception as e:
        print(f'Erro ao carregar resumo de torneios em eventos: {e}')

    return render_template('eventos.html', eventos=dados, torneios_resumo=torneios_resumo)


@app.route('/torneios')
def torneios():
    try:
        dados = supabase.table('torneios').select('*').eq('publicado', True).order('data_torneio').execute().data or []
        for t in dados:
            try:
                inscr = supabase.table('inscricoes_torneio').select('id').eq('torneio_id', t['id']).execute().data or []
                t['total_inscritos'] = len(inscr)
                t['participantes'] = _safe_table('inscricoes_torneio','*',torneio_id=t['id'])
                t['usuario_inscrito'] = bool(session.get('usuario_email') and any(x.get('usuario_email')==session.get('usuario_email') for x in t['participantes']))
                t['partidas'] = _safe_table('partidas_torneio','*',torneio_id=t['id'])
                t['campeao'] = t.get('campeao_nick') if t.get('status_torneio') == 'finalizado' else None
            except Exception:
                t['total_inscritos'] = 0
                t['participantes'] = []; t['partidas']=[]; t['usuario_inscrito']=False; t['campeao']=None
    except Exception as e:
        print(f'Erro ao carregar torneios: {e}')
        dados = []
    mapa_temporadas = {x.get('id'): x.get('nome') for x in _safe_table('temporadas')}
    mapa_formatos = {x.get('codigo'): x.get('nome') for x in _safe_table('formatos_competitivos')}
    for t in dados:
        t['temporada_nome'] = mapa_temporadas.get(t.get('temporada_id'))
        t['formato_nome_config'] = mapa_formatos.get(t.get('formato_codigo'))
    return render_template('torneios.html', torneios=dados)


@app.route('/torneios/<int:torneio_id>/inscrever', methods=['POST'])
@login_required
def inscrever_torneio(torneio_id):
    email = session.get('usuario_email')
    nick = session.get('nick_jogo')
    try:
        torneio = supabase.table('torneios').select('*').eq('id', torneio_id).limit(1).execute().data
        if not torneio:
            flash('Torneio não encontrado.', 'erro')
            return redirect(url_for('torneios'))
        torneio = torneio[0]
        if not torneio.get('inscricoes_abertas'):
            flash('As inscrições deste torneio estão fechadas.', 'erro')
            return redirect(url_for('torneios'))

        existentes = supabase.table('inscricoes_torneio').select('id').eq('torneio_id', torneio_id).eq('usuario_email', email).execute().data or []
        if existentes:
            flash('Você já está inscrito neste torneio.', 'info')
            return redirect(url_for('torneios'))

        limite = torneio.get('limite_participantes')
        if limite:
            total = supabase.table('inscricoes_torneio').select('id').eq('torneio_id', torneio_id).execute().data or []
            if len(total) >= int(limite):
                flash('As vagas deste torneio já foram preenchidas.', 'erro')
                return redirect(url_for('torneios'))

        supabase.table('inscricoes_torneio').insert({
            'torneio_id': torneio_id,
            'usuario_email': email,
            'nick_jogo': nick
        }).execute()
        criar_notificacao(email, 'Inscrição confirmada', f"Você está inscrito no torneio {torneio.get('titulo')}.", 'torneio', url_for('torneios'))
        flash('Inscrição realizada com sucesso! 🏆', 'sucesso')
    except Exception as e:
        flash(f'Não foi possível realizar a inscrição: {e}', 'erro')
    return redirect(url_for('torneios'))


@app.route('/admin/conteudo')
@login_required
def admin_conteudo():
    if not _pode_administrar_conteudo():
        flash('Você não tem permissão para gerenciar eventos e torneios.', 'erro')
        return redirect(url_for('painel'))
    try:
        eventos_lista = supabase.table('eventos').select('*').order('data_evento', desc=True).execute().data or []
        torneios_lista = supabase.table('torneios').select('*').order('data_torneio', desc=True).execute().data or []
    except Exception as e:
        flash(f'Erro ao carregar conteúdo: {e}', 'erro')
        eventos_lista, torneios_lista = [], []
    for e in eventos_lista: e['total_inscritos']=len(_safe_table('inscricoes_evento','id',evento_id=e.get('id')))
    for t in torneios_lista: t['total_inscritos']=len(_safe_table('inscricoes_torneio','id',torneio_id=t.get('id')))
    temporadas_lista = sorted(_safe_table('temporadas'), key=lambda x: str(x.get('inicio') or ''), reverse=True)
    formatos_lista = sorted([x for x in _safe_table('formatos_competitivos') if x.get('ativo', True)], key=lambda x:(x.get('nome') or '').casefold())
    replays = sorted(_safe_table('hype_live_replays'), key=lambda x: str(x.get('created_at') or ''), reverse=True)
    cfg = {x.get('chave'): (x.get('valor') or '') for x in _safe_table('configuracoes_site')}
    return render_template('admin_conteudo.html', eventos=eventos_lista, torneios=torneios_lista, temporadas=temporadas_lista,
                           formatos_competitivos=formatos_lista, replays=replays, cfg=cfg)


@app.route('/admin/eventos/criar', methods=['POST'])
@login_required
def criar_evento():
    if not _pode_administrar_conteudo():
        flash('Acesso negado.', 'erro')
        return redirect(url_for('painel'))
    try:
        supabase.table('eventos').insert({
            'titulo': request.form.get('titulo', '').strip(),
            'descricao': request.form.get('descricao', '').strip(),
            'data_evento': request.form.get('data_evento'),
            'local_evento': request.form.get('local_evento', '').strip() or None,
            'imagem_url': request.form.get('imagem_url', '').strip() or None,
            'limite_participantes': int(request.form.get('limite_participantes')) if request.form.get('limite_participantes') else None,
            'publicado': request.form.get('publicado') == 'on',
            'criado_por': session.get('usuario_email')
        }).execute()
        flash('Evento publicado com sucesso! 📅', 'sucesso')
    except Exception as e:
        flash(f'Erro ao criar evento: {e}', 'erro')
    return redirect(url_for('admin_conteudo'))


@app.route('/admin/torneios/criar', methods=['POST'])
@login_required
def criar_torneio():
    if not _pode_administrar_conteudo():
        flash('Acesso negado.', 'erro')
        return redirect(url_for('painel'))
    try:
        supabase.table('torneios').insert({
            'titulo': request.form.get('titulo', '').strip(),
            'descricao': request.form.get('descricao', '').strip(),
            'data_torneio': request.form.get('data_torneio'),
            'formato': request.form.get('formato', '').strip() or None,
            'formato_codigo': request.form.get('formato_codigo') or None,
            'temporada_id': int(request.form.get('temporada_id')) if request.form.get('temporada_id') else None,
            'ranking_ativo': request.form.get('ranking_ativo') == 'on',
            'pontos_campeao': max(0, int(request.form.get('pontos_campeao') or 10)),
            'pontos_vice': max(0, int(request.form.get('pontos_vice') or 6)),
            'regras': request.form.get('regras', '').strip() or None,
            'premio': request.form.get('premio', '').strip() or None,
            'imagem_url': request.form.get('imagem_url', '').strip() or None,
            'limite_participantes': int(request.form.get('limite_participantes')) if request.form.get('limite_participantes') else None,
            'inscricoes_abertas': request.form.get('inscricoes_abertas') == 'on',
            'publicado': request.form.get('publicado') == 'on',
            'criado_por': session.get('usuario_email')
        }).execute()
        flash('Torneio publicado com sucesso! 🏆', 'sucesso')
    except Exception as e:
        flash(f'Erro ao criar torneio: {e}', 'erro')
    return redirect(url_for('admin_conteudo'))


@app.route('/admin/eventos/<int:item_id>/excluir', methods=['POST'])
@login_required
def excluir_evento(item_id):
    if not _pode_administrar_conteudo():
        flash('Acesso negado.', 'erro')
        return redirect(url_for('painel'))
    try:
        supabase.table('eventos').delete().eq('id', item_id).execute()
        flash('Evento excluído.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao excluir evento: {e}', 'erro')
    return redirect(url_for('admin_conteudo'))


@app.route('/admin/torneios/<int:item_id>/excluir', methods=['POST'])
@login_required
def excluir_torneio(item_id):
    if not _pode_administrar_conteudo():
        flash('Acesso negado.', 'erro')
        return redirect(url_for('painel'))
    try:
        supabase.table('torneios').delete().eq('id', item_id).execute()
        flash('Torneio excluído.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao excluir torneio: {e}', 'erro')
    return redirect(url_for('admin_conteudo'))



@app.route('/eventos/<int:evento_id>/inscrever', methods=['POST'])
@login_required
def inscrever_evento(evento_id):
    email=session['usuario_email']; nick=session.get('nick_jogo') or email
    try:
        existentes=supabase.table('inscricoes_evento').select('id').eq('evento_id',evento_id).eq('usuario_email',email).execute().data or []
        if existentes: flash('Você já está inscrito neste evento.','info')
        else:
            evento=(supabase.table('eventos').select('*').eq('id',evento_id).limit(1).execute().data or [None])[0]
            if not evento: flash('Evento não encontrado.','erro')
            else:
                limite=evento.get('limite_participantes')
                total=supabase.table('inscricoes_evento').select('id').eq('evento_id',evento_id).execute().data or []
                if limite and len(total)>=int(limite): flash('As vagas deste evento acabaram.','erro')
                else:
                    supabase.table('inscricoes_evento').insert({'evento_id':evento_id,'usuario_email':email,'nick_jogo':nick}).execute()
                    criar_notificacao(email, 'Participação confirmada', f"Você está participando de {evento.get('titulo')}.", 'evento', url_for('eventos'))
                    flash('Inscrição no evento realizada!','sucesso')
    except Exception as e: flash(f'Erro na inscrição: {e}','erro')
    return redirect(url_for('eventos'))

@app.route('/eventos/<int:evento_id>/cancelar', methods=['POST'])
@login_required
def cancelar_evento(evento_id):
    try:
        supabase.table('inscricoes_evento').delete().eq('evento_id',evento_id).eq('usuario_email',session['usuario_email']).execute()
        flash('Inscrição no evento cancelada.','sucesso')
    except Exception as e: flash(f'Erro: {e}','erro')
    return redirect(url_for('eventos'))

@app.route('/torneios/<int:torneio_id>/cancelar', methods=['POST'])
@login_required
def cancelar_torneio(torneio_id):
    try:
        supabase.table('inscricoes_torneio').delete().eq('torneio_id',torneio_id).eq('usuario_email',session['usuario_email']).execute()
        flash('Inscrição no torneio cancelada.','sucesso')
    except Exception as e: flash(f'Erro: {e}','erro')
    return redirect(url_for('torneios'))


@app.route('/admin/eventos/<int:item_id>/editar', methods=['POST'])
@login_required
def editar_evento(item_id):
    if not tem_permissao('pode_gerenciar_eventos'): return redirect(url_for('painel'))
    payload={'titulo':request.form.get('titulo','').strip(),'descricao':request.form.get('descricao','').strip(),
             'data_evento':request.form.get('data_evento'),'local_evento':request.form.get('local_evento','').strip() or None,
             'imagem_url':request.form.get('imagem_url','').strip() or None,
             'limite_participantes':int(request.form.get('limite_participantes')) if request.form.get('limite_participantes') else None,
             'publicado':request.form.get('publicado')=='on'}
    try: supabase.table('eventos').update(payload).eq('id',item_id).execute(); flash('Evento atualizado.','sucesso')
    except Exception as e: flash(f'Erro: {e}','erro')
    return redirect(url_for('admin_conteudo'))

@app.route('/admin/torneios/<int:item_id>/editar', methods=['POST'])
@login_required
def editar_torneio(item_id):
    if not tem_permissao('pode_gerenciar_torneios'): return redirect(url_for('painel'))
    payload={'titulo':request.form.get('titulo','').strip(),'descricao':request.form.get('descricao','').strip(),
             'data_torneio':request.form.get('data_torneio'),'formato':request.form.get('formato','').strip() or None,
             'formato_codigo':request.form.get('formato_codigo') or None,
             'temporada_id':int(request.form.get('temporada_id')) if request.form.get('temporada_id') else None,
             'ranking_ativo':request.form.get('ranking_ativo')=='on',
             'pontos_campeao':max(0,int(request.form.get('pontos_campeao') or 10)),
             'pontos_vice':max(0,int(request.form.get('pontos_vice') or 6)),
             'regras':request.form.get('regras','').strip() or None,'premio':request.form.get('premio','').strip() or None,
             'limite_participantes':int(request.form.get('limite_participantes')) if request.form.get('limite_participantes') else None,
             'publicado':request.form.get('publicado')=='on','inscricoes_abertas':request.form.get('inscricoes_abertas')=='on'}
    try: supabase.table('torneios').update(payload).eq('id',item_id).execute(); flash('Torneio atualizado.','sucesso')
    except Exception as e: flash(f'Erro: {e}','erro')
    return redirect(url_for('admin_conteudo'))

@app.route('/admin/eventos/<int:item_id>/participantes')
@login_required
def participantes_evento(item_id):
    if not tem_permissao('pode_gerenciar_eventos'): return redirect(url_for('painel'))
    return render_template('admin_participantes.html', tipo='evento', item_id=item_id,
                           participantes=_safe_table('inscricoes_evento','*',evento_id=item_id))

@app.route('/admin/torneios/<int:item_id>/participantes')
@login_required
def participantes_torneio(item_id):
    if not tem_permissao('pode_gerenciar_torneios'): return redirect(url_for('painel'))
    return render_template('admin_participantes.html', tipo='torneio', item_id=item_id,
                           participantes=_safe_table('inscricoes_torneio','*',torneio_id=item_id))

@app.route('/admin/torneios/<int:torneio_id>/gerar-chave', methods=['POST'])
@login_required
def gerar_chave_torneio(torneio_id):
    if not tem_permissao('pode_gerenciar_torneios'): return redirect(url_for('painel'))
    inscritos=_safe_table('inscricoes_torneio','*',torneio_id=torneio_id)
    if len(inscritos)<2:
        flash('São necessários pelo menos 2 participantes.','erro'); return redirect(url_for('admin_conteudo'))
    try:
        supabase.table('partidas_torneio').delete().eq('torneio_id',torneio_id).execute()
        # Chave inicial determinística pela ordem de inscrição.
        inscritos=sorted(inscritos,key=lambda x:(x.get('created_at') or '',x.get('id') or 0))
        potencia=1
        while potencia<len(inscritos): potencia*=2
        jogadores=[{'email':x.get('usuario_email'),'nick':x.get('nick_jogo')} for x in inscritos]+[None]*(potencia-len(inscritos))
        ordem=1
        for i in range(0,potencia,2):
            a,b=jogadores[i],jogadores[i+1]
            vencedor=a or b
            payload={'torneio_id':torneio_id,'rodada':1,'ordem':ordem,
                     'jogador1_email':a.get('email') if a else None,'jogador1_nick':a.get('nick') if a else 'BYE',
                     'jogador2_email':b.get('email') if b else None,'jogador2_nick':b.get('nick') if b else 'BYE',
                     'status':'finalizada' if vencedor and (not a or not b) else 'pendente',
                     'vencedor_email':vencedor.get('email') if vencedor and (not a or not b) else None,
                     'vencedor_nick':vencedor.get('nick') if vencedor and (not a or not b) else None}
            supabase.table('partidas_torneio').insert(payload).execute(); ordem+=1
        supabase.table('torneios').update({'inscricoes_abertas':False,'status_torneio':'em_andamento'}).eq('id',torneio_id).execute()
        flash('Chaveamento criado e inscrições fechadas.','sucesso')
    except Exception as e: flash(f'Erro ao gerar chave: {e}','erro')
    return redirect(url_for('admin_conteudo'))

@app.route('/admin/partidas/<int:partida_id>/resultado', methods=['POST'])
@login_required
def resultado_partida(partida_id):
    if not tem_permissao('pode_gerenciar_torneios'): return redirect(url_for('painel'))
    vencedor=request.form.get('vencedor_email')
    try:
        rows=supabase.table('partidas_torneio').select('*').eq('id',partida_id).limit(1).execute().data or []
        if not rows: raise ValueError('Partida não encontrada')
        p=rows[0]
        if vencedor not in (p.get('jogador1_email'),p.get('jogador2_email')): raise ValueError('Vencedor inválido')
        nick=p.get('jogador1_nick') if vencedor==p.get('jogador1_email') else p.get('jogador2_nick')
        supabase.table('partidas_torneio').update({'vencedor_email':vencedor,'vencedor_nick':nick,'status':'finalizada','finalizada_em':agora_iso()}).eq('id',partida_id).execute()
        criar_notificacao(vencedor,'Vitória registrada',f'Você venceu uma partida do torneio.','torneio',url_for('torneios'))
        flash('Resultado registrado.','sucesso')
    except Exception as e: flash(f'Erro: {e}','erro')
    return redirect(url_for('admin_chave_torneio',torneio_id=p.get('torneio_id') if 'p' in locals() else 0))

@app.route('/admin/torneios/<int:torneio_id>/chave')
@login_required
def admin_chave_torneio(torneio_id):
    if not tem_permissao('pode_gerenciar_torneios'): return redirect(url_for('painel'))
    partidas=_safe_table('partidas_torneio','*',torneio_id=torneio_id)
    return render_template('admin_chave.html',torneio_id=torneio_id,partidas=sorted(partidas,key=lambda x:(x.get('rodada',0),x.get('ordem',0))))

@app.route('/admin/torneios/<int:torneio_id>/proxima-rodada', methods=['POST'])
@login_required
def proxima_rodada(torneio_id):
    if not tem_permissao('pode_gerenciar_torneios'): return redirect(url_for('painel'))
    partidas=_safe_table('partidas_torneio','*',torneio_id=torneio_id)
    if not partidas: return redirect(url_for('admin_conteudo'))
    rodada=max(int(x.get('rodada') or 1) for x in partidas)
    atuais=sorted([x for x in partidas if int(x.get('rodada') or 1)==rodada],key=lambda x:x.get('ordem') or 0)
    if any(x.get('status')!='finalizada' for x in atuais):
        flash('Finalize todas as partidas da rodada atual.','erro'); return redirect(url_for('admin_chave_torneio',torneio_id=torneio_id))
    vencedores=[{'email':x.get('vencedor_email'),'nick':x.get('vencedor_nick')} for x in atuais if x.get('vencedor_email')]
    if len(vencedores)==1:
        campeao = vencedores[0]
        final = atuais[0] if atuais else {}
        vice_email = final.get('jogador2_email') if campeao['email'] == final.get('jogador1_email') else final.get('jogador1_email')
        vice_nick = final.get('jogador2_nick') if campeao['email'] == final.get('jogador1_email') else final.get('jogador1_nick')
        torneio_rows = _safe_table('torneios','*',id=torneio_id)
        torneio = torneio_rows[0] if torneio_rows else {}
        atualizacao = {
            'status_torneio':'finalizado',
            'campeao_email':campeao['email'],
            'campeao_nick':campeao['nick'],
            'vice_campeao_email':vice_email,
            'vice_campeao_nick':vice_nick,
            'finalizado_em':agora_iso()
        }
        supabase.table('torneios').update(atualizacao).eq('id',torneio_id).execute()

        if torneio.get('ranking_ativo') and torneio.get('temporada_id') and not torneio.get('ranking_processado'):
            def adicionar_ranking(email, pontos, vitorias=0, podios=0):
                if not email: return
                atual = _safe_table('ranking_temporada','*',temporada_id=torneio.get('temporada_id'),usuario_email=email)
                row = atual[0] if atual else {}
                payload = {
                    'temporada_id': torneio.get('temporada_id'),
                    'usuario_email': email,
                    'pontos': int(row.get('pontos') or 0) + int(pontos or 0),
                    'vitorias': int(row.get('vitorias') or 0) + int(vitorias or 0),
                    'podios': int(row.get('podios') or 0) + int(podios or 0),
                    'updated_at': agora_iso()
                }
                supabase.table('ranking_temporada').upsert(payload,on_conflict='temporada_id,usuario_email').execute()
            adicionar_ranking(campeao['email'], torneio.get('pontos_campeao') or 10, 1, 1)
            adicionar_ranking(vice_email, torneio.get('pontos_vice') or 6, 0, 1)
            supabase.table('torneios').update({'ranking_processado':True}).eq('id',torneio_id).execute()
            registrar_log('pontuar_torneio','ranking','torneio',torneio_id,{
                'temporada_id':torneio.get('temporada_id'),
                'campeao':campeao['email'],
                'vice':vice_email,
                'pontos_campeao':torneio.get('pontos_campeao') or 10,
                'pontos_vice':torneio.get('pontos_vice') or 6
            })

        criar_notificacao(campeao['email'],'CAMPEÃO! 🏆','Você conquistou o torneio do Clã Hype!','campeao',url_for('torneios'))
        if vice_email:
            criar_notificacao(vice_email,'Vice-campeão HYPE','Você chegou à final do torneio HYPE.','torneio',url_for('torneios'))
        flash(f"Campeão definido: {campeao['nick']}! 🏆",'sucesso'); return redirect(url_for('admin_chave_torneio',torneio_id=torneio_id))
    if len(vencedores)%2:
        flash('Quantidade de vencedores inválida para próxima rodada.','erro'); return redirect(url_for('admin_chave_torneio',torneio_id=torneio_id))
    prox=rodada+1
    if any(int(x.get('rodada') or 0)==prox for x in partidas):
        flash('A próxima rodada já foi criada.','info'); return redirect(url_for('admin_chave_torneio',torneio_id=torneio_id))
    for i in range(0,len(vencedores),2):
        a,b=vencedores[i],vencedores[i+1]
        supabase.table('partidas_torneio').insert({'torneio_id':torneio_id,'rodada':prox,'ordem':i//2+1,
          'jogador1_email':a['email'],'jogador1_nick':a['nick'],'jogador2_email':b['email'],'jogador2_nick':b['nick'],'status':'pendente'}).execute()
    flash('Próxima rodada criada.','sucesso')
    return redirect(url_for('admin_chave_torneio',torneio_id=torneio_id))



def _breed_v312_clonar_tabela(origem_id, nome=None):
    origem = _breed_v312_tabela_por_id(origem_id)
    if not origem:
        raise ValueError('Tabela de origem não encontrada.')
    payload = {
        'nome': (nome or f"Cópia de {origem.get('nome') or 'Tabela HYPE'}").strip()[:120],
        'status': 'rascunho',
        'desconto_membro_hype_percentual': float(origem.get('desconto_membro_hype_percentual') or 0),
        'desconto_maximo_percentual': float(origem.get('desconto_maximo_percentual') or 100),
        'minimo_breeder_liquido': int(origem.get('minimo_breeder_liquido') or 0),
        'criado_por': session.get('usuario_email'),
        'updated_at': agora_iso(),
    }
    res = supabase.table('breed_tabelas_preco').insert(payload).execute().data or []
    if not res:
        raise RuntimeError('Não foi possível criar o rascunho.')
    nova = res[0]
    componentes = list(_breed_v312_componentes(origem_id).values())
    if componentes:
        supabase.table('breed_tabela_componentes').insert([{
            'tabela_id': nova['id'], 'codigo': x.get('codigo'), 'nome': x.get('nome'),
            'grupo': x.get('grupo'), 'valor': int(x.get('valor') or 0),
            'ativo': x.get('ativo', True), 'ordem': int(x.get('ordem') or 0),
            'updated_at': agora_iso()
        } for x in componentes]).execute()
    excecoes = _safe_table('breed_preco_especie_excecoes', '*', tabela_id=origem_id)
    if excecoes:
        supabase.table('breed_preco_especie_excecoes').insert([{
            'tabela_id': nova['id'], 'pokemon_id': int(x.get('pokemon_id')),
            'pokemon_nome': x.get('pokemon_nome') or f"Pokémon #{x.get('pokemon_id')}",
            'categoria_override': x.get('categoria_override'),
            'valor_base_override': x.get('valor_base_override'),
            'adicional_fixo': int(x.get('adicional_fixo') or 0),
            'multiplicador': float(x.get('multiplicador') or 1),
            'observacao': x.get('observacao')
        } for x in excecoes if x.get('pokemon_id')]).execute()
    _breed_v312_registrar_historico(nova['id'], 'criar_rascunho', detalhes={'origem_id':origem_id})
    return nova


def _breed_v312_status_visual(tabela):
    status = str(tabela.get('status') or '').lower()
    agora = datetime.now(timezone.utc)
    inicio = parse_data_supabase(tabela.get('inicio_em'))
    fim = parse_data_supabase(tabela.get('fim_em'))
    if status == 'agendada':
        if inicio and agora < inicio: return 'agendada'
        if (not inicio or inicio <= agora) and (not fim or agora < fim): return 'ativa_agora'
        if fim and agora >= fim: return 'encerrada'
    return status


def _breed_v312_relatorio():
    inicio = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        pedidos = supabase.table('pedidos_breed').select(
            'id,preco_total,taxa_clan_valor,valor_breeder,categoria_preco,breed_tipo,ha,zero_speed,status,created_at'
        ).gte('created_at', inicio).order('created_at', desc=True).limit(1000).execute().data or []
    except Exception as exc:
        print(f'[V31.2 relatorio] {exc}')
        pedidos = []
    faturamento = sum(int(x.get('preco_total') or 0) for x in pedidos)
    taxa = sum(int(x.get('taxa_clan_valor') or 0) for x in pedidos)
    breeder = sum(int(x.get('valor_breeder') or 0) for x in pedidos)
    return {
        'pedidos': len(pedidos), 'faturamento': faturamento, 'taxa_clan': taxa,
        'breeders': breeder, 'ticket_medio': int(faturamento / len(pedidos)) if pedidos else 0,
        'raros': sum(1 for x in pedidos if str(x.get('categoria_preco') or '').lower() == 'raro'),
        'ultra_raros': sum(1 for x in pedidos if str(x.get('categoria_preco') or '').lower() == 'ultra_raro'),
        'ha': sum(1 for x in pedidos if x.get('ha')),
        'zero_speed': sum(1 for x in pedidos if x.get('zero_speed')),
        'personalizados': sum(1 for x in pedidos if str(x.get('breed_tipo') or '').upper() == 'PERSONALIZADO' or x.get('modo_pedido') == 'personalizado'),
    }


def _breed_v312_impacto(tabela_id):
    cenarios = [
        ('Comum F5','F5',False,False,'comum'), ('Comum F5 + HA','F5',True,False,'comum'),
        ('Comum F5 + Zero','F5',False,True,'comum'), ('Comum HA + Zero','F5',True,True,'comum'),
        ('Raro F5','F5',False,False,'raro'), ('Raro F5 + HA','F5',True,False,'raro'),
        ('Raro HA + Zero','F5',True,True,'raro'), ('Raro F6 + HA','F6',True,False,'raro'),
        ('Ultra Raro F5','F5',False,False,'ultra_raro'), ('Ultra Raro + HA + Zero','F5',True,True,'ultra_raro'),
        ('Personalizado Comum','PERSONALIZADO',False,False,'comum'), ('Personalizado Raro + HA','PERSONALIZADO',True,False,'raro'),
        ('Personalizado Ultra Raro + HA','PERSONALIZADO',True,False,'ultra_raro'),
    ]
    saida=[]
    for nome, bt, ha, zero, cat in cenarios:
        calc = _calcular_preco_breed_v312(bt, ha=ha, zero_speed=zero, categoria=cat, nature='Adamant', tabela_id_override=tabela_id)
        if calc is not None:
            saida.append({'nome':nome,'valor':int(calc[0] or 0)})
    return saida

@app.route('/admin/precos', methods=['GET','POST'])
@login_required
def admin_precos():
    if not tem_permissao('pode_gerenciar_precos'):
        return redirect(url_for('painel'))
    if request.method == 'POST':
        acao = request.form.get('acao','').strip() or 'preco'
        try:
            if acao == 'criar_rascunho':
                origem_id = int(request.form.get('origem_id') or (_breed_v312_tabela_atual() or {}).get('id') or 0)
                nome = request.form.get('nome','').strip() or None
                nova = _breed_v312_clonar_tabela(origem_id, nome)
                flash(f"Rascunho '{nova.get('nome')}' criado. Edite e publique quando estiver pronto.", 'sucesso')

            elif acao == 'salvar_componente':
                tabela_id = int(request.form.get('tabela_id') or 0)
                tabela = _breed_v312_tabela_por_id(tabela_id)
                if not tabela or tabela.get('status') != 'rascunho':
                    raise ValueError('Somente um rascunho pode ser editado. Crie um rascunho da tabela atual primeiro.')
                codigo = request.form.get('codigo','').strip()
                if codigo not in BREED_V312_COMPONENTES_META:
                    raise ValueError('Componente de preço inválido.')
                valor = parse_valor_moeda(request.form.get('valor',0))
                atual = (_breed_v312_componentes(tabela_id).get(codigo) or {})
                anterior = int(atual.get('valor') or 0)
                nome, grupo, ordem = BREED_V312_COMPONENTES_META[codigo]
                supabase.table('breed_tabela_componentes').upsert({
                    'tabela_id':tabela_id,'codigo':codigo,'nome':nome,'grupo':grupo,'valor':valor,
                    'ativo':True,'ordem':ordem,'updated_at':agora_iso()
                }, on_conflict='tabela_id,codigo').execute()
                _breed_v312_registrar_historico(tabela_id,'alterar_componente',codigo,anterior,valor)
                flash(f'{nome} atualizado no rascunho.', 'sucesso')

            elif acao == 'salvar_regras':
                tabela_id = int(request.form.get('tabela_id') or 0)
                tabela = _breed_v312_tabela_por_id(tabela_id)
                if not tabela or tabela.get('status') != 'rascunho':
                    raise ValueError('As regras só podem ser alteradas em um rascunho.')
                nome = request.form.get('nome','').strip()[:120] or tabela.get('nome') or 'Tabela HYPE'
                membro = float((request.form.get('desconto_membro_hype_percentual') or '0').replace(',','.'))
                maximo = float((request.form.get('desconto_maximo_percentual') or '100').replace(',','.'))
                minimo = parse_valor_moeda(request.form.get('minimo_breeder_liquido',0))
                if not 0 <= membro <= 100 or not 0 <= maximo <= 100:
                    raise ValueError('Percentuais precisam ficar entre 0% e 100%.')
                supabase.table('breed_tabelas_preco').update({
                    'nome':nome,'desconto_membro_hype_percentual':membro,
                    'desconto_maximo_percentual':maximo,'minimo_breeder_liquido':minimo,
                    'updated_at':agora_iso()
                }).eq('id',tabela_id).execute()
                _breed_v312_registrar_historico(tabela_id,'alterar_regras',detalhes={'membro_pct':membro,'max_desconto_pct':maximo,'min_breeder':minimo})
                flash('Regras da tabela salvas.', 'sucesso')

            elif acao in ('publicar_tabela','agendar_tabela'):
                tabela_id = int(request.form.get('tabela_id') or 0)
                tabela = _breed_v312_tabela_por_id(tabela_id)
                if not tabela or tabela.get('status') != 'rascunho':
                    raise ValueError('Selecione um rascunho válido.')
                erros = _breed_v312_validar_tabela(tabela_id)
                if erros:
                    raise ValueError('Não é possível publicar: ' + ' '.join(erros))
                if acao == 'publicar_tabela':
                    for atual in _breed_v312_tabelas():
                        if atual.get('status') == 'ativa' and int(atual.get('id') or 0) != tabela_id:
                            supabase.table('breed_tabelas_preco').update({'status':'arquivada','updated_at':agora_iso()}).eq('id',atual.get('id')).execute()
                    supabase.table('breed_tabelas_preco').update({
                        'status':'ativa','inicio_em':agora_iso(),'fim_em':None,
                        'publicado_por':session.get('usuario_email'),'publicado_em':agora_iso(),'updated_at':agora_iso()
                    }).eq('id',tabela_id).execute()
                    _breed_v312_registrar_historico(tabela_id,'publicar_tabela')
                    flash('Nova tabela publicada. Somente novos pedidos usarão esses valores.', 'sucesso')
                else:
                    inicio = _promo_datetime_form_para_utc(request.form.get('inicio_em') or '')
                    fim = _promo_datetime_form_para_utc(request.form.get('fim_em') or '') if request.form.get('fim_em') else None
                    if not inicio:
                        raise ValueError('Informe quando a tabela agendada deve começar.')
                    if fim and _parse_promo_datetime(inicio) >= _parse_promo_datetime(fim):
                        raise ValueError('O término precisa ser posterior ao início.')
                    supabase.table('breed_tabelas_preco').update({
                        'status':'agendada','inicio_em':inicio,'fim_em':fim,
                        'publicado_por':session.get('usuario_email'),'publicado_em':agora_iso(),'updated_at':agora_iso()
                    }).eq('id',tabela_id).execute()
                    _breed_v312_registrar_historico(tabela_id,'agendar_tabela',detalhes={'inicio':inicio,'fim':fim})
                    flash('Tabela agendada. No período definido ela substituirá temporariamente a tabela normal.', 'sucesso')

            elif acao == 'arquivar_tabela':
                tabela_id = int(request.form.get('tabela_id') or 0)
                tabela = _breed_v312_tabela_por_id(tabela_id)
                if not tabela:
                    raise ValueError('Tabela não encontrada.')
                if tabela.get('status') == 'ativa':
                    raise ValueError('Não arquive a tabela ativa sem publicar/restaurar outra primeiro.')
                supabase.table('breed_tabelas_preco').update({'status':'arquivada','updated_at':agora_iso()}).eq('id',tabela_id).execute()
                _breed_v312_registrar_historico(tabela_id,'arquivar_tabela')
                flash('Tabela arquivada.', 'sucesso')

            elif acao == 'restaurar_tabela':
                tabela_id = int(request.form.get('tabela_id') or 0)
                tabela = _breed_v312_tabela_por_id(tabela_id)
                if not tabela:
                    raise ValueError('Versão não encontrada.')
                erros = _breed_v312_validar_tabela(tabela_id)
                if erros:
                    raise ValueError('Esta versão não pode ser restaurada: ' + ' '.join(erros))
                for atual in _breed_v312_tabelas():
                    if atual.get('status') == 'ativa' and int(atual.get('id') or 0) != tabela_id:
                        supabase.table('breed_tabelas_preco').update({'status':'arquivada','updated_at':agora_iso()}).eq('id',atual.get('id')).execute()
                supabase.table('breed_tabelas_preco').update({
                    'status':'ativa','inicio_em':agora_iso(),'fim_em':None,
                    'publicado_por':session.get('usuario_email'),'publicado_em':agora_iso(),'updated_at':agora_iso()
                }).eq('id',tabela_id).execute()
                _breed_v312_registrar_historico(tabela_id,'restaurar_tabela')
                flash('Versão restaurada como tabela ativa.', 'sucesso')

            elif acao == 'salvar_classificacao_pokemon':
                pokemon_id = int(request.form.get('pokemon_id') or 0)
                pokemon_nome = request.form.get('pokemon_nome','').strip()[:100]
                categoria_override = request.form.get('categoria_override','').strip().lower() or None
                ditto_mode = request.form.get('usa_ditto_override','auto').strip().lower()
                motivo_override = request.form.get('motivo_override','').strip()[:300] or None
                if pokemon_id <= 0 or not pokemon_nome:
                    raise ValueError('Informe ID e nome do Pokémon.')
                if categoria_override not in (None, *BREED_CATEGORIAS_PRECO):
                    raise ValueError('Categoria inválida.')
                if ditto_mode not in ('auto','sim','nao'):
                    raise ValueError('Regra de Ditto inválida.')
                if categoria_override == 'ultra_raro' and ditto_mode == 'nao':
                    raise ValueError('Ultra Raro significa que a espécie depende de Ditto. Use Ditto automático ou forçado.')
                if categoria_override in ('comum','raro') and ditto_mode == 'sim':
                    raise ValueError('Uma espécie forçada como dependente de Ditto será Ultra Rara. Remova a categoria manual ou escolha Ultra Raro.')
                ditto_override = None if ditto_mode == 'auto' else ditto_mode == 'sim'
                atual = classificar_pokemon_preco(pokemon_id)
                payload = {
                    'pokemon_id':pokemon_id,'pokemon_nome':pokemon_nome,
                    'categoria': atual.get('categoria_automatica') or 'comum',
                    'categoria_override':categoria_override,
                    'motivo_override':motivo_override,
                    'usa_ditto_override':ditto_override,
                    'usa_ditto_padrao': bool(ditto_override) if ditto_override is not None else False,
                    'gender_rate': atual.get('gender_rate'),
                    'classificacao_origem':'manual' if categoria_override or ditto_override is not None else 'automatico',
                    'classificacao_motivo': atual.get('classificacao_motivo'),
                    'updated_at':agora_iso()
                }
                supabase.table('pokemon_precificacao').upsert(payload, on_conflict='pokemon_id').execute()
                novo = classificar_pokemon_preco(pokemon_id)
                registrar_log('classificar_pokemon_preco','breed_pricing','pokemon',pokemon_id,{
                    'categoria_override':categoria_override,'usa_ditto_override':ditto_override,'motivo':motivo_override
                })
                if categoria_override or ditto_override is not None:
                    flash(f'{pokemon_nome}: exceção manual salva. Novos pedidos usarão a regra configurada.', 'sucesso')
                else:
                    flash(f'{pokemon_nome}: voltou para classificação automática.', 'sucesso')

            elif acao == 'salvar_excecao':
                tabela_id = int(request.form.get('tabela_id') or 0)
                tabela = _breed_v312_tabela_por_id(tabela_id)
                if not tabela or tabela.get('status') != 'rascunho':
                    raise ValueError('Exceções por Pokémon são editadas dentro de um rascunho.')
                pokemon_id = int(request.form.get('pokemon_id') or 0)
                pokemon_nome = request.form.get('pokemon_nome','').strip()[:100]
                if pokemon_id <= 0 or not pokemon_nome:
                    raise ValueError('Informe ID e nome do Pokémon.')
                cat = request.form.get('categoria_override','').strip().lower() or None
                if cat not in (None, *BREED_CATEGORIAS_PRECO):
                    raise ValueError('Categoria inválida.')
                base_raw = request.form.get('valor_base_override','').strip()
                base = parse_valor_moeda(base_raw) if base_raw else None
                adicional = parse_valor_moeda(request.form.get('adicional_fixo',0))
                mult = float((request.form.get('multiplicador') or '1').replace(',','.'))
                if mult < .1 or mult > 10:
                    raise ValueError('Multiplicador precisa ficar entre 0,1 e 10.')
                supabase.table('breed_preco_especie_excecoes').upsert({
                    'tabela_id':tabela_id,'pokemon_id':pokemon_id,'pokemon_nome':pokemon_nome,
                    'categoria_override':cat,'valor_base_override':base,'adicional_fixo':adicional,
                    'multiplicador':mult,'observacao':request.form.get('observacao','').strip()[:300] or None,
                    'updated_at':agora_iso()
                }, on_conflict='tabela_id,pokemon_id').execute()
                _breed_v312_registrar_historico(tabela_id,'salvar_excecao',detalhes={'pokemon_id':pokemon_id,'pokemon':pokemon_nome})
                flash('Regra especial do Pokémon salva.', 'sucesso')

            elif acao == 'excluir_excecao':
                tabela_id = int(request.form.get('tabela_id') or 0)
                pokemon_id = int(request.form.get('pokemon_id') or 0)
                tabela = _breed_v312_tabela_por_id(tabela_id)
                if not tabela or tabela.get('status') != 'rascunho':
                    raise ValueError('Somente exceções de rascunho podem ser removidas.')
                supabase.table('breed_preco_especie_excecoes').delete().eq('tabela_id',tabela_id).eq('pokemon_id',pokemon_id).execute()
                _breed_v312_registrar_historico(tabela_id,'excluir_excecao',detalhes={'pokemon_id':pokemon_id})
                flash('Exceção removida.', 'sucesso')

            elif acao == 'preco':
                # Compatibilidade com a tela legada / bancos que ainda não migraram.
                codigo=request.form.get('codigo','').strip(); valor=parse_valor_moeda(request.form.get('valor',0))
                supabase.table('precos_breed').update({'valor':valor}).eq('codigo',codigo).execute()
                flash('Preço legado atualizado.', 'sucesso')

            elif acao == 'criar_promocao':
                nome=request.form.get('nome','').strip() or 'Promoção HYPE'
                percentual=float((request.form.get('percentual') or '0').replace(',','.'))
                if percentual <= 0 or percentual > 100:
                    raise ValueError('O desconto deve ficar entre 0,01% e 100%.')
                tabela_atual = _breed_v312_tabela_atual()
                if tabela_atual and percentual > float(tabela_atual.get('desconto_maximo_percentual') or 100):
                    raise ValueError(f"Esta tabela permite no máximo {tabela_atual.get('desconto_maximo_percentual')}% de desconto.")
                todos=request.form.get('aplicar_todos')=='1'; codigos=request.form.getlist('codigos_preco')
                if not todos and not codigos:
                    raise ValueError('Selecione pelo menos um componente ou marque Aplicar em todos.')
                inicio_local=request.form.get('inicio_em') or None; fim_local=request.form.get('fim_em') or None
                inicio=_promo_datetime_form_para_utc(inicio_local); fim=_promo_datetime_form_para_utc(fim_local)
                if inicio and fim and _parse_promo_datetime(inicio) >= _parse_promo_datetime(fim):
                    raise ValueError('O término precisa ser posterior ao início.')
                codigo_cupom = request.form.get('codigo_cupom','').strip().upper() or None
                somente_membros = request.form.get('somente_membros_hype') == '1'
                limite_raw = request.form.get('limite_usos','').strip()
                limite = int(limite_raw) if limite_raw else None
                if limite is not None and limite <= 0:
                    raise ValueError('O limite de usos precisa ser maior que zero.')
                automatico = False if codigo_cupom else True
                payload = {'nome':nome,'percentual':percentual,'aplicar_todos':todos,'codigos_preco':codigos,
                           'inicio_em':inicio,'fim_em':fim,'ativo':True,'criado_por':session.get('usuario_email'),
                           'codigo_cupom':codigo_cupom,'aplicar_automaticamente':automatico,
                           'somente_membros_hype':somente_membros,'limite_usos':limite,'usos':0}
                supabase.table('promocoes_breed').insert(payload).execute()
                flash('Cupom criado.' if codigo_cupom else 'Promoção automática criada.', 'sucesso')

            elif acao == 'toggle_promocao':
                pid=int(request.form.get('promocao_id')); ativo=request.form.get('ativo')=='1'
                supabase.table('promocoes_breed').update({'ativo':ativo,'updated_at':agora_iso()}).eq('id',pid).execute()
                flash('Promoção atualizada.','sucesso')

            elif acao == 'excluir_promocao':
                pid=int(request.form.get('promocao_id'))
                supabase.table('promocoes_breed').delete().eq('id',pid).execute()
                flash('Promoção removida. Pedidos antigos mantêm o preço já fechado.','sucesso')

            elif acao == 'taxa_clan':
                taxa=float((request.form.get('taxa_clan_percentual') or '0').replace(',','.'))
                if taxa < 0 or taxa > 100:
                    raise ValueError('A taxa do clã deve ficar entre 0% e 100%.')
                supabase.table('configuracoes_site').upsert({'chave':'breed_taxa_clan_percentual','valor':str(taxa)},on_conflict='chave').execute()
                flash('Taxa do clã atualizada. Novos pedidos usarão o novo percentual.','sucesso')

        except ValueError as exc:
            flash(str(exc), 'erro')
        except Exception as exc:
            print(f'[V31.2 admin precos] {type(exc).__name__}: {exc}')
            flash('Não foi possível concluir a alteração de preços. Verifique as migrações V31.2/V31.3 e tente novamente.', 'erro')
        return redirect(url_for('admin_precos'))

    tabelas = _breed_v312_tabelas()
    pricing_v2 = bool(tabelas)
    tabela_atual = _breed_v312_tabela_atual() if pricing_v2 else None
    pricing_v3 = bool(tabela_atual and 'base_ultra_raro_f5' in _breed_v312_componentes(tabela_atual.get('id')))
    pricing_v4 = bool(tabela_atual and 'base_comum_personalizado' in _breed_v312_componentes(tabela_atual.get('id')))
    if tabela_atual:
        tabela_atual['status_visual'] = _breed_v312_status_visual(tabela_atual)
    rascunhos = sorted([x for x in tabelas if x.get('status') == 'rascunho'], key=lambda x:int(x.get('id') or 0), reverse=True)
    rascunho = rascunhos[0] if rascunhos else None
    tabela_edicao = rascunho or tabela_atual
    componentes = list(_breed_v312_componentes((tabela_edicao or {}).get('id')).values()) if tabela_edicao else []
    componentes.sort(key=lambda x:(int(x.get('ordem') or 0), str(x.get('nome') or '')))
    excecoes = _safe_table('breed_preco_especie_excecoes','*',tabela_id=tabela_edicao.get('id')) if tabela_edicao else []
    classificacoes_pokemon = []
    for row in _safe_table('pokemon_precificacao','*'):
        try:
            calculada = classificar_pokemon_preco(int(row.get('pokemon_id') or 0))
            exibicao = dict(row)
            exibicao.update({
                'categoria': calculada.get('categoria') or row.get('categoria') or 'comum',
                'categoria_automatica': calculada.get('categoria_automatica'),
                'classificacao_motivo': calculada.get('classificacao_motivo'),
                'taxa_femea_percentual': calculada.get('taxa_femea_percentual'),
                'so_com_ditto': calculada.get('so_com_ditto'),
            })
            classificacoes_pokemon.append(exibicao)
        except Exception:
            classificacoes_pokemon.append(row)
    classificacoes_pokemon.sort(key=lambda x: str(x.get('pokemon_nome') or '').lower())
    historico = []
    try:
        historico = supabase.table('breed_preco_historico').select('*').order('created_at',desc=True).limit(80).execute().data or []
    except Exception as exc:
        print(f'[V31.2 historico admin] {exc}')
    promos = _safe_table('promocoes_breed','*')
    agora = datetime.now(timezone.utc)
    for promo in promos:
        promo['status_calculado'] = _status_promocao(promo, agora)
        for campo in ('inicio_em','fim_em'):
            dt = _parse_promo_datetime(promo.get(campo))
            promo[campo + '_local'] = dt.astimezone(HYPE_TZ).strftime('%d/%m/%Y %H:%M') if dt else None
    promos.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    for tabela in tabelas:
        tabela['status_visual'] = _breed_v312_status_visual(tabela)
        for campo in ('inicio_em','fim_em','publicado_em','created_at'):
            dt = parse_data_supabase(tabela.get(campo))
            tabela[campo + '_local'] = dt.astimezone(HYPE_TZ).strftime('%d/%m/%Y %H:%M') if dt else None
    tabelas.sort(key=lambda x:int(x.get('id') or 0), reverse=True)
    alertas = _breed_v312_validar_tabela(tabela_edicao.get('id')) if tabela_edicao else []
    impacto_atual = _breed_v312_impacto(tabela_atual.get('id')) if tabela_atual else []
    impacto_rascunho = _breed_v312_impacto(rascunho.get('id')) if rascunho else []
    promo_itens = [x for x in componentes if x.get('codigo') in BREED_V312_COMPONENTES_META] if componentes else _safe_table('precos_breed','*')
    return render_template(
        'admin_precos.html', pricing_v2=pricing_v2, pricing_v3=pricing_v3, pricing_v4=pricing_v4, tabela_atual=tabela_atual, rascunho=rascunho,
        tabela_edicao=tabela_edicao, tabelas=tabelas, componentes=componentes, excecoes=excecoes,
        classificacoes_pokemon=classificacoes_pokemon,
        historico=historico, promocoes=promos, taxa_clan=obter_taxa_clan_breed(),
        alertas_preco=alertas, relatorio=_breed_v312_relatorio(), pacotes=BREED_V312_PACOTES,
        impacto_atual=impacto_atual, impacto_rascunho=impacto_rascunho, promo_itens=promo_itens,
        precos_legados=_safe_table('precos_breed','*')
    )


@app.route('/admin/precos/simular')
@login_required
def admin_precos_simular():
    if not tem_permissao('pode_gerenciar_precos'):
        return jsonify({'ok':False,'error':'Sem permissão.'}), 403
    try:
        tabela_id = int(request.args.get('tabela_id') or ((_breed_v312_tabela_atual() or {}).get('id') or 0))
        categoria = request.args.get('categoria','comum').strip().lower()
        bt = request.args.get('breed_tipo','F5').strip().upper()
        ha = request.args.get('ha','nao') == 'sim'
        zero = request.args.get('zero_speed','nao') == 'sim'
        ditto = request.args.get('usa_ditto','nao') == 'sim'
        genero = request.args.get('genero','indiferente')
        treinado = request.args.get('treinado','nao') == 'sim'
        nature = request.args.get('nature','sim') == 'sim'
        membro = request.args.get('membro_hype','nao') == 'sim'
        pokemon_id_raw = request.args.get('pokemon_id','').strip()
        pokemon_id = int(pokemon_id_raw) if pokemon_id_raw else None
        cupom = request.args.get('cupom','').strip().upper()
        usuario = session.get('usuario_email') if membro else None
        calc = _calcular_preco_breed_v312(bt,ha=ha,zero_speed=zero,categoria=categoria,usa_ditto=ditto,
                                          genero=genero,treinado=treinado,nature='Adamant' if nature else None,
                                          pokemon_id=pokemon_id,usuario_email=usuario,codigo_cupom=cupom,
                                          tabela_id_override=tabela_id, forcar_membro_hype=membro)
        if calc is None:
            return jsonify({'ok':False,'error':'Execute a migração V31.2 para habilitar o simulador.'}), 422
        total, detalhes = calc
        taxa_pct, taxa_valor, breeder = calcular_divisao_breed(total)
        return jsonify({'ok':True,'total':total,'taxa_percentual':taxa_pct,'taxa_valor':taxa_valor,'breeder_valor':breeder,**detalhes})
    except Exception as exc:
        print(f'[V31.2 simulador] {type(exc).__name__}: {exc}')
        return jsonify({'ok':False,'error':'Não foi possível simular esta combinação.'}), 400


@app.route('/admin/feed', methods=['GET','POST'])
@login_required
def admin_feed():
    if not _pode_administrar_conteudo(): return redirect(url_for('painel'))
    if request.method=='POST':
        tipo=request.form.get('tipo')
        tabela={'noticia':'noticias','video':'videos','galeria':'galeria'}.get(tipo)
        if tabela:
            payload={'titulo':request.form.get('titulo','').strip(),'url':request.form.get('url','').strip() or None,
                     'descricao':request.form.get('descricao','').strip() or None,'publicado':True}
            try:
                arquivo=request.files.get('arquivo')
                if arquivo and arquivo.filename and tipo == 'galeria':
                    nome=secure_filename(arquivo.filename); ext=os.path.splitext(nome)[1].lower()
                    if ext not in ('.png','.jpg','.jpeg','.webp','.gif'):
                        raise ValueError('Formato de imagem não permitido.')
                    caminho=f"galeria/{uuid4().hex}{ext}"
                    supabase.storage.from_('hype-media').upload(caminho, arquivo.read(), {'content-type': arquivo.mimetype or 'application/octet-stream'})
                    pub=supabase.storage.from_('hype-media').get_public_url(caminho)
                    payload['url']=pub if isinstance(pub,str) else getattr(pub,'public_url',None) or str(pub)
                supabase.table(tabela).insert(payload).execute(); registrar_log('publicar','midia',tabela,None,{'titulo':payload['titulo']}); flash('Conteúdo publicado.','sucesso')
            except Exception as e: flash(f'Erro: {e}','erro')
        return redirect(url_for('admin_feed'))
    return render_template('admin_feed.html', noticias=_safe_table('noticias'), videos=_safe_table('videos'), galeria=_safe_table('galeria'))

@app.route('/admin/conquistas', methods=['GET','POST'])
@login_required
def admin_conquistas():
    if not _pode_administrar_conteudo(): return redirect(url_for('painel'))
    if request.method=='POST':
        try:
            supabase.table('conquistas_usuario').insert({
                'usuario_email':request.form.get('usuario_email'),'titulo':request.form.get('titulo'),
                'descricao':request.form.get('descricao'),'icone':request.form.get('icone') or '🏅'
            }).execute(); flash('Conquista entregue!','sucesso')
        except Exception as e: flash(f'Erro: {e}','erro')
        return redirect(url_for('admin_conquistas'))
    return render_template('admin_conquistas.html', usuarios=_safe_table('usuarios_clan','email,nick_jogo'), conquistas=_safe_table('conquistas_usuario'))



# ============================================================================
# HYPE 4.0 - BUILDS, FUNÇÕES SECUNDÁRIAS E CANCELAMENTO DE BREED
# ============================================================================

def usuario_tem_funcao(email, funcao):
    if not email:
        return False
    try:
        dados = supabase.table('usuarios_funcoes').select('funcao').eq('usuario_email', email).eq('funcao', funcao).execute().data or []
        return bool(dados)
    except Exception:
        return False

@app.route('/breed/admin/resetar/<int:pedido_id>', methods=['POST'])
@login_required
def admin_resetar_breed(pedido_id):
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos', False):
        flash('Apenas administradores podem resetar pedidos.', 'erro')
        return redirect(url_for('breed_fila_breeders'))
    try:
        rows = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute().data or []
        if not rows:
            flash('Pedido não encontrado.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        pedido = rows[0]
        if pedido.get('status') in ('entregue','cancelado'):
            flash('Pedido entregue ou cancelado não pode ser resetado.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        anterior = pedido.get('status')
        updates = {
            'status':'pendente', 'breeder_responsavel':None, 'assumido_em':None,
            'pagamento_confirmado_em':None, 'pagamento_confirmado_por':None,
            'concluido_em':None, 'prazo_notificado':False,
            'cancelamento_solicitado_em':None, 'cancelamento_solicitado_por':None,
            'motivo_cancelamento_solicitado':None, 'status_antes_cancelamento':None,
            'cancelamento_decidido_em':None, 'cancelamento_decidido_por':None,
            'cancelamento_decisao':None
        }
        supabase.table('pedidos_breed').update(updates).eq('id', pedido_id).execute()
        registrar_historico('breed', pedido_id, anterior, 'pendente', 'Pedido resetado administrativamente e devolvido à fila.')
        registrar_log('resetar_pedido', 'breed', 'pedido_breed', pedido_id, {'status_anterior': anterior})
        criar_notificacao(pedido.get('usuario_email'), 'Pedido voltou para a fila', f"Seu pedido de {pedido.get('pokemon')} foi resetado pela administração e está aguardando um Breeder.", 'aviso', url_for('breed_meus_pedidos'))
        flash('Pedido resetado e devolvido para Pendente.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao resetar pedido: {e}', 'erro')
    return redirect(url_for('breed_fila_breeders'))


@app.route('/breed/restaurar/<int:pedido_id>', methods=['POST'])
@login_required
def restaurar_breed_cancelado(pedido_id):
    """V15.1: restaura um pedido cancelado para Pendente sem criar duplicata."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    try:
        rows = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute().data or []
        if not rows:
            flash('Pedido não encontrado.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        pedido = rows[0]
        if pedido.get('status') != 'cancelado':
            flash('Somente pedidos cancelados podem ser restaurados.', 'erro')
            return redirect(url_for('breed_fila_breeders'))

        admin = permissoes.get('pode_gerenciar_cargos', False)
        era_breeder = pedido.get('breeder_responsavel') == email
        cancelou = pedido.get('cancelado_por') == email
        if not admin and not (permissoes.get('pode_assumir_breed', False) and (era_breeder or cancelou)):
            flash('Você não tem permissão para restaurar este pedido.', 'erro')
            return redirect(url_for('breed_fila_breeders'))

        updates = {
            'status':'pendente', 'breeder_responsavel':None, 'assumido_em':None,
            'pagamento_confirmado_em':None, 'pagamento_confirmado_por':None,
            'concluido_em':None, 'entregue_em':None, 'prazo_notificado':False,
            'cancelado_em':None, 'cancelado_por':None, 'motivo_cancelamento':None,
            'cancelamento_solicitado_em':None, 'cancelamento_solicitado_por':None,
            'motivo_cancelamento_solicitado':None, 'status_antes_cancelamento':None,
            'cancelamento_decidido_em':None, 'cancelamento_decidido_por':None,
            'cancelamento_decisao':None
        }
        resultado = supabase.table('pedidos_breed').update(updates).eq('id', pedido_id).eq('status','cancelado').execute()
        if not resultado.data:
            flash('O pedido mudou de estado antes da restauração. Atualize a página.', 'erro')
            return redirect(url_for('breed_fila_breeders'))
        registrar_historico('breed', pedido_id, 'cancelado', 'pendente', f'Pedido restaurado para a fila por {email}.')
        registrar_log('restaurar_pedido', 'breed', 'pedido_breed', pedido_id, {'status_anterior':'cancelado'})
        criar_notificacao(pedido.get('usuario_email'), 'Pedido restaurado', f"Seu pedido #{pedido_id} de {pedido.get('pokemon')} voltou para a fila de Breeders.", 'aviso', url_for('breed_meus_pedidos'))
        flash('Pedido restaurado e devolvido para Pendente.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao restaurar pedido: {e}', 'erro')
    return redirect(url_for('breed_fila_breeders'))


@app.route('/breed/cancelar/<int:pedido_id>', methods=['POST'])
@login_required
def cancelar_breed(pedido_id):
    email = session.get('usuario_email')
    motivo = request.form.get('motivo','').strip()[:500]
    try:
        dados = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute().data or []
        if not dados:
            flash('Pedido não encontrado.', 'erro'); return redirect(url_for('breed'))
        p = dados[0]
        admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
        if p.get('usuario_email') != email and not admin:
            flash('Você não pode cancelar este pedido.', 'erro'); return redirect(url_for('breed'))
        if p.get('status') in ('entregue','cancelado') or (p.get('status') == 'concluido' and not admin):
            flash('Este pedido não pode mais ser cancelado.', 'erro'); return redirect(url_for('breed'))
        if p.get('status') == 'cancelamento_solicitado':
            flash('O cancelamento deste pedido já está aguardando decisão.', 'info'); return redirect(url_for('breed'))

        status_atual = p.get('status')
        if status_atual == 'pendente' or admin:
            supabase.table('pedidos_breed').update({
                'status':'cancelado','cancelado_em':agora_iso(),'cancelado_por':email,
                'motivo_cancelamento':motivo or None
            }).eq('id',pedido_id).execute()
            registrar_historico('breed',pedido_id,status_atual,'cancelado',motivo or 'Cancelamento direto')
            registrar_log('cancelar','breed','pedido_breed',pedido_id,{'motivo':motivo,'direto':True})
            if p.get('pagamento_confirmado_em'):
                valor_mov = int(p.get('preco_total') or 0)
                taxa_clan = int(p.get('taxa_clan_valor') or 0)
                valor_breeder = int(p.get('valor_breeder') or max(0, valor_mov - taxa_clan))
                ciclo = str(p.get('pagamento_confirmado_em') or 'sem_pagamento')
                registrar_transacao_hype(p.get('usuario_email'),'entrada','estorno_breed',f"Estorno do Breed #{pedido_id}",valor_mov,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('breeder_responsavel'),chave_unica=f'breed:{pedido_id}:estorno_cliente:{ciclo}')
                registrar_transacao_hype(p.get('breeder_responsavel'),'saida','estorno_breed',f"Estorno do Breed #{pedido_id}",valor_breeder,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('usuario_email'),chave_unica=f'breed:{pedido_id}:estorno_breeder:{ciclo}')
                cancelar_comissao_breed(pedido_id, 'Pedido cancelado pela administracao/cliente')
            if p.get('breeder_responsavel') and p.get('breeder_responsavel') != email:
                criar_notificacao(p.get('breeder_responsavel'),'Breed cancelado',f"O pedido de {p.get('pokemon')} foi cancelado.",'aviso',url_for('breed'))
            flash('Pedido cancelado.', 'sucesso')
            return redirect(url_for('breed'))

        # Após um Breeder assumir, o cliente solicita cancelamento e o Breeder decide.
        if status_atual not in ('aguardando_pagamento','em_producao'):
            flash('Este pedido não pode solicitar cancelamento neste status.', 'erro')
            return redirect(url_for('breed'))
        supabase.table('pedidos_breed').update({
            'status':'cancelamento_solicitado',
            'status_antes_cancelamento': status_atual,
            'cancelamento_solicitado_em': agora_iso(),
            'cancelamento_solicitado_por': email,
            'motivo_cancelamento_solicitado': motivo or None,
            'cancelamento_decisao': None,
            'cancelamento_decidido_em': None,
            'cancelamento_decidido_por': None
        }).eq('id',pedido_id).execute()
        registrar_historico('breed',pedido_id,status_atual,'cancelamento_solicitado',motivo)
        registrar_log('solicitar_cancelamento','breed','pedido_breed',pedido_id,{'motivo':motivo})
        if p.get('breeder_responsavel'):
            criar_notificacao(
                p.get('breeder_responsavel'),'Solicitação de cancelamento',
                f"O cliente solicitou cancelamento do pedido #{pedido_id} de {p.get('pokemon')}. Revise e aprove ou recuse.",
                'aviso',url_for('breed')
            )
        flash('Solicitação de cancelamento enviada ao Breeder responsável.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao cancelar pedido: {e}', 'erro')
    return redirect(url_for('breed'))


@app.route('/breed/cancelamento/<int:pedido_id>/<decisao>', methods=['POST'])
@login_required
def decidir_cancelamento_breed(pedido_id, decisao):
    email = session.get('usuario_email')
    if decisao not in ('aprovar','recusar'):
        flash('Decisão inválida.', 'erro'); return redirect(url_for('breed'))
    try:
        dados = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).limit(1).execute().data or []
        if not dados:
            flash('Pedido não encontrado.', 'erro'); return redirect(url_for('breed'))
        p = dados[0]
        admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
        if p.get('breeder_responsavel') != email and not admin:
            flash('Somente o Breeder responsável pode decidir este cancelamento.', 'erro')
            return redirect(url_for('breed'))
        if p.get('status') != 'cancelamento_solicitado':
            flash('Este pedido não possui cancelamento aguardando decisão.', 'erro')
            return redirect(url_for('breed'))

        if decisao == 'aprovar':
            novo_status = 'cancelado'
            updates = {
                'status':'cancelado','cancelado_em':agora_iso(),'cancelado_por':p.get('cancelamento_solicitado_por') or p.get('usuario_email'),
                'motivo_cancelamento':p.get('motivo_cancelamento_solicitado'),
                'cancelamento_decisao':'aprovado','cancelamento_decidido_em':agora_iso(),'cancelamento_decidido_por':email
            }
            msg = 'Seu pedido teve o cancelamento aprovado pelo Breeder.'
        else:
            novo_status = p.get('status_antes_cancelamento') or ('em_producao' if p.get('pagamento_confirmado_em') else 'aguardando_pagamento')
            if novo_status not in ('aguardando_pagamento','em_producao'):
                novo_status = 'aguardando_pagamento'
            updates = {
                'status':novo_status,
                'cancelamento_decisao':'recusado','cancelamento_decidido_em':agora_iso(),'cancelamento_decidido_por':email
            }
            msg = 'Sua solicitação de cancelamento foi recusada. O pedido voltou ao fluxo anterior.'

        supabase.table('pedidos_breed').update(updates).eq('id',pedido_id).eq('status','cancelamento_solicitado').execute()
        if decisao == 'aprovar' and p.get('pagamento_confirmado_em'):
            valor_mov = int(p.get('preco_total') or 0)
            taxa_clan = int(p.get('taxa_clan_valor') or 0)
            valor_breeder = int(p.get('valor_breeder') or max(0, valor_mov - taxa_clan))
            registrar_transacao_hype(p.get('usuario_email'),'entrada','estorno_breed',f"Estorno do Breed #{pedido_id}",valor_mov,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('breeder_responsavel'),chave_unica=f'breed:{pedido_id}:estorno_cliente:{str(p.get("pagamento_confirmado_em") or "sem_pagamento")}')
            registrar_transacao_hype(p.get('breeder_responsavel'),'saida','estorno_breed',f"Estorno do Breed #{pedido_id}",valor_breeder,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('usuario_email'),chave_unica=f'breed:{pedido_id}:estorno_breeder:{str(p.get("pagamento_confirmado_em") or "sem_pagamento")}')
            cancelar_comissao_breed(pedido_id, 'Cancelamento aprovado pelo Breeder/administracao')
        registrar_historico('breed',pedido_id,'cancelamento_solicitado',novo_status,f'Cancelamento {updates["cancelamento_decisao"]}.')
        registrar_log('decidir_cancelamento','breed','pedido_breed',pedido_id,{'decisao':updates['cancelamento_decisao']})
        criar_notificacao(p.get('usuario_email'),'Cancelamento do Breed',msg,'aviso',url_for('breed'))
        flash('Decisão de cancelamento registrada.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao decidir cancelamento: {e}', 'erro')
    return redirect(url_for('breed'))

@app.route('/builds')
@login_required
def builds():
    itens = _safe_table('builds','*',publicado=True)
    itens = sorted(itens,key=lambda x:x.get('created_at') or '',reverse=True)
    return render_template('builds.html', builds=itens)

@app.route('/builds/solicitar', methods=['GET','POST'])
@login_required
def solicitar_build():
    if request.method == 'POST':
        try:
            supabase.table('pedidos_build').insert({'usuario_email':session['usuario_email'],'pokemon':request.form.get('pokemon','').strip(),'objetivo':request.form.get('objetivo','').strip(),'observacoes':request.form.get('observacoes','').strip() or None}).execute()
            flash('Pedido de Build enviado!', 'sucesso'); return redirect(url_for('solicitar_build'))
        except Exception as e: flash(f'Erro ao enviar Build: {e}','erro')
    meus = _safe_table('pedidos_build','*',usuario_email=session['usuario_email'])
    return render_template('solicitar_build.html', pedidos=meus)

@app.route('/builder', methods=['GET','POST'])
@login_required
def painel_builder():
    email=session['usuario_email']; admin=bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    if not (usuario_tem_funcao(email,'builder') or admin):
        flash('Área exclusiva para Builders.', 'erro'); return redirect(url_for('painel'))
    if request.method=='POST':
        try:
            imagem_url=request.form.get('imagem_url','').strip() or None
            arquivo=request.files.get('imagem')
            if arquivo and arquivo.filename:
                nome=secure_filename(arquivo.filename); ext=os.path.splitext(nome)[1].lower()
                if ext not in ('.png','.jpg','.jpeg','.webp','.gif'):
                    raise ValueError('Formato de imagem não permitido.')
                caminho=f"portfolio/{email.replace('@','_')}/{uuid4().hex}{ext}"
                supabase.storage.from_('hype-media').upload(caminho, arquivo.read(), {'content-type': arquivo.mimetype or 'application/octet-stream'})
                pub=supabase.storage.from_('hype-media').get_public_url(caminho)
                imagem_url=pub if isinstance(pub,str) else getattr(pub,'public_url',None) or str(pub)
            supabase.table('builds').insert({'criado_por':email,'pokemon':request.form.get('pokemon','').strip(),'titulo':request.form.get('titulo','').strip(),'nature':request.form.get('nature','').strip() or None,'ability':request.form.get('ability','').strip() or None,'evs':request.form.get('evs','').strip() or None,'moves':request.form.get('moves','').strip() or None,'item':request.form.get('item','').strip() or None,'descricao':request.form.get('descricao','').strip() or None,'imagem_url':imagem_url,'publicado':True}).execute()
            flash('Build publicada!', 'sucesso')
        except Exception as e: flash(f'Erro: {e}','erro')
    fila=_safe_table('pedidos_build'); publicados=_safe_table('builds','*',criado_por=email)
    return render_template('builder.html', pedidos=fila, builds=publicados)

@app.route('/builder/pedido/<int:pedido_id>/assumir', methods=['POST'])
@login_required
def assumir_build(pedido_id):
    email=session['usuario_email']; admin=bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    if not (usuario_tem_funcao(email,'builder') or admin): return redirect(url_for('painel'))
    try: supabase.table('pedidos_build').update({'status':'em_andamento','builder_responsavel':email,'assumido_em':agora_iso()}).eq('id',pedido_id).eq('status','pendente').execute(); flash('Build assumida.','sucesso')
    except Exception as e: flash(f'Erro: {e}','erro')
    return redirect(url_for('painel_builder'))

@app.route('/builder/pedido/<int:pedido_id>/concluir', methods=['POST'])
@login_required
def concluir_build(pedido_id):
    email=session['usuario_email']; admin=bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    if not (usuario_tem_funcao(email,'builder') or admin): return redirect(url_for('painel'))
    try: supabase.table('pedidos_build').update({'status':'concluido','concluido_em':agora_iso()}).eq('id',pedido_id).eq('builder_responsavel',email).execute(); flash('Pedido de Build concluído.','sucesso')
    except Exception as e: flash(f'Erro: {e}','erro')
    return redirect(url_for('painel_builder'))



# ============================================================================
# HYPE 5.0 - CHAT, AVALIACOES, PRAZOS, AUDITORIA E BUILDER COMPLETO
# ============================================================================

def _is_admin(email=None):
    email = email or session.get('usuario_email')
    return bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos', False))

def registrar_log(acao, modulo, alvo_tipo=None, alvo_id=None, detalhes=None):
    try:
        supabase.table('logs_admin').insert({
            'usuario_email': session.get('usuario_email'), 'acao': acao, 'modulo': modulo,
            'alvo_tipo': alvo_tipo, 'alvo_id': str(alvo_id) if alvo_id is not None else None,
            'detalhes': detalhes or {}
        }).execute()
    except Exception as e: print(f'[logs_admin] {e}')

def registrar_historico(tipo, pedido_id, status_anterior, status_novo, observacao=None):
    try:
        supabase.table('historico_pedidos').insert({
            'tipo_pedido': tipo, 'pedido_id': pedido_id, 'usuario_email': session.get('usuario_email'),
            'status_anterior': status_anterior, 'status_novo': status_novo, 'observacao': observacao
        }).execute()
    except Exception as e: print(f'[historico] {e}')

def _pedido(tipo, pedido_id):
    tabela = 'pedidos_breed' if tipo == 'breed' else 'pedidos_build'
    dados = supabase.table(tabela).select('*').eq('id', pedido_id).limit(1).execute().data or []
    return dados[0] if dados else None

def _pode_ver_pedido(tipo, p, email):
    if not p: return False
    responsavel = p.get('breeder_responsavel') if tipo == 'breed' else p.get('builder_responsavel')
    return email in (p.get('usuario_email'), responsavel) or _is_admin(email)

def _dias_restantes(p):
    inicio = parse_data_supabase(p.get('assumido_em'))
    if not inicio: return None
    return max(-999, 3 - (datetime.now(timezone.utc) - inicio).days)

@app.route('/pedido/<tipo>/<int:pedido_id>/chat', methods=['GET','POST'])
@login_required
def chat_pedido(tipo, pedido_id):
    if tipo not in ('breed','build'): return redirect(url_for('painel'))
    email=session['usuario_email']; p=_pedido(tipo,pedido_id)
    if not _pode_ver_pedido(tipo,p,email):
        flash('Você não tem acesso a esta conversa.','erro'); return redirect(url_for('painel'))
    responsavel_atual = p.get('breeder_responsavel') if tipo == 'breed' else p.get('builder_responsavel')
    if not responsavel_atual and not _is_admin(email):
        flash('O chat será liberado assim que um responsável assumir o pedido.','info')
        return redirect(url_for('breed_meus_pedidos') if tipo == 'breed' else url_for('painel'))
    if request.method=='POST':
        if tipo == 'breed' and p.get('status') in ('entregue','cancelado'):
            flash('Esta conversa foi arquivada e está disponível somente para leitura.','info')
            return redirect(url_for('chat_pedido',tipo=tipo,pedido_id=pedido_id))
        msg=request.form.get('mensagem','').strip()[:1500]
        if msg:
            supabase.table('mensagens_pedido').insert({'tipo_pedido':tipo,'pedido_id':pedido_id,'remetente_email':email,'mensagem':msg}).execute()
            responsavel=p.get('breeder_responsavel') if tipo=='breed' else p.get('builder_responsavel')
            destino=responsavel if email==p.get('usuario_email') else p.get('usuario_email')
            if destino and destino!=email: criar_notificacao(destino,'Nova mensagem',f'Você recebeu uma mensagem no pedido #{pedido_id}.','mensagem',url_for('chat_pedido',tipo=tipo,pedido_id=pedido_id))
        return redirect(url_for('chat_pedido',tipo=tipo,pedido_id=pedido_id))
    msgs=supabase.table('mensagens_pedido').select('*').eq('tipo_pedido',tipo).eq('pedido_id',pedido_id).order('created_at').execute().data or []
    supabase.table('mensagens_pedido').update({'lida':True}).eq('tipo_pedido',tipo).eq('pedido_id',pedido_id).neq('remetente_email',email).execute()
    mapa = mapa_nicks_por_email()
    cliente_nick = mapa.get(p.get('usuario_email'), {}).get('nick') or p.get('player') or 'Membro HYPE'
    responsavel_nick = mapa.get(responsavel_atual, {}).get('nick') if responsavel_atual else None
    for m in msgs:
        remetente = m.get('remetente_email')
        if remetente == email:
            m['autor_nick'] = 'Você'
        elif remetente == p.get('usuario_email'):
            m['autor_nick'] = cliente_nick
        elif remetente == responsavel_atual:
            m['autor_nick'] = responsavel_nick or 'Breeder HYPE'
        else:
            m['autor_nick'] = mapa.get(remetente, {}).get('nick') or 'Equipe HYPE'
    return render_template('chat_pedido.html',tipo=tipo,pedido=p,mensagens=msgs,chat_readonly=(tipo == 'breed' and p.get('status') in ('entregue','cancelado')), cliente_nick=cliente_nick, responsavel_nick=responsavel_nick, permissoes=obter_permissoes_usuario(email))

@app.route('/pedido/<tipo>/<int:pedido_id>/avaliar', methods=['POST'])
@login_required
def avaliar_pedido(tipo,pedido_id):
    if tipo not in ('breed','build'): return redirect(url_for('painel'))
    email=session['usuario_email']; p=_pedido(tipo,pedido_id)
    status_permitido = p and ((tipo == 'breed' and p.get('status') == 'entregue') or (tipo == 'build' and p.get('status') in ('concluido','entregue')))
    if not p or p.get('usuario_email') != email or not status_permitido:
        flash('Este pedido não pode ser avaliado.','erro')
        return redirect(url_for('breed_meus_pedidos') if tipo == 'breed' else url_for('painel'))
    nota=int(request.form.get('nota') or 0); comentario=request.form.get('comentario','').strip()[:700]
    if nota not in range(1,6): flash('A nota deve ser de 1 a 5.','erro'); return redirect(url_for('painel'))
    avaliado=p.get('breeder_responsavel') if tipo=='breed' else p.get('builder_responsavel')
    try:
        supabase.table('avaliacoes').insert({'tipo_pedido':tipo,'pedido_id':pedido_id,'avaliador_email':email,'avaliado_email':avaliado,'nota':nota,'comentario':comentario or None}).execute()
        destino_avaliacao = url_for('perfil_breeder', nick=(mapa_nicks_por_email().get(avaliado, {}).get('nick') or session.get('nick_jogo'))) if tipo == 'breed' else url_for('painel')
        criar_notificacao(avaliado,'Nova avaliação',f'Você recebeu uma avaliação de {nota}/5.','sucesso',destino_avaliacao)
        flash('Avaliação enviada. Obrigado!','sucesso')
    except Exception: flash('Este pedido já foi avaliado ou ocorreu um erro.','erro')
    return redirect(url_for('breed_meus_pedidos') if tipo == 'breed' else url_for('painel'))

@app.route('/builder/disponibilidade', methods=['POST'])
@login_required
def disponibilidade_builder():
    email=session['usuario_email']
    if not (usuario_tem_funcao(email,'builder') or _is_admin(email)): return redirect(url_for('painel'))
    status=request.form.get('status','disponivel')
    if status not in ('disponivel','ocupado','indisponivel'): status='disponivel'
    supabase.table('disponibilidade_funcoes').upsert({'usuario_email':email,'funcao':'builder','status':status,'updated_at':agora_iso()}).execute()
    return redirect(url_for('painel_builder'))

@app.route('/breeder/disponibilidade', methods=['POST'])
@login_required
def disponibilidade_breeder():
    email=session['usuario_email']
    if not (usuario_tem_funcao(email,'breeder') or obter_permissoes_usuario(email).get('pode_assumir_breed') or _is_admin(email)): return redirect(url_for('painel'))
    status=request.form.get('status','disponivel')
    if status not in ('disponivel','ocupado','indisponivel'): status='disponivel'
    agora=agora_iso()
    supabase.table('disponibilidade_funcoes').upsert(
        {'usuario_email':email,'funcao':'breeder','status':status,'updated_at':agora},
        on_conflict='usuario_email,funcao'
    ).execute()
    # Mantém o perfil operacional sincronizado para telas/rotas antigas.
    supabase.table('breeders_perfil').upsert(
        {'usuario_email':email,'status':status,'updated_at':agora},on_conflict='usuario_email'
    ).execute()
    return redirect(request.referrer or url_for('painel_breeder_hype'))

@app.route('/builds/cancelar/<int:pedido_id>', methods=['POST'])
@login_required
def cancelar_build(pedido_id):
    email=session['usuario_email']; p=_pedido('build',pedido_id); motivo=request.form.get('motivo','').strip()[:500]
    if not p or (p.get('usuario_email')!=email and not _is_admin(email)):
        flash('Você não pode cancelar este pedido.','erro'); return redirect(url_for('solicitar_build'))
    if p.get('status') in ('concluido','cancelado'):
        flash('Este pedido não pode mais ser cancelado.','erro'); return redirect(url_for('solicitar_build'))
    supabase.table('pedidos_build').update({'status':'cancelado','cancelado_em':agora_iso(),'cancelado_por':email,'motivo_cancelamento':motivo or None}).eq('id',pedido_id).execute()
    registrar_historico('build',pedido_id,p.get('status'),'cancelado',motivo)
    registrar_log('cancelar','build','pedido_build',pedido_id,{'motivo':motivo})
    if p.get('builder_responsavel') and p.get('builder_responsavel')!=email: criar_notificacao(p['builder_responsavel'],'Build cancelada',f'O pedido #{pedido_id} foi cancelado.','aviso',url_for('painel_builder'))
    flash('Pedido de Build cancelado.','sucesso'); return redirect(url_for('solicitar_build'))

@app.route('/builder/pedido/<int:pedido_id>/entregar', methods=['POST'])
@login_required
def entregar_build(pedido_id):
    email=session['usuario_email']; p=_pedido('build',pedido_id)
    if not p or (p.get('builder_responsavel')!=email and not _is_admin(email)) or p.get('status')!='concluido':
        flash('Não foi possível entregar este pedido.','erro'); return redirect(url_for('painel_builder'))
    supabase.table('pedidos_build').update({'status':'entregue','entregue_em':agora_iso()}).eq('id',pedido_id).execute()
    registrar_historico('build',pedido_id,'concluido','entregue')
    criar_notificacao(p['usuario_email'],'Build entregue',f'Sua Build #{pedido_id} foi entregue. Você já pode avaliá-la.','sucesso',url_for('painel'))
    flash('Build entregue.','sucesso'); return redirect(url_for('painel_builder'))

@app.route('/builder/perfil/<nick>')
def perfil_builder(nick):
    us=supabase.table('usuarios_clan').select('*').ilike('nick_jogo',nick).limit(1).execute().data or []
    if not us: return redirect(url_for('pagina_inicial'))
    u=us[0]; email=u['email']
    itens=_safe_table('builds','*',criado_por=email); avals=_safe_table('avaliacoes','*',avaliado_email=email)
    avals=[a for a in avals if a.get('tipo_pedido')=='build']; media=round(sum(int(a.get('nota') or 0) for a in avals)/len(avals),1) if avals else None
    disp=_safe_table('disponibilidade_funcoes','*',usuario_email=email); disp=next((d for d in disp if d.get('funcao')=='builder'),None)
    return render_template('perfil_builder.html',usuario=u,builds=itens,avaliacoes=avals,media=media,disponibilidade=disp)

@app.route('/ranking/breeders')
@login_required
def ranking_breeders():
    mes=request.args.get('mes') or datetime.now(timezone.utc).strftime('%Y-%m')
    try: inicio=datetime.strptime(mes+'-01','%Y-%m-%d').replace(tzinfo=timezone.utc)
    except: inicio=datetime.now(timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0); mes=inicio.strftime('%Y-%m')
    fim=(inicio.replace(day=28)+timedelta(days=4)).replace(day=1)
    pedidos=supabase.table('pedidos_breed').select('*').in_('status',['concluido','entregue']).gte('concluido_em',inicio.isoformat()).lt('concluido_em',fim.isoformat()).execute().data or []
    mapa=mapa_nicks_por_email(); dados={}
    for p in pedidos:
        e=p.get('breeder_responsavel');
        if not e: continue
        d=dados.setdefault(e,{'email':e,'nick':mapa.get(e,{}).get('nick',e),'total':0,'valor':0}); d['total']+=1; d['valor']+=int(p.get('preco_total') or 0)
    avals=_safe_table('avaliacoes');
    for e,d in dados.items():
        notas=[int(a.get('nota') or 0) for a in avals if a.get('avaliado_email')==e and a.get('tipo_pedido')=='breed']; d['media']=round(sum(notas)/len(notas),1) if notas else None
    ranking=sorted(dados.values(),key=lambda x:(-x['total'],-x['valor']))
    return render_template('ranking_breeders.html',ranking=ranking,mes=mes)


# ============================================================================
# GRANDE ATUALIZACAO HYPE 2026-09-28
# Central dos Breeders + Hall da Fama + carreira detalhada
# ============================================================================
def _hype_dt(valor):
    if not valor: return None
    try:
        d=datetime.fromisoformat(str(valor).replace('Z','+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception: return None

def _hype_breeder_metricas(email, pedidos=None, avaliacoes=None):
    pedidos=pedidos if pedidos is not None else _safe_table('pedidos_breed','*')
    avaliacoes=avaliacoes if avaliacoes is not None else _safe_table('avaliacoes','*')
    meus=[p for p in pedidos if p.get('breeder_responsavel')==email]
    entregues=[p for p in meus if p.get('status')=='entregue']
    ativos=[p for p in meus if p.get('status') in ('aguardando_pagamento','em_producao','cancelamento_solicitado')]
    notas=[int(a.get('nota') or 0) for a in avaliacoes if a.get('avaliado_email')==email and a.get('tipo_pedido')=='breed' and a.get('nota')]
    tempos=[]
    for p in entregues:
        ini=_hype_dt(p.get('pagamento_confirmado_em') or p.get('assumido_em')); fim=_hype_dt(p.get('concluido_em'))
        if ini and fim and fim>=ini: tempos.append((fim-ini).total_seconds()/3600)
    finalizados=[p for p in meus if p.get('status') in ('entregue','cancelado')]
    taxa=(len(entregues)/len(finalizados)*100) if finalizados else None
    pok={}
    for p in entregues:
        n=p.get('pokemon') or 'Pokémon'; pok[n]=pok.get(n,0)+1
    return {'entregues':len(entregues),'ativos':len(ativos),'avaliacoes':len(notas),
      'media':round(sum(notas)/len(notas),1) if notas else None,
      'tempo_medio_h':round(sum(tempos)/len(tempos),1) if tempos else None,
      'taxa_conclusao':round(taxa,1) if taxa is not None else None,
      'top_pokemon':sorted(pok.items(),key=lambda x:(-x[1],x[0].casefold()))[:8]}

@app.route('/breeders/<nick>')
def perfil_breeder(nick):
    u=next((x for x in _safe_table('usuarios_clan','*') if str(x.get('nick_jogo') or '').casefold()==str(nick).casefold()),None)
    if not u: return redirect(url_for('team_breeders'))
    email=u.get('email'); pedidos=_safe_table('pedidos_breed','*'); avals=_safe_table('avaliacoes','*')
    metricas=_hype_breeder_metricas(email,pedidos,avals)
    perfil=next(iter(_safe_table('breeders_perfil','*',usuario_email=email)),{})
    disp=next((d for d in _safe_table('disponibilidade_funcoes','*',usuario_email=email) if d.get('funcao')=='breeder'),{})
    cons=_safe_table('conquistas_usuario','*',usuario_email=email)
    reviews=[a for a in avals if a.get('avaliado_email')==email and a.get('tipo_pedido')=='breed']
    reviews.sort(key=lambda x:str(x.get('created_at') or ''),reverse=True)
    mapa=mapa_nicks_por_email()
    for a in reviews: a['avaliador_nick']=mapa.get(a.get('avaliador_email'),{}).get('nick') or 'Membro HYPE'
    return render_template('perfil_breeder.html',usuario=u,perfil=perfil,disponibilidade=disp,metricas=metricas,conquistas=cons,avaliacoes=reviews[:30])

@app.route('/breed/hall-da-fama')
def breed_hall_fama():
    hall=_safe_table('hype_breed_hall_fama','*')
    meses=sorted({str(x.get('mes'))[:7] for x in hall if x.get('mes')},reverse=True)
    mes=request.args.get('mes') or (meses[0] if meses else datetime.now(timezone.utc).strftime('%Y-%m'))
    itens=[x for x in hall if str(x.get('mes') or '')[:7]==mes]; mapa=mapa_nicks_por_email()
    for x in itens: x['nick']=mapa.get(x.get('usuario_email'),{}).get('nick') or x.get('usuario_email')
    return render_template('breed_hall_fama.html',itens=itens,meses=meses,mes=mes)

@app.route('/admin/breed/hall-da-fama/fechar-mes',methods=['POST'])
@login_required
def admin_fechar_mes_breed():
    if not _is_admin(): return redirect(url_for('painel'))
    mes=(request.form.get('mes') or '').strip()
    try: inicio=datetime.strptime(mes+'-01','%Y-%m-%d').replace(tzinfo=timezone.utc)
    except Exception:
        flash('Mês inválido.','erro'); return redirect(url_for('ranking_breeders'))
    fim=(inicio.replace(day=28)+timedelta(days=4)).replace(day=1)
    entregues=[]
    for p in _safe_table('pedidos_breed','*'):
        d=_hype_dt(p.get('entregue_em') or p.get('recebimento_confirmado_em') or p.get('concluido_em'))
        if p.get('status')=='entregue' and d and inicio<=d<fim: entregues.append(p)
    mapa=mapa_nicks_por_email(); pb={}; pp={}; pc={}
    for p in entregues:
        b=p.get('breeder_responsavel'); c=p.get('usuario_email'); pk=p.get('pokemon') or 'Pokémon'
        if b: pb[b]=pb.get(b,0)+1
        if c: pc[c]=pc.get(c,0)+1
        pp[pk]=pp.get(pk,0)+1
    linhas=[]
    for pos,(e,total) in enumerate(sorted(pb.items(),key=lambda x:-x[1])[:3],1):
        linhas.append({'mes':inicio.date().isoformat(),'categoria':'breeder_entregas','usuario_email':e,'posicao':pos,'valor_numerico':total,'valor_texto':mapa.get(e,{}).get('nick') or e})
    for pos,(pk,total) in enumerate(sorted(pp.items(),key=lambda x:-x[1])[:3],1):
        linhas.append({'mes':inicio.date().isoformat(),'categoria':'pokemon_mais_breedado','pokemon':pk,'posicao':pos,'valor_numerico':total,'valor_texto':pk})
    for pos,(e,total) in enumerate(sorted(pc.items(),key=lambda x:-x[1])[:3],1):
        linhas.append({'mes':inicio.date().isoformat(),'categoria':'cliente_mais_pedidos','usuario_email':e,'posicao':pos,'valor_numerico':total,'valor_texto':mapa.get(e,{}).get('nick') or e})
    for row in linhas:
        try: supabase.table('hype_breed_hall_fama').insert(row).execute()
        except Exception as e: print('Hall HYPE:',e)
    registrar_log('fechar_mes','hype_breed_hall_fama','mes',mes,{'registros':len(linhas)})
    flash(f'Temporada Breed {mes} registrada no Hall da Fama.','sucesso')
    return redirect(url_for('breed_hall_fama',mes=mes))

@app.route('/admin/logs')
@login_required
def admin_logs():
    if not _is_admin(): return redirect(url_for('painel'))
    logs=supabase.table('logs_admin').select('*').order('created_at',desc=True).limit(200).execute().data or []
    return render_template('admin_logs.html',logs=logs)

@app.route('/admin/funcoes', methods=['GET','POST'])
@login_required
def admin_funcoes():
    if not _is_admin(): return redirect(url_for('painel'))
    if request.method=='POST':
        email=request.form.get('usuario_email'); funcao=request.form.get('funcao'); acao=request.form.get('acao')
        if funcao in ('breeder','builder','organizador_eventos','organizador_torneios'):
            if acao=='adicionar': supabase.table('usuarios_funcoes').upsert({'usuario_email':email,'funcao':funcao}).execute()
            elif acao=='remover': supabase.table('usuarios_funcoes').delete().eq('usuario_email',email).eq('funcao',funcao).execute()
            registrar_log(acao,'funcoes','usuario',email,{'funcao':funcao})
        return redirect(url_for('admin_funcoes'))
    return render_template('admin_funcoes.html',usuarios=_safe_table('usuarios_clan','email,nick_jogo,cargo'),funcoes=_safe_table('usuarios_funcoes'))

@app.route('/admin/pokemon-bloqueados', methods=['GET','POST'])
@login_required
def admin_pokemon_bloqueados():
    if not _is_admin(): return redirect(url_for('painel'))
    if request.method=='POST':
        nome=request.form.get('pokemon','').strip().lower(); acao=request.form.get('acao')
        if nome:
            if acao=='adicionar': supabase.table('pokemon_bloqueados').upsert({'pokemon':nome,'motivo':request.form.get('motivo','').strip() or None,'ativo':True}).execute()
            else: supabase.table('pokemon_bloqueados').delete().eq('pokemon',nome).execute()
            registrar_log(acao,'breed','pokemon',nome)
        return redirect(url_for('admin_pokemon_bloqueados'))
    return render_template('admin_pokemon_bloqueados.html',itens=_safe_table('pokemon_bloqueados'))

@app.context_processor
def hype5_context():
    email=session.get('usuario_email')
    funcoes=[]; nao_lidas=0
    if email:
        funcoes=[x.get('funcao') for x in _safe_table('usuarios_funcoes','funcao',usuario_email=email)]
        nao_lidas=len([x for x in _safe_table('mensagens_pedido','id,lida,remetente_email') if not x.get('lida') and x.get('remetente_email')!=email])
    return {'funcoes_usuario':funcoes,'mensagens_nao_lidas':nao_lidas,'dias_restantes':_dias_restantes,'discord_url':os.getenv('DISCORD_URL','')}


# ============================================================================
# CONSTRUTORES / LOJAS / PAINEL DO REINO
# ============================================================================

def registrar_atividade_reino(tipo, ator_email, descricao, referencia_tipo=None, referencia_id=None):
    try:
        supabase.table('atividades_reino').insert({
            'tipo': tipo,
            'ator_email': ator_email,
            'descricao': descricao,
            'referencia_tipo': referencia_tipo,
            'referencia_id': referencia_id
        }).execute()
    except Exception as e:
        print(f"Atividade do Reino não registrada: {e}")


# ============================================================================
# HYPE V31 - REINO HYPE 2.0 / ALUGUEIS E COBRANCAS
# Dividas semanais de casas e lojas: membro informa pagamento e Admin confirma.
# ============================================================================
def _reino_admin_financeiro(email=None):
    email = email or session.get('usuario_email')
    if not email:
        return False
    p = obter_permissoes_usuario(email)
    return bool(
        p.get('pode_gerenciar_reino')
        or p.get('pode_gerenciar_economia')
        or p.get('pode_gerenciar_cargos')
    )


def _reino_data(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor)[:10]).date()
    except Exception:
        return None


def _reino_sincronizar_cobrancas(usuario_email=None):
    """Gera cobranças vencidas de forma idempotente e avança o próximo vencimento.

    A função só avança o contrato quando a cobrança correspondente já existe ou
    foi criada com sucesso. Assim uma falha de schema/conexão não faz o Reino
    perder uma semana de aluguel.
    """
    hoje = datetime.now(timezone.utc).date()
    criadas = 0
    for tabela, tipo, id_key in (
        ('contratos_casas', 'casa', 'casa_id'),
        ('contratos_lojas', 'loja', 'loja_id'),
    ):
        filtros = {'status': 'ativo'}
        if usuario_email:
            filtros['usuario_email'] = usuario_email
        contratos = _safe_table(tabela, '*', **filtros)
        for contrato in contratos:
            venc = _reino_data(contrato.get('proximo_vencimento'))
            if not venc:
                continue
            processou = False
            seguranca = 0
            while venc <= hoje and seguranca < 260:
                seguranca += 1
                existente = _safe_table(
                    'hype_reino_cobrancas', 'id,status',
                    tipo_unidade=tipo,
                    contrato_id=contrato.get('id'),
                    referencia_vencimento=venc.isoformat(),
                )
                if not existente:
                    payload = {
                        'tipo_unidade': tipo,
                        'contrato_id': contrato.get('id'),
                        'usuario_email': contrato.get('usuario_email'),
                        'casa_id': contrato.get('casa_id') if tipo == 'casa' else None,
                        'loja_id': contrato.get('loja_id') if tipo == 'loja' else None,
                        'referencia_vencimento': venc.isoformat(),
                        'valor': max(0, int(contrato.get('valor_semanal') or 0)),
                        'status': 'pendente',
                        'gerada_em': agora_iso(),
                    }
                    try:
                        supabase.table('hype_reino_cobrancas').insert(payload).execute()
                        criadas += 1
                        criar_notificacao(
                            contrato.get('usuario_email'),
                            'Aluguel do Reino pendente',
                            f"O aluguel da sua {('casa' if tipo == 'casa' else 'loja')} venceu em {venc.strftime('%d/%m/%Y')}. Valor: {formatar_preco(payload['valor'])}.",
                            'aviso', url_for('reino_financeiro_usuario')
                        )
                    except Exception as e:
                        # Se outra requisição criou ao mesmo tempo, pode continuar.
                        texto = str(e).lower()
                        if 'duplicate' not in texto and 'unique' not in texto:
                            print(f'[V31 Reino] Falha ao gerar cobrança do contrato #{contrato.get("id")}: {e}')
                            break
                processou = True
                venc += timedelta(days=7)
            if processou:
                try:
                    supabase.table(tabela).update({'proximo_vencimento': venc.isoformat()}).eq('id', contrato.get('id')).execute()
                except Exception as e:
                    print(f'[V31 Reino] Falha ao avançar vencimento do contrato #{contrato.get("id")}: {e}')
            # Aviso de vencimento próximo (uma vez por data de vencimento).
            dias_para_vencer = (venc - hoje).days
            ultimo_aviso = str(contrato.get('ultimo_aviso_vencimento') or '')[:10]
            if 0 < dias_para_vencer <= 1 and ultimo_aviso != venc.isoformat():
                try:
                    criar_notificacao(
                        contrato.get('usuario_email'), 'Aluguel do Reino vence amanhã',
                        f"Seu aluguel de {('casa' if tipo == 'casa' else 'loja')} no valor de {formatar_preco(contrato.get('valor_semanal'))} vence em {venc.strftime('%d/%m/%Y')}.",
                        'aviso', url_for('reino_financeiro_usuario')
                    )
                    supabase.table(tabela).update({'ultimo_aviso_vencimento': venc.isoformat()}).eq('id', contrato.get('id')).execute()
                except Exception as e:
                    print(f'[V31 Reino] Aviso de vencimento não enviado para contrato #{contrato.get("id")}: {e}')
    return criadas


def _reino_decorar_cobrancas(cobrancas):
    cobrancas = [dict(x) for x in (cobrancas or [])]
    usuarios = {x.get('email'): x for x in _safe_table('usuarios_clan', 'email,nick_jogo,nome_exibicao,avatar_url')}
    casas = {x.get('id'): x for x in _safe_table('casas_reino')}
    lojas_map = {x.get('id'): x for x in _safe_table('lojas_reino')}
    for c in cobrancas:
        u = usuarios.get(c.get('usuario_email')) or {}
        c['usuario_nick'] = u.get('nome_exibicao') or u.get('nick_jogo') or c.get('usuario_email')
        c['avatar_url'] = u.get('avatar_url')
        if c.get('tipo_unidade') == 'casa':
            un = casas.get(c.get('casa_id')) or {}
            c['unidade_nome'] = un.get('nome') or f"Casa #{c.get('casa_id')}"
            c['unidade_codigo'] = un.get('codigo') or 'CASA'
        else:
            un = lojas_map.get(c.get('loja_id')) or {}
            c['unidade_nome'] = un.get('nome') or f"Loja #{c.get('loja_id')}"
            c['unidade_codigo'] = un.get('codigo') or (f"LOJA-{un.get('posicao'):03d}" if un.get('posicao') else 'LOJA')
    return cobrancas


def _reino_resumo_usuario(email):
    _reino_sincronizar_cobrancas(email)
    cobrancas = _safe_table('hype_reino_cobrancas', '*', usuario_email=email)
    contratos_c = _safe_table('contratos_casas', '*', usuario_email=email, status='ativo')
    contratos_l = _safe_table('contratos_lojas', '*', usuario_email=email, status='ativo')
    abertas = [x for x in cobrancas if x.get('status') in ('pendente', 'informado')]
    pendentes = [x for x in cobrancas if x.get('status') == 'pendente']
    informadas = [x for x in cobrancas if x.get('status') == 'informado']
    proximos = [
        _reino_data(x.get('proximo_vencimento'))
        for x in (contratos_c + contratos_l)
        if _reino_data(x.get('proximo_vencimento'))
    ]
    return {
        'divida': sum(int(x.get('valor') or 0) for x in abertas),
        'pendente': sum(int(x.get('valor') or 0) for x in pendentes),
        'informado': sum(int(x.get('valor') or 0) for x in informadas),
        'quantidade_aberta': len(abertas),
        'contratos_ativos': len(contratos_c) + len(contratos_l),
        'proximo_vencimento': min(proximos).isoformat() if proximos else None,
    }


def _reino_notificar_admins(titulo, mensagem):
    try:
        for u in _safe_table('usuarios_clan', 'email,cargo'):
            if u.get('cargo') in ('lider', 'sub_lider') and u.get('email'):
                criar_notificacao(u.get('email'), titulo, mensagem, 'aviso', url_for('admin_reino_financeiro'))
    except Exception as e:
        print(f'[V31 Reino] Falha ao notificar administração: {e}')


def _construtor_perfil(email):
    if not email:
        return None
    rows = _safe_table('construtores_perfil', '*', usuario_email=email)
    return rows[0] if rows else None


def _pode_construir(email):
    return bool(_construtor_perfil(email)) or bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))


@app.route('/construtores')
@login_required
def construtores():
    perfis = _safe_table('construtores_perfil')
    portfolios = _safe_table('construcoes_portfolio')
    pedidos = _safe_table('pedidos_construcao')
    mapa = mapa_nicks_por_email()
    for x in perfis:
        x['nick'] = mapa.get(x.get('usuario_email'), {}).get('nick') or x.get('usuario_email')
        x['trabalhos'] = [p for p in portfolios if p.get('construtor_email') == x.get('usuario_email')]
        x['ativos'] = len([p for p in pedidos if p.get('construtor_email') == x.get('usuario_email') and p.get('status') in ('aceito','em_andamento')])
    email = session.get('usuario_email')
    admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    meus = [p for p in pedidos if p.get('solicitante_email') == email or p.get('construtor_email') == email]
    return render_template('construtores.html', construtores=perfis, meus_pedidos=meus, pode_publicar=_pode_construir(email), admin=admin)


@app.route('/construtores/publicar', methods=['POST'])
@login_required
def publicar_construcao():
    email = session.get('usuario_email')
    if not _pode_construir(email):
        flash('Apenas Construtores podem publicar trabalhos.', 'erro')
        return redirect(url_for('construtores'))
    titulo = request.form.get('titulo','').strip()
    descricao = request.form.get('descricao','').strip()
    imagens = [x.strip() for x in request.form.get('imagens_urls','').splitlines() if x.strip()]
    for arquivo in request.files.getlist('imagens'):
        if not arquivo or not arquivo.filename:
            continue
        nome = secure_filename(arquivo.filename)
        ext = os.path.splitext(nome)[1].lower()
        if ext not in ('.png','.jpg','.jpeg','.webp','.gif'):
            continue
        try:
            caminho = f"construcoes/{email.replace('@','_')}/{uuid4().hex}{ext}"
            supabase.storage.from_('hype-media').upload(
                caminho, arquivo.read(), {'content-type': arquivo.mimetype or 'application/octet-stream'}
            )
            pub = supabase.storage.from_('hype-media').get_public_url(caminho)
            imagens.append(pub if isinstance(pub, str) else getattr(pub, 'public_url', None) or str(pub))
        except Exception as e:
            print(f"Upload construção: {e}")
    if not titulo:
        flash('Informe o nome do trabalho.', 'erro')
        return redirect(url_for('construtores'))
    try:
        supabase.table('construcoes_portfolio').insert({
            'construtor_email': email, 'titulo': titulo, 'descricao': descricao or None,
            'imagens': imagens, 'destaque': False
        }).execute()
        registrar_atividade_reino('construcao_publicada', email, f'Novo trabalho: {titulo}', 'construcao')
        flash('Trabalho publicado no seu portfólio.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao publicar construção: {e}', 'erro')
    return redirect(url_for('construtores'))


@app.route('/construtores/pedir', methods=['POST'])
@login_required
def pedir_construcao():
    email = session.get('usuario_email')
    titulo = request.form.get('titulo','').strip()
    descricao = request.form.get('descricao','').strip()
    construtor_email = request.form.get('construtor_email','').strip() or None
    referencias = [x.strip() for x in request.form.get('referencias','').splitlines() if x.strip()]
    if not titulo or not descricao:
        flash('Informe título e descrição do projeto.', 'erro')
        return redirect(url_for('construtores'))
    try:
        supabase.table('pedidos_construcao').insert({
            'solicitante_email': email,
            'construtor_email': construtor_email,
            'titulo': titulo,
            'descricao': descricao,
            'referencias': referencias,
            'status': 'pendente'
        }).execute()
        if construtor_email:
            criar_notificacao(construtor_email, 'Novo pedido de construção', titulo, 'info', url_for('construtores'))
        registrar_atividade_reino('pedido_construcao', email, f'Pedido de construção: {titulo}', 'construcao')
        flash('Pedido de construção enviado.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao criar pedido: {e}', 'erro')
    return redirect(url_for('construtores'))


@app.route('/construtores/pedido/<int:pedido_id>', methods=['GET','POST'])
@login_required
def pedido_construcao(pedido_id):
    email = session.get('usuario_email')
    admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    rows = _safe_table('pedidos_construcao', '*', id=pedido_id)
    if not rows:
        flash('Pedido não encontrado.', 'erro')
        return redirect(url_for('construtores'))
    p = rows[0]
    pode_ver = admin or p.get('solicitante_email') == email or p.get('construtor_email') == email or (not p.get('construtor_email') and _pode_construir(email))
    if not pode_ver:
        flash('Você não tem acesso a este pedido.', 'erro')
        return redirect(url_for('construtores'))
    if request.method == 'POST':
        msg = request.form.get('mensagem','').strip()[:1500]
        if msg:
            supabase.table('mensagens_construcao').insert({
                'pedido_id': pedido_id, 'autor_email': email, 'mensagem': msg
            }).execute()
            registrar_atividade_reino('mensagem_construcao', email, f'Mensagem no pedido #{pedido_id}', 'construcao', pedido_id)
        return redirect(url_for('pedido_construcao', pedido_id=pedido_id))
    mensagens = _safe_table('mensagens_construcao', '*', pedido_id=pedido_id)
    mensagens = sorted(mensagens, key=lambda x: x.get('created_at') or '')
    mapa = mapa_nicks_por_email()
    for m in mensagens:
        m['nick'] = mapa.get(m.get('autor_email'), {}).get('nick') or m.get('autor_email')
    return render_template('pedido_construcao.html', pedido=p, mensagens=mensagens, admin=admin, pode_construir=_pode_construir(email))


@app.route('/construtores/pedido/<int:pedido_id>/acao', methods=['POST'])
@login_required
def acao_pedido_construcao(pedido_id):
    email = session.get('usuario_email')
    admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    rows = _safe_table('pedidos_construcao', '*', id=pedido_id)
    if not rows:
        flash('Pedido não encontrado.', 'erro')
        return redirect(url_for('construtores'))
    p = rows[0]
    acao = request.form.get('acao','')
    motivo = request.form.get('motivo','').strip()[:500] or None
    updates = {}

    if acao == 'assumir':
        if not _pode_construir(email) or (p.get('construtor_email') and p.get('construtor_email') != email and not admin):
            flash('Você não pode assumir este pedido.', 'erro'); return redirect(url_for('construtores'))
        perfil = _construtor_perfil(email) or {}
        limite = int(perfil.get('max_ativos') or 3)
        ativos = len([x for x in _safe_table('pedidos_construcao') if x.get('construtor_email') == email and x.get('status') in ('aceito','em_andamento')])
        if ativos >= limite and not admin:
            flash('Você atingiu seu limite de construções ativas.', 'erro'); return redirect(url_for('construtores'))
        updates = {'construtor_email': email, 'status': 'aceito'}
    elif acao == 'iniciar' and (admin or p.get('construtor_email') == email):
        updates = {'status': 'em_andamento'}
    elif acao == 'devolver' and (admin or p.get('construtor_email') == email):
        updates = {'status': 'pendente', 'construtor_email': None, 'motivo': motivo}
    elif acao == 'recusar' and (admin or p.get('construtor_email') == email):
        if not motivo:
            flash('Informe o motivo da recusa.', 'erro'); return redirect(url_for('pedido_construcao', pedido_id=pedido_id))
        updates = {'status': 'recusado', 'motivo': motivo}
    elif acao == 'concluir' and (admin or p.get('construtor_email') == email):
        updates = {'status': 'concluido'}
    elif acao == 'entregar' and (admin or p.get('construtor_email') == email):
        updates = {'status': 'entregue'}
    elif acao == 'cancelar' and (admin or p.get('solicitante_email') == email):
        updates = {'status': 'cancelado', 'motivo': motivo}
    else:
        flash('Ação não permitida.', 'erro')
        return redirect(url_for('pedido_construcao', pedido_id=pedido_id))

    supabase.table('pedidos_construcao').update(updates).eq('id', pedido_id).execute()
    novo = updates.get('status')
    if novo:
        criar_notificacao(p.get('solicitante_email'), 'Construção atualizada', f'Pedido #{pedido_id}: {novo.replace("_"," ")}.', 'info', url_for('pedido_construcao', pedido_id=pedido_id))
    if novo == 'entregue':
        conceder_conquista_se_ausente(p.get('construtor_email') or email, 'Primeira Construção Entregue', 'Concluiu e entregou um trabalho pelo sistema de Construtores.', '🏗️')
    registrar_atividade_reino(f'construcao_{acao}', email, f'Pedido de construção #{pedido_id}: {acao}', 'construcao', pedido_id)
    flash('Pedido atualizado.', 'sucesso')
    return redirect(url_for('pedido_construcao', pedido_id=pedido_id))


@app.route('/admin/construtores', methods=['POST'])
@login_required
def admin_construtores():
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))
    alvo = request.form.get('usuario_email','').strip()
    acao = request.form.get('acao','salvar')
    if not alvo:
        flash('Informe o e-mail do membro.', 'erro')
        return redirect(url_for('construtores'))
    if acao == 'remover':
        supabase.table('construtores_perfil').delete().eq('usuario_email', alvo).execute()
    else:
        supabase.table('construtores_perfil').upsert({
            'usuario_email': alvo,
            'bio': request.form.get('bio','').strip() or None,
            'especialidades': [x.strip() for x in request.form.get('especialidades','').split(',') if x.strip()],
            'status': request.form.get('status','disponivel'),
            'max_ativos': max(1, min(10, int(request.form.get('max_ativos') or 3)))
        }).execute()
    flash('Construtor atualizado.', 'sucesso')
    return redirect(url_for('construtores'))


@app.route('/lojas')
@login_required
def lojas():
    email = session.get('usuario_email')
    _reino_sincronizar_cobrancas(email)
    itens = sorted([x for x in _safe_table('lojas_reino') if x.get('ativa', True) and x.get('status') != 'desativada'], key=lambda x: int(x.get('posicao') or 999999))
    produtos = _safe_table('produtos_loja')
    for loja in itens:
        loja['produtos'] = [p for p in produtos if p.get('loja_id') == loja.get('id') and p.get('ativo', True)]
        loja['eh_minha'] = loja.get('dono_email') == email
    admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    meus_pedidos = [p for p in _safe_table('pedidos_loja') if p.get('comprador_email') == email or p.get('lojista_email') == email]
    return render_template('lojas.html', lojas=itens, meus_pedidos=meus_pedidos, admin=admin, meu_reino=_reino_resumo_usuario(email))


@app.route('/lojas/<int:loja_id>')
@login_required
def loja_detalhe(loja_id):
    rows = _safe_table('lojas_reino', '*', id=loja_id)
    if not rows:
        flash('Loja não encontrada.', 'erro'); return redirect(url_for('lojas'))
    loja = rows[0]
    email = session.get('usuario_email')
    admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    dono = loja.get('dono_email') == email
    if (not loja.get('ativa', True) or loja.get('status') == 'desativada') and not (admin or dono):
        flash('Esta loja está desativada.', 'info')
        return redirect(url_for('lojas'))
    produtos = [p for p in _safe_table('produtos_loja', '*', loja_id=loja_id) if p.get('ativo', True)]
    pedidos = [p for p in _safe_table('pedidos_loja', '*', loja_id=loja_id) if admin or dono or p.get('comprador_email') == email]
    return render_template('loja_detalhe.html', loja=loja, produtos=produtos, pedidos=pedidos, pode_gerenciar=admin or dono, admin=admin)


@app.route('/lojas/<int:loja_id>/produto', methods=['POST'])
@login_required
def loja_produto(loja_id):
    email = session.get('usuario_email')
    rows = _safe_table('lojas_reino', '*', id=loja_id)
    if not rows:
        return redirect(url_for('lojas'))
    loja = rows[0]
    admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    if loja.get('dono_email') != email and not admin:
        flash('Você não pode editar esta loja.', 'erro'); return redirect(url_for('loja_detalhe', loja_id=loja_id))
    try:
        supabase.table('produtos_loja').insert({
            'loja_id': loja_id,
            'nome': request.form.get('nome','').strip(),
            'descricao': request.form.get('descricao','').strip() or None,
            'imagem_url': request.form.get('imagem_url','').strip() or None,
            'preco': parse_valor_moeda(request.form.get('preco')),
            'estoque': max(0, int(request.form.get('estoque') or 0)),
            'ativo': True
        }).execute()
        registrar_atividade_reino('produto_loja', email, f"Produto cadastrado em {loja.get('nome')}", 'loja', loja_id)
        flash('Produto adicionado.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao adicionar produto: {e}', 'erro')
    return redirect(url_for('loja_detalhe', loja_id=loja_id))


@app.route('/lojas/<int:loja_id>/reservar/<int:produto_id>', methods=['POST'])
@login_required
def reservar_produto(loja_id, produto_id):
    email = session.get('usuario_email')
    lojas_rows = _safe_table('lojas_reino', '*', id=loja_id)
    prod_rows = _safe_table('produtos_loja', '*', id=produto_id)
    if not lojas_rows or not prod_rows or prod_rows[0].get('loja_id') != loja_id:
        flash('Produto não encontrado.', 'erro'); return redirect(url_for('lojas'))
    loja, prod = lojas_rows[0], prod_rows[0]
    if not loja.get('ativa', True) or loja.get('status') in ('manutencao','desativada'):
        flash('Esta loja não está aceitando reservas no momento.', 'erro')
        return redirect(url_for('lojas'))
    qtd = max(1, int(request.form.get('quantidade') or 1))
    estoque = int(prod.get('estoque') or 0)
    if qtd > estoque:
        flash('Quantidade indisponível em estoque.', 'erro'); return redirect(url_for('loja_detalhe', loja_id=loja_id))
    try:
        total = int(prod.get('preco') or 0) * qtd
        supabase.table('pedidos_loja').insert({
            'loja_id': loja_id,
            'produto_id': produto_id,
            'produto_nome': prod.get('nome'),
            'comprador_email': email,
            'lojista_email': loja.get('dono_email'),
            'quantidade': qtd,
            'total': total,
            'status': 'pedido'
        }).execute()
        # Reserva o estoque imediatamente; cancelamento do lojista pode devolver manualmente.
        supabase.table('produtos_loja').update({'estoque': estoque - qtd}).eq('id', produto_id).execute()
        if loja.get('dono_email'):
            criar_notificacao(loja.get('dono_email'), 'Nova reserva na loja', f"{qtd}x {prod.get('nome')}", 'info', url_for('loja_detalhe', loja_id=loja_id))
        registrar_atividade_reino('reserva_loja', email, f"Reserva: {qtd}x {prod.get('nome')}", 'loja', loja_id)
        flash('Produto reservado. Aguarde a loja separar para retirada.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao reservar: {e}', 'erro')
    return redirect(url_for('loja_detalhe', loja_id=loja_id))


@app.route('/lojas/pedido/<int:pedido_id>/status', methods=['POST'])
@login_required
def status_pedido_loja(pedido_id):
    email = session.get('usuario_email')
    rows = _safe_table('pedidos_loja', '*', id=pedido_id)
    if not rows:
        flash('Pedido não encontrado.', 'erro'); return redirect(url_for('lojas'))
    p = rows[0]
    admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    if p.get('lojista_email') != email and not admin:
        flash('Você não pode atualizar este pedido.', 'erro'); return redirect(url_for('lojas'))
    novo = request.form.get('status','')
    if novo not in ('aceito','separando','pronto_retirada','entregue','cancelado'):
        flash('Status inválido.', 'erro'); return redirect(url_for('lojas'))
    status_anterior = p.get('status')
    if status_anterior == 'entregue' and novo != 'entregue':
        flash('Pedido já entregue não pode voltar de status. Faça um ajuste no extrato se houver devolução excepcional.', 'erro')
        return redirect(url_for('loja_detalhe', loja_id=p.get('loja_id')))
    supabase.table('pedidos_loja').update({'status': novo}).eq('id', pedido_id).execute()
    if novo == 'entregue' and status_anterior != 'entregue':
        valor_mov = int(p.get('total') or 0)
        registrar_transacao_hype(
            p.get('comprador_email'), 'saida', 'loja',
            f"Compra na loja - {p.get('produto_nome')}", valor_mov,
            origem_tipo='loja', origem_id=pedido_id, contraparte_email=p.get('lojista_email'),
            chave_unica=f'loja:{pedido_id}:comprador'
        )
        registrar_transacao_hype(
            p.get('lojista_email'), 'entrada', 'loja',
            f"Venda - {p.get('produto_nome')}", valor_mov,
            origem_tipo='loja', origem_id=pedido_id, contraparte_email=p.get('comprador_email'),
            chave_unica=f'loja:{pedido_id}:lojista'
        )
    criar_notificacao(p.get('comprador_email'), 'Pedido da loja atualizado', f"{p.get('produto_nome')}: {novo.replace('_',' ')}.", 'info', url_for('lojas'))
    registrar_atividade_reino('status_loja', email, f"Pedido de loja #{pedido_id}: {novo}", 'loja', p.get('loja_id'))
    flash('Status atualizado.', 'sucesso')
    return redirect(url_for('loja_detalhe', loja_id=p.get('loja_id')))


@app.route('/admin/lojas', methods=['POST'])
@login_required
def admin_lojas():
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))
    loja_id = int(request.form.get('loja_id') or 0)
    status = request.form.get('status','disponivel')
    if status not in ('disponivel','ocupada','reservada','manutencao','desativada'):
        status = 'disponivel'
    dono_email = request.form.get('dono_email','').strip() or None
    if dono_email and not _safe_table('membros_hype','usuario_email',usuario_email=dono_email,ativo=True):
        flash('A loja só pode ser atribuída a um membro HYPE ativo.', 'erro')
        return redirect(request.referrer or url_for('admin_reino'))
    if dono_email and status == 'disponivel':
        status = 'ocupada'
    ativa = request.form.get('ativa') == 'on'
    if status == 'desativada' or not ativa:
        status = 'desativada'
        ativa = False
        dono_email = None
    dados = {
        'nome': request.form.get('nome','').strip(),
        'codigo': request.form.get('codigo','').strip().upper() or None,
        'setor': request.form.get('setor','').strip() or None,
        'dono_email': dono_email,
        'descricao': request.form.get('descricao','').strip() or None,
        'imagem_url': request.form.get('imagem_url','').strip() or None,
        'valor_aluguel': parse_valor_moeda(request.form.get('valor_aluguel')),
        'status': status,
        'ativa': ativa
    }
    try:
        antigas = _safe_table('lojas_reino','*',id=loja_id)
        antiga = antigas[0] if antigas else {}
        dono_antigo = antiga.get('dono_email')
        supabase.table('lojas_reino').update(dados).eq('id', loja_id).execute()
        hoje = datetime.now(timezone.utc).date()
        if dono_antigo and dono_antigo != dono_email:
            supabase.table('contratos_lojas').update({
                'status':'encerrado','fim':hoje.isoformat()
            }).eq('loja_id',loja_id).eq('status','ativo').execute()
        if dono_email and dono_email != dono_antigo:
            supabase.table('contratos_lojas').update({
                'status':'encerrado','fim':hoje.isoformat()
            }).eq('loja_id',loja_id).eq('status','ativo').execute()
            supabase.table('contratos_lojas').insert({
                'loja_id':loja_id,'usuario_email':dono_email,
                'valor_semanal':dados.get('valor_aluguel') or 0,
                'inicio':hoje.isoformat(),
                'proximo_vencimento':(hoje+timedelta(days=7)).isoformat(),
                'status':'ativo'
            }).execute()
            criar_notificacao(dono_email,'Loja no Reino HYPE',f"Você foi vinculado à loja {dados.get('nome')}.",'info',url_for('lojas'))
        elif dono_email and dono_email == dono_antigo:
            supabase.table('contratos_lojas').update({
                'valor_semanal':dados.get('valor_aluguel') or 0
            }).eq('loja_id',loja_id).eq('status','ativo').execute()
        registrar_log('editar','reino','loja',loja_id,{'status':status,'dono_email':dono_email})
        registrar_atividade_reino('loja_atualizada', email, f"Loja atualizada: {dados.get('nome')}", 'loja', loja_id)
        flash('Loja atualizada.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao atualizar loja: {e}', 'erro')
    return redirect(request.referrer or url_for('loja_detalhe', loja_id=loja_id))



# ============================================================================
# HYPE V25 - TESOURO / ARSENAL COMPETITIVO 2.0
# Área exclusiva para membros ativos do Clã HYPE: Pokémon e Megas.
# ============================================================================

def _tesouro_pode_gerenciar(email=None):
    email = email or session.get('usuario_email')
    if not email or not membro_hype_ativo(email):
        return False
    permissoes = obter_permissoes_usuario(email)
    return bool(permissoes.get('pode_gerenciar_cofre', permissoes.get('pode_gerenciar_cargos', False)))


def _tesouro_proximo_codigo(tipo):
    prefixo = 'HYPE-PKM-' if tipo == 'pokemon' else 'HYPE-MEGA-'
    maior = 0
    for item in _safe_table('cofre_itens', 'codigo'):
        codigo = str(item.get('codigo') or '')
        if not codigo.startswith(prefixo):
            continue
        try:
            maior = max(maior, int(codigo.rsplit('-', 1)[-1]))
        except Exception:
            pass
    return f'{prefixo}{maior + 1:04d}'


def _tesouro_metadata(item):
    metadata = item.get('metadata') if isinstance(item, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _tesouro_upload_imagem(arquivo):
    if not arquivo or not getattr(arquivo, 'filename', None):
        return None
    nome = secure_filename(arquivo.filename or '')
    ext = os.path.splitext(nome)[1].lower()
    if ext not in ('.png','.jpg','.jpeg','.webp','.gif'):
        raise ValueError('Formato de imagem não permitido. Use PNG, JPG, WEBP ou GIF.')
    conteudo = arquivo.read()
    if len(conteudo) > 8 * 1024 * 1024:
        raise ValueError('A imagem deve ter no máximo 8 MB.')
    caminho = f"tesouro/{uuid4().hex}{ext}"
    supabase.storage.from_('hype-media').upload(caminho, conteudo, {'content-type': arquivo.mimetype or 'application/octet-stream'})
    pub = supabase.storage.from_('hype-media').get_public_url(caminho)
    return pub if isinstance(pub, str) else getattr(pub, 'public_url', None) or str(pub)


def _tesouro_disponivel(item):
    if not item or not item.get('ativo', True):
        return 0
    if (item.get('situacao') or 'disponivel') != 'disponivel':
        return 0
    total = int(item.get('quantidade_total') or 0)
    reservado = int(item.get('quantidade_reservada') or 0)
    return max(0, total - reservado)


def _tesouro_preparar_item(item):
    item = dict(item or {})
    item['metadata'] = _tesouro_metadata(item)
    item['situacao'] = item.get('situacao') or 'disponivel'
    item['disponivel'] = _tesouro_disponivel(item)
    item['reservado'] = max(0, int(item.get('quantidade_reservada') or 0))
    return item


def _tesouro_atualizar_atrasos():
    hoje = datetime.now(HYPE_TZ).date()
    for emp in _safe_table('cofre_emprestimos', '*'):
        if emp.get('status') != 'retirado' or not emp.get('prazo_devolucao'):
            continue
        try:
            prazo = datetime.fromisoformat(str(emp.get('prazo_devolucao'))[:10]).date()
        except Exception:
            continue
        if prazo < hoje:
            try:
                supabase.table('cofre_emprestimos').update({'status': 'atrasado'}).eq('id', emp.get('id')).eq('status', 'retirado').execute()
                _tesouro_registrar_movimento(emp.get('item_id'), emp.get('id'), 'emprestimo_atrasado', f'Prazo vencido em {prazo.isoformat()}')
            except Exception as e:
                print(f'[tesouro atraso] {e}')


def _tesouro_registrar_movimento(item_id, emprestimo_id, acao, observacao=None):
    try:
        supabase.table('cofre_movimentacoes').insert({
            'item_id': item_id,
            'emprestimo_id': emprestimo_id,
            'usuario_email': session.get('usuario_email'),
            'acao': acao,
            'observacao': (observacao or '').strip()[:1000] or None
        }).execute()
    except Exception as e:
        print(f'[cofre_movimentacoes] {e}')


def _tesouro_enriquecer_emprestimos(emprestimos, itens_map=None, usuarios_map=None):
    itens_map = itens_map or {x.get('id'): _tesouro_preparar_item(x) for x in _safe_table('cofre_itens')}
    usuarios_map = usuarios_map or mapa_nicks_por_email()
    hoje = datetime.now(HYPE_TZ).date()
    saida = []
    for raw in emprestimos or []:
        emp = dict(raw)
        emp['item'] = itens_map.get(emp.get('item_id'), {})
        usuario = usuarios_map.get(emp.get('usuario_email'), {})
        emp['usuario_nick'] = usuario.get('nick') or emp.get('usuario_email')
        emp['dias_restantes'] = None
        if emp.get('prazo_devolucao'):
            try:
                prazo = datetime.fromisoformat(str(emp.get('prazo_devolucao'))[:10]).date()
                emp['dias_restantes'] = (prazo - hoje).days
            except Exception:
                pass
        saida.append(emp)
    return saida


@app.route('/tesouro')
@membro_hype_required
def tesouro_hype():
    email = session['usuario_email']
    _tesouro_atualizar_atrasos()
    todos_itens = [_tesouro_preparar_item(x) for x in _safe_table('cofre_itens')]
    itens = [x for x in todos_itens if x.get('ativo', True)]
    ordem = {'pokemon': 0, 'mega': 1}
    itens = sorted(itens, key=lambda x: (0 if x.get('destaque') else 1, ordem.get(x.get('tipo'), 9), (x.get('nome') or '').lower()))
    emprestimos = sorted(
        _tesouro_enriquecer_emprestimos(_safe_table('cofre_emprestimos', '*', usuario_email=email), {x.get('id'):x for x in todos_itens}),
        key=lambda x: x.get('solicitado_em') or x.get('created_at') or '', reverse=True
    )
    ativos_status = ('solicitado','aprovado','retirado','atrasado','devolucao_solicitada')
    ativos = [e for e in emprestimos if e.get('status') in ativos_status]
    resumo = {
        'pokemons': sum(int(x.get('quantidade_total') or 0) for x in itens if x.get('tipo') == 'pokemon'),
        'megas': sum(int(x.get('quantidade_total') or 0) for x in itens if x.get('tipo') == 'mega'),
        'disponiveis': sum(int(x.get('disponivel') or 0) for x in itens),
        'meus_ativos': len(ativos),
        'meus_atrasados': sum(1 for e in ativos if e.get('status') == 'atrasado'),
    }
    return render_template(
        'tesouro_hype.html', itens=itens, emprestimos=emprestimos, emprestimos_ativos=ativos,
        resumo=resumo, pode_gerenciar=_tesouro_pode_gerenciar(email)
    )


@app.route('/tesouro/item/<int:item_id>')
@membro_hype_required
def tesouro_item(item_id):
    email = session['usuario_email']
    _tesouro_atualizar_atrasos()
    rows = _safe_table('cofre_itens', '*', id=item_id)
    if not rows or not rows[0].get('ativo', True):
        flash('Patrimônio do Tesouro não encontrado.', 'erro')
        return redirect(url_for('tesouro_hype'))
    item = _tesouro_preparar_item(rows[0])
    meus = _tesouro_enriquecer_emprestimos(_safe_table('cofre_emprestimos', '*', usuario_email=email), {item_id:item})
    meus = [e for e in meus if e.get('item_id') == item_id]
    meus.sort(key=lambda x: x.get('solicitado_em') or '', reverse=True)
    todos_item = _safe_table('cofre_emprestimos', '*', item_id=item_id)
    resumo_item = {
        'emprestimos_total': len(todos_item),
        'devolvidos': sum(1 for e in todos_item if e.get('status') == 'devolvido'),
        'em_uso': sum(1 for e in todos_item if e.get('status') in ('aprovado','retirado','atrasado','devolucao_solicitada')),
    }
    return render_template(
        'tesouro_item.html', item=item, meus_emprestimos=meus, resumo_item=resumo_item,
        pode_gerenciar=_tesouro_pode_gerenciar(email)
    )


@app.route('/tesouro/solicitar/<int:item_id>', methods=['POST'])
@membro_hype_required
def tesouro_solicitar(item_id):
    email = session['usuario_email']
    itens = _safe_table('cofre_itens', '*', id=item_id)
    if not itens:
        flash('Item do Tesouro não encontrado.', 'erro')
        return redirect(url_for('tesouro_hype'))
    item = _tesouro_preparar_item(itens[0])
    if not item.get('ativo', True) or item.get('situacao') != 'disponivel':
        flash('Este patrimônio está temporariamente indisponível para empréstimo.', 'erro')
        return redirect(request.referrer or url_for('tesouro_hype'))
    try:
        quantidade = max(1, min(99, int(request.form.get('quantidade') or 1)))
    except Exception:
        quantidade = 1
    disponivel = _tesouro_disponivel(item)
    if quantidade > disponivel:
        flash('Não há quantidade suficiente disponível no Tesouro.', 'erro')
        return redirect(request.referrer or url_for('tesouro_hype'))
    existentes = _safe_table('cofre_emprestimos', '*', usuario_email=email)
    if any(e.get('item_id') == item_id and e.get('status') in ('solicitado','aprovado','retirado','atrasado','devolucao_solicitada') for e in existentes):
        flash('Você já possui uma solicitação ou empréstimo ativo deste patrimônio.', 'erro')
        return redirect(request.referrer or url_for('tesouro_hype'))
    observacao = request.form.get('observacao','').strip()[:800] or None
    try:
        res = supabase.table('cofre_emprestimos').insert({
            'item_id': item_id,
            'usuario_email': email,
            'quantidade': quantidade,
            'status': 'solicitado',
            'observacao_solicitante': observacao
        }).execute()
        emp = (res.data or [{}])[0]
        _tesouro_registrar_movimento(item_id, emp.get('id'), 'solicitacao_criada', observacao)
        registrar_atividade_reino('tesouro_solicitacao', email, f"Solicitação no Tesouro: {item.get('nome')}", 'tesouro', item_id)
        flash('Solicitação enviada ao Tesouro HYPE.', 'sucesso')
    except Exception as e:
        flash(f'Não foi possível solicitar o empréstimo: {e}', 'erro')
    return redirect(request.referrer or url_for('tesouro_hype'))


@app.route('/tesouro/emprestimo/<int:emprestimo_id>/cancelar', methods=['POST'])
@membro_hype_required
def tesouro_cancelar_solicitacao(emprestimo_id):
    email = session['usuario_email']
    rows = _safe_table('cofre_emprestimos', '*', id=emprestimo_id)
    if not rows or rows[0].get('usuario_email') != email or rows[0].get('status') != 'solicitado':
        flash('Esta solicitação não pode ser cancelada.', 'erro')
        return redirect(request.referrer or url_for('tesouro_hype'))
    try:
        supabase.table('cofre_emprestimos').update({'status':'cancelado'}).eq('id', emprestimo_id).eq('usuario_email', email).eq('status','solicitado').execute()
        _tesouro_registrar_movimento(rows[0].get('item_id'), emprestimo_id, 'solicitacao_cancelada')
        flash('Solicitação cancelada.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao cancelar: {e}', 'erro')
    return redirect(request.referrer or url_for('tesouro_hype'))


@app.route('/tesouro/emprestimo/<int:emprestimo_id>/solicitar-devolucao', methods=['POST'])
@membro_hype_required
def tesouro_solicitar_devolucao(emprestimo_id):
    email = session['usuario_email']
    rows = _safe_table('cofre_emprestimos', '*', id=emprestimo_id)
    if not rows or rows[0].get('usuario_email') != email or rows[0].get('status') not in ('retirado','atrasado'):
        flash('Este empréstimo não está disponível para solicitação de devolução.', 'erro')
        return redirect(request.referrer or url_for('tesouro_hype'))
    emp = rows[0]
    observacao = request.form.get('observacao','').strip()[:800] or None
    agora = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table('cofre_emprestimos').update({
            'status':'devolucao_solicitada',
            'devolucao_solicitada_em':agora,
            'devolucao_observacao':observacao
        }).eq('id', emprestimo_id).eq('usuario_email', email).execute()
        _tesouro_registrar_movimento(emp.get('item_id'), emprestimo_id, 'devolucao_solicitada', observacao)
        flash('Devolução solicitada. A administração precisa confirmar o recebimento.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao solicitar devolução: {e}', 'erro')
    return redirect(request.referrer or url_for('tesouro_hype'))


@app.route('/admin/tesouro')
@membro_hype_required
def admin_tesouro():
    email = session['usuario_email']
    if not _tesouro_pode_gerenciar(email):
        flash('Você não possui permissão para gerenciar o Tesouro.', 'erro')
        return redirect(url_for('tesouro_hype'))
    _tesouro_atualizar_atrasos()
    itens = [_tesouro_preparar_item(x) for x in _safe_table('cofre_itens')]
    itens.sort(key=lambda x: (x.get('tipo') or '', x.get('nome') or ''))
    itens_map = {x.get('id'):x for x in itens}
    usuarios_map = mapa_nicks_por_email()
    emprestimos = _tesouro_enriquecer_emprestimos(_safe_table('cofre_emprestimos'), itens_map, usuarios_map)
    emprestimos.sort(key=lambda x: x.get('solicitado_em') or x.get('created_at') or '', reverse=True)
    movimentos = sorted(_safe_table('cofre_movimentacoes'), key=lambda x: x.get('created_at') or '', reverse=True)[:60]
    for mov in movimentos:
        mov['item'] = itens_map.get(mov.get('item_id'), {})
        mov['usuario_nick'] = usuarios_map.get(mov.get('usuario_email'),{}).get('nick') or mov.get('usuario_email') or 'Sistema'
    resumo = {
        'itens': len([x for x in itens if x.get('ativo', True)]),
        'disponiveis': sum(int(x.get('disponivel') or 0) for x in itens if x.get('ativo', True)),
        'solicitados': sum(1 for e in emprestimos if e.get('status') == 'solicitado'),
        'em_uso': sum(1 for e in emprestimos if e.get('status') in ('aprovado','retirado','devolucao_solicitada')),
        'atrasados': sum(1 for e in emprestimos if e.get('status') == 'atrasado'),
        'devolucao': sum(1 for e in emprestimos if e.get('status') == 'devolucao_solicitada'),
    }
    return render_template('admin_tesouro.html', itens=itens, emprestimos=emprestimos, movimentos=movimentos, resumo=resumo)


@app.route('/admin/tesouro/item/novo', methods=['POST'])
@membro_hype_required
def admin_tesouro_novo_item():
    email = session['usuario_email']
    if not _tesouro_pode_gerenciar(email):
        return redirect(url_for('tesouro_hype'))
    tipo = request.form.get('tipo','').strip().lower()
    if tipo not in ('pokemon','mega'):
        flash('Tipo inválido. Use Pokémon ou Mega.', 'erro')
        return redirect(url_for('admin_tesouro'))
    nome = request.form.get('nome','').strip()[:120]
    if not nome:
        flash('Informe o nome do Pokémon ou da Mega.', 'erro')
        return redirect(url_for('admin_tesouro'))
    try:
        quantidade = max(1, min(999, int(request.form.get('quantidade_total') or 1)))
    except Exception:
        quantidade = 1
    metadata = {
        'pokemon': request.form.get('pokemon','').strip()[:100] or None,
        'nature': request.form.get('nature','').strip()[:60] or None,
        'ability': request.form.get('ability','').strip()[:100] or None,
        'ivs': request.form.get('ivs','').strip()[:150] or None,
        'evs': request.form.get('evs','').strip()[:180] or None,
        'level': request.form.get('level','').strip()[:20] or None,
        'genero': request.form.get('genero','').strip()[:40] or None,
        'item': request.form.get('held_item','').strip()[:100] or None,
        'moves': request.form.get('moves','').strip()[:300] or None,
        'compatibilidade': request.form.get('compatibilidade','').strip()[:150] or None,
    }
    metadata = {k:v for k,v in metadata.items() if v}
    imagem_url = request.form.get('imagem_url','').strip()[:1000] or None
    if request.files.get('imagem') and request.files.get('imagem').filename:
        try:
            imagem_url = _tesouro_upload_imagem(request.files.get('imagem'))
        except Exception as e:
            flash(f'Erro na imagem: {e}', 'erro')
            return redirect(url_for('admin_tesouro'))
    dados = {
        'codigo': _tesouro_proximo_codigo(tipo), 'tipo': tipo, 'nome': nome,
        'descricao': request.form.get('descricao','').strip()[:1200] or None,
        'imagem_url': imagem_url,
        'quantidade_total': quantidade, 'quantidade_reservada': 0,
        'metadata': metadata, 'ativo': True, 'situacao': 'disponivel',
        'destaque': request.form.get('destaque') == '1', 'criado_por': email
    }
    try:
        res = supabase.table('cofre_itens').insert(dados).execute()
        item = (res.data or [{}])[0]
        _tesouro_registrar_movimento(item.get('id'), None, 'item_cadastrado', dados['codigo'])
        registrar_log('criar','tesouro','item',item.get('id'),{'codigo':dados['codigo'],'tipo':tipo})
        flash(f"{nome} adicionado ao Tesouro como {dados['codigo']}.", 'sucesso')
    except Exception as e:
        flash(f'Erro ao cadastrar no Tesouro: {e}', 'erro')
    return redirect(url_for('admin_tesouro'))


@app.route('/admin/tesouro/item/<int:item_id>', methods=['POST'])
@membro_hype_required
def admin_tesouro_editar_item(item_id):
    email = session['usuario_email']
    if not _tesouro_pode_gerenciar(email):
        return redirect(url_for('tesouro_hype'))
    rows = _safe_table('cofre_itens','*',id=item_id)
    if not rows:
        flash('Item não encontrado.', 'erro'); return redirect(url_for('admin_tesouro'))
    item=_tesouro_preparar_item(rows[0])
    try:
        total = max(int(item.get('quantidade_reservada') or 0), int(request.form.get('quantidade_total') or item.get('quantidade_total') or 1))
    except Exception:
        total = int(item.get('quantidade_total') or 1)
    situacao = request.form.get('situacao','disponivel').strip().lower()
    if situacao not in ('disponivel','manutencao','indisponivel'):
        situacao = 'disponivel'
    metadata = dict(_tesouro_metadata(item))
    campos = {
        'pokemon': ('pokemon',100), 'nature': ('nature',60), 'ability': ('ability',100),
        'ivs': ('ivs',150), 'evs': ('evs',180), 'level': ('level',20),
        'genero': ('genero',40), 'item': ('held_item',100), 'moves': ('moves',300),
        'compatibilidade': ('compatibilidade',150)
    }
    for chave,(form_key,limite) in campos.items():
        if form_key in request.form:
            valor = request.form.get(form_key,'').strip()[:limite]
            if valor: metadata[chave] = valor
            else: metadata.pop(chave, None)
    imagem_url = request.form.get('imagem_url','').strip()[:1000] or item.get('imagem_url')
    if request.files.get('imagem') and request.files.get('imagem').filename:
        try:
            imagem_url = _tesouro_upload_imagem(request.files.get('imagem'))
        except Exception as e:
            flash(f'Erro na imagem: {e}', 'erro')
            return redirect(url_for('admin_tesouro'))
    dados = {
        'nome': request.form.get('nome', item.get('nome') or '').strip()[:120],
        'descricao': request.form.get('descricao','').strip()[:1200] or None,
        'imagem_url': imagem_url,
        'quantidade_total': total, 'metadata': metadata, 'situacao': situacao,
        'destaque': request.form.get('destaque') == '1',
        'ativo': request.form.get('ativo') == '1'
    }
    try:
        supabase.table('cofre_itens').update(dados).eq('id',item_id).execute()
        _tesouro_registrar_movimento(item_id,None,'item_editado', situacao)
        registrar_log('editar','tesouro','item',item_id,{'nome':dados['nome'],'situacao':situacao,'ativo':dados['ativo']})
        flash('Patrimônio do Tesouro atualizado.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao atualizar: {e}', 'erro')
    return redirect(url_for('admin_tesouro'))


@app.route('/admin/tesouro/emprestimo/<int:emprestimo_id>/<acao>', methods=['POST'])
@membro_hype_required
def admin_tesouro_emprestimo(emprestimo_id, acao):
    email = session['usuario_email']
    if not _tesouro_pode_gerenciar(email):
        return redirect(url_for('tesouro_hype'))
    rows = _safe_table('cofre_emprestimos','*',id=emprestimo_id)
    if not rows:
        flash('Empréstimo não encontrado.', 'erro'); return redirect(url_for('admin_tesouro'))
    emp=rows[0]
    itens=_safe_table('cofre_itens','*',id=emp.get('item_id'))
    if not itens:
        flash('Item do empréstimo não existe mais.', 'erro'); return redirect(url_for('admin_tesouro'))
    item=_tesouro_preparar_item(itens[0])
    status=emp.get('status')
    qtd=int(emp.get('quantidade') or 1)
    motivo=request.form.get('motivo','').strip()[:800] or None
    hoje=datetime.now(HYPE_TZ).date()
    agora=datetime.now(timezone.utc).isoformat()
    try:
        if acao == 'aprovar' and status == 'solicitado':
            disponivel=_tesouro_disponivel(item)
            if qtd > disponivel:
                flash('Estoque insuficiente para aprovar.', 'erro'); return redirect(url_for('admin_tesouro'))
            if item.get('situacao') != 'disponivel':
                flash('O patrimônio está marcado como indisponível/manutenção.', 'erro'); return redirect(url_for('admin_tesouro'))
            prazo_raw=request.form.get('prazo_devolucao','').strip()
            prazo=prazo_raw or (hoje + timedelta(days=7)).isoformat()
            supabase.table('cofre_itens').update({'quantidade_reservada':int(item.get('quantidade_reservada') or 0)+qtd}).eq('id',item.get('id')).execute()
            supabase.table('cofre_emprestimos').update({'status':'aprovado','aprovado_por':email,'aprovado_em':agora,'prazo_devolucao':prazo,'motivo_decisao':motivo}).eq('id',emprestimo_id).eq('status','solicitado').execute()
            criar_notificacao(emp.get('usuario_email'),'Tesouro HYPE: empréstimo aprovado',f"Seu pedido de {item.get('nome')} foi aprovado. Prazo: {prazo}.",'sucesso',url_for('tesouro_hype'))
            novo='aprovado'
        elif acao == 'recusar' and status == 'solicitado':
            supabase.table('cofre_emprestimos').update({'status':'recusado','decidido_por':email,'decidido_em':agora,'motivo_decisao':motivo}).eq('id',emprestimo_id).eq('status','solicitado').execute()
            criar_notificacao(emp.get('usuario_email'),'Tesouro HYPE: solicitação recusada',f"A solicitação de {item.get('nome')} foi recusada.",'info',url_for('tesouro_hype'))
            novo='recusado'
        elif acao == 'retirar' and status == 'aprovado':
            supabase.table('cofre_emprestimos').update({'status':'retirado','retirado_em':agora}).eq('id',emprestimo_id).eq('status','aprovado').execute()
            criar_notificacao(emp.get('usuario_email'),'Tesouro HYPE: retirada registrada',f"A retirada de {item.get('nome')} foi registrada.",'info',url_for('tesouro_hype'))
            novo='retirado'
        elif acao == 'prorrogar' and status in ('aprovado','retirado','atrasado'):
            prazo=request.form.get('prazo_devolucao','').strip()
            if not prazo:
                flash('Informe o novo prazo.', 'erro'); return redirect(url_for('admin_tesouro'))
            novo_status = 'retirado' if status == 'atrasado' else status
            supabase.table('cofre_emprestimos').update({
                'status':novo_status,'prazo_devolucao':prazo,'prorrogado_em':agora,
                'prorrogado_por':email,'prorrogacoes':int(emp.get('prorrogacoes') or 0)+1
            }).eq('id',emprestimo_id).execute()
            criar_notificacao(emp.get('usuario_email'),'Tesouro HYPE: prazo atualizado',f"O novo prazo de {item.get('nome')} é {prazo}.",'info',url_for('tesouro_hype'))
            novo='prazo_prorrogado'
        elif acao == 'devolver' and status in ('retirado','atrasado','devolucao_solicitada','aprovado'):
            reservado=max(0,int(item.get('quantidade_reservada') or 0)-qtd)
            supabase.table('cofre_itens').update({'quantidade_reservada':reservado}).eq('id',item.get('id')).execute()
            supabase.table('cofre_emprestimos').update({'status':'devolvido','devolvido_em':agora,'devolucao_confirmada_por':email}).eq('id',emprestimo_id).execute()
            criar_notificacao(emp.get('usuario_email'),'Tesouro HYPE: devolução confirmada',f"A devolução de {item.get('nome')} foi confirmada. Obrigado!",'sucesso',url_for('tesouro_hype'))
            novo='devolvido'
        elif acao == 'cancelar' and status == 'aprovado':
            reservado=max(0,int(item.get('quantidade_reservada') or 0)-qtd)
            supabase.table('cofre_itens').update({'quantidade_reservada':reservado}).eq('id',item.get('id')).execute()
            supabase.table('cofre_emprestimos').update({'status':'cancelado','motivo_decisao':motivo}).eq('id',emprestimo_id).eq('status','aprovado').execute()
            novo='cancelado'
        else:
            flash('Ação incompatível com o estado atual do empréstimo.', 'erro'); return redirect(url_for('admin_tesouro'))
        _tesouro_registrar_movimento(item.get('id'),emprestimo_id,f'emprestimo_{novo}',motivo)
        registrar_log(acao,'tesouro','emprestimo',emprestimo_id,{'status_anterior':status,'status_novo':novo})
        flash('Empréstimo atualizado.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao atualizar empréstimo: {e}', 'erro')
    return redirect(url_for('admin_tesouro'))

@app.route('/reino/financeiro')
@login_required
def reino_financeiro_usuario():
    email = session.get('usuario_email')
    _reino_sincronizar_cobrancas(email)
    cobrancas = _reino_decorar_cobrancas(
        sorted(_safe_table('hype_reino_cobrancas', '*', usuario_email=email), key=lambda x: str(x.get('referencia_vencimento') or ''), reverse=True)
    )
    contratos_c = _safe_table('contratos_casas', '*', usuario_email=email, status='ativo')
    contratos_l = _safe_table('contratos_lojas', '*', usuario_email=email, status='ativo')
    casas = {x.get('id'): x for x in _safe_table('casas_reino')}
    lojas_map = {x.get('id'): x for x in _safe_table('lojas_reino')}
    contratos = []
    for c in contratos_c:
        un = casas.get(c.get('casa_id')) or {}
        contratos.append({**c, 'tipo':'Casa', 'unidade_nome':un.get('nome') or 'Casa', 'unidade_codigo':un.get('codigo') or 'CASA'})
    for c in contratos_l:
        un = lojas_map.get(c.get('loja_id')) or {}
        contratos.append({**c, 'tipo':'Loja', 'unidade_nome':un.get('nome') or 'Loja', 'unidade_codigo':un.get('codigo') or 'LOJA'})
    resumo = _reino_resumo_usuario(email)
    resumo['pago'] = sum(int(x.get('valor') or 0) for x in cobrancas if x.get('status') == 'pago')
    return render_template('reino_financeiro.html', cobrancas=cobrancas, contratos=contratos, resumo=resumo)


@app.route('/reino/financeiro/cobranca/<int:cobranca_id>/informar', methods=['POST'])
@login_required
def reino_informar_pagamento(cobranca_id):
    email = session.get('usuario_email')
    rows = _safe_table('hype_reino_cobrancas', '*', id=cobranca_id)
    if not rows or rows[0].get('usuario_email') != email:
        flash('Cobrança não encontrada.', 'erro')
        return redirect(url_for('reino_financeiro_usuario'))
    c = rows[0]
    if c.get('status') != 'pendente':
        flash('Esta cobrança não está pendente para informar pagamento.', 'info')
        return redirect(url_for('reino_financeiro_usuario'))
    obs = (request.form.get('observacao') or '').strip()[:500] or None
    try:
        supabase.table('hype_reino_cobrancas').update({
            'status':'informado', 'informado_pagamento_em':agora_iso(),
            'informado_pagamento_por':email, 'observacao_pagamento':obs,
            'recusado_em':None, 'recusado_por':None, 'motivo_recusa':None,
        }).eq('id', cobranca_id).eq('status', 'pendente').execute()
        registrar_log('informar_pagamento_aluguel','reino_financeiro','cobranca_reino',cobranca_id,{'valor':c.get('valor')})
        registrar_atividade_reino('aluguel_informado', email, f"Pagamento de aluguel informado: {formatar_preco(c.get('valor'))}", 'cobranca_reino', cobranca_id)
        _reino_notificar_admins('Pagamento de aluguel informado', f"{session.get('nick_jogo') or email} informou pagamento de {formatar_preco(c.get('valor'))} no Reino HYPE.")
        flash('Pagamento informado. Agora aguarde a confirmação do Admin.', 'sucesso')
    except Exception as e:
        flash(f'Não foi possível informar o pagamento: {e}', 'erro')
    return redirect(url_for('reino_financeiro_usuario'))


@app.route('/reino/financeiro/informar-todas', methods=['POST'])
@login_required
def reino_informar_todas():
    email = session.get('usuario_email')
    pendentes = _safe_table('hype_reino_cobrancas', '*', usuario_email=email, status='pendente')
    if not pendentes:
        flash('Você não possui aluguéis pendentes.', 'info')
        return redirect(url_for('reino_financeiro_usuario'))
    agora = agora_iso()
    ids = []
    total = 0
    try:
        for c in pendentes:
            supabase.table('hype_reino_cobrancas').update({
                'status':'informado', 'informado_pagamento_em':agora,
                'informado_pagamento_por':email,
            }).eq('id', c.get('id')).eq('status', 'pendente').execute()
            ids.append(c.get('id')); total += int(c.get('valor') or 0)
        registrar_log('informar_pagamento_total_alugueis','reino_financeiro','usuario',email,{'cobrancas':ids,'valor':total})
        _reino_notificar_admins('Pagamento total de aluguéis informado', f"{session.get('nick_jogo') or email} informou pagamento total de {formatar_preco(total)} em {len(ids)} aluguel(is).")
        flash(f'Pagamento de {formatar_preco(total)} informado. Aguarde a confirmação do Admin.', 'sucesso')
    except Exception as e:
        flash(f'Não foi possível informar todos os pagamentos: {e}', 'erro')
    return redirect(url_for('reino_financeiro_usuario'))


@app.route('/admin/reino/financeiro')
@login_required
def admin_reino_financeiro():
    email = session.get('usuario_email')
    if not _reino_admin_financeiro(email):
        return redirect(url_for('painel'))
    _reino_sincronizar_cobrancas()
    cobrancas = _reino_decorar_cobrancas(
        sorted(_safe_table('hype_reino_cobrancas'), key=lambda x: str(x.get('referencia_vencimento') or ''), reverse=True)
    )
    aberto = ('pendente','informado')
    total_a_receber = sum(int(x.get('valor') or 0) for x in cobrancas if x.get('status') in aberto)
    total_informado = sum(int(x.get('valor') or 0) for x in cobrancas if x.get('status') == 'informado')
    total_recebido = sum(int(x.get('valor') or 0) for x in cobrancas if x.get('status') == 'pago')
    agora = datetime.now(timezone.utc)
    recebido_mes = 0
    for x in cobrancas:
        if x.get('status') != 'pago' or not x.get('confirmado_em'):
            continue
        try:
            dt = datetime.fromisoformat(str(x.get('confirmado_em')).replace('Z','+00:00'))
            if dt.year == agora.year and dt.month == agora.month:
                recebido_mes += int(x.get('valor') or 0)
        except Exception:
            pass
    agrupado = {}
    for c in cobrancas:
        e = c.get('usuario_email') or 'sem-usuario'
        g = agrupado.setdefault(e, {'email':e,'nick':c.get('usuario_nick') or e,'pendente':0,'informado':0,'pago':0,'total_devido':0,'quantidade_aberta':0})
        v = int(c.get('valor') or 0); st = c.get('status')
        if st == 'pendente': g['pendente'] += v
        elif st == 'informado': g['informado'] += v
        elif st == 'pago': g['pago'] += v
        if st in aberto:
            g['total_devido'] += v; g['quantidade_aberta'] += 1
    por_membro = sorted(agrupado.values(), key=lambda x:(-x['total_devido'],-x['informado'],x['nick'].lower()))
    contratos_ativos = len(_safe_table('contratos_casas','id',status='ativo')) + len(_safe_table('contratos_lojas','id',status='ativo'))
    atrasados = sum(1 for x in cobrancas if x.get('status') in aberto and (_reino_data(x.get('referencia_vencimento')) or agora.date()) < agora.date())
    caixa = _safe_table('hype_caixa_clan')
    saldo_caixa = sum((int(x.get('valor') or 0) if x.get('tipo') == 'entrada' else -int(x.get('valor') or 0)) for x in caixa)
    return render_template('admin_reino_financeiro.html', cobrancas=cobrancas, por_membro=por_membro,
        total_a_receber=total_a_receber,total_informado=total_informado,total_recebido=total_recebido,
        recebido_mes=recebido_mes,contratos_ativos=contratos_ativos,atrasados=atrasados,saldo_caixa=saldo_caixa)


@app.route('/admin/reino/financeiro/cobranca/<int:cobranca_id>/confirmar', methods=['POST'])
@login_required
def admin_reino_confirmar_pagamento(cobranca_id):
    email = session.get('usuario_email')
    if not _reino_admin_financeiro(email):
        return redirect(url_for('painel'))
    rows = _safe_table('hype_reino_cobrancas', '*', id=cobranca_id)
    if not rows:
        flash('Cobrança não encontrada.', 'erro')
        return redirect(url_for('admin_reino_financeiro'))
    c = rows[0]
    if c.get('status') not in ('pendente','informado'):
        flash('Esta cobrança já foi finalizada.', 'info')
        return redirect(url_for('admin_reino_financeiro'))
    agora = agora_iso(); valor = int(c.get('valor') or 0)
    try:
        chave_caixa = f'reino:cobranca:{cobranca_id}:pago'
        chave_usuario = f'reino:cobranca:{cobranca_id}:usuario'
        caixa_ok = registrar_caixa_clan(
            'entrada','aluguel_reino',f"Aluguel {c.get('tipo_unidade')} - cobrança #{cobranca_id}",valor,
            origem_tipo='reino_cobranca',origem_id=cobranca_id,chave_unica=chave_caixa
        ) or bool(_safe_table('hype_caixa_clan','id',chave_unica=chave_caixa))
        usuario_ok = registrar_transacao_hype(
            c.get('usuario_email'),'saida','aluguel_reino',f"Pagamento de aluguel do Reino - cobrança #{cobranca_id}",valor,
            origem_tipo='reino_cobranca',origem_id=cobranca_id,chave_unica=chave_usuario
        ) or bool(_safe_table('transacoes_hype','id',chave_unica=chave_usuario))
        if not caixa_ok or not usuario_ok:
            raise RuntimeError('Não foi possível registrar a movimentação financeira antes da baixa.')
        supabase.table('hype_reino_cobrancas').update({
            'status':'pago','confirmado_em':agora,'confirmado_por':email
        }).eq('id',cobranca_id).execute()
        criar_notificacao(c.get('usuario_email'),'Aluguel HYPE confirmado',f"O Clã confirmou o recebimento de {formatar_preco(valor)}. Obrigado!",'sucesso',url_for('reino_financeiro_usuario'))
        registrar_log('confirmar_pagamento_aluguel','reino_financeiro','cobranca_reino',cobranca_id,{'valor':valor,'usuario':c.get('usuario_email')})
        registrar_atividade_reino('aluguel_pago', c.get('usuario_email'), f"Aluguel confirmado: {formatar_preco(valor)}", 'cobranca_reino', cobranca_id)
        flash('Recebimento confirmado e valor lançado no Caixa HYPE.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao confirmar pagamento: {e}', 'erro')
    return redirect(url_for('admin_reino_financeiro'))


@app.route('/admin/reino/financeiro/cobranca/<int:cobranca_id>/rejeitar', methods=['POST'])
@login_required
def admin_reino_rejeitar_pagamento(cobranca_id):
    email = session.get('usuario_email')
    if not _reino_admin_financeiro(email):
        return redirect(url_for('painel'))
    rows = _safe_table('hype_reino_cobrancas', '*', id=cobranca_id)
    if not rows or rows[0].get('status') != 'informado':
        flash('Somente pagamentos informados podem voltar para pendente.', 'erro')
        return redirect(url_for('admin_reino_financeiro'))
    motivo = (request.form.get('motivo') or '').strip()[:500]
    if not motivo:
        flash('Informe o motivo da recusa.', 'erro')
        return redirect(url_for('admin_reino_financeiro'))
    c = rows[0]
    try:
        supabase.table('hype_reino_cobrancas').update({
            'status':'pendente','recusado_em':agora_iso(),'recusado_por':email,'motivo_recusa':motivo,
            'informado_pagamento_em':None,'informado_pagamento_por':None
        }).eq('id',cobranca_id).execute()
        criar_notificacao(c.get('usuario_email'),'Pagamento de aluguel não confirmado',f"O pagamento informado não foi confirmado. Motivo: {motivo}",'aviso',url_for('reino_financeiro_usuario'))
        registrar_log('rejeitar_pagamento_aluguel','reino_financeiro','cobranca_reino',cobranca_id,{'motivo':motivo})
        flash('Cobrança devolvida para pendente.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao rejeitar pagamento: {e}', 'erro')
    return redirect(url_for('admin_reino_financeiro'))


@app.route('/admin/reino/financeiro/cobranca/<int:cobranca_id>/cancelar', methods=['POST'])
@login_required
def admin_reino_cancelar_cobranca(cobranca_id):
    email = session.get('usuario_email')
    if not _reino_admin_financeiro(email):
        return redirect(url_for('painel'))
    rows = _safe_table('hype_reino_cobrancas', '*', id=cobranca_id)
    if not rows:
        flash('Cobrança não encontrada.', 'erro')
        return redirect(url_for('admin_reino_financeiro'))
    c = rows[0]
    if c.get('status') == 'pago':
        flash('Cobrança já paga não pode ser cancelada por esta tela.', 'erro')
        return redirect(url_for('admin_reino_financeiro'))
    motivo = (request.form.get('motivo') or '').strip()[:500]
    if not motivo:
        flash('Informe o motivo do cancelamento.', 'erro')
        return redirect(url_for('admin_reino_financeiro'))
    try:
        supabase.table('hype_reino_cobrancas').update({
            'status':'cancelado','cancelado_em':agora_iso(),'cancelado_por':email,'motivo_cancelamento':motivo
        }).eq('id',cobranca_id).execute()
        criar_notificacao(c.get('usuario_email'),'Cobrança de aluguel cancelada',f"Uma cobrança de aluguel foi cancelada. Motivo: {motivo}",'info',url_for('reino_financeiro_usuario'))
        registrar_log('cancelar_cobranca_aluguel','reino_financeiro','cobranca_reino',cobranca_id,{'motivo':motivo})
        flash('Cobrança cancelada.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao cancelar cobrança: {e}', 'erro')
    return redirect(url_for('admin_reino_financeiro'))


@app.route('/reino')
@login_required
def painel_reino():
    email = session.get('usuario_email')
    _reino_sincronizar_cobrancas(email)
    meu_reino = _reino_resumo_usuario(email)
    breeds = sorted(_safe_table('pedidos_breed'), key=lambda x: x.get('created_at') or '', reverse=True)[:8]
    construcoes = sorted(_safe_table('pedidos_construcao'), key=lambda x: x.get('created_at') or '', reverse=True)[:8]
    lojas_pedidos = sorted(_safe_table('pedidos_loja'), key=lambda x: x.get('created_at') or '', reverse=True)[:8]
    eventos = sorted([x for x in _safe_table('eventos') if x.get('publicado', True)], key=lambda x: x.get('data_evento') or '')[:5]
    atividades = sorted(_safe_table('atividades_reino'), key=lambda x: x.get('created_at') or '', reverse=True)[:20]
    casas = [x for x in _safe_table('casas_reino') if x.get('ativa', True)]
    lojas_unidades = [x for x in _safe_table('lojas_reino') if x.get('ativa', True)]
    reino_resumo = {
        'casas_total': len(casas),
        'casas_ocupadas': sum(x.get('status') == 'ocupada' for x in casas),
        'casas_disponiveis': sum(x.get('status') == 'disponivel' for x in casas),
        'lojas_total': len(lojas_unidades),
        'lojas_ocupadas': sum(x.get('status') == 'ocupada' for x in lojas_unidades),
    }
    return render_template(
        'reino.html', breeds=breeds, construcoes=construcoes, lojas_pedidos=lojas_pedidos,
        eventos=eventos, atividades=atividades, reino_resumo=reino_resumo, meu_reino=meu_reino,
        casas_preview=casas[:8], lojas_preview=lojas_unidades[:6]
    )


@app.route('/admin/atividades')
@login_required
def admin_atividades_reino():
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))
    itens = sorted(_safe_table('atividades_reino'), key=lambda x: x.get('created_at') or '', reverse=True)[:300]
    return render_template('admin_atividades_reino.html', atividades=itens)



# ============================================================================
# GRANDE ATUALIZAÇÃO 2026-09-24 - MEMBROS HYPE / CASAS / LOJAS ESCALÁVEIS
# ============================================================================

@app.route('/admin/membros', methods=['GET','POST'])
@login_required
def admin_membros_hype():
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))

    if request.method == 'POST':
        alvo = request.form.get('usuario_email','').strip()
        acao = request.form.get('acao','ativar')
        observacao = request.form.get('observacao','').strip()[:500] or None
        usuarios = _safe_table('usuarios_clan','email,nick_jogo',email=alvo)
        if not usuarios:
            flash('Usuário não encontrado.', 'erro')
            return redirect(url_for('admin_membros_hype'))
        try:
            existente = _safe_table('membros_hype','*',usuario_email=alvo)
            if acao == 'desativar':
                if existente:
                    hoje = datetime.now(timezone.utc).date().isoformat()
                    supabase.table('membros_hype').update({
                        'ativo': False, 'saiu_em': hoje,
                        'observacao': observacao
                    }).eq('usuario_email',alvo).execute()
                    # Ao sair do clã, libera moradia/loja sem apagar os históricos.
                    supabase.table('contratos_casas').update({'status':'encerrado','fim':hoje}).eq('usuario_email',alvo).eq('status','ativo').execute()
                    supabase.table('contratos_lojas').update({'status':'encerrado','fim':hoje}).eq('usuario_email',alvo).eq('status','ativo').execute()
                    supabase.table('casas_reino').update({'ocupante_email':None,'status':'disponivel'}).eq('ocupante_email',alvo).execute()
                    supabase.table('lojas_reino').update({'dono_email':None,'status':'disponivel'}).eq('dono_email',alvo).execute()
                registrar_log('remover_membro_hype','membros','usuario',alvo,{'observacao':observacao})
                registrar_atividade_reino('membro_hype_removido', email, f'Membro removido do clã: {usuarios[0].get("nick_jogo")}', 'membro')
                flash('Membro removido do Clã HYPE. Moradias e lojas vinculadas foram liberadas sem apagar o histórico.', 'sucesso')
            else:
                dados = {
                    'usuario_email': alvo, 'ativo': True,
                    'saiu_em': None, 'observacao': observacao
                }
                if not existente:
                    dados['entrou_em'] = datetime.now(timezone.utc).date().isoformat()
                supabase.table('membros_hype').upsert(dados).execute()
                registrar_log('adicionar_membro_hype','membros','usuario',alvo,{'observacao':observacao})
                flash('Usuário confirmado como membro HYPE.', 'sucesso')
        except Exception as e:
            flash(f'Erro ao atualizar membro HYPE: {e}', 'erro')
        return redirect(url_for('admin_membros_hype'))

    usuarios = sorted(_safe_table('usuarios_clan','email,nick_jogo,cargo'), key=lambda x:(x.get('nick_jogo') or '').lower())
    registros = {x.get('usuario_email'):x for x in _safe_table('membros_hype')}
    for u in usuarios:
        u['membro_hype'] = registros.get(u.get('email'))
    return render_template('admin_membros_hype.html', usuarios=usuarios)


@app.route('/casas')
@login_required
def casas_reino():
    email = session.get('usuario_email')
    _reino_sincronizar_cobrancas(email)
    casas = sorted([c for c in _safe_table('casas_reino') if c.get('ativa', True) and c.get('status') != 'desativada'], key=lambda x:(x.get('setor') or '', x.get('codigo') or ''))
    mapa = mapa_nicks_por_email()
    for casa in casas:
        casa['ocupante_nick'] = mapa.get(casa.get('ocupante_email'),{}).get('nick') if casa.get('ocupante_email') else None
        casa['eh_minha'] = casa.get('ocupante_email') == email
    return render_template('casas.html', casas=casas, meu_reino=_reino_resumo_usuario(email))


@app.route('/admin/reino')
@login_required
def admin_reino():
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))
    _reino_sincronizar_cobrancas()
    casas = sorted(_safe_table('casas_reino'), key=lambda x:(x.get('setor') or '', x.get('codigo') or ''))
    lojas = sorted(_safe_table('lojas_reino'), key=lambda x:int(x.get('posicao') or 999999))
    membros_ativos = {x.get('usuario_email') for x in _safe_table('membros_hype','usuario_email,ativo',ativo=True)}
    todos_usuarios = _safe_table('usuarios_clan','email,nick_jogo')
    usuarios = sorted(
        [u for u in todos_usuarios if u.get('email') in membros_ativos],
        key=lambda x:(x.get('nick_jogo') or '').lower()
    )
    nicks = {u.get('email'):u.get('nick_jogo') or u.get('email') for u in todos_usuarios}
    casas_por_id = {c.get('id'):c for c in casas}
    contratos = sorted(_safe_table('contratos_casas'), key=lambda x:x.get('created_at') or '', reverse=True)
    for contrato in contratos:
        contrato['usuario_nick'] = nicks.get(contrato.get('usuario_email'), contrato.get('usuario_email'))
        casa_ref = casas_por_id.get(contrato.get('casa_id'), {})
        contrato['casa_nome'] = casa_ref.get('nome') or f"Casa #{contrato.get('casa_id')}"
        contrato['casa_codigo'] = casa_ref.get('codigo') or '—'
    lojas_por_id = {l.get('id'):l for l in lojas}
    contratos_lojas = sorted(_safe_table('contratos_lojas'), key=lambda x:x.get('created_at') or '', reverse=True)
    for contrato in contratos_lojas:
        contrato['usuario_nick'] = nicks.get(contrato.get('usuario_email'), contrato.get('usuario_email'))
        loja_ref = lojas_por_id.get(contrato.get('loja_id'), {})
        contrato['loja_nome'] = loja_ref.get('nome') or f"Loja #{contrato.get('loja_id')}"
        contrato['loja_codigo'] = loja_ref.get('codigo') or '—'
    return render_template('admin_reino.html', casas=casas, lojas=lojas, usuarios=usuarios, contratos=contratos, contratos_lojas=contratos_lojas)


@app.route('/admin/reino/casas/nova', methods=['POST'])
@login_required
def admin_casa_nova():
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))
    codigo = request.form.get('codigo','').strip().upper()
    nome = request.form.get('nome','').strip()
    if not codigo or not nome:
        flash('Informe código e nome da casa.', 'erro')
        return redirect(url_for('admin_reino'))
    try:
        supabase.table('casas_reino').insert({
            'codigo': codigo,
            'nome': nome,
            'setor': request.form.get('setor','').strip() or None,
            'status': 'disponivel',
            'valor_aluguel': parse_valor_moeda(request.form.get('valor_aluguel')),
            'descricao': request.form.get('descricao','').strip() or None,
            'imagem_url': request.form.get('imagem_url','').strip() or None,
            'ativa': True
        }).execute()
        registrar_log('criar','reino','casa',codigo,{})
        registrar_atividade_reino('casa_criada', email, f'Casa criada: {codigo} - {nome}', 'casa')
        flash('Casa adicionada ao Reino HYPE.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao criar casa: {e}', 'erro')
    return redirect(url_for('admin_reino'))


@app.route('/admin/reino/casas/<int:casa_id>', methods=['POST'])
@login_required
def admin_casa_salvar(casa_id):
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))
    rows = _safe_table('casas_reino','*',id=casa_id)
    if not rows:
        flash('Casa não encontrada.', 'erro'); return redirect(url_for('admin_reino'))
    antiga = rows[0]
    ocupante = request.form.get('ocupante_email','').strip() or None
    if ocupante and not _safe_table('membros_hype','usuario_email',usuario_email=ocupante,ativo=True):
        flash('A casa só pode ser vinculada a um membro HYPE ativo.', 'erro')
        return redirect(url_for('admin_reino'))
    status = request.form.get('status','disponivel')
    if status not in ('disponivel','ocupada','reservada','manutencao','desativada'):
        status = 'disponivel'
    if ocupante and status == 'disponivel':
        status = 'ocupada'
    if not ocupante and status == 'ocupada':
        status = 'disponivel'
    valor = parse_valor_moeda(request.form.get('valor_aluguel'))
    ativa = request.form.get('ativa') == 'on'
    if status == 'desativada' or not ativa:
        status = 'desativada'
        ocupante = None
    dados = {
        'codigo': request.form.get('codigo','').strip().upper() or antiga.get('codigo'),
        'nome': request.form.get('nome','').strip() or antiga.get('nome'),
        'setor': request.form.get('setor','').strip() or None,
        'status': status,
        'valor_aluguel': valor,
        'ocupante_email': ocupante,
        'descricao': request.form.get('descricao','').strip() or None,
        'imagem_url': request.form.get('imagem_url','').strip() or None,
        'ativa': ativa
    }
    try:
        supabase.table('casas_reino').update(dados).eq('id',casa_id).execute()
        ocupante_antigo = antiga.get('ocupante_email')
        if ocupante_antigo and ocupante_antigo != ocupante:
            supabase.table('contratos_casas').update({
                'status':'encerrado','fim':datetime.now(timezone.utc).date().isoformat()
            }).eq('casa_id',casa_id).eq('status','ativo').execute()
        if ocupante and ocupante != ocupante_antigo:
            # Garante apenas um contrato ativo por casa.
            supabase.table('contratos_casas').update({
                'status':'encerrado','fim':datetime.now(timezone.utc).date().isoformat()
            }).eq('casa_id',casa_id).eq('status','ativo').execute()
            supabase.table('contratos_casas').insert({
                'casa_id':casa_id,'usuario_email':ocupante,'valor_semanal':valor,
                'inicio':datetime.now(timezone.utc).date().isoformat(),
                'proximo_vencimento':(datetime.now(timezone.utc).date()+timedelta(days=7)).isoformat(),
                'status':'ativo'
            }).execute()
            criar_notificacao(ocupante,'Moradia no Reino HYPE',f"Você foi vinculado à {dados['nome']} ({dados['codigo']}).",'info',url_for('casas_reino'))
        elif ocupante and ocupante == ocupante_antigo:
            supabase.table('contratos_casas').update({'valor_semanal':valor}).eq('casa_id',casa_id).eq('status','ativo').execute()
        registrar_log('editar','reino','casa',casa_id,{'status':status,'ocupante':ocupante})
        registrar_atividade_reino('casa_atualizada', email, f"Casa atualizada: {dados['codigo']} - {dados['nome']}", 'casa', casa_id)
        flash('Casa atualizada.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao atualizar casa: {e}', 'erro')
    return redirect(url_for('admin_reino'))


@app.route('/admin/reino/lojas/nova', methods=['POST'])
@login_required
def admin_loja_nova():
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))
    lojas = _safe_table('lojas_reino','posicao')
    proxima = max([int(x.get('posicao') or 0) for x in lojas] or [0]) + 1
    try:
        posicao = max(1, int(request.form.get('posicao') or proxima))
    except (TypeError, ValueError):
        flash('Posição da loja inválida.', 'erro')
        return redirect(url_for('admin_reino'))
    nome = request.form.get('nome','').strip() or f'Loja {posicao}'
    codigo = request.form.get('codigo','').strip().upper() or f'LOJA-{posicao:03d}'
    try:
        supabase.table('lojas_reino').insert({
            'posicao':posicao,'codigo':codigo,'nome':nome,
            'setor':request.form.get('setor','').strip() or None,
            'descricao':request.form.get('descricao','').strip() or None,
            'imagem_url':request.form.get('imagem_url','').strip() or None,
            'valor_aluguel':parse_valor_moeda(request.form.get('valor_aluguel')),
            'status':'disponivel','ativa':True
        }).execute()
        registrar_log('criar','reino','loja',codigo,{})
        registrar_atividade_reino('loja_criada', email, f'Loja criada: {codigo} - {nome}', 'loja')
        flash('Nova loja adicionada ao Reino HYPE.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao criar loja: {e}', 'erro')
    return redirect(url_for('admin_reino'))



# ============================================================================
# HYPE V19 - GRANDE ATUALIZACAO INTEGRADA 2026-09-29
# Rankings centralizados + Perfil 2.0 visual + XP/Conquistas automáticos
# + temporadas mensais automáticas + ajustes administrativos
# ============================================================================

def _hype_media_upload(arquivo, pasta, email):
    """Upload seguro de imagem para o bucket já existente hype-media."""
    if not arquivo or not getattr(arquivo, 'filename', None):
        return None
    nome = secure_filename(arquivo.filename or '')
    ext = os.path.splitext(nome)[1].lower()
    if ext not in ('.png','.jpg','.jpeg','.webp','.gif'):
        raise ValueError('Formato de imagem não permitido. Use PNG, JPG, WEBP ou GIF.')
    if getattr(arquivo, 'content_length', None) and arquivo.content_length > 8 * 1024 * 1024:
        raise ValueError('A imagem deve ter no máximo 8 MB.')
    caminho = f"perfis/{email.replace('@','_').replace('.','_')}/{pasta}/{uuid4().hex}{ext}"
    conteudo = arquivo.read()
    if len(conteudo) > 8 * 1024 * 1024:
        raise ValueError('A imagem deve ter no máximo 8 MB.')
    supabase.storage.from_('hype-media').upload(caminho, conteudo, {'content-type': arquivo.mimetype or 'application/octet-stream'})
    pub = supabase.storage.from_('hype-media').get_public_url(caminho)
    return pub if isinstance(pub, str) else getattr(pub, 'public_url', None) or str(pub)


def _hype_auto_conquista(email, titulo, descricao, icone='🏅'):
    try:
        existentes = supabase.table('conquistas_usuario').select('id').eq('usuario_email',email).eq('titulo',titulo).limit(1).execute().data or []
        if existentes:
            return False
        supabase.table('conquistas_usuario').insert({'usuario_email':email,'titulo':titulo,'descricao':descricao,'icone':icone}).execute()
        criar_notificacao(email, 'Nova conquista!', f'Você desbloqueou: {titulo}.', 'sucesso', url_for('perfil_publico',nick=(mapa_nicks_por_email().get(email,{}).get('nick') or session.get('nick_jogo') or '')))
        return True
    except Exception as e:
        print(f'[conquista auto] {e}')
        return False


def _hype_recalcular_progressao(email):
    """XP é derivado das ações reais + ajustes do Admin; pode ser recalculado sem duplicar pontos."""
    if not email:
        return {'xp':0,'nivel':1,'progresso':0}
    pedidos = _safe_table('pedidos_breed','*')
    compras = _safe_table('pedidos_loja','*')
    inscr_t = _safe_table('inscricoes_torneio','*',usuario_email=email)
    inscr_e = _safe_table('inscricoes_evento','*',usuario_email=email)
    resultados = _safe_table('resultados_evento','*',usuario_email=email)
    builds = _safe_table('builds_pokemon','*',autor_email=email)
    meus_pedidos = [p for p in pedidos if p.get('usuario_email')==email]
    entregues_cliente = [p for p in meus_pedidos if p.get('status')=='entregue']
    entregues_breeder = [p for p in pedidos if p.get('breeder_responsavel')==email and p.get('status')=='entregue']
    compras_entregues = [p for p in compras if p.get('comprador_email')==email and p.get('status')=='entregue']
    vitorias_evento = [r for r in resultados if int(r.get('colocacao') or 999)==1]
    podios_evento = [r for r in resultados if int(r.get('colocacao') or 999)<=3]
    base = (
        len(entregues_cliente)*60 + len(entregues_breeder)*90 + len(inscr_t)*40 + len(inscr_e)*30 +
        len(resultados)*80 + len(vitorias_evento)*180 + len(podios_evento)*70 + len(builds)*45 + len(compras_entregues)*25
    )
    ajustes = 0
    try:
        for a in _safe_table('hype_xp_ajustes','*',usuario_email=email):
            ajustes += int(a.get('delta') or 0)
    except Exception:
        pass
    xp=max(0,base+ajustes)
    nivel=max(1,(xp//1000)+1)
    try:
        supabase.table('usuarios_clan').update({'xp':xp,'nivel':nivel}).eq('email',email).execute()
    except Exception as e:
        print(f'[xp sync] {e}')
    # conquistas de progressão e participação
    if entregues_cliente: _hype_auto_conquista(email,'Primeiro Breed','Recebeu seu primeiro Pokémon pelo HYPE Breed.','🥚')
    if len(entregues_cliente)>=10: _hype_auto_conquista(email,'Cliente Fiel','Concluiu 10 pedidos de Breed.','⭐')
    if len(entregues_breeder)>=10: _hype_auto_conquista(email,'Breeder em Ascensão','Entregou 10 pedidos de Breed.','⚡')
    if len(entregues_breeder)>=100: _hype_auto_conquista(email,'100 Breeds','Entregou 100 pedidos de Breed.','🥚')
    if vitorias_evento: _hype_auto_conquista(email,'Campeão HYPE','Conquistou uma vitória registrada em evento.','🏆')
    if nivel>=5: _hype_auto_conquista(email,'Veterano HYPE','Alcançou o nível 5 no site.','👑')
    return {'xp':xp,'nivel':nivel,'progresso':round((xp%1000)/10,1),'base':base,'ajustes':ajustes}


def _hype_temporada_mensal_auto():
    """Garante temporada do mês e arquiva o mês anterior no primeiro acesso após a virada."""
    hoje=datetime.now(HYPE_TZ).date() if 'HYPE_TZ' in globals() else datetime.now(timezone.utc).date()
    mes=hoje.replace(day=1)
    chave=mes.isoformat()
    try:
        atual=_safe_table('hype_temporadas_mensais','*',mes=chave)
        if not atual:
            supabase.table('hype_temporadas_mensais').insert({'mes':chave,'nome':f'Temporada {mes.strftime("%m/%Y")}','status':'ativa'}).execute()
        # fecha qualquer temporada anterior ainda ativa
        antigas=[x for x in _safe_table('hype_temporadas_mensais','*') if x.get('status')=='ativa' and str(x.get('mes') or '')[:10] < chave]
        for t in antigas:
            m=str(t.get('mes'))[:7]
            if not _safe_table('hype_rank_snapshots','id',mes=m):
                dados=_hype_montar_rankings(m)
                linhas=[]
                for tipo, itens in dados.items():
                    if tipo.startswith('_'): continue
                    for pos,item in enumerate(itens[:10],1):
                        linhas.append({'mes':m,'tipo':tipo,'posicao':pos,'usuario_email':item.get('email'),'nome':item.get('nome'),'valor':float(item.get('valor') or 0),'metadata':item})
                if linhas: supabase.table('hype_rank_snapshots').insert(linhas).execute()
            supabase.table('hype_temporadas_mensais').update({'status':'encerrada','encerrada_em':agora_iso()}).eq('id',t.get('id')).execute()
    except Exception as e:
        print(f'[temporada mensal auto] {e}')
    return chave[:7]


def _hype_rank_avatar(email):
    u=next((x for x in _safe_table('usuarios_clan','email,nick_jogo,nome_exibicao,avatar_url,xp,nivel') if x.get('email')==email),{})
    return {'email':email,'nome':u.get('nome_exibicao') or u.get('nick_jogo') or email or '—','avatar_url':u.get('avatar_url'),'xp':int(u.get('xp') or 0),'nivel':int(u.get('nivel') or 1)}


def _hype_montar_rankings(mes=None):
    """Monta todos os rankings centrais usando dados reais do banco."""
    pedidos=_safe_table('pedidos_breed','*')
    usuarios=_safe_table('usuarios_clan','email,nick_jogo,nome_exibicao,avatar_url,xp,nivel')
    umap={u.get('email'):u for u in usuarios}
    def dt_mes(v): return str(v or '')[:7]
    entregues=[p for p in pedidos if p.get('status')=='entregue' and (not mes or dt_mes(p.get('entregue_em') or p.get('concluido_em') or p.get('created_at'))==mes)]
    avals=[a for a in _safe_table('avaliacoes','*') if a.get('tipo_pedido')=='breed' and (not mes or dt_mes(a.get('created_at'))==mes)]
    pb={}; pc={}; pp={}
    for p in entregues:
        b=p.get('breeder_responsavel'); c=p.get('usuario_email'); pk=(p.get('pokemon') or 'Pokémon').strip(); pid=p.get('pokemon_id')
        if b:
            d=pb.setdefault(b,{'total':0,'valor':0}); d['total']+=1; d['valor']+=int(p.get('preco_total') or 0)
        if c:
            d=pc.setdefault(c,{'total':0,'valor':0}); d['total']+=1; d['valor']+=int(p.get('preco_total') or 0)
        key=pk.casefold(); d=pp.setdefault(key,{'nome':pk,'pokemon_id':pid,'total':0,'valor':0}); d['total']+=1; d['valor']+=int(p.get('preco_total') or 0)
    breeders=[]
    for e,d in pb.items():
        u=umap.get(e,{})
        notas=[int(a.get('nota') or 0) for a in avals if a.get('avaliado_email')==e]
        media=round(sum(notas)/len(notas),1) if notas else None
        # score equilibrado: produção + reputação, sem transformar ranking principal em mera quantidade
        score=round(d['total']*10 + (media or 0)*12 + min(len(notas),20)*2,1)
        breeders.append({'email':e,'nome':u.get('nome_exibicao') or u.get('nick_jogo') or e,'nick':u.get('nick_jogo') or e,'avatar_url':u.get('avatar_url'),'valor':score,'total':d['total'],'valor_gerado':d['valor'],'media':media,'avaliacoes':len(notas)})
    breeders.sort(key=lambda x:(-x['valor'],-x['total'],x['nome'].casefold()))
    clientes=[]
    for e,d in pc.items():
        u=umap.get(e,{})
        clientes.append({'email':e,'nome':u.get('nome_exibicao') or u.get('nick_jogo') or e,'nick':u.get('nick_jogo') or e,'avatar_url':u.get('avatar_url'),'valor':d['total'],'total':d['total'],'valor_gasto':d['valor']})
    clientes.sort(key=lambda x:(-x['valor'],-x.get('valor_gasto',0),x['nome'].casefold()))
    pokemons=[{'nome':d['nome'],'pokemon_id':d['pokemon_id'],'valor':d['total'],'total':d['total'],'valor_gerado':d['valor']} for d in pp.values()]
    pokemons.sort(key=lambda x:(-x['valor'],x['nome'].casefold()))
    # competitivo
    comp=[]
    temporadas=_safe_table('temporadas','*'); ativa=next((t for t in temporadas if t.get('ativa')),None)
    if ativa:
        for r in _safe_table('ranking_temporada','*',temporada_id=ativa.get('id')):
            u=umap.get(r.get('usuario_email'),{})
            comp.append({'email':r.get('usuario_email'),'nome':u.get('nome_exibicao') or u.get('nick_jogo') or r.get('usuario_email'),'nick':u.get('nick_jogo') or r.get('usuario_email'),'avatar_url':u.get('avatar_url'),'valor':int(r.get('pontos') or 0),'vitorias':int(r.get('vitorias') or 0),'podios':int(r.get('podios') or 0)})
    comp.sort(key=lambda x:(-x['valor'],-x['vitorias'],-x['podios']))
    # eventos
    er={}
    for r in _safe_table('resultados_evento','*'):
        if mes and dt_mes(r.get('created_at'))!=mes: continue
        e=r.get('usuario_email'); pos=int(r.get('colocacao') or 999); d=er.setdefault(e,{'pontos':0,'vitorias':0,'podios':0}); d['pontos']+=max(1,11-min(pos,10)); d['vitorias']+=1 if pos==1 else 0; d['podios']+=1 if pos<=3 else 0
    eventos=[]
    for e,d in er.items():
        u=umap.get(e,{})
        eventos.append({'email':e,'nome':u.get('nome_exibicao') or u.get('nick_jogo') or e,'nick':u.get('nick_jogo') or e,'avatar_url':u.get('avatar_url'),'valor':d['pontos'],**d})
    eventos.sort(key=lambda x:(-x['valor'],-x['vitorias'],-x['podios']))
    # XP global
    xp=[]
    for u in usuarios:
        xp.append({'email':u.get('email'),'nome':u.get('nome_exibicao') or u.get('nick_jogo') or u.get('email'),'nick':u.get('nick_jogo') or u.get('email'),'avatar_url':u.get('avatar_url'),'valor':int(u.get('xp') or 0),'nivel':int(u.get('nivel') or 1)})
    xp.sort(key=lambda x:(-x['valor'],x['nome'].casefold()))
    # compras no reino
    cr={}
    for p in _safe_table('pedidos_loja','*'):
        if p.get('status')!='entregue' or (mes and dt_mes(p.get('created_at'))!=mes): continue
        e=p.get('comprador_email'); d=cr.setdefault(e,{'total':0,'valor':0}); d['total']+=int(p.get('quantidade') or 1); d['valor']+=int(p.get('total') or 0)
    compras=[]
    for e,d in cr.items():
        u=umap.get(e,{})
        compras.append({'email':e,'nome':u.get('nome_exibicao') or u.get('nick_jogo') or e,'nick':u.get('nick_jogo') or e,'avatar_url':u.get('avatar_url'),'valor':d['total'],'total':d['total'],'valor_gasto':d['valor']})
    compras.sort(key=lambda x:(-x['valor'],-x['valor_gasto']))
    # ajustes manuais (somente acréscimo/subtração transparente, nunca apaga o cálculo real)
    try:
        ajustes=_safe_table('hype_ranking_ajustes','*')
        for tipo,lista in [('breeders',breeders),('clientes',clientes),('competitivo',comp),('eventos',eventos),('xp',xp),('compras',compras)]:
            for a in ajustes:
                if a.get('tipo')!=tipo or (a.get('mes') and mes and str(a.get('mes'))[:7]!=mes): continue
                alvo=next((x for x in lista if x.get('email')==a.get('usuario_email')),None)
                if alvo:
                    alvo['valor']=float(alvo.get('valor') or 0)+float(a.get('delta') or 0)
                    alvo['ajuste_admin']=float(alvo.get('ajuste_admin') or 0)+float(a.get('delta') or 0)
            lista.sort(key=lambda x:-float(x.get('valor') or 0))
    except Exception: pass
    return {'breeders':breeders,'pokemons':pokemons,'clientes':clientes,'competitivo':comp,'eventos':eventos,'xp':xp,'compras':compras,'_mes':mes}


@app.route('/rankings')
def central_rankings():
    mes=_hype_temporada_mensal_auto()
    escopo=request.args.get('escopo','mensal')
    dados=_hype_montar_rankings(mes if escopo=='mensal' else None)
    return render_template('rankings.html',dados=dados,mes=mes,escopo=escopo)


@app.route('/rankings/<tipo>')
def ranking_detalhe(tipo):
    tipos={'breeders':'Breeders','pokemons':'Pokémon mais breedados','clientes':'Clientes do Breed','competitivo':'Competitivo','eventos':'Eventos','xp':'XP & Nível','compras':'Compras no Reino'}
    if tipo not in tipos: return redirect(url_for('central_rankings'))
    mes=_hype_temporada_mensal_auto(); escopo=request.args.get('escopo','mensal')
    dados=_hype_montar_rankings(mes if escopo=='mensal' else None)
    return render_template('ranking_detalhe.html',tipo=tipo,titulo=tipos[tipo],itens=dados.get(tipo,[])[:100],mes=mes,escopo=escopo)


@app.route('/rankings/pokemon/<nome>')
def ranking_pokemon_detalhe(nome):
    pedidos=[p for p in _safe_table('pedidos_breed','*') if p.get('status')=='entregue' and str(p.get('pokemon') or '').casefold()==str(nome).casefold()]
    pedidos.sort(key=lambda p:str(p.get('entregue_em') or p.get('concluido_em') or p.get('created_at') or ''),reverse=True)
    mapa=mapa_nicks_por_email()
    for p in pedidos:
        p['cliente_nick']=mapa.get(p.get('usuario_email'),{}).get('nick') or p.get('player') or 'Membro HYPE'
        p['breeder_nick']=mapa.get(p.get('breeder_responsavel'),{}).get('nick') or '—'
    return render_template('ranking_pokemon_detalhe.html',nome=nome,pedidos=pedidos)


@app.route('/admin/rankings/ajustar',methods=['POST'])
@login_required
def admin_ranking_ajustar():
    if not _is_admin(): return redirect(url_for('central_rankings'))
    tipo=(request.form.get('tipo') or '').strip(); email=(request.form.get('usuario_email') or '').strip(); motivo=(request.form.get('motivo') or '').strip()[:300]
    try: delta=float(request.form.get('delta') or 0)
    except: delta=0
    if tipo not in ('breeders','clientes','competitivo','eventos','xp','compras') or not email or not delta:
        flash('Ajuste de ranking inválido.','erro'); return redirect(request.referrer or url_for('central_rankings'))
    try:
        supabase.table('hype_ranking_ajustes').insert({'tipo':tipo,'usuario_email':email,'mes':request.form.get('mes') or None,'delta':delta,'motivo':motivo or None,'criado_por':session.get('usuario_email')}).execute()
        registrar_log('ajustar_ranking','rankings','usuario',email,{'tipo':tipo,'delta':delta,'motivo':motivo})
        flash('Ajuste aplicado ao ranking.','sucesso')
    except Exception as e: flash(f'Erro ao ajustar ranking: {e}','erro')
    return redirect(request.referrer or url_for('central_rankings'))


@app.route('/admin/xp/ajustar',methods=['POST'])
@login_required
def admin_xp_ajustar():
    if not _is_admin(): return redirect(url_for('painel'))
    email=(request.form.get('usuario_email') or '').strip(); motivo=(request.form.get('motivo') or '').strip()[:300]
    try: delta=int(request.form.get('delta') or 0)
    except: delta=0
    if not email or not delta:
        flash('Ajuste de XP inválido.','erro'); return redirect(request.referrer or url_for('painel'))
    try:
        supabase.table('hype_xp_ajustes').insert({'usuario_email':email,'delta':delta,'motivo':motivo or None,'criado_por':session.get('usuario_email')}).execute()
        _hype_recalcular_progressao(email); registrar_log('ajustar_xp','xp','usuario',email,{'delta':delta,'motivo':motivo}); flash('XP ajustado.','sucesso')
    except Exception as e: flash(f'Erro ao ajustar XP: {e}','erro')
    return redirect(request.referrer or url_for('painel'))


@app.route('/perfil/midia',methods=['POST'])
@login_required
def perfil_upload_midia():
    email=session.get('usuario_email'); tipo=(request.form.get('tipo') or '').strip()
    if tipo not in ('avatar','banner'): return redirect(url_for('conta_hype'))
    try:
        url=_hype_media_upload(request.files.get('imagem'),tipo,email)
        if not url: raise ValueError('Selecione uma imagem.')
        campo='avatar_url' if tipo=='avatar' else 'banner_url'
        supabase.table('usuarios_clan').update({campo:url}).eq('email',email).execute()
        flash(('Foto de perfil' if tipo=='avatar' else 'Capa')+' atualizada!','sucesso')
    except Exception as e: flash(str(e),'erro')
    return redirect(url_for('conta_hype')+'#perfil')


@app.before_request
def hype_v19_progressao_automatica():
    # Atualização leve e idempotente para o membro autenticado em páginas centrais.
    if session.get('usuario_email') and request.endpoint in ('painel','conta_hype','central_rankings','perfil_publico'):
        try: _hype_recalcular_progressao(session.get('usuario_email'))
        except Exception as e: print(f'[progressao auto] {e}')


# ============================================================================
# MÓDULOS HYPE - recursos finais separados
# ============================================================================
from modules.final_features import create_final_blueprint
app.register_blueprint(create_final_blueprint(supabase, login_required, _safe_table, _is_admin, registrar_log))

from modules.expansion_features import create_expansion_blueprint
app.register_blueprint(create_expansion_blueprint(
    supabase, login_required, _safe_table, _is_admin, registrar_log,
    parse_valor_moeda, criar_notificacao, _reino_sincronizar_cobrancas
))

from modules.competitive_features import create_competitive_blueprint
app.register_blueprint(create_competitive_blueprint(
    supabase, login_required, _safe_table, _is_admin, registrar_log, criar_notificacao
))

from modules.builders_hub import create_builders_hub_blueprint
app.register_blueprint(create_builders_hub_blueprint(
    supabase, login_required, _safe_table, _is_admin
))


from modules.events_v26 import create_events_v26_blueprint
app.register_blueprint(create_events_v26_blueprint(
    supabase, login_required, _safe_table, _is_admin, registrar_log, criar_notificacao
))

from modules.community_v30 import create_community_blueprint
app.register_blueprint(create_community_blueprint(
    supabase, login_required, _safe_table, _is_admin, registrar_log, criar_notificacao
))


# ============================================================================
# INICIALIZADOR DO SERVIDOR
# ============================================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)