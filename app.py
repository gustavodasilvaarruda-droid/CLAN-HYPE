import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client

app = Flask(__name__)

# Configurações de Segurança e Conexão Supabase
app.secret_key = 'chave_secreta_super_segura_do_cla'

# AJUSTADO: Agora com o ID do seu projeto correto antes do '.supabase.co'
SUPABASE_URL = 'https://fxldojcgvzgdnmpoodqp.supabase.co'

# Sua chave perfeitamente limpa
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ4bGRvamNndnpnZG5tcG9vZHFwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4OTYxMjUzNiwiZXhwIjoyMTA1MTg4NTM2fQ.r95AHcWbRYdQpybBeVjrcmp5nvekhq2wR6TXXZDQtxo'

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


# ============================================================================
# ROTAS PRINCIPAIS
# ============================================================================

@app.route('/')
def pagina_inicial():
    """Página inicial com Hero e Modal de Login/Cadastro."""
    return render_template('index.html')


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
    """Painel do Membro logado."""
    email = session.get('usuario_email')
    
    # CORREÇÃO: Removeu .single() para garantir estabilidade mesmo se o cache falhar
    res_usr = supabase.table('usuarios_clan').select('*').eq('email', email).execute()
    usr = res_usr.data[0] if res_usr.data else {}

    permissoes = obter_permissoes_usuario(email)
    pode_gerenciar = permissoes.get('pode_gerenciar_cargos', False)

    return render_template(
        'painel.html',
        usuario_email=usr.get('email'),
        nick_jogo=usr.get('nick_jogo'),
        cargo=usr.get('cargo', 'membro'),
        pode_gerenciar=pode_gerenciar
    )



# ============================================================================
# ROTAS DO BERÇÁRIO (BREED)
# ============================================================================

@app.route('/breed', methods=['GET', 'POST'])
@login_required
def breed():
    """Exibe pedidos de breed e processa novos pedidos."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if request.method == 'POST':
        # Permissão para solicitar breed
        if not permissoes.get('pode_fazer_pedido_breed', True):
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

            flash('Pedido de breed enviado com sucesso!', 'sucesso')
        except Exception as e:
            flash(f'Erro ao registrar pedido: {e}', 'erro')

        return redirect(url_for('breed'))

    # Método GET: Listar Pedidos
    pode_ver_fila = permissoes.get('pode_ver_fila_breed', False)

    if pode_ver_fila:
        # Breeders e Admins veem todos os pedidos da fila
        pedidos_query = supabase.table('pedidos_breed').select('*').order('created_at', desc=True).execute()
    else:
        # Membros comuns veem apenas os seus próprios pedidos
        pedidos_query = supabase.table('pedidos_breed').select('*').eq('usuario_email', email).order('created_at', desc=True).execute()

    return render_template(
        'breed.html',
        pedidos=pedidos_query.data or [],
        permissoes=permissoes
    )


@app.route('/breed/assumir/<int:pedido_id>', methods=['POST'])
@login_required
def assumir_breed(pedido_id):
    """Assume um pedido de breed na fila."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes.get('pode_assumir_breed', False):
        flash('Você não tem permissão para assumir pedidos de breed.', 'erro')
        return redirect(url_for('breed'))

    try:
        supabase.table('pedidos_breed').update({
            'status': 'em_andamento',
            'breeder_responsavel': email
        }).eq('id', pedido_id).execute()

        flash('Você assumiu este pedido de breed!', 'sucesso')
    except Exception as e:
        flash(f'Erro ao assumir pedido: {e}', 'erro')

    return redirect(url_for('breed'))


@app.route('/breed/concluir/<int:pedido_id>', methods=['POST'])
@login_required
def concluir_breed(pedido_id):
    """Marca um pedido de breed como concluído."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes.get('pode_concluir_breed', False):
        flash('Você não tem permissão para concluir pedidos.', 'erro')
        return redirect(url_for('breed'))

    try:
        supabase.table('pedidos_breed').update({
            'status': 'concluido'
        }).eq('id', pedido_id).execute()

        flash('Pedido marcado como concluído!', 'sucesso')
    except Exception as e:
        flash(f'Erro ao concluir pedido: {e}', 'erro')

    return redirect(url_for('breed'))


# ============================================================================
# ROTAS ADMINISTRATIVAS (GESTÃO DE CARGOS)
# ============================================================================

@app.route('/admin/cargos')
@login_required
def admin_cargos():
    """Painel Admin para criação de cargos e atribuição aos membros."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes.get('pode_gerenciar_cargos', False):
        flash('Acesso negado: Você não é um administrador do clã.', 'erro')
        return redirect(url_for('painel'))

    # Listar todos os usuários e cargos cadastrados
    usuarios = supabase.table('usuarios_clan').select('*').order('nick_jogo').execute()
    cargos = supabase.table('cargos').select('*').execute()

    return render_template(
        'admin_cargos.html',
        usuarios=usuarios.data or [],
        cargos=cargos.data or []
    )


@app.route('/admin/criar-cargo', methods=['POST'])
@login_required
def criar_novo_cargo():
    """Cria um novo cargo e define suas permissões no Supabase."""
    email = session.get('usuario_email')
    permissoes = obter_permissoes_usuario(email)

    if not permissoes.get('pode_gerenciar_cargos', False):
        flash('Acesso negado.', 'erro')
        return redirect(url_for('painel'))

    nome_cargo = request.form.get('nome_cargo', '').strip()
    id_cargo = request.form.get('id_cargo', '').strip().lower().replace(' ', '_')

    if not nome_cargo or not id_cargo:
        flash('Preencha o nome e o ID do cargo.', 'erro')
        return redirect(url_for('admin_cargos'))

    try:
        # 1. Inserir Cargo (O Trigger no Postgres cria a linha em permissoes_cargos)
        supabase.table('cargos').insert({
            'id': id_cargo,
            'nome_cargo': nome_cargo
        }).execute()

        # 2. Atualizar Permissões marcadas no formulário
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

    if not permissoes.get('pode_gerenciar_cargos', False):
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


if __name__ == '__main__':
    app.run(debug=True)
