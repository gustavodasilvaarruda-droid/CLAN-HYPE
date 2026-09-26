import os
import json
import csv
import io
from functools import wraps, lru_cache
from datetime import datetime, timedelta, timezone

from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from uuid import uuid4
from urllib.request import urlopen
from urllib.parse import quote
from supabase import create_client, Client
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

app = Flask(__name__)


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


def mapa_nicks_por_email():
    """Mapa usado para nunca precisar exibir e-mail do Breeder na interface."""
    try:
        res = supabase.table('usuarios_clan').select('email,nick_jogo,cargo').execute()
        return {
            u.get('email'): {
                'nick': u.get('nick_jogo') or u.get('email'),
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
        p['breeder_nick'] = mapa.get(email_breeder, {}).get('nick') if email_breeder else None
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


def calcular_preco_breed(breed_tipo, ha=False, genero='indiferente', categoria='comum',
                         usa_ditto=False, treinado=False, nature=None):
    """Calcula o preço no servidor. Ditto é automático; HPWR foi removido do formulário."""
    linhas = _safe_table('precos_breed', '*', ativo=True)
    precos = {x.get('codigo'): int(x.get('valor') or 0) for x in linhas}
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
    base = int(precos.get(codigo, 0) or 0)
    total = base
    extras = []

    if genero in ('macho', 'femea'):
        if ha and not usa_ditto:
            extra_key = 'ha_sem_ditto_genero'
        else:
            extra_key = 'comum_genero'
        v = int(precos.get(extra_key, precos.get('escolher_genero', 0)) or 0)
        total += v
        extras.append({'codigo': extra_key, 'valor': v})

        if categoria == 'raro' and genero == 'femea':
            v = int(precos.get('femea_rara', 0) or 0)
            total += v
            extras.append({'codigo': 'femea_rara', 'valor': v})

    if treinado:
        v = int(precos.get('treinado', 0) or 0)
        total += v
        extras.append({'codigo': 'treinado', 'valor': v})

    return total, {
        'base_codigo': codigo,
        'base_valor': base,
        'breed_especial_ditto': bool(usa_ditto),
        'extras': extras,
        'total': total
    }


def classificar_pokemon_preco(pokemon_id):
    rows=_safe_table('pokemon_precificacao','*',pokemon_id=pokemon_id)
    return rows[0] if rows else {'categoria':'comum','usa_ditto_padrao':False}



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

    so_com_ditto = bool(meta.get("usa_ditto_padrao") or externa.get("so_com_ditto"))
    return {
        "breedavel": True, "so_com_ditto": so_com_ditto,
        "breed_especial": so_com_ditto, "motivo": None,
        "egg_groups": externa.get("egg_groups", []), "categoria_bloqueio": None,
        "is_baby": False, "is_legendary": False, "is_mythical": False,
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


def criar_notificacao(usuario_email, titulo, mensagem, tipo='info', link=None):
    try:
        supabase.table('notificacoes').insert({
            'usuario_email': usuario_email, 'titulo': titulo, 'mensagem': mensagem,
            'tipo': tipo, 'link': link, 'lida': False
        }).execute()
    except Exception as e:
        print(f"Notificação não registrada: {e}")


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

    noticias_home = [x for x in _safe_table('noticias') if x.get('publicado', True)][:3]
    videos_home = [x for x in _safe_table('videos') if x.get('publicado', True)][:3]
    galeria_home = [x for x in _safe_table('galeria') if x.get('publicado', True)][:6]

    return render_template(
        'index.html',
        resumo=resumo,
        destaques=destaques,
        top_breeders=top_breeders,
        eventos_home=eventos_home,
        torneios_home=torneios_home,
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

    # CADASTRO DE NOVO GUERREIRO
    if acao == 'cadastro':
        if not nick_jogo:
            flash('Informe seu Nick no Jogo para se cadastrar.', 'erro')
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

            session['usuario_email'] = email
            session['nick_jogo'] = nick_jogo
            session['cargo'] = 'membro'

            flash(f'Bem-vindo ao Clã, {nick_jogo}!', 'sucesso')
            return redirect(url_for('painel'))
        except Exception as e:
            flash(f'Erro ao cadastrar: {e}', 'erro')
            return redirect(url_for('pagina_inicial'))

    # LOGIN DE GUERREIRO EXISTENTE
    else:
        res = supabase.table('usuarios_clan').select('*').eq('email', email).execute()
        if not res.data or not check_password_hash(res.data[0]['senha'], senha):
            flash('E-mail ou senha incorretos.', 'erro')
            return redirect(url_for('pagina_inicial'))

        usuario = res.data[0]
        session['usuario_email'] = usuario['email']
        session['nick_jogo'] = usuario['nick_jogo']
        session['cargo'] = usuario['cargo']

        flash(f'Olá novamente, {usuario["nick_jogo"]}!', 'sucesso')
        return redirect(url_for('painel'))


@app.route('/logout')
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
        'avatar_url': request.form.get('avatar_url','').strip() or None,
        'banner_url': request.form.get('banner_url','').strip() or None,
        'nome_exibicao': request.form.get('nome_exibicao','').strip()[:80] or None,
        'bio': request.form.get('bio','').strip()[:500] or None,
        'pokemon_favorito': request.form.get('pokemon_favorito','').strip()[:80] or None,
        'pokemon_time': time_pokemon,
        'links_perfil': {
            'discord': request.form.get('discord','').strip()[:120],
            'youtube': request.form.get('youtube','').strip()[:250]
        }
    }
    try:
        supabase.table('usuarios_clan').update(dados).eq('email', session['usuario_email']).execute()
        flash('Perfil atualizado!', 'sucesso')
    except Exception as e: flash(f'Erro ao atualizar perfil: {e}', 'erro')
    return redirect(url_for('painel'))


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
        membro['times_salvos'] = sorted(_safe_table('times_pokemon', '*', usuario_email=email), key=lambda x: x.get('updated_at') or x.get('created_at') or '', reverse=True)[:6] if membro['mostrar_times'] else []
        mh = _safe_table('membros_hype', '*', usuario_email=email)
        membro['membro_hype'] = bool(mh and mh[0].get('ativo'))
        membro['membro_hype_desde'] = mh[0].get('entrou_em') if membro['membro_hype'] else None
        return render_template('perfil.html', membro=membro)
    except Exception as e:
        print(f'Erro perfil: {e}')
        flash('Não foi possível abrir este perfil.', 'erro')
        return redirect(url_for('pagina_inicial'))


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

        if breed_tipo not in ('F5', 'F6'):
            flash('Selecione F5 ou F6.', 'erro')
            return redirect(url_for('breed'))

        if breed_tipo == 'F5':
            if iv_descartado not in IVS_F5_VALIDOS:
                flash('No F5, escolha qual IV não precisa.', 'erro')
                return redirect(url_for('breed'))
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
        ativos_usuario = supabase.table('pedidos_breed').select(
            'pokemon_id,nature,ha,genero,breed_tipo,iv_descartado,zero_speed,status'
        ).eq('usuario_email', email).in_('status', [
            'pendente','aguardando_pagamento','em_producao','cancelamento_solicitado'
        ]).execute().data or []
        duplicado = any(
            int(x.get('pokemon_id') or 0) == pokemon_id
            and (x.get('nature') or '') == (nature or '')
            and bool(x.get('ha')) == (ha == 'sim')
            and (x.get('genero') or '') == genero
            and (x.get('breed_tipo') or '') == breed_tipo
            and (x.get('iv_descartado') or '') == (iv_descartado or '')
            and bool(x.get('zero_speed')) == bool(zero_speed)
            for x in ativos_usuario
        )
        if duplicado:
            flash('Você já possui um pedido idêntico pendente ou em andamento.', 'erro')
            return redirect(url_for('breed'))

        meta = classificar_pokemon_preco(pokemon_id)
        categoria = (meta.get('categoria') or 'comum').lower()
        if categoria not in ('comum', 'raro'):
            categoria = 'comum'

        # Ditto nunca é escolha manual. O sistema decide pela regra do Pokémon.
        usa_ditto = bool(regra.get('so_com_ditto'))
        preco_total, preco_detalhes = calcular_preco_breed(
            breed_tipo,
            ha=(ha == 'sim'),
            genero=genero,
            categoria=categoria,
            usa_ditto=usa_ditto,
            treinado=treinado,
            nature=nature or None
        )
        if preco_total <= 0:
            flash('Não foi possível calcular o preço. Verifique a tabela de preços no painel administrativo.', 'erro')
            return redirect(url_for('breed'))

        try:
            supabase.table('pedidos_breed').insert({
                'usuario_email': email,
                'player': session.get('nick_jogo'),
                'pokemon': pokemon,
                'pokemon_id': pokemon_id,
                'nature': nature or None,
                'ha': ha == 'sim',
                'genero': genero,
                'breed_tipo': breed_tipo,
                'iv_descartado': iv_descartado,
                'zero_speed': zero_speed,
                'categoria_preco': categoria,
                'usa_ditto': usa_ditto,
                'breed_especial': bool(usa_ditto),
                'hpwr': False,
                'treinado': treinado,
                'preco_total': preco_total,
                'preco_detalhes': preco_detalhes,
                # Mantidos por compatibilidade com pedidos/estrutura antigos.
                'ability': 'HA' if ha == 'sim' else 'Sem HA',
                'nao_precisa': iv_descartado if breed_tipo == 'F5' else None,
                'status': 'pendente'
            }).execute()

            registrar_atividade_reino('breed_criado', email, f"Pedido de Breed: {pokemon}", 'breed')
            especial_txt = ' • BREED ESPECIAL COM DITTO' if usa_ditto else ''
            flash((f'Pedido enviado! Valor calculado: ${preco_total:,}{especial_txt}. Acompanhe o progresso na fila. ⏳').replace(',', '.'), 'sucesso')
        except Exception as e:
            flash(f'Erro ao registrar pedido: {e}', 'erro')

        return redirect(url_for('breed'))

    pode_ver_fila = permissoes.get('pode_ver_fila_breed', False) if permissoes else False

    try:
        # Mantém a lógica existente de devolver pedidos antigos à fila.
        res_verificacao = supabase.table('pedidos_breed').select('*').eq('status', 'em_producao').execute()
        if res_verificacao and res_verificacao.data:
            agora = datetime.now(timezone.utc)
            for pedido in res_verificacao.data:
                data_referencia = parse_data_supabase(pedido.get('pagamento_confirmado_em') or pedido.get('assumido_em') or pedido.get('created_at'))
                try:
                    if data_referencia and agora - data_referencia > timedelta(days=3) and not pedido.get('prazo_notificado'):
                        # O prazo nasce quando o pagamento é confirmado. Não apagamos o responsável:
                        # o pedido fica atrasado e todos recebem aviso, preservando o histórico.
                        supabase.table('pedidos_breed').update({'prazo_notificado': True}).eq('id', pedido['id']).execute()
                        criar_notificacao(pedido.get('breeder_responsavel'), 'Prazo do Breed excedido', f"O pedido #{pedido.get('id')} de {pedido.get('pokemon')} passou de 3 dias.", 'aviso', url_for('breed'))
                        criar_notificacao(pedido.get('usuario_email'), 'Atualização do seu Breed', f"Seu pedido #{pedido.get('id')} passou do prazo de 3 dias e a equipe foi avisada.", 'aviso', url_for('breed'))
                except Exception as err_date:
                    print(f"Erro ao processar data do pedido {pedido.get('id')}: {err_date}")

        if pode_ver_fila:
            pedidos_query = supabase.table('pedidos_breed').select('*').order('created_at', desc=True).execute()
        else:
            pedidos_query = supabase.table('pedidos_breed').select('*').eq('usuario_email', email).order('created_at', desc=True).execute()

        todos_pedidos = pedidos_query.data if (pedidos_query and pedidos_query.data) else []
    except Exception as e:
        print(f"Erro ao buscar pedidos: {e}")
        todos_pedidos = []

    todos_pedidos = enriquecer_pedidos_com_nicks(todos_pedidos)
    fila_ativa = [p for p in todos_pedidos if p.get('status') in [
        'pendente', 'aguardando_pagamento', 'em_producao', 'cancelamento_solicitado'
    ]]
    historico_concluido = [p for p in todos_pedidos if p.get('status') in ['concluido', 'entregue', 'cancelado']]

    return render_template(
        'breed.html',
        fila_ativa=fila_ativa,
        historico_concluido=historico_concluido,
        permissoes=permissoes
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
    ativos = [p for p in pedidos if p.get('status') in ('pendente','aguardando_pagamento','em_producao','cancelamento_solicitado')]
    historico = [p for p in pedidos if p.get('status') in ('concluido','entregue','cancelado')]
    return render_template('breed_meus_pedidos.html', pedidos_ativos=ativos, historico=historico, permissoes=permissoes)


@app.route('/breed/fila')
@login_required
def breed_fila_breeders():
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)
    if not permissoes.get('pode_ver_fila_breed', False):
        flash('A Fila dos Breeders é exclusiva para usuários autorizados.', 'erro')
        return redirect(url_for('breed_meus_pedidos'))
    try:
        pedidos = supabase.table('pedidos_breed').select('*').in_('status', [
            'pendente','aguardando_pagamento','em_producao','cancelamento_solicitado'
        ]).order('created_at', desc=False).execute().data or []
    except Exception as e:
        print(f'Erro ao buscar fila dos Breeders: {e}')
        pedidos = []
    pedidos = enriquecer_pedidos_com_nicks(pedidos)
    return render_template('breed_fila.html', fila_ativa=pedidos, permissoes=permissoes)


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
        if pedido.get('status') != 'pendente':
            flash('Este pedido não está mais disponível para ser assumido.', 'erro')
            return redirect(url_for('breed'))

        pedidos_ativos = supabase.table('pedidos_breed').select('id').eq(
            'breeder_responsavel', email
        ).in_('status', ['aguardando_pagamento','em_producao','cancelamento_solicitado']).execute()

        if pedidos_ativos.data and len(pedidos_ativos.data) >= 4:
            flash('Você já atingiu o limite máximo de 4 pedidos ativos por vez!', 'erro')
            return redirect(url_for('breed'))

        resultado = supabase.table('pedidos_breed').update({
            'status': 'aguardando_pagamento',
            'breeder_responsavel': email,
            'assumido_em': agora_iso(),
            'prazo_notificado': False
        }).eq('id', pedido_id).eq('status', 'pendente').execute()

        if not resultado.data:
            flash('Este pedido acabou de ser assumido por outro Breeder.', 'erro')
            return redirect(url_for('breed'))

        valor = filtro_preco(pedido.get('preco_total') or 0)
        criar_notificacao(
            pedido.get('usuario_email'),
            'Aguardando pagamento',
            f"Seu pedido de {pedido.get('pokemon')} foi assumido por {session.get('nick_jogo')}. Valor: {valor}. A produção só começa após o Breeder confirmar o pagamento.",
            'aviso', url_for('breed')
        )
        criar_notificacao(
            email,
            'Não inicie a produção ainda',
            f"O pedido #{pedido_id} está aguardando pagamento. Confirme o recebimento antes de começar a breedar/chocar.",
            'aviso', url_for('breed')
        )
        registrar_historico('breed', pedido_id, 'pendente', 'aguardando_pagamento', 'Pedido assumido; aguardando confirmação do pagamento.')
        registrar_log('assumir', 'breed', 'pedido_breed', pedido_id, {'status_novo':'aguardando_pagamento'})
        flash('Pedido assumido. Aguarde o pagamento e confirme o recebimento antes de iniciar a produção.', 'sucesso')
    except Exception as e:
        flash(f'Erro ao assumir pedido: {e}', 'erro')

    return redirect(url_for('breed'))


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
            'sucesso', url_for('breed')
        )
        registrar_historico('breed', pedido_id, 'aguardando_pagamento', 'em_producao', 'Pagamento confirmado pelo Breeder; produção liberada.')
        registrar_log('confirmar_pagamento', 'breed', 'pedido_breed', pedido_id, {'valor': pedido.get('preco_total') or 0})
        registrar_atividade_reino('breed_pagamento_confirmado', email, f"Pagamento confirmado: {pedido.get('pokemon')}", 'breed', pedido_id)
        valor_mov = int(pedido.get('preco_total') or 0)
        registrar_transacao_hype(
            pedido.get('usuario_email'), 'saida', 'breed',
            f"Pagamento do Breed #{pedido_id} - {pedido.get('pokemon')}", valor_mov,
            origem_tipo='breed', origem_id=pedido_id, contraparte_email=pedido.get('breeder_responsavel'),
            chave_unica=f'breed:{pedido_id}:cliente'
        )
        registrar_transacao_hype(
            pedido.get('breeder_responsavel'), 'entrada', 'breed',
            f"Recebimento do Breed #{pedido_id} - {pedido.get('pokemon')}", valor_mov,
            origem_tipo='breed', origem_id=pedido_id, contraparte_email=pedido.get('usuario_email'),
            chave_unica=f'breed:{pedido_id}:breeder'
        )
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

        criar_notificacao(pedido.get('usuario_email'), 'Pokémon pronto!', f"Seu {pedido.get('pokemon')} foi concluído e está pronto para entrega.", 'sucesso', url_for('breed'))
        atualizar_conquistas_breeder(pedido.get('breeder_responsavel') or email)
        registrar_atividade_reino('breed_concluido', email, f"Breed concluído: {pedido.get('pokemon')}", 'breed', pedido_id)
        flash('Pedido marcado como concluído! O jogador foi notificado. 🎉', 'sucesso')
    except Exception as e:
        flash(f'Erro ao concluir pedido: {e}', 'erro')

    return redirect(url_for('breed'))


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
            'status': 'entregue',
            'entregue_em': agora_iso()
        }).eq('id', pedido_id).eq('status', 'concluido').execute()

        if not resultado.data:
            flash('Não foi possível entregar este pedido.', 'erro')
            return redirect(url_for('breed'))

        flash('Pokémon entregue com sucesso! Obrigado pelo serviço. ⚔️', 'sucesso')
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
          'especialidades':perfil.get('especialidades') or [],'bio':perfil.get('bio_breeder')})
    ordem={'disponivel':0,'ocupado':1,'ausente':2}
    cards.sort(key=lambda x:(ordem.get(x['status'],9),x['ativos'],x['nick'].casefold()))
    return render_template('team_breeders.html', breeders=cards, permissoes=obter_permissoes_usuario(session.get('usuario_email')))

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
            'pode_gerenciar_economia': request.form.get('pode_gerenciar_economia') is not None
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
    return render_template('admin_conteudo.html', eventos=eventos_lista, torneios=torneios_lista, temporadas=temporadas_lista, formatos_competitivos=formatos_lista)


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


@app.route('/admin/precos', methods=['GET','POST'])
@login_required
def admin_precos():
    if not tem_permissao('pode_gerenciar_precos'): return redirect(url_for('painel'))
    if request.method=='POST':
        codigo=request.form.get('codigo','').strip()
        try:
            valor=parse_valor_moeda(request.form.get('valor',0))
            supabase.table('precos_breed').update({'valor':valor}).eq('codigo',codigo).execute()
            flash('Preço atualizado.','sucesso')
        except Exception as e: flash(f'Erro: {e}','erro')
        return redirect(url_for('admin_precos'))
    return render_template('admin_precos.html', precos=_safe_table('precos_breed','*'))

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
        if p.get('status') in ('concluido','entregue','cancelado'):
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
                registrar_transacao_hype(p.get('usuario_email'),'entrada','estorno_breed',f"Estorno do Breed #{pedido_id}",valor_mov,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('breeder_responsavel'),chave_unica=f'breed:{pedido_id}:estorno_cliente')
                registrar_transacao_hype(p.get('breeder_responsavel'),'saida','estorno_breed',f"Estorno do Breed #{pedido_id}",valor_mov,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('usuario_email'),chave_unica=f'breed:{pedido_id}:estorno_breeder')
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
            registrar_transacao_hype(p.get('usuario_email'),'entrada','estorno_breed',f"Estorno do Breed #{pedido_id}",valor_mov,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('breeder_responsavel'),chave_unica=f'breed:{pedido_id}:estorno_cliente')
            registrar_transacao_hype(p.get('breeder_responsavel'),'saida','estorno_breed',f"Estorno do Breed #{pedido_id}",valor_mov,origem_tipo='breed',origem_id=pedido_id,contraparte_email=p.get('usuario_email'),chave_unica=f'breed:{pedido_id}:estorno_breeder')
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
    if request.method=='POST':
        msg=request.form.get('mensagem','').strip()[:1500]
        if msg:
            supabase.table('mensagens_pedido').insert({'tipo_pedido':tipo,'pedido_id':pedido_id,'remetente_email':email,'mensagem':msg}).execute()
            responsavel=p.get('breeder_responsavel') if tipo=='breed' else p.get('builder_responsavel')
            destino=responsavel if email==p.get('usuario_email') else p.get('usuario_email')
            if destino and destino!=email: criar_notificacao(destino,'Nova mensagem',f'Você recebeu uma mensagem no pedido #{pedido_id}.','mensagem',url_for('chat_pedido',tipo=tipo,pedido_id=pedido_id))
        return redirect(url_for('chat_pedido',tipo=tipo,pedido_id=pedido_id))
    msgs=supabase.table('mensagens_pedido').select('*').eq('tipo_pedido',tipo).eq('pedido_id',pedido_id).order('created_at').execute().data or []
    supabase.table('mensagens_pedido').update({'lida':True}).eq('tipo_pedido',tipo).eq('pedido_id',pedido_id).neq('remetente_email',email).execute()
    return render_template('chat_pedido.html',tipo=tipo,pedido=p,mensagens=msgs)

@app.route('/pedido/<tipo>/<int:pedido_id>/avaliar', methods=['POST'])
@login_required
def avaliar_pedido(tipo,pedido_id):
    if tipo not in ('breed','build'): return redirect(url_for('painel'))
    email=session['usuario_email']; p=_pedido(tipo,pedido_id)
    if not p or p.get('usuario_email')!=email or p.get('status') not in ('concluido','entregue'):
        flash('Este pedido não pode ser avaliado.','erro'); return redirect(url_for('painel'))
    nota=int(request.form.get('nota') or 0); comentario=request.form.get('comentario','').strip()[:700]
    if nota not in range(1,6): flash('A nota deve ser de 1 a 5.','erro'); return redirect(url_for('painel'))
    avaliado=p.get('breeder_responsavel') if tipo=='breed' else p.get('builder_responsavel')
    try:
        supabase.table('avaliacoes').insert({'tipo_pedido':tipo,'pedido_id':pedido_id,'avaliador_email':email,'avaliado_email':avaliado,'nota':nota,'comentario':comentario or None}).execute()
        criar_notificacao(avaliado,'Nova avaliação',f'Você recebeu uma avaliação de {nota}/5.','sucesso',url_for('perfil_publico',nick=session.get('nick_jogo')))
        flash('Avaliação enviada. Obrigado!','sucesso')
    except Exception: flash('Este pedido já foi avaliado ou ocorreu um erro.','erro')
    return redirect(url_for('painel'))

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
    supabase.table('disponibilidade_funcoes').upsert({'usuario_email':email,'funcao':'breeder','status':status,'updated_at':agora_iso()}).execute()
    return redirect(url_for('breed'))

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
    itens = sorted([x for x in _safe_table('lojas_reino') if x.get('ativa', True) and x.get('status') != 'desativada'], key=lambda x: int(x.get('posicao') or 999999))
    produtos = _safe_table('produtos_loja')
    for loja in itens:
        loja['produtos'] = [p for p in produtos if p.get('loja_id') == loja.get('id') and p.get('ativo', True)]
    email = session.get('usuario_email')
    admin = bool(obter_permissoes_usuario(email).get('pode_gerenciar_cargos'))
    meus_pedidos = [p for p in _safe_table('pedidos_loja') if p.get('comprador_email') == email or p.get('lojista_email') == email]
    return render_template('lojas.html', lojas=itens, meus_pedidos=meus_pedidos, admin=admin)


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


@app.route('/reino')
@login_required
def painel_reino():
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
        eventos=eventos, atividades=atividades, reino_resumo=reino_resumo,
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
    casas = sorted([c for c in _safe_table('casas_reino') if c.get('ativa', True) and c.get('status') != 'desativada'], key=lambda x:(x.get('setor') or '', x.get('codigo') or ''))
    mapa = mapa_nicks_por_email()
    for casa in casas:
        casa['ocupante_nick'] = mapa.get(casa.get('ocupante_email'),{}).get('nick') if casa.get('ocupante_email') else None
    return render_template('casas.html', casas=casas)


@app.route('/admin/reino')
@login_required
def admin_reino():
    email = session.get('usuario_email')
    if not obter_permissoes_usuario(email).get('pode_gerenciar_cargos'):
        return redirect(url_for('painel'))
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
# MÓDULOS HYPE - recursos finais separados
# ============================================================================
from modules.final_features import create_final_blueprint
app.register_blueprint(create_final_blueprint(supabase, login_required, _safe_table, _is_admin, registrar_log))

from modules.expansion_features import create_expansion_blueprint
app.register_blueprint(create_expansion_blueprint(
    supabase, login_required, _safe_table, _is_admin, registrar_log,
    parse_valor_moeda, criar_notificacao
))

from modules.competitive_features import create_competitive_blueprint
app.register_blueprint(create_competitive_blueprint(
    supabase, login_required, _safe_table, _is_admin, registrar_log, criar_notificacao
))

from modules.builders_hub import create_builders_hub_blueprint
app.register_blueprint(create_builders_hub_blueprint(
    supabase, login_required, _safe_table, _is_admin
))

# ============================================================================
# INICIALIZADOR DO SERVIDOR
# ============================================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)