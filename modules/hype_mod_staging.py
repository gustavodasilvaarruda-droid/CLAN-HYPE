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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4
from zipfile import ZipFile, BadZipFile

from flask import abort, flash, redirect, render_template, request, session, send_file, url_for
from modules.hype_signed_release import InvalidRelease, verify_signed_manifest, validate_binary
from modules.hype_mod_build_checks import check_fabric_classes, check_candidate_compatibility, UnsafeBuild

BUCKET = "hype-mod-originals"
TABLE = "hype_mod_release_drafts"
PUBLISHED = "hype_mod_published_releases"
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


def parse_draft_id(raw):
    """Accept live UUID draft IDs and older bigint IDs, rejecting malformed values."""
    value = (raw or "").strip()
    if value.isdecimal():
        numeric_id = int(value)
        if numeric_id > 0:
            return numeric_id
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Identificador da versão inválido.") from None


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
            compatibility = {
                "minecraft": depends.get("minecraft") if isinstance(depends.get("minecraft"), str) else None,
                "fabricloader": depends.get("fabricloader") if isinstance(depends.get("fabricloader"), str) else None,
                "cobblemon": depends.get("cobblemon") if isinstance(depends.get("cobblemon"), str) else None,
                "java": depends.get("java") if isinstance(depends.get("java"), str) else None,
            }
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
                "compatibility": compatibility,
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


def audit_candidate_pair(original, candidate, draft):
    """Read-only, static checks of the exact archived binaries; never execute JAR code."""
    meta = draft.get("meta") or {}
    protected = meta.get("protected") or {}
    expected = protected.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise InvalidJar("Build candidato não registrado ou hash inválido.")
    validate_binary(original, expected_sha=draft["sha256"])
    validate_binary(candidate, expected_sha=expected)
    first = inspect_original(original)
    second = inspect_original(candidate)
    if (first["module_id"], first["version"]) != (draft["module_id"], draft["version"]):
        raise InvalidJar("Metadados do original divergentes do registro.")
    if (second["module_id"], second["version"]) != (draft["module_id"], draft["version"]):
        raise InvalidJar("Metadados do candidato divergentes do registro.")
    if protected.get("size_bytes") != len(candidate):
        raise InvalidJar("Tamanho do candidato não confere.")
    class_audit = check_candidate_compatibility(original, candidate)
    if draft["module_id"] == "hypeclient" and not class_audit.get("updater_present"):
        raise InvalidJar("Atualizador HYPE Client ausente.")
    return {
        "status": "passed",
        "candidate_sha256": expected,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "integrity": "passed",
            "fabric_metadata": "passed",
            "classes": "passed",
            "updater": "passed" if draft["module_id"] == "hypeclient" else "not_applicable",
        },
        "entrypoints_checked": class_audit["entrypoints_checked"],
    }


def read_original_for_admin_test(db, draft_id):
    """Admin-gated caller only: read an archived original without publication.

    Never returns a public Storage URL, changes draft status, or puts the
    unprotected bytes into the player-facing update catalog.
    """
    parsed = parse_draft_id(str(draft_id))
    rows = (db.table(TABLE)
            .select("id,module_id,version,status,sha256,storage_path")
            .eq("id", parsed).limit(2).execute().data or [])
    if len(rows) != 1:
        raise InvalidJar("Original de teste nao encontrado.")
    draft = rows[0]
    module_id = draft.get("module_id")
    sha = draft.get("sha256")
    path = draft.get("storage_path")
    if (module_id not in IDS
            or draft.get("status") not in ("aguardando_protecao", "em_teste")
            or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
            or not isinstance(path, str)
            or not re.fullmatch(rf"{re.escape(module_id)}/[0-9a-f]{{32}}/{sha}\\.jar", path)):
        raise InvalidJar("Original indisponivel para teste privado.")
    assert_private_bucket(db.storage)
    raw = db.storage.from_(BUCKET).download(path)
    if not isinstance(raw, bytes):
        raise InvalidJar("Leitura do JAR privado invalida.")
    validate_binary(raw, expected_sha=sha)
    report = inspect_original(raw)
    if (report["module_id"] != module_id
            or report["version"] != draft.get("version")
            or report["sha256"] != sha):
        raise InvalidJar("Arquivo privado nao corresponde a versao registrada.")
    return raw, report


def register_mod_release_routes(bp, is_admin, registrar_log, db=None):
    """Offer admin-only, non-persistent inspection; retain opt-in private staging."""
    staging_enabled = os.getenv("HYPE_MOD_STAGING_ENABLED", "").lower() in ("1", "true", "yes")
    publish_enabled = staging_enabled and os.getenv("HYPE_MOD_PUBLISH_ENABLED", "").lower() in ("1", "true", "yes")
    protected_upload_enabled = staging_enabled and os.getenv("HYPE_MOD_PROTECTED_UPLOAD_ENABLED", "").lower() in ("1", "true", "yes")
    protection_queue_enabled = staging_enabled and os.getenv("HYPE_MOD_PROTECTION_QUEUE_ENABLED", "").lower() in ("1", "true", "yes")
    original_test_download_enabled = staging_enabled and os.getenv(
        "HYPE_MOD_ORIGINAL_TEST_DOWNLOAD_ENABLED", ""
    ).lower() in ("1", "true", "yes")
    # Explicit independent gate; must never be enabled by ordinary staging.
    private_publish_enabled = publish_enabled and os.getenv("HYPE_MOD_PRIVATE_PUBLISH_ENABLED", "").lower() in ("1", "true", "yes")
    from modules.hype_mod_pilot_scope import pilot_scope_status
    @bp.app_template_filter("hype_br_datetime")
    def hype_br_datetime(value):
        """Show upload timestamps in Brazil time, never fabricate missing dates."""
        if not value:
            return "Data não disponível"
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y às %H:%M")
        except (TypeError, ValueError, OverflowError):
            return "Data não disponível"

    # Reuse the site's existing server-side Supabase connection. Staging
    # stays disabled unless explicitly enabled in the Render environment.
    # Never expose a service_key or database credentials to templates or JAR files.
    if not staging_enabled:
        db = None

    def admin_only():
        if not session.get("usuario_email") or not is_admin():
            abort(403)

    def load_drafts():
        """Load real stored files both on the dashboard and after inspection."""
        if db is None:
            return []
        return (db.table(TABLE).select(
            "id,module_id,version,status,created_at,sha256,meta,size_bytes,original_filename"
        ).order("created_at", desc=True).limit(100).execute().data or [])

    def load_protection_jobs():
        if db is None or not protection_queue_enabled:
            return {}
        from modules.hype_mod_protection_queue import jobs_for_drafts
        return jobs_for_drafts(db)

    @bp.get("/admin/modulos/releases/original-teste/<draft_id>")
    def mod_release_original_test_download(draft_id):
        """Admin-only download for local testing. NEVER a Bootstrap release."""
        admin_only()
        if not original_test_download_enabled or db is None:
            abort(404)
        try:
            raw, report = read_original_for_admin_test(db, draft_id)
        except (InvalidJar, InvalidRelease, ValueError):
            abort(404)
        except Exception:
            abort(503)
        filename = f'{report["module_id"]}-original-teste-{report["sha256"][:12]}.jar'
        response = send_file(
            io.BytesIO(raw), mimetype="application/java-archive",
            as_attachment=True, download_name=filename, max_age=0,
        )
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @bp.get("/admin/modulos/releases")
    def mod_releases():
        admin_only()
        drafts = []
        if db is not None:
            try:
                drafts = load_drafts()
            except Exception:
                flash("Erro ao consultar rascunhos no banco.", "erro")
        try:
            protection_jobs = load_protection_jobs()
        except Exception:
            protection_jobs = {}
            flash("Nao foi possivel consultar a fila de protecao.", "erro")
        return render_template(
            "admin_hype_mod_releases.html", drafts=drafts,
            protection_queue_enabled=protection_queue_enabled, protection_jobs=protection_jobs,
            staging_enabled=staging_enabled, publish_enabled=publish_enabled,
            protected_upload_enabled=protected_upload_enabled,
            original_test_download_enabled=original_test_download_enabled,
            private_publish_enabled=private_publish_enabled,
            private_rollout_status=pilot_scope_status(),
            report=None, error=None,
        )

    @bp.post("/admin/modulos/releases/analisar")
    def mod_release_inspect():
        """Analyze a supplied JAR in memory only. Never store or publish it."""
        admin_only()
        file = request.files.get("jar")
        report, error = None, None
        if not file or not (file.filename or "").lower().endswith(".jar"):
            error = "Selecione um arquivo .jar válido."
        else:
            try:
                report = inspect_original(file.stream.read(MAX_UPLOAD + 1))
            except InvalidJar as exc:
                error = str(exc)
        # Inspection must never make the stored versions disappear from the UI.
        try:
            drafts = load_drafts()
        except Exception:
            drafts = []
            flash("Nao foi possivel carregar a lista de JARs armazenados.", "erro")
        try:
            protection_jobs = load_protection_jobs()
        except Exception:
            protection_jobs = {}
            flash("Nao foi possivel consultar a fila de protecao.", "erro")
        return render_template(
            "admin_hype_mod_releases.html", drafts=drafts,
            protection_queue_enabled=protection_queue_enabled, protection_jobs=protection_jobs,
            staging_enabled=staging_enabled, publish_enabled=publish_enabled,
            protected_upload_enabled=protected_upload_enabled,
            original_test_download_enabled=original_test_download_enabled,
            private_publish_enabled=private_publish_enabled,
            private_rollout_status=pilot_scope_status(),
            report=report, error=error,
        )

    @bp.post("/admin/modulos/releases/solicitar-protecao")
    def mod_release_request_protection():
        """Admin-only request. The web request NEVER executes the obfuscator."""
        admin_only()
        if not protection_queue_enabled or db is None:
            abort(404)
        try:
            from modules.hype_mod_protection_queue import queue_protection
            job_id = queue_protection(db, request.form.get("draft_id"), session["usuario_email"])
            if registrar_log:
                registrar_log("solicitar_protecao_jar", "hype_mods", "hype_mod_protection_jobs",
                              str(job_id), {"status": "queued"})
            flash("Protecao solicitada. O original continua privado e nada foi publicado.", "sucesso")
        except (InvalidJar, ValueError) as exc:
            flash(str(exc), "erro")
        except Exception:
            flash("Nao foi possivel agendar a protecao. Confira a fila e o banco de dados.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))

    @bp.post("/admin/modulos/releases/upload")
    def mod_release_upload():
        admin_only()
        if not staging_enabled or db is None:
            abort(404)
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
            try:
                static_audit = check_fabric_classes(raw)
            except UnsafeBuild as exc:
                # Originals may be archived for analysis even before the
                # updater/entrypoints are fixed; candidates remain strict.
                static_audit = {"status": "needs_review", "reason": str(exc)}
            saved = db.table(TABLE).insert({
                "module_id": report["module_id"], "version": report["version"],
                "sha256": report["sha256"], "size_bytes": report["size_bytes"],
                "original_filename": (file.filename or "")[:200], "storage_path": path,
                "uploaded_by": session["usuario_email"], "status": "aguardando_protecao",
                "meta": {"has_mixins": report["has_mixins"], "requires_client": report["requires_client"],
                         "compatibility": report["compatibility"], "static_audit": static_audit},
            }).execute()
            if registrar_log:
                registrar_log("upload_jar_original", "hype_mods", "hype_mod_release_drafts",
                              (saved.data or [{}])[0].get("id"),
                              {"modulo": report["module_id"], "sha256": report["sha256"]})
            if protection_queue_enabled:
                # Enfileira automaticamente apenas depois do upload privado e
                # do registro do draft. Falha na fila nao apaga o original.
                try:
                    from modules.hype_mod_protection_queue import queue_after_upload
                    job_id = queue_after_upload(
                        db, (saved.data or [None])[0],
                        session["usuario_email"], enabled=True,
                    )
                except Exception:
                    flash(
                        "Original guardado em privado, mas a fila de proteção falhou. "
                        "Use 'Solicitar proteção' para tentar novamente.",
                        "erro",
                    )
                else:
                    if registrar_log:
                        try:
                            registrar_log(
                                "solicitar_protecao_jar_automatica", "hype_mods",
                                "hype_mod_protection_jobs", str(job_id),
                                {"status": "queued", "module_id": report["module_id"]},
                            )
                        except Exception:
                            pass  # Falha de log nao reverte o upload nem a fila.
                    flash(
                        "Original guardado em privado e enviado automaticamente "
                        "para a fila. Ainda NÃO foi ofuscado ou publicado.",
                        "sucesso",
                    )
            else:
                flash("Original armazenado em privado. Ainda NÃO foi protegido ou publicado.", "sucesso")
        except Exception:
            if uploaded:
                try:
                    db.storage.from_(BUCKET).remove([path])
                except Exception:
                    pass
            flash("Falha no armazenamento privado. Verifique tabela, bucket e permissões.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))


    @bp.post("/admin/modulos/releases/protegido")
    def mod_release_protected_upload():
        """Stage a separately built candidate, never an automatically published JAR."""
        admin_only()
        if not protected_upload_enabled or db is None:
            abort(404)
        path = None
        try:
            draft_id = parse_draft_id(request.form.get("draft_id"))
            file = request.files.get("jar")
            if not file or not (file.filename or "").lower().endswith(".jar"):
                raise InvalidJar("Escolha um build protegido .jar.")
            rows = (db.table(TABLE).select(
                "id,module_id,version,status,sha256,storage_path,meta"
            ).eq("id", draft_id).limit(1).execute().data or [])
            if not rows:
                abort(404)
            draft = rows[0]
            if draft["status"] != "em_teste":
                raise InvalidJar("Coloque a versão em teste antes de registrar o build protegido.")
            if (draft.get("meta") or {}).get("protected"):
                raise InvalidJar("Já existe um candidato neste registro. Crie um novo rascunho para outro JAR, preservando o histórico.")
            assert_private_bucket(db.storage)
            original = db.storage.from_(BUCKET).download(draft["storage_path"])
            validate_binary(original, expected_sha=draft["sha256"])
            raw = file.stream.read(MAX_UPLOAD + 1)
            report = inspect_original(raw)
            check_candidate_compatibility(original, raw)
            if (report["module_id"], report["version"]) != (draft["module_id"], draft["version"]):
                raise InvalidJar("O build deve ter o mesmo módulo e versão do original.")
            path = f'{report["module_id"]}/{draft_id}/protected/{uuid4().hex}/{report["sha256"]}.jar'
            db.storage.from_(BUCKET).upload(
                path=path, file=raw,
                file_options={"content-type": "application/java-archive", "upsert": "false"},
            )
            try:
                meta = dict(draft.get("meta") or {})
                meta["protected"] = {
                    "storage_path": path, "sha256": report["sha256"],
                    "size_bytes": report["size_bytes"], "static_audit": "passed",
                    "obfuscation_verified": False,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                }
                meta["automatic_review"] = audit_candidate_pair(
                    original, raw, {**draft, "meta": meta}
                )
                meta.pop("manual_review", None)
                saved = (db.table(TABLE).update({"meta": meta})
                         .eq("id", draft_id).eq("status", "em_teste").execute())
                if not saved.data:
                    raise RuntimeError("Registro alterado durante o envio.")
            except Exception:
                db.storage.from_(BUCKET).remove([path])
                raise
            if registrar_log:
                try:
                    registrar_log("upload_jar_protected_candidate", "hype_mods", TABLE, draft_id,
                                  {"sha256": report["sha256"]})
                except Exception:
                    pass
            flash("Build candidato guardado e verificado. A ofuscação e o teste em jogo ainda precisam ser validados.", "sucesso")
        except (InvalidJar, UnsafeBuild, InvalidRelease, ValueError) as exc:
            flash(str(exc), "erro")
        except Exception:
            flash("Falha no armazenamento do build candidato. Confira o bucket e as permissões.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))



    @bp.post("/admin/modulos/releases/vincular-existente")
    def mod_release_link_existing():
        """Reuse an already archived candidate, copying it to a private protected path.

        This is a safe *linking* operation, NOT an obfuscator. Both input records
        stay immutable, and a candidate can never be published without Minecraft
        review plus a valid Ed25519-signed manifest.
        """
        admin_only()
        if not protected_upload_enabled or db is None:
            abort(404)
        path = None
        try:
            draft_id = parse_draft_id(request.form.get("draft_id"))
            source_id = parse_draft_id(request.form.get("source_id"))
            if draft_id == source_id:
                raise InvalidJar("O candidato e o original devem ser arquivos diferentes.")
            target_rows = (db.table(TABLE).select(
                "id,module_id,version,status,sha256,storage_path,meta"
            ).eq("id", draft_id).limit(1).execute().data or [])
            source_rows = (db.table(TABLE).select(
                "id,module_id,version,status,sha256,storage_path,meta"
            ).eq("id", source_id).limit(1).execute().data or [])
            if not target_rows or not source_rows:
                raise InvalidJar("Original ou candidato armazenado nao encontrado.")
            draft, source = target_rows[0], source_rows[0]
            if draft["status"] != "em_teste":
                raise InvalidJar("Escolha um original que esteja em teste.")
            if (draft.get("meta") or {}).get("protected"):
                raise InvalidJar("Esse original ja tem um candidato. Crie outro rascunho.")
            if source["status"] not in ("aguardando_protecao", "em_teste"):
                raise InvalidJar("O arquivo candidato selecionado nao esta disponivel.")
            if (source.get("meta") or {}).get("protected"):
                raise InvalidJar("Escolha um arquivo simples, sem candidato vinculado.")
            if (source["module_id"], source["version"]) != (draft["module_id"], draft["version"]):
                raise InvalidJar("O candidato deve ter o mesmo modulo e versao do original.")
            if source["sha256"] == draft["sha256"]:
                raise InvalidJar("O candidato e identico ao original. Nenhuma protecao detectavel.")

            assert_private_bucket(db.storage)
            original = db.storage.from_(BUCKET).download(draft["storage_path"])
            candidate = db.storage.from_(BUCKET).download(source["storage_path"])
            validate_binary(original, expected_sha=draft["sha256"])
            validate_binary(candidate, expected_sha=source["sha256"])
            report = inspect_original(candidate)
            if (report["module_id"], report["version"]) != (draft["module_id"], draft["version"]):
                raise InvalidJar("Metadados Fabric do candidato divergentes.")
            check_candidate_compatibility(original, candidate)
            path = (f'{report["module_id"]}/{draft_id}/protected/'
                    f'{uuid4().hex}/{report["sha256"]}.jar')
            db.storage.from_(BUCKET).upload(
                path=path, file=candidate,
                file_options={"content-type": "application/java-archive", "upsert": "false"},
            )
            try:
                meta = dict(draft.get("meta") or {})
                meta["protected"] = {
                    "storage_path": path,
                    "sha256": report["sha256"],
                    "size_bytes": report["size_bytes"],
                    "static_audit": "passed",
                    "obfuscation_verified": False,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "source_draft_id": str(source_id),
                }
                meta["automatic_review"] = audit_candidate_pair(
                    original, candidate, {**draft, "meta": meta}
                )
                meta.pop("manual_review", None)
                saved = (db.table(TABLE).update({"meta": meta})
                         .eq("id", draft_id).eq("status", "em_teste").execute())
                if not saved.data:
                    raise RuntimeError("A versao mudou. Atualize a pagina.")
            except Exception:
                db.storage.from_(BUCKET).remove([path])
                raise
            if registrar_log:
                try:
                    registrar_log("vincular_jar_protegido_armazenado", "hype_mods", TABLE, draft_id,
                                  {"candidate_sha256": report["sha256"],
                                   "source_draft_id": str(source_id)})
                except Exception:
                    pass
            flash("Candidato armazenado vinculado e verificado. Ainda falta testar no Minecraft e aprovar.", "sucesso")
        except (InvalidJar, InvalidRelease, UnsafeBuild, ValueError) as exc:
            flash(str(exc), "erro")
        except Exception:
            flash("Falha ao vincular o arquivo. Nada foi publicado.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))

    @bp.post("/admin/modulos/releases/verificar")
    def mod_release_verify():
        """Re-run static checks against private stored bytes; no Minecraft runtime execution."""
        admin_only()
        if not protected_upload_enabled or db is None:
            abort(404)
        try:
            draft_id = parse_draft_id(request.form.get("draft_id"))
            rows = (db.table(TABLE).select(
                "id,module_id,version,status,sha256,storage_path,meta"
            ).eq("id", draft_id).limit(1).execute().data or [])
            if not rows:
                raise ValueError("Rascunho não encontrado.")
            draft = rows[0]
            if draft["status"] != "em_teste":
                raise ValueError("Somente versões em teste podem ser verificadas novamente.")
            meta = dict(draft.get("meta") or {})
            protected = meta.get("protected") or {}
            if not protected.get("storage_path"):
                raise ValueError("Registre o JAR candidato antes da verificação.")
            assert_private_bucket(db.storage)
            original = db.storage.from_(BUCKET).download(draft["storage_path"])
            candidate = db.storage.from_(BUCKET).download(protected["storage_path"])
            report = audit_candidate_pair(original, candidate, draft)
            meta["automatic_review"] = report
            meta.pop("manual_review", None)
            saved = (db.table(TABLE).update({"meta": meta})
                     .eq("id", draft_id).eq("status", "em_teste").execute())
            if not saved.data:
                raise ValueError("A versão mudou durante a verificação. Atualize a página.")
            if registrar_log:
                registrar_log("verificar_jar_candidato", "hype_mods", TABLE, draft_id,
                              {"sha256": report["candidate_sha256"], "resultado": "passed"})
            flash("Verificações estáticas passaram. Falta confirmar os testes dentro do Minecraft.", "sucesso")
        except (InvalidJar, UnsafeBuild, InvalidRelease, ValueError, RuntimeError) as exc:
            # A failed recheck must never leave an older passing report trusted.
            if "draft" in locals() and draft.get("status") == "em_teste":
                try:
                    meta = dict(draft.get("meta") or {})
                    meta["automatic_review"] = {
                        "status": "failed",
                        "candidate_sha256": (meta.get("protected") or {}).get("sha256"),
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "reason": str(exc)[:300],
                    }
                    meta.pop("manual_review", None)
                    db.table(TABLE).update({"meta": meta}).eq("id", draft_id).eq("status", "em_teste").execute()
                except Exception:
                    pass
            flash(str(exc), "erro")
        except Exception:
            flash("Não foi possível verificar os arquivos privados. Não aprove até corrigir.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))

    @bp.post("/admin/modulos/releases/excluir")
    def mod_release_delete():
        """Delete an unused private draft and its stored JARs, never a live release."""
        admin_only()
        if not staging_enabled or db is None:
            abort(404)
        if request.form.get("confirm_delete") != "yes":
            flash("Confirme a exclusão do JAR antes de continuar.", "erro")
            return redirect(url_for("hype_mod_admin.mod_releases"))
        try:
            draft_id = parse_draft_id(request.form.get("draft_id"))
            rows = (db.table(TABLE).select(
                "id,module_id,version,status,sha256,storage_path,meta"
            ).eq("id", draft_id).limit(1).execute().data or [])
            if not rows:
                raise ValueError("Arquivo não encontrado. Atualize a página.")
            draft = rows[0]
            state = draft.get("status")
            if state not in {"aguardando_protecao", "rejeitado"}:
                raise ValueError("Apenas arquivos pendentes ou rejeitados podem ser apagados. "
                                 "Versões em teste, aprovadas ou publicadas estão protegidas.")

            # Storage paths always come from trusted DB records, never a browser field.
            module_id = draft.get("module_id")
            sha = draft.get("sha256")
            original_path = draft.get("storage_path")
            if (module_id not in IDS or not isinstance(sha, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", sha)
                    or not isinstance(original_path, str)
                    or not re.fullmatch(
                        rf"{re.escape(module_id)}/[0-9a-f]{{32}}/{sha}\.jar",
                        original_path,
                    )):
                raise ValueError("Caminho do original inválido; exclusão bloqueada por segurança.")
            paths = [original_path]
            protected = (draft.get("meta") or {}).get("protected") or {}
            if protected:
                protected_sha = protected.get("sha256")
                protected_path = protected.get("storage_path")
                if (not isinstance(protected_sha, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", protected_sha)
                        or not isinstance(protected_path, str)
                        or not re.fullmatch(
                            rf"{re.escape(module_id)}/{re.escape(str(draft_id))}/protected/"
                            rf"[0-9a-f]{{32}}/{protected_sha}\.jar",
                            protected_path,
                        )):
                    raise ValueError("Caminho do build protegido inválido; exclusão bloqueada.")
                paths.append(protected_path)

            # Never delete a release referenced in the catalog, including disabled
            # releases retained for rollback and old versions still in use.
            if (db.table(PUBLISHED).select("release").eq("draft_id", draft_id)
                    .limit(1).execute().data or []):
                raise ValueError("Esta versão está vinculada a uma publicação e não pode ser apagada.")
            for path in paths:
                if (db.table(PUBLISHED).select("release").eq("storage_path", path)
                        .limit(1).execute().data or []):
                    raise ValueError("Este arquivo faz parte de uma publicação e não pode ser apagado.")

            assert_private_bucket(db.storage)
            # Delete the database record first. A published release's FK protects
            # it even if another admin starts publication between the two checks.
            # Then remove ONLY the paths belonging to this now-deleted draft.
            removed = (db.table(TABLE).delete().eq("id", draft_id)
                       .eq("status", state).execute().data or [])
            if not removed:
                raise ValueError("O arquivo mudou de estado. Atualize a página.")
            try:
                db.storage.from_(BUCKET).remove(paths)
            except Exception:
                # Orphaned files are private; no active release is ever broken.
                if registrar_log:
                    try:
                        registrar_log("limpeza_jar_pendente", "hype_mods", TABLE, draft_id,
                                      {"storage_paths": paths, "motivo": "falha_no_storage"})
                    except Exception:
                        pass
                flash("Registro removido, mas a limpeza do armazenamento falhou. "
                      "É necessária conferência administrativa.", "erro")
                return redirect(url_for("hype_mod_admin.mod_releases"))
            if registrar_log:
                try:
                    registrar_log("excluir_jar_privado", "hype_mods", TABLE, draft_id,
                                  {"modulo": module_id, "status": state,
                                   "sha256": sha, "arquivos": len(paths)})
                except Exception:
                    pass
            flash("JAR privado antigo excluído com segurança.", "sucesso")
        except ValueError as exc:
            flash(str(exc), "erro")
        except Exception:
            flash("Não foi possível excluir o JAR. Nenhuma versão publicada foi liberada.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))


    @bp.post("/admin/modulos/releases/revisar")
    def mod_release_review():
        """Keep manual evidence bound to the same candidate SHA-256 as the static report."""
        admin_only()
        if not staging_enabled or db is None:
            abort(404)
        try:
            draft_id = parse_draft_id(request.form.get("draft_id"))
            target = request.form.get("status") or ""
            if target not in {"em_teste", "pronto_para_aprovacao", "rejeitado"}:
                raise ValueError("Etapa de revisão inválida.")
            items = (db.table(TABLE).select("id,status,module_id,meta")
                     .eq("id", draft_id).limit(1).execute().data or [])
            if not items:
                abort(404)
            old = items[0]["status"]
            # Nao permitir que o admin mova manualmente um original enquanto
            # um worker ja esta trabalhando na mesma versao.
            if protection_queue_enabled and old == "aguardando_protecao" and target == "em_teste":
                from modules.hype_mod_protection_queue import JOBS
                jobs = (db.table(JOBS).select("status")
                        .eq("draft_id", str(draft_id)).limit(1).execute().data or [])
                if jobs and jobs[0].get("status") in ("queued", "running"):
                    raise ValueError("Esta versao esta na fila de protecao. Aguarde o resultado.")
            permitted = {
                "aguardando_protecao": {"em_teste", "rejeitado"},
                "em_teste": {"pronto_para_aprovacao", "rejeitado"},
                "pronto_para_aprovacao": {"em_teste", "rejeitado"},
            }
            if target not in permitted.get(old, set()):
                raise ValueError("Transição de revisão inválida. Atualize a página e tente novamente.")
            meta = dict(items[0].get("meta") or {})
            if target == "pronto_para_aprovacao":
                protected = meta.get("protected") or {}
                sha = protected.get("sha256")
                if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                    raise ValueError("Registre um build candidato verificado antes de aprovar.")
                auto = meta.get("automatic_review") or {}
                if auto.get("status") != "passed" or auto.get("candidate_sha256") != sha:
                    raise ValueError("Execute as verificações automáticas deste candidato antes de aprovar.")
                if request.form.get("candidate_sha256") != sha:
                    raise ValueError("O candidato mudou. Atualize a página e confira o SHA-256.")
                required = ("game_launch", "menus", "server_connection", "no_crashes")
                if any(request.form.get("test_" + key) != "yes" for key in required):
                    raise ValueError("Confirme os quatro testes no Minecraft antes da aprovação.")
                meta["manual_review"] = {
                    "candidate_sha256": sha,
                    "checks": {key: True for key in required},
                    "tested_by": session["usuario_email"],
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                    "notes": (request.form.get("test_notes") or "").strip()[:1000],
                }
            else:
                # A returning/rejected build cannot keep a stale approval receipt.
                meta.pop("manual_review", None)
            updated = (db.table(TABLE).update({"status": target, "meta": meta})
                       .eq("id", draft_id).eq("status", old).execute())
            if not updated.data:
                raise ValueError("A versão mudou. Atualize a página e tente novamente.")
            if registrar_log:
                registrar_log("revisar_release_jar", "hype_mods", TABLE, draft_id,
                              {"antes": old, "depois": target,
                               "candidate_sha256": (meta.get("protected") or {}).get("sha256")})
            flash("Revisão registrada. O mod não foi publicado.", "sucesso")
        except ValueError as exc:
            flash(str(exc) or "Revisão inválida.", "erro")
        except Exception:
            flash("Não foi possível atualizar a revisão.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))

    @bp.post("/admin/modulos/releases/publicar-privado")
    def mod_release_publish_private():
        """Publish one admin-approved private JAR; no automatic signing/upload."""
        admin_only()
        if not private_publish_enabled or db is None:
            abort(404)
        from modules.hype_mod_private_publication import (
            publish_first_private_release,
        )
        from modules.hype_mod_private_releases import InvalidPrivateRelease
        try:
            if request.form.get("confirm_release") != "yes":
                raise InvalidPrivateRelease("Confirme explicitamente a publicacao deste JAR.")
            draft_id = parse_draft_id(request.form.get("draft_id"))
            manifest_file = request.files.get("manifest")
            if not manifest_file or not (manifest_file.filename or "").endswith(".properties"):
                raise InvalidPrivateRelease("Envie o manifesto assinado .properties.")
            manifest = manifest_file.stream.read(16385)
            record = publish_first_private_release(
                db, draft_id=draft_id, manifest_bytes=manifest,
                published_by=session["usuario_email"])
            if registrar_log:
                registrar_log(
                    "publicar_release_mod_privado", "hype_mods",
                    "hype_mod_restricted_releases", record["release"],
                    {"modulo": record["module_id"], "draft_id": draft_id,
                     "sha256": record["sha256"]})
            flash("Release privada registrada. Downloads continuam protegidos pelas flags e permissoes.", "sucesso")
        except (InvalidPrivateRelease, ValueError) as exc:
            flash(str(exc), "erro")
        except Exception:
            flash("Nao foi possivel publicar a release privada; nada foi liberado automaticamente.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))

    @bp.post("/admin/modulos/releases/publicar")
    def mod_release_publish():
        """Publish only a JAR with an independently signed, matching manifest.

        No private signing key is stored on the web server. A human must review
        the protected build, game-test it, and supply the Ed25519-signed manifest.
        """
        admin_only()
        if not publish_enabled or db is None:
            abort(404)
        try:
            draft_id = parse_draft_id(request.form.get("draft_id"))
            signed_file = request.files.get("manifest")
            if not signed_file or not (signed_file.filename or "").endswith(".properties"):
                raise InvalidRelease("Envie o manifesto assinado .properties.")
            signed_bytes = signed_file.stream.read(16385)
            rows = (db.table(TABLE).select(
                "id,module_id,version,status,sha256,size_bytes,storage_path,meta"
            ).eq("id", draft_id).limit(1).execute().data or [])
            if not rows:
                raise InvalidRelease("Versão não encontrada.")
            draft = rows[0]
            if draft["module_id"] != "hypeclient" or draft["status"] != "pronto_para_aprovacao":
                raise InvalidRelease("Somente o Client aprovado e testado pode ser publicado.")
            draft_meta = draft.get("meta") or {}
            protected = draft_meta.get("protected") or {}
            sha = protected.get("sha256")
            automatic = draft_meta.get("automatic_review") or {}
            manual = draft_meta.get("manual_review") or {}
            if (automatic.get("status") != "passed"
                    or automatic.get("candidate_sha256") != sha
                    or manual.get("candidate_sha256") != sha
                    or not all(manual.get("checks", {}).get(key) is True for key in
                               ("game_launch", "menus", "server_connection", "no_crashes"))):
                raise InvalidRelease("Revisão automática e teste manual deste JAR não estão completos.")
            size = protected.get("size_bytes")
            storage_path = protected.get("storage_path") or ""
            if not (isinstance(sha, str) and re.fullmatch("[0-9a-f]{64}", sha)
                    and isinstance(size, int) and 1000 <= size <= MAX_UPLOAD
                    and storage_path.startswith(f'hypeclient/{draft_id}/protected/')
                    and storage_path.endswith("/" + sha + ".jar")):
                raise InvalidRelease("Falta o build candidato protegido verificado.")
            assert_private_bucket(db.storage)
            original = db.storage.from_(BUCKET).download(draft["storage_path"])
            raw = db.storage.from_(BUCKET).download(storage_path)
            validate_binary(original, expected_sha=draft["sha256"])
            validate_binary(raw, expected_sha=sha)
            check_candidate_compatibility(original, raw)
            report = inspect_original(raw)
            if (report["module_id"] != draft["module_id"] or
                    report["version"] != draft["version"] or
                    report["size_bytes"] != size):
                raise InvalidRelease("Metadados do JAR não conferem com a versão aprovada.")
            # Reject a release that cannot check for subsequent updates.
            with ZipFile(io.BytesIO(raw)) as archive:
                if "br/clanhype/client/update/HypeAutoUpdateClient.class" not in archive.namelist():
                    raise InvalidRelease("O HYPE Client enviado não possui o atualizador.")
            signed = verify_signed_manifest(
                signed_bytes, version=draft["version"], sha256=sha,
                size_bytes=size)
            prior = (db.table(PUBLISHED).select("release")
                     .order("release", desc=True).limit(1).execute().data or [])
            if prior and signed["release"] <= int(prior[0]["release"]):
                raise InvalidRelease("A nova release precisa ter número maior que as anteriores.")
            db.table(PUBLISHED).insert({
                "release": signed["release"], "draft_id": draft_id,
                "module_id": "hypeclient", "version": signed["version"],
                "sha256": signed["sha256"], "size_bytes": signed["size_bytes"],
                "storage_path": storage_path, "manifest": signed["content"],
                "status": "published", "published_by": session["usuario_email"],
            }).execute()
            if registrar_log:
                registrar_log("publicar_release_hypeclient", "hype_mods", PUBLISHED,
                              signed["release"], {"sha256": signed["sha256"], "draft_id": draft_id})
            flash("Versão assinada registrada. A entrega exige HYPE_MOD_DISTRIBUTION_ENABLED=1.", "sucesso")
        except (InvalidRelease, InvalidJar, UnsafeBuild, ValueError) as exc:
            flash(str(exc), "erro")
        except Exception:
            flash("Falha na publicação; confira o catálogo, o bucket e a configuração.", "erro")
        return redirect(url_for("hype_mod_admin.mod_releases"))
