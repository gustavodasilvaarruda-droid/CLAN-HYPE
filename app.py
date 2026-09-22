import os
from functools import wraps
from datetime import datetime, timedelta, timezone

from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

app = Flask(__name__)

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
                         usa_ditto=False, hpwr=False, treinado=False, nature=None):
    """Preço final calculado no servidor e salvo como snapshot no pedido."""
    linhas = _safe_table('precos_breed', '*', ativo=True)
    precos = {x.get('codigo'): int(x.get('valor') or 0) for x in linhas}
    naturado = bool(nature)
    bt = breed_tipo.lower()
    if hpwr:
        codigo = 'hpwr_com_ditto' if usa_ditto else 'hpwr_sem_ditto'
    elif ha:
        codigo = f"ha_{'com' if usa_ditto else 'sem'}_ditto_{bt}_{'naturado' if naturado else 'sem_nature'}"
    elif categoria == 'raro':
        codigo = f"raro_{bt}_{'naturado' if naturado else 'sem_nature'}"
    else:
        codigo = f"comum_{bt}_{'naturado' if naturado else 'sem_nature'}"
    base = precos.get(codigo)
    if base is None:
        # fallback compatível com códigos antigos
        base = precos.get(codigo.rsplit('_',1)[0], 0)
    total = int(base or 0)
    extras = []
    if genero in ('macho','femea'):
        extra_key = 'escolher_genero_raro' if categoria == 'raro' else 'escolher_genero'
        v = int(precos.get(extra_key, precos.get('escolher_genero',0)) or 0)
        total += v; extras.append({'codigo':extra_key,'valor':v})
    if treinado:
        v=int(precos.get('treinado',0) or 0); total += v; extras.append({'codigo':'treinado','valor':v})
    return total, {'base_codigo': codigo, 'base_valor': int(base or 0), 'extras': extras, 'total': total}


def classificar_pokemon_preco(pokemon_id):
    rows=_safe_table('pokemon_precificacao','*',pokemon_id=pokemon_id)
    return rows[0] if rows else {'categoria':'comum','usa_ditto_padrao':False}


def criar_notificacao(usuario_email, titulo, mensagem, tipo='info', link=None):
    try:
        supabase.table('notificacoes').insert({
            'usuario_email': usuario_email, 'titulo': titulo, 'mensagem': mensagem,
            'tipo': tipo, 'link': link, 'lida': False
        }).execute()
    except Exception as e:
        print(f"Notificação não registrada: {e}")


# ============================================================================
# ROTAS PRINCIPAIS
# ============================================================================

@app.route('/')
def pagina_inicial():
    """Home pública do Clã Hype com dados reais do Supabase."""
    resumo = {'membros': 0, 'breeds': 0, 'breeders': 0}
    destaques = []
    eventos_home = []
    torneios_home = []

    try:
        usuarios = supabase.table('usuarios_clan').select('email,nick_jogo,cargo').execute().data or []
        resumo['membros'] = len(usuarios)
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
        'andamento': sum(p.get('status') == 'em_andamento' for p in pedidos),
        'prontos': sum(p.get('status') == 'concluido' for p in pedidos),
        'entregues': sum(p.get('status') == 'entregue' for p in pedidos),
    }
    notificacoes = _safe_table('notificacoes', '*', usuario_email=email)
    notificacoes = sorted(notificacoes, key=lambda x: x.get('created_at') or '', reverse=True)[:8]
    eventos_proximos = _safe_table('eventos', '*', publicado=True)[:4]
    torneios_proximos = _safe_table('torneios', '*', publicado=True)[:4]
    minhas_inscricoes = _safe_table('inscricoes_torneio', '*', usuario_email=email)

    return render_template('painel.html', usuario=usr, nick_jogo=usr.get('nick_jogo', session.get('nick_jogo')),
        cargo=usr.get('cargo','membro'), pode_gerenciar=pode_gerenciar, permissoes=permissoes,
        resumo=resumo, pedidos=pedidos[:6], notificacoes=notificacoes, eventos_proximos=eventos_proximos,
        torneios_proximos=torneios_proximos, minhas_inscricoes=minhas_inscricoes)


@app.route('/perfil/editar', methods=['POST'])
@login_required
def editar_perfil():
    dados = {
        'avatar_url': request.form.get('avatar_url','').strip() or None,
        'bio': request.form.get('bio','').strip()[:500] or None,
        'pokemon_favorito': request.form.get('pokemon_favorito','').strip()[:80] or None
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
        membro['conquistas'] = _safe_table('conquistas_usuario', '*', usuario_email=email)
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
    'defesa_especial', 'velocidade', 'zero_speed'
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
        usa_ditto = request.form.get('usa_ditto') == 'sim'
        hpwr = request.form.get('hpwr') == 'sim'
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
                flash('No F5, escolha qual IV não precisa ou selecione Zero Speed.', 'erro')
                return redirect(url_for('breed'))
        else:
            iv_descartado = None

        meta = classificar_pokemon_preco(pokemon_id)
        categoria = (meta.get('categoria') or 'comum').lower()
        if categoria not in ('comum','raro'):
            categoria = 'comum'
        # Ditto pode ser exigido pelo cadastro do Pokémon ou escolhido no pedido.
        usa_ditto = bool(usa_ditto or meta.get('usa_ditto_padrao'))
        preco_total, preco_detalhes = calcular_preco_breed(
            breed_tipo, ha=(ha == 'sim'), genero=genero, categoria=categoria,
            usa_ditto=usa_ditto, hpwr=hpwr, treinado=treinado, nature=nature or None
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
                'categoria_preco': categoria,
                'usa_ditto': usa_ditto,
                'hpwr': hpwr,
                'treinado': treinado,
                'preco_total': preco_total,
                'preco_detalhes': preco_detalhes,
                # Mantidos por compatibilidade com pedidos/estrutura antigos.
                'ability': 'HA' if ha == 'sim' else 'Sem HA',
                'nao_precisa': iv_descartado if breed_tipo == 'F5' else None,
                'status': 'pendente'
            }).execute()

            flash(f'Pedido enviado! Valor calculado: ${preco_total:,}. Acompanhe o progresso na fila. ⏳'.replace(',', '.'), 'sucesso')
        except Exception as e:
            flash(f'Erro ao registrar pedido: {e}', 'erro')

        return redirect(url_for('breed'))

    pode_ver_fila = permissoes.get('pode_ver_fila_breed', False) if permissoes else False

    try:
        # Mantém a lógica existente de devolver pedidos antigos à fila.
        res_verificacao = supabase.table('pedidos_breed').select('*').eq('status', 'em_andamento').execute()
        if res_verificacao and res_verificacao.data:
            agora = datetime.now(timezone.utc)
            for pedido in res_verificacao.data:
                data_referencia = parse_data_supabase(pedido.get('assumido_em') or pedido.get('created_at'))
                try:
                    if data_referencia and agora - data_referencia > timedelta(days=3):
                        supabase.table('pedidos_breed').update({
                            'status': 'pendente',
                            'breeder_responsavel': None,
                            'assumido_em': None
                        }).eq('id', pedido['id']).execute()
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
    fila_ativa = [p for p in todos_pedidos if p.get('status') in ['pendente', 'em_andamento']]
    historico_concluido = [p for p in todos_pedidos if p.get('status') in ['concluido', 'entregue']]

    return render_template(
        'breed.html',
        fila_ativa=fila_ativa,
        historico_concluido=historico_concluido,
        permissoes=permissoes
    )


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
        ).eq('status', 'em_andamento').execute()

        if pedidos_ativos.data and len(pedidos_ativos.data) >= 4:
            flash('Você já atingiu o limite máximo de 4 pedidos ativos por vez!', 'erro')
            return redirect(url_for('breed'))

        resultado = supabase.table('pedidos_breed').update({
            'status': 'em_andamento',
            'breeder_responsavel': email,
            'assumido_em': agora_iso()
        }).eq('id', pedido_id).eq('status', 'pendente').execute()

        if not resultado.data:
            flash('Este pedido acabou de ser assumido por outro Breeder.', 'erro')
            return redirect(url_for('breed'))

        criar_notificacao(pedido.get('usuario_email'), 'Breed assumido', f"{session.get('nick_jogo')} assumiu seu pedido de {pedido.get('pokemon')}.", 'breed', url_for('breed'))
        flash('Você assumiu este pedido de breed! Mãos à obra. 🥚', 'sucesso')
    except Exception as e:
        flash(f'Erro ao assumir pedido: {e}', 'erro')

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
        if pedido.get('status') != 'em_andamento':
            flash('Somente pedidos em andamento podem ser concluídos.', 'erro')
            return redirect(url_for('breed'))

        # Regra principal: Breeder comum nunca conclui trabalho de outro Breeder.
        pode_gerenciar = permissoes.get('pode_gerenciar_cargos', False)
        if pedido.get('breeder_responsavel') != email and not pode_gerenciar:
            flash('Somente o Breeder responsável pode concluir este pedido.', 'erro')
            return redirect(url_for('breed'))

        resultado = supabase.table('pedidos_breed').update({
            'status': 'concluido',
            'concluido_em': agora_iso()
        }).eq('id', pedido_id).eq('status', 'em_andamento').execute()

        if not resultado.data:
            flash('Não foi possível concluir este pedido.', 'erro')
            return redirect(url_for('breed'))

        criar_notificacao(pedido.get('usuario_email'), 'Pokémon pronto!', f"Seu {pedido.get('pokemon')} foi concluído e está pronto para entrega.", 'sucesso', url_for('breed'))
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
            'pode_gerenciar_cargos': request.form.get('pode_gerenciar_cargos') is not None
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
    return render_template('eventos.html', eventos=dados)


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
                t['campeao'] = next((x.get('vencedor_nick') for x in sorted(t['partidas'], key=lambda y:(y.get('rodada',0),y.get('ordem',0)), reverse=True) if x.get('status')=='finalizada'), None) if t['partidas'] else None
            except Exception:
                t['total_inscritos'] = 0
                t['participantes'] = []; t['partidas']=[]; t['usuario_inscrito']=False; t['campeao']=None
    except Exception as e:
        print(f'Erro ao carregar torneios: {e}')
        dados = []
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
    return render_template('admin_conteudo.html', eventos=eventos_lista, torneios=torneios_lista)


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
        supabase.table('torneios').update({'status_torneio':'finalizado','campeao_email':vencedores[0]['email'],'campeao_nick':vencedores[0]['nick']}).eq('id',torneio_id).execute()
        criar_notificacao(vencedores[0]['email'],'CAMPEÃO! 🏆','Você conquistou o torneio do Clã Hype!','campeao',url_for('torneios'))
        flash(f"Campeão definido: {vencedores[0]['nick']}! 🏆",'sucesso'); return redirect(url_for('admin_chave_torneio',torneio_id=torneio_id))
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
            valor=max(0,int(request.form.get('valor',0)))
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
            try: supabase.table(tabela).insert(payload).execute(); flash('Conteúdo publicado.','sucesso')
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
# INICIALIZADOR DO SERVIDOR
# ============================================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)