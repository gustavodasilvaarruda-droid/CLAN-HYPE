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
from uuid import UUID, uuid4
from zipfile import ZipFile, BadZipFile

from flask import abort, flash, redirect, render_template, request, session, url_for
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


def register_mod_release_routes(bp, is_admin, registrar_log, db=None):
    """Offer admin-only, non-persistent inspection; retain opt-in private staging."""
    staging_enabled = os.getenv("HYPE_MOD_STAGING_ENABLED", "").lower() in ("1", "true", "yes")
    publish_enabled = staging_enabled and os.getenv("HYPE_MOD_PUBLISH_ENABLED", "").lower() in ("1", "true", "yes")
    protected_upload_enabled = staging_enabled and os.getenv("HYPE_MOD_PROTECTED_UPLOAD_ENABLED", "").lower() in ("1", "true", "yes")
    # Reuse the site's existing server-side Supabase connection. Staging
    # stays disabled unless explicitly enabled in the Render environment.
    # Never expose a service_key or database credentials to templates or JAR files.
    if not staging_enabled:
        db = None

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
                    "id,module_id,version,status,created_at,sha256,meta,size_bytes"
                ).order("created_at", desc=True).limit(100).execute().data or [])
            except Exception:
                flash("Erro ao consultar rascunhos no banco.", "erro")
        return render_template(
            "admin_hype_mod_releases.html", drafts=drafts,
            staging_enabled=staging_enabled, publish_enabled=publish_enabled,
            protected_upload_enabled=protected_upload_enabled,
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
        return render_template(
            "admin_hype_mod_releases.html", drafts=[],
            staging_enabled=staging_enabled, publish_enabled=publish_enabled,
            protected_upload_enabled=protected_upload_enabled,
            report=report, error=error,
        )

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
                }
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


    @bp.post("/admin/modulos/releases/revisar")
    def mod_release_review():
        """Explicit manual review step; this does not publish the original file."""
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
            permitted = {
                "aguardando_protecao": {"em_teste", "rejeitado"},
                "em_teste": {"pronto_para_aprovacao", "rejeitado"},
                "pronto_para_aprovacao": {"em_teste", "rejeitado"},
            }
            if target not in permitted.get(old, set()):
                raise ValueError("Transição de revisão inválida. Atualize a página e tente novamente.")
            if target == "pronto_para_aprovacao" and not (items[0].get("meta") or {}).get("protected"):
                raise ValueError("Registre um build candidato verificado antes de aprovar.")
            if target == "pronto_para_aprovacao" and request.form.get("tested") != "yes":
                raise ValueError("Confirme os testes no jogo antes da aprovação.")
            db.table(TABLE).update({"status": target}).eq("id", draft_id).eq("status", old).execute()
            if registrar_log:
                registrar_log("revisar_release_jar", "hype_mods", TABLE, draft_id,
                              {"antes": old, "depois": target})
            flash("Estado da revisão salvo. O mod ainda não foi publicado.", "sucesso")
        except ValueError as exc:
            flash(str(exc) or "Revisão inválida.", "erro")
        except Exception:
            flash("Não foi possível atualizar a revisão.", "erro")
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
            protected = (draft.get("meta") or {}).get("protected") or {}
            sha = protected.get("sha256")
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
