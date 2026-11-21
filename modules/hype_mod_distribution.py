"""Publicação manual de JARs HYPE e catálogo autenticado para o Client.

Arquivos de distribuição ficam em bucket PRIVADO diferente dos originais.
Não produz assinaturas e não ativa instalação automática no Minecraft.
"""
import hashlib
import io
import os
import re

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from modules.hype_mod_access import visible_modules_for_user
from modules.hype_mod_staging import IDS, InvalidJar, inspect_original

TABLE = "hype_mod_distribuicao"
BUCKET = "hype-mod-distribuicao"
VALID_PATH = re.compile(r"\A[a-z0-9_]+/[0-9a-f]{64}\.jar\Z")
ALIAS = {
    "hype_pokedex": ("hype_pokedex", "pokedex"),
    "hype_breed_calculator": ("hype_breed_calculator", "breed_calculator"),
    "hype_battlefield": ("hype_battlefield", "campo_batalha", "campo_de_batalha"),
    "hype_battle_ai": ("hype_battle_ai", "battle_ai"),
}


def enabled():
    return os.environ.get("HYPE_MOD_DISTRIBUTION_ENABLED", "").strip().lower() in ("1", "true", "yes")


def bucket_private(storage):
    bucket = storage.get_bucket(BUCKET)
    public = bucket.get("public") if isinstance(bucket, dict) else getattr(bucket, "public", None)
    if public is not False:
        raise RuntimeError("O bucket de distribuição deve ser comprovadamente privado.")


def latest(db):
    """Retorna apenas a versão publicada mais recentemente de cada mod."""
    rows = (db.table(TABLE).select(
        "id,module_id,version,sha256,size_bytes,storage_path,published_at"
    ).eq("status", "publicado").order("published_at", desc=True).limit(300).execute().data or [])
    found = {}
    for row in rows:
        module_id = row.get("module_id")
        if module_id in IDS and module_id not in found:
            found[module_id] = row
    return found


def permitted(db, email, is_member):
    """Sem permissão no gerenciador, não existe link nem download."""
    if not email:
        return set()
    allowed = {"hypeclient"}  # Client é necessário para autenticar os demais mods.
    try:
        u = (db.table("usuarios_clan").select("cargo").eq("email", email)
             .limit(1).execute().data or [])
        if not u:
            return set()
        members = db.table("hype_modulos").select(
            "codigo,nome,estado,visivel,ordem"
        ).limit(300).execute().data or []
        roles = db.table("hype_modulos_grupos").select(
            "modulo_codigo,cargo_id"
        ).limit(2000).execute().data or []
        overrides = db.table("hype_modulos_acessos").select(
            "modulo_codigo,decisao,inicio_em,fim_em"
        ).eq("usuario_email", email).limit(1000).execute().data or []
        decisions = visible_modules_for_user(
            members, roles, overrides, u[0].get("cargo"), bool(is_member(email))
        )
        permitted_codes = {d["codigo"] for d in decisions if d.get("permitido")}
        for module_id, aliases in ALIAS.items():
            if any(code in permitted_codes for code in aliases):
                allowed.add(module_id)
        return allowed
    except Exception:
        return set()  # Falha fechada quando não é possível validar autorização.


def fetch_verified_jar(db, release):
    path = str(release.get("storage_path") or "")
    if not VALID_PATH.fullmatch(path) or not path.startswith(release["module_id"] + "/"):
        abort(503)
    try:
        bucket_private(db.storage)
        raw = db.storage.from_(BUCKET).download(path)
        if not isinstance(raw, bytes):
            raw = bytes(raw)
    except Exception:
        abort(503)
    if (len(raw) != int(release["size_bytes"])
            or hashlib.sha256(raw).hexdigest() != release["sha256"]):
        abort(503)
    result = send_file(
        io.BytesIO(raw), mimetype="application/java-archive",
        as_attachment=True, download_name=release["module_id"] + "-" + release["sha256"][:12] + ".jar"
    )
    result.headers["Cache-Control"] = "no-store, private"
    result.headers["X-Content-Type-Options"] = "nosniff"
    return result


def register_distribution_routes(bp, db, is_admin, registrar_log, is_member):
    def admin():
        if not session.get("usuario_email") or not is_admin():
            abort(403)

    def auth():
        email = session.get("usuario_email")
        if not email:
            return None
        return email

    @bp.get("/mods")
    def downloads():
        email = auth()
        if not email:
            return redirect(url_for("pagina_inicial") + "#entrar")
        releases, allowed, error = {}, set(), None
        if enabled():
            try:
                releases = latest(db)
                allowed = set(IDS) if is_admin() else permitted(db, email, is_member)
            except Exception:
                error = "Catálogo de downloads temporariamente indisponível."
        return render_template(
            "hype_mod_downloads.html", releases=releases, allowed=allowed,
            module_names=IDS, error=error, distribution_enabled=enabled(),
        )

    @bp.get("/mods/<module_id>/baixar")
    def download(module_id):
        email = auth()
        if not email:
            abort(401)
        if not enabled() or module_id not in IDS:
            abort(404)
        if not is_admin() and module_id not in permitted(db, email, is_member):
            abort(403)
        try:
            release = latest(db).get(module_id)
        except Exception:
            abort(503)
        if not release:
            abort(404)
        return fetch_verified_jar(db, release)

    @bp.get("/admin/modulos/publicacoes")
    def publications():
        admin()
        rows, error = [], None
        if enabled():
            try:
                rows = (db.table(TABLE).select(
                    "id,module_id,version,sha256,status,created_at,published_at"
                ).order("created_at", desc=True).limit(150).execute().data or [])
            except Exception:
                error = "Não foi possível ler as publicações. Confira a migração SQL."
        return render_template(
            "admin_hype_mod_distribution.html", items=rows, error=error,
            distribution_enabled=enabled(), module_names=IDS,
        )

    @bp.post("/admin/modulos/publicacoes/enviar")
    def upload():
        admin()
        if not enabled():
            abort(404)
        file = request.files.get("jar")
        if not file or not (file.filename or "").lower().endswith(".jar"):
            flash("Selecione um arquivo .jar de distribuição.", "erro")
            return redirect(url_for("hype_mod_admin.publications"))
        try:
            raw = file.stream.read(10 * 1024 * 1024 + 1)
            report = inspect_original(raw)
            bucket_private(db.storage)
            path = report["module_id"] + "/" + report["sha256"] + ".jar"
            db.storage.from_(BUCKET).upload(
                path=path, file=raw,
                file_options={"content-type": "application/java-archive", "upsert": "false"},
            )
            try:
                db.table(TABLE).insert({
                    "module_id": report["module_id"], "version": report["version"],
                    "sha256": report["sha256"], "size_bytes": report["size_bytes"],
                    "storage_path": path, "status": "rascunho",
                    "uploaded_by": session["usuario_email"],
                }).execute()
            except Exception:
                db.storage.from_(BUCKET).remove([path])
                raise
            if registrar_log:
                registrar_log("preparar_distribuicao_mod", TABLE, "modulo", report["module_id"],
                              {"versao": report["version"], "sha256": report["sha256"]})
            flash("JAR recebido em privado, como rascunho. Nada foi publicado.", "sucesso")
        except InvalidJar as exc:
            flash(str(exc), "erro")
        except Exception:
            flash("Falha ao guardar arquivo; confira bucket, banco e duplicidades.", "erro")
        return redirect(url_for("hype_mod_admin.publications"))

    @bp.post("/admin/modulos/publicacoes/<release_id>/estado")
    def change_status(release_id):
        admin()
        if not enabled():
            abort(404)
        desired = request.form.get("estado")
        if desired not in ("publicado", "suspenso"):
            abort(400)
        try:
            rows = (db.table(TABLE).select("id,module_id,version,status").eq("id", release_id)
                    .limit(1).execute().data or [])
            if not rows:
                abort(404)
            row = rows[0]
            if desired == "publicado" and row["status"] not in ("rascunho", "suspenso"):
                abort(400)
            if desired == "suspenso" and row["status"] != "publicado":
                abort(400)
            from datetime import datetime, timezone
            values = {"status": desired}
            if desired == "publicado":
                values["published_at"] = datetime.now(timezone.utc).isoformat()
            db.table(TABLE).update(values).eq("id", release_id).execute()
            if registrar_log:
                registrar_log("estado_distribuicao_mod", TABLE, "modulo", row["module_id"],
                              {"versao": row["version"], "estado": desired})
            flash("Publicação atualizada.", "sucesso")
        except Exception as exc:
            from werkzeug.exceptions import HTTPException
            if isinstance(exc, HTTPException):
                raise
            flash("Falha ao atualizar a publicação.", "erro")
        return redirect(url_for("hype_mod_admin.publications"))


def register_client_distribution_api(api, secure, db, is_member):
    """Preparação de catálogo para uso por futuras versões do HYPE Client.

    Não habilita instalação automática: somente metadados e downloads autenticados.
    """
    @api.get("/atualizacoes-hype")
    @secure
    def hype_mod_catalog():
        if not enabled():
            return jsonify({"ok": True, "mods": [], "auto_instalacao": False})
        email = g.hype_user["email"]
        try:
            available = permitted(db, email, is_member)
            data = latest(db)
            result = [{
                "modulo": key, "versao": value["version"],
                "sha256": value["sha256"], "tamanho": value["size_bytes"],
                "url": url_for("hype_client_api.hype_mod_binary", module_id=key),
                "auto_instalar": False,
            } for key, value in data.items() if key in available]
            return jsonify({"ok": True, "mods": result, "auto_instalacao": False})
        except Exception:
            return jsonify({"ok": False, "erro": "Catálogo indisponível."}), 503

    @api.get("/atualizacoes-hype/<module_id>/download")
    @secure
    def hype_mod_binary(module_id):
        if not enabled() or module_id not in IDS:
            abort(404)
        if module_id not in permitted(db, g.hype_user["email"], is_member):
            abort(403)
        try:
            item = latest(db).get(module_id)
        except Exception:
            abort(503)
        if not item:
            abort(404)
        return fetch_verified_jar(db, item)
