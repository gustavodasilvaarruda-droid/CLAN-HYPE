import os
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client
from dotenv import load_dotenv

# Carrega as variáveis salvas no arquivo .env
load_dotenv()

app = Flask(__name__)

# Configurações de Segurança e Conexão Supabase
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'chave_secreta_padrao_local')

# Puxando as credenciais corretas direto do arquivo .env
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_ANON_KEY')

# Validação para alertar caso as chaves não estejam configuradas no servidor (Render)
if not SUPABASE_URL or not SUPABASE_KEY:
    print("ATENÇÃO: SUPABASE_URL ou SUPABASE_KEY não foram encontradas nas variáveis de ambiente!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================================================
# HELPER FUNCTIONS & DECORATORS
# ============================================================================

def obter_permissoes_usuario(email):
    """Busca as permissões do cargo atual do usuário logado de forma segura."""
    if not email:
        return {}
    
    try:
        res_usr = supabase.table('usuarios_clan').select('cargo').eq('email', email).execute()
        if not res_usr.data:
            return {}
        
        cargo_id = res_usr.data[0].get('cargo')
        
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


# ============================================================================
# ROTAS PRINCIPAIS
# ============================================================================

@app.route('/')
def pagina_inicial():
    """Página inicial com Hero e Modal de Login/Cadastro."""
    return render_template('index.html')


@app.route('/login', methods=['POST'])
def login_membro():
    """Processa tanto o Login quanto o Cadastro do clã."""
    acao = request.form.get('acao')
    email = request.form.get('email', '').strip().lower()
    senha = request.form.get('senha', '').strip()
    nick_jogo = request.form.get('nick_jogo', '').strip()

    if not email or not senha:
        flash('Preencha todos os campos obrigatórios!', 'erro')
        return redirect(url_for('pagina_inicial'))

    # CADASTRO DE NOVO MEMBRO
    if acao == 'cadastro':
        if not nick_jogo:
            flash('Informe seu Nick no Jogo para se cadastrar.', 'erro')
            return redirect(url_for('pagina_inicial'))

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

            flash(f'Bem-vindo ao Clã, {nick_jogo}! ⚔️', 'sucesso')
            return redirect(url_for('painel'))
        except Exception as e:
            flash(f'Erro ao cadastrar: {e}', 'erro')
            return redirect(url_for('pagina_inicial'))

    # LOGIN DE USUÁRIO JÁ EXISTENTE
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
    """Encerra a sessão atual do usuário."""
    session.clear()
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('pagina_inicial'))


@app.route('/painel')
@login_required
def painel():
    """Painel principal do jogador com sistema de Notificação Inteligente."""
    email = session.get('usuario_email')
    
    try:
        res_usr = supabase.table('usuarios_clan').select('*').eq('email', email).execute()
        usr = res_usr.data[0] if (res_usr and res_usr.data) else {}
    except Exception as e:
        print(f"Erro ao buscar usuário: {e}")
        usr = {}

    permissoes = obter_permissoes_usuario(email)
    pode_gerenciar = permissoes.get('pode_gerenciar_cargos', False) if permissoes else False

    notificacao = None
    try:
        res_notif = supabase.table('pedidos_breed').select('*').eq('usuario_email', email).eq('status', 'concluido').order('created_at', desc=True).execute()
        
        if res_notif and getattr(res_notif, 'data', None) and len(res_notif.data) > 0:
            ultimo_pronto = res_notif.data[0]
            breeder = ultimo_pronto.get('breeder_responsavel', 'um Breeder')
            pokemon_nome = ultimo_pronto.get('pokemon', 'Pokémon')
            notificacao = f"Excelente notícia! Seu pedido de {pokemon_nome.upper()} foi chocado com sucesso por {breeder}! Combine a entrega no jogo. 🎉"
    except Exception as e:
        print(f"Erro na notificação: {e}")

    return render_template(
        'painel.html',
        usuario_email=usr.get('email', email),
        nick_jogo=usr.get('nick_jogo', session.get('nick_jogo')),
        cargo=usr.get('cargo', 'membro'),
        pode_gerenciar=pode_gerenciar,
        notificacao=notificacao
    )


# ============================================================================
# ROTAS DO BERÇÁRIO (SISTEMA DE BREED UPGRADED) 🌟
# ============================================================================

@app.route('/breed', methods=['GET', 'POST'])
@login_required
def breed():
    """Exibe fila ativa de trabalho, histórico separado e recebe pedidos com reset automático de 3 dias."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if request.method == 'POST':
        if not permissoes or not permissoes.get('pode_fazer_pedido_breed', True):
            flash('Seu cargo não possui permissão para solicitar breeds.', 'erro')
            return redirect(url_for('breed'))

        pokemon = request.form.get('pokemon', '').strip()
        nature = request.form.get('nature', '').strip()
        ability = request.form.get('ability', '').strip()
        nao_precisa = request.form.get('nao_precisa', '').strip()

        if not pokemon or not nature:
            flash('Os campos Pokémon e Nature são obrigatórios!', 'erro')
            return redirect(url_for('breed'))

        try:
            supabase.table('pedidos_breed').insert({
                'usuario_email': email,
                'player': session.get('nick_jogo'),
                'pokemon': pokemon,
                'nature': nature,
                'ability': ability,
                'nao_precisa': nao_precisa,
                'status': 'pendente'
            }).execute()

            flash('Pedido enviado com sucesso! Acompanhe o progresso na linha do tempo. ⏳', 'sucesso')
        except Exception as e:
            flash(f'Erro ao registrar pedido: {e}', 'erro')

        return redirect(url_for('breed'))

    pode_ver_fila = permissoes.get('pode_ver_fila_breed', False) if permissoes else False

    try:
        res_verificacao = supabase.table('pedidos_breed').select('*').eq('status', 'em_andamento').execute()
        if res_verificacao and res_verificacao.data:
            agora = datetime.utcnow()
            for pedido in res_verificacao.data:
                created_at_str = pedido.get('created_at', '').split('+')[0]
                try:
                    data_pedido = datetime.fromisoformat(created_at_str)
                    if agora - data_pedido > timedelta(days=3):
                        supabase.table('pedidos_breed').update({
                            'status': 'pendente',
                            'breeder_responsavel': None
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
    
    fila_ativa = [p for p in todos_pedidos if p.get('status') in ['pendente', 'em_andamento']]
    historico_concluido = [p for p in todos_pedidos if p.get('status') in ['concluido', 'entregue']]

    return render_template(
        'breed.html',
        fila_ativa=fila_ativa,
        historico_concluido=historico_concluido,
        permissoes=permissoes
    )


@app.route('/breed/assumir/<int:pedido_id>', methods=['POST'])
@login_required
def assumir_breed(pedido_id):
    """Modifica o status para 'em_andamento' aplicando regras de travas."""
    email = session.get('usuario_email')  
    permissoes = obter_permissoes_usuario(email)

    if not permissoes or not permissoes.get('pode_assumir_breed', False):
        flash('Você não tem permissão para assumir pedidos de breed.', 'erro')
        return redirect(url_for('breed'))

    try:
        checar_pedido = supabase.table('pedidos_breed').select('*').eq('id', pedido_id).execute()
        if checar_pedido and checar_pedido.data:
            if checar_pedido.data[0].get('status') == 'em_andamento':
                flash('Este pedido já foi assumido por outro Breeder!', 'erro')
                return redirect(url_for('breed'))

        pedidos_ativos = supabase.table('pedidos_breed').select('id').eq('breeder_responsavel', email).eq('status', 'em_andamento').execute()
        if pedidos_ativos and pedidos_ativos.data and len(pedidos_ativos.data) >= 4:
            flash('Você já atingiu o limite máximo de 4 pedidos ativos por vez! Conclua algum antes de pegar outro. ❌', 'erro')
            return redirect(url_for('breed'))

        supabase.table('pedidos_breed').update({
            'status': 'em_andamento',
            'breeder_responsavel': email  
        }).eq('id', pedido_id).execute()

        flash('Você assumiu este pedido de breed! Mãos à obra. 🥚', 'sucesso')
    except Exception as e:
        flash(f'Erro ao assumir pedido: {e}', 'erro')

    return redirect(url_for('breed'))


@app.route('/breed/concluir/<int:pedido_id>', methods=['POST'])
@login_required
def concluir_breed(pedido_id):
    """Marca o pedido como concluído e envia o Pokémon para o Histórico."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes or not permissoes.get('pode_assumir_breed', False):
        flash('Você não tem permissão para concluir pedidos de breed.', 'erro')
        return redirect(url_for('breed'))

    try:
        supabase.table('pedidos_breed').update({
            'status': 'concluido'
        }).eq('id', pedido_id).execute()

        flash('Pedido marcado como concluído! O jogador será notificado no painel. 🎉', 'sucesso')
    except Exception as e:
        flash(f'Erro ao concluir pedido: {e}', 'erro')

    return redirect(url_for('breed'))


@app.route('/breed/entregar/<int:pedido_id>', methods=['POST'])
@login_required
def entregar_breed(pedido_id):
    """Marca o pedido como entregue ao jogador finalizando o ciclo."""
    try:
        supabase.table('pedidos_breed').update({
            'status': 'entregue'
        }).eq('id', pedido_id).execute()

        flash('Pokémon entregue com sucesso! Obrigado pelo serviço. ⚔️', 'sucesso')
    except Exception as e:
        flash(f'Erro ao entregar pedido: {e}', 'erro')

    return redirect(url_for('breed'))


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
        res_usuarios = supabase.table('usuarios_clan').select('*').execute()
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

        supabase.table('permissoes_cargos').update({
            'pode_ver_fila_breed': bool(request.form.get('pode_ver_fila_breed')),
            'pode_assumir_breed': bool(request.form.get('pode_assumir_breed')),
            'pode_concluir_breed': bool(request.form.get('pode_concluir_breed')),
            'pode_gerenciar_cargos': bool(request.form.get('pode_gerenciar_cargos'))
        }).eq('cargo_id', id_cargo).execute()

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
# INICIALIZADOR DO SERVIDOR (APENAS NO FINAL DO ARQUIVO)
# ============================================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
