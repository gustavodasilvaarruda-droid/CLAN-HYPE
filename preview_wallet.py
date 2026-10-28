"""Previa visual isolada da Carteira HYPE, sem acesso a banco de dados.

Somente para homologacao visual. Nao usa Supabase nem aceita POST/pagamentos.
Os templates e arquivos estaticos sao os mesmos da branch de desenvolvimento.
"""
from flask import Flask, redirect, render_template, session, url_for as flask_url_for
from markupsafe import Markup

app = Flask(__name__)
# Apenas dados demonstrativos; nao reutilizar esta aplicacao para producao.
app.secret_key = "hype-preview-visual-sem-contas-reais"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True


@app.template_filter("preco")
def preco(valor):
    try:
        numero = int(valor or 0)
    except (TypeError, ValueError):
        return str(valor)
    if numero >= 1_000_000:
        return f"{numero / 1_000_000:g}kk"
    if numero >= 1_000:
        return f"{numero / 1_000:g}k"
    return str(numero)


def preview_url_for(endpoint, **values):
    if endpoint == "static":
        return flask_url_for("static", **values)
    rotas = {
        "pagina_inicial": "/carteira-hype",
        "painel": "/carteira-hype",
        "hype_wallet.carteira": "/carteira-hype",
        "hype_wallet.admin_depositos": "/admin/carteira-hype",
    }
    return rotas.get(endpoint, "/carteira-hype#somente-demonstracao")


@app.before_request
def marcar_usuario_ficticio():
    session["usuario_email"] = "demonstracao@hype.invalid"
    session["nick_jogo"] = "JogadorDemo"
    session["cargo"] = "lider"


@app.context_processor
def contexto_preview():
    return dict(
        url_for=preview_url_for,
        csrf_token=lambda: "",
        hype_membro_hype=True,
        hype_permissoes={"pode_gerenciar_cargos": True, "pode_ver_fila_breed": True},
        funcoes_usuario=["breeder"],
        hype_header_user={"avatar_url": "", "nome_exibicao": "Jogador de Exemplo", "cargo": "lider"},
        hype_notificacoes_nao_lidas=0,
    )


def pagina_demo(**dados):
    html = render_template("hype_wallet.html", **dados)
    faixa = (
        '<div role="status" style="background:#3b2608;color:#ffe49e;'
        'border:1px solid #d5a341;padding:13px 20px;font:700 13px Arial,sans-serif;'
        'text-align:center">PREVIA VISUAL HYPE — DADOS FICTICIOS. '
        'Nao ha login real, conexao com Supabase, depositos ou transacoes. '
        '<a style="color:#fff;text-decoration:underline;margin-left:14px" '
        'href="/carteira-hype">Carteira</a> | '
        '<a style="color:#fff;text-decoration:underline" '
        'href="/admin/carteira-hype">Area do lider</a></div>'
    )
    return Markup(html.replace('<div class="hgb-app', faixa + '<div class="hgb-app', 1))


@app.get("/")
def home():
    return redirect("/carteira-hype")


@app.get("/carteira-hype")
def carteira():
    return pagina_demo(
        administrador=False, carteira_ativa=True, depositos_ativos=False,
        saldo=1_250_000,
        depositos=[
            {"amount": 500_000, "status": "confirmed", "created_at": "2026-10-27T15:20:00"},
            {"amount": 150_000, "status": "pending", "created_at": "2026-10-28T10:45:00"},
        ],
        movimentos=[
            {"kind": "deposit", "delta": 500_000, "created_at": "2026-10-27T15:30:00"},
            {"kind": "refund", "delta": 750_000, "created_at": "2026-10-24T17:00:00"},
        ],
    )


@app.get("/admin/carteira-hype")
def admin_carteira():
    return pagina_demo(
        administrador=True, carteira_ativa=True, depositos_ativos=False,
        saldo=0, depositos=[], movimentos=[],
        pendentes=[
            {"id": "00000000-0000-4000-8000-000000000001",
             "owner_id": "jogador.exemplo@hype.invalid",
             "amount": 150_000, "created_at": "2026-10-28T10:45:00", "status": "pending"},
        ],
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok", "mode": "visual-preview-no-database"}
