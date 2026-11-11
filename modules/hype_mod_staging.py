"""Admin-only drafts of HYPE Fabric JAR releases. NO automatic publication.

Feature flag is OFF by default. Never put service keys in templates or client JARs.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
from uuid import uuid4
from zipfile import ZipFile, BadZipFile

from flask import abort, flash, redirect, render_template, request, session, url_for
from supabase import create_client

BUCKET = "hype-mod-originals"
TABLE = "hype_mod_release_drafts"
MAX_UPLOAD = 10 * 1024 * 1024
MAX_ENTRIES = 8000
MAX_UNCOMPRESSED = 300 * 1024 * 1024
IDS = {
    "hypeclient": "HYPE Client",
    "hype_pokedex": "HYPE Pokédex",
    "hype_breed_calculator": "HYPE Breed Calculator",
    "hype_battlefield": "HYPE Campo de Batalha",
    "hype_battle_ai": "HYPE Battle AI",
}

class InvalidJar(ValueError):
    pass


def inspect_original(raw):
    """Inspect ZIP metadata, content CRCs and a strict initial HYPE allowlist."""
    if not raw or len(raw) > MAX_UPLOAD:
        raise InvalidJar("Arquivo vazio ou maior que 10 MiB.")
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES:
                raise InvalidJar("JAR possui arquivos demais.")
            names, expanded = set(), 0
            for entry in entries:
                name = entry.filename
                if (not name or name in names or name.startswith("/")
                    or "\\" in name or ".." in name.split("/")
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                    raise InvalidJar("JAR possui entrada ZIP insegura.")
                names.add(name)
                expanded += entry.file_size
                if expanded > MAX_UNCOMPRESSED:
                    raise InvalidJar("Conteúdo descompactado excede o limite.")
            if "fabric.mod.json" not in names:
                raise InvalidJar("Arquivo não contém fabric.mod.json.")
            if archive.getinfo("fabric.mod.json").file_size > 65536:
                raise InvalidJar("Metadados Fabric grandes demais.")
            metadata = json.loads(archive.read("fabric.mod.json"))
            if not isinstance(metadata, dict):
                raise InvalidJar("Metadados Fabric inválidos.")
            module_id = metadata.get("id")
            version = metadata.get("version")
            if not isinstance(module_id, str) or module_id not in IDS:
                raise InvalidJar("Módulo não cadastrado nesta primeira etapa.")
            if not isinstance(version, str) or not 0 < len(version) <= 120:
                raise InvalidJar("Versão do mod inválida.")
            depends = metadata.get("depends") or {}
            if not isinstance(depends, dict):
                raise InvalidJar("Dependências Fabric inválidas.")
            for entry in entries:
                if not entry.is_dir():
                    with archive.open(entry) as stream:
                        for _ in iter(lambda: stream.read(1024 * 1024), b""):
                            pass  # Verify CRC for every ZIP member
            return {
                "module_id": module_id,
                "name": IDS[module_id],
                "version": version,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "has_mixins": bool(metadata.get("mixins")),
                "requires_client": module_id == "hypeclient" or "hypeclient" in depends,
            }
    except (BadZipFile, OSError, EOFError, RuntimeError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidJar("JAR Fabric inválido ou corrompido.") from exc


def assert_private_bucket(storage):
    """Fail closed before uploading original source-equivalent binaries."""
    bucket = storage.get_bucket(BUCKET)
    public = bucket.get("public") if isinstance(bucket, dict) else getattr(bucket, "public", None)
    if public is not False:
        raise RuntimeError("Bucket de originais não é comprovadamente privado.")


def register_mod_release_routes(bp, is_admin, registrar_log):
    """Register routes only when explicit staging flag is enabled."""
    enabled = os.getenv("HYPE_MOD_STAGING_ENABLED", "").lower() in ("1", "true", "yes")
    db = None
    if enabled:
        service_key = os.getenv("HYPE_RELEASE_SUPABASE_SERVICE_ROLE_KEY", "")
        server_url = os.getenv("SUPABASE_URL", "")
        if not server_url or not service_key:
            raise RuntimeError("Configure SUPABASE_URL e a service-role privada no staging.")
        db = create_client(server_url, service_key)

    def admin_only():
        if not session.get("usuario_email") or not is_admin():
            abort(403)

    @bp.get("/admin/modulos/releases")
    def mod_releases():
        admin_only()
        drafts = []
        if db is not None:
            try:
                drafts = (db.table(TABLE).select(
                    "id,module_id,version,status,created_at,sha256"
                ).order("created_at", desc=True).limit(100).execute().data or [])
            except Exception:
                flash("Erro ao consultar rascunhos no banco.", "erro")
        return render_template("admin_hype_mod_releases.html", drafts=drafts,
                               report=None, staging_enabled=enabled)

    @bp.post("/admin/modulos/releases/inspecionar")
    def mod_release_inspect():
        admin_only()
        file = request.files.get("jar")
        if not file or not (file.filename or "").lower().endswith(".jar"):
            flash("Escolha um arquivo .jar.", "erro")
            return redirect(url_for("hype_mod_admin.mod_releases"))
        try:
            report = inspect_original(file.stream.read(MAX_UPLOAD + 1))
        except InvalidJar as exc:
            flash(str(exc), "erro")
            return redirect(url_for("hype_mod_admin.mod_releases"))
        # No file bytes or paths persist in this safe inspection route.
        return render_template("admin_hype_mod_releases.html", drafts=[],
                               report=report, staging_enabled=enabled)

    if not enabled:
        return

    @bp.post("/admin/modulos/releases/upload")
    def mod_release_upload():
        admin_only()
        file = request.files.get("jar")
        if not file or not (file.filename or "").lower().endswith(".jar"):
            flash("Escolha um arquivo .jar.", "erro")
            return redirect(url_for("hype_mod_admin.mod_releases"))
        raw = file.stream.read(MAX_UPLOAD + 1)
        try:
            report = inspect_original(raw)
        except InvalidJar as exc:
            flash(str(exc), "erro")
            return redirect(url_for("hype_mod_admin.mod_releases"))
        path = f'{report["module_id"]}/{uuid4().hex}/{report["sha256"]}.jar'
        uploaded = False
        try:
            assert_private_bucket(db.storage)
            db.storage.from_(BUCKET).upload(
                path=path, file=raw,
                file_options={"content-type": "application/java-archive", "upsert": "false"},
            )
            uploaded = True
            saved = db.table(TABLE).insert({
                "module_id": report["module_id"], "version": report["version"],
                "sha256": report["sha256"], "size_bytes": report["size_bytes"],
                "original_filename": (file.filename or "")[:200], "storage_path": path,
                "uploaded_by": session["usuario_email"], "status": "aguardando_protecao",
                "meta": {"has_mixins": report["has_mixins"], "requires_client": report["requires_client"]},
            }).execute()
            if registrar_log:
                registrar_log("upload_jar_original", "hype_mods", "hype_mod_release_drafts",
                              (saved.data or [{}])[0].get("id"),
                              {"modulo": report["module_id"], "sha256": report["sha256"]})
            flash("Original armazenado em privado. Ainda NÃO foi protegido ou publicado.", "sucesso")
        except Exception:
            if uploaded:
                try:
                    db.storage.from_(BUCKET).remove([path])
                except Exception:
                    pass
            flash("Falha no armazenamento privado. Verifique tabela, bucket e permissões.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))
