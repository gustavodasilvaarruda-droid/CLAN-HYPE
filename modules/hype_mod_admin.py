"""Painel administrativo dos módulos HYPE.

Toda gravação passa pela sessão web, permissão administrativa e CSRF global
do app.py. A API do mod continua separada e somente de leitura.
"""
import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

TZ = ZoneInfo("America/Sao_Paulo")
ESTADOS = {"ativo", "manutencao", "desativado"}
DECISOES = {"permitir", "bloquear"}
DURACOES = {"sem_prazo", "horas", "dias", "semanas", "meses", "intervalo"}


def _local_datetime(texto):
    """O input datetime-local é interpretado no fuso de Brasília."""
    if not texto:
        return None
    value = datetime.fromisoformat(texto)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return value.astimezone(timezone.utc)


def calcular_periodo(inicio_texto, tipo, quantidade_texto, fim_texto, *, agora=None):
    """Retorna início/fim em UTC; início inclusivo, fim exclusivo."""
    if tipo not in DURACOES:
        raise ValueError("Escolha uma duração válida.")
    inicio = _local_datetime(inicio_texto) or agora or datetime.now(timezone.utc)
    if tipo == "sem_prazo":
        return inicio.isoformat(), None
    if tipo == "intervalo":
        fim = _local_datetime(fim_texto)
        if fim is None:
            raise ValueError("Informe a data final do intervalo.")
    else:
        try:
            n = int(quantidade_texto)
        except (TypeError, ValueError):
            raise ValueError("Informe uma quantidade inteira válida.") from None
        limites = {"horas": 87600, "dias": 3650, "semanas": 520, "meses": 120}
        if n < 1 or n > limites[tipo]:
            raise ValueError("A quantidade deve ser positiva e não ultrapassar dez anos.")
        if tipo == "horas":
            fim = inicio + timedelta(hours=n)
        elif tipo == "dias":
            fim = inicio + timedelta(days=n)
        elif tipo == "semanas":
            fim = inicio + timedelta(weeks=n)
        else:
            local = inicio.astimezone(TZ)
            mes_zero = local.year * 12 + local.month - 1 + n
            ano, indice_mes = divmod(mes_zero, 12)
            mes = indice_mes + 1
            dia = min(local.day, calendar.monthrange(ano, mes)[1])
            fim = local.replace(year=ano, month=mes, day=dia).astimezone(timezone.utc)
    if fim <= inicio:
        raise ValueError("A data final deve ser posterior à data inicial.")
    return inicio.isoformat(), fim.isoformat()


def create_hype_mod_admin_blueprint(db, login_required, is_admin, registrar_log):
    bp = Blueprint("hype_mod_admin", __name__)

    def exigir_admin():
        if not is_admin():
            abort(403)

    def consultar(tabela, campos="*", limite=2000):
        return db.table(tabela).select(campos).limit(limite).execute().data or []

    def modulo_existente(codigo):
        if not codigo or len(codigo) > 100:
            abort(404)
        itens = (db.table("hype_modulos").select("codigo,nome,estado")
                 .eq("codigo", codigo).limit(1).execute().data or [])
        if not itens:
            abort(404)
        return itens[0]

    def voltar():
        return redirect(url_for("hype_mod_admin.painel"))

    @bp.get("/admin/modulos")
    @login_required
    def painel():
        exigir_admin()
        erro = None
        try:
            modulos = consultar("hype_modulos", "codigo,nome,descricao,estado,versao,visivel,ordem")
            modulos.sort(key=lambda m: (m.get("ordem") or 0, m.get("nome") or ""))
            cargos = consultar("cargos", "id,nome_cargo")
            grupos = consultar("hype_modulos_grupos", "modulo_codigo,cargo_id", 5000)
            acessos = consultar(
                "hype_modulos_acessos",
                "modulo_codigo,usuario_email,decisao,inicio_em,fim_em", 5000
            )
            # Não exibir senhas nem carregar perfis de usuários no painel.
            agora = datetime.now(timezone.utc)
            for acesso in acessos:
                fim = acesso.get("fim_em")
                try:
                    termino = datetime.fromisoformat(fim.replace("Z", "+00:00")) if fim else None
                    acesso["expirado"] = bool(termino and termino <= agora)
                except (ValueError, TypeError):
                    acesso["expirado"] = False
        except Exception:
            erro = "Não foi possível carregar o controle de módulos. Execute a migração SQL desta atualização."
            modulos, cargos, grupos, acessos = [], [], [], []
        return render_template(
            "admin_hype_modulos.html", modulos=modulos, cargos=cargos,
            grupos=grupos, acessos=acessos, erro=erro,
            grupos_virtuais=[
                {"id": "membro", "nome_cargo": "Conta cadastrada (inclui visitantes)"},
                {"id": "membro_hype", "nome_cargo": "Membro HYPE ativo"},
            ],
        )

    @bp.post("/admin/modulos/<codigo>/estado")
    @login_required
    def estado(codigo):
        exigir_admin()
        anterior = modulo_existente(codigo)
        novo = (request.form.get("estado") or "").strip()
        if novo not in ESTADOS:
            flash("Estado de módulo inválido.", "erro")
            return voltar()
        try:
            db.table("hype_modulos").update({"estado": novo}).eq("codigo", codigo).execute()
            registrar_log("alterar_estado_modulo", "hype_modulos", "modulo", codigo,
                          {"antes": anterior.get("estado"), "depois": novo})
            flash("Estado do módulo atualizado.", "sucesso")
        except Exception:
            flash("Não foi possível alterar o estado do módulo.", "erro")
        return voltar()

    @bp.post("/admin/modulos/<codigo>/cargo")
    @login_required
    def cargo(codigo):
        exigir_admin()
        modulo_existente(codigo)
        cargo_id = (request.form.get("cargo_id") or "").strip()
        acao = (request.form.get("acao") or "").strip()
        if acao not in {"permitir", "remover"}:
            flash("Ação inválida.", "erro")
            return voltar()
        if cargo_id not in {"membro", "membro_hype"}:
            ids = {str(c.get("id")) for c in consultar("cargos", "id")}
            if cargo_id not in ids:
                flash("Cargo desconhecido.", "erro")
                return voltar()
        try:
            if acao == "permitir":
                db.table("hype_modulos_grupos").upsert(
                    {"modulo_codigo": codigo, "cargo_id": cargo_id},
                    on_conflict="modulo_codigo,cargo_id"
                ).execute()
            else:
                (db.table("hype_modulos_grupos").delete()
                 .eq("modulo_codigo", codigo).eq("cargo_id", cargo_id).execute())
            registrar_log("alterar_cargo_modulo", "hype_modulos", "modulo", codigo,
                          {"cargo": cargo_id, "acao": acao})
            flash("Permissão do cargo atualizada.", "sucesso")
        except Exception:
            flash("Não foi possível salvar a permissão do cargo.", "erro")
        return voltar()

    @bp.post("/admin/modulos/<codigo>/usuario")
    @login_required
    def usuario(codigo):
        exigir_admin()
        modulo_existente(codigo)
        email = (request.form.get("usuario_email") or "").strip().lower()
        decisao = (request.form.get("decisao") or "").strip()
        if not email or len(email) > 254 or "@" not in email or decisao not in DECISOES:
            flash("Informe um e-mail cadastrado e uma decisão válida.", "erro")
            return voltar()
        try:
            usuario_existe = (db.table("usuarios_clan").select("email")
                              .eq("email", email).limit(1).execute().data or [])
            if not usuario_existe:
                flash("Esse usuário não está cadastrado no site.", "erro")
                return voltar()
            inicio, fim = calcular_periodo(
                request.form.get("inicio_em"), request.form.get("duracao"),
                request.form.get("quantidade"), request.form.get("fim_em")
            )
            registro = {"modulo_codigo": codigo, "usuario_email": email,
                        "decisao": decisao, "inicio_em": inicio, "fim_em": fim}
            db.table("hype_modulos_acessos").upsert(
                registro, on_conflict="modulo_codigo,usuario_email"
            ).execute()
            registrar_log("definir_acesso_modulo", "hype_modulos", "usuario", email,
                          {"modulo": codigo, "decisao": decisao, "inicio_em": inicio, "fim_em": fim})
            flash("Permissão individual salva. Uma nova concessão substitui a anterior.", "sucesso")
        except (ValueError, OverflowError) as exc:
            flash(str(exc), "erro")
        except Exception:
            flash("Não foi possível salvar o acesso. Confira a migração SQL.", "erro")
        return voltar()

    @bp.post("/admin/modulos/<codigo>/usuario/remover")
    @login_required
    def remover_usuario(codigo):
        exigir_admin()
        modulo_existente(codigo)
        email = (request.form.get("usuario_email") or "").strip().lower()
        if not email:
            flash("Usuário inválido.", "erro")
            return voltar()
        try:
            (db.table("hype_modulos_acessos").delete()
             .eq("modulo_codigo", codigo).eq("usuario_email", email).execute())
            registrar_log("revogar_acesso_modulo", "hype_modulos", "usuario", email, {"modulo": codigo})
            flash("Permissão individual encerrada.", "sucesso")
        except Exception:
            flash("Não foi possível encerrar a permissão.", "erro")
        return voltar()

    return bp
