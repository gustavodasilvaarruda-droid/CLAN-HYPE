"""Owner-only HYPE pilot: signed updates containing the archived ORIGINAL JAR.

This is intentionally separate from the protected production release catalogue.
A pilot record lives in the draft's private JSON metadata, so publishing does
not require changing existing Supabase tables. No private signing key is stored
here and no unsigned JAR is ever offered to the Bootstrap.
"""
import io
import os
import re
from datetime import datetime, timezone
from uuid import UUID

from modules.hype_mod_pilot_scope import (
    pilot_scope_status, can_account_download_private_mods,
)
from modules.hype_mod_private_releases import (
    BUCKET, DRAFTS, BASE_URL, MAX_BYTES, InvalidPrivateRelease,
    parse_signed_manifest,
)
from modules.hype_mod_staging import assert_private_bucket, inspect_original
from modules.hype_mod_update_access import MOD_TO_SITE_MODULE
from modules.hype_signed_release import SHA, validate_binary


def pilot_original_enabled(authenticated_email=None):
    """Explicit server toggle AND single-account scope; never clan/public."""
    enabled = os.getenv("HYPE_MOD_PILOT_ORIGINAL_ENABLED", "").lower() in ("1", "true", "yes")
    if not enabled or pilot_scope_status() != "single_ready":
        return False
    return (authenticated_email is None or
            can_account_download_private_mods(authenticated_email))


def _safe_draft(draft):
    """Validate the immutable ORIGINAL path, never a protected candidate path."""
    if not isinstance(draft, dict):
        raise InvalidPrivateRelease("Rascunho piloto invalido")
    try:
        draft_id = str(UUID(str(draft["id"])))
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidPrivateRelease("ID do rascunho invalido") from exc
    mod_id, sha = draft.get("module_id"), draft.get("sha256")
    size, path = draft.get("size_bytes"), draft.get("storage_path")
    if (mod_id not in MOD_TO_SITE_MODULE or
            draft.get("status") not in ("aguardando_protecao", "em_teste", "pronto_para_aprovacao") or
            not isinstance(sha, str) or not SHA.fullmatch(sha) or
            type(size) is not int or not 1000 <= size <= MAX_BYTES or
            not isinstance(path, str) or
            not re.fullmatch(rf"{re.escape(mod_id)}/[a-f0-9]{{32}}/{sha}\.jar", path)):
        raise InvalidPrivateRelease("Original nao elegivel para teste privado")
    return draft_id


def _pilot_record(draft):
    _safe_draft(draft)
    pilot = (draft.get("meta") or {}).get("pilot_original")
    if not isinstance(pilot, dict):
        return None
    release = pilot.get("release")
    if type(release) is not int or not 1 <= release <= 999999999:
        raise InvalidPrivateRelease("Numero de release piloto invalido")
    parse_signed_manifest(
        pilot.get("manifest"), module_id=draft["module_id"],
        version=draft["version"], release=release,
        sha256=draft["sha256"], size_bytes=draft["size_bytes"],
    )
    return {
        "id": draft["module_id"], "version": draft["version"],
        "release": release, "sha256": draft["sha256"],
        "size": draft["size_bytes"],
        "url": f"{BASE_URL}{draft['module_id']}/{draft['sha256']}.jar",
        "manifest": pilot["manifest"],
    }


def find_pilot_original(db, module_id, *, sha256=None):
    """Return the latest SIGNED original from private drafts for ONE module."""
    if module_id not in MOD_TO_SITE_MODULE:
        return None
    if sha256 is not None and (not isinstance(sha256, str) or not SHA.fullmatch(sha256)):
        return None
    # Small administrative pilot only; never use a publicly queryable table.
    rows = (db.table(DRAFTS)
            .select("id,module_id,version,status,sha256,size_bytes,storage_path,meta")
            .eq("module_id", module_id).order("created_at", desc=True)
            .limit(500).execute().data or [])
    signed_rows = []
    for draft in rows:
        if not (draft.get("meta") or {}).get("pilot_original"):
            continue
        record = _pilot_record(draft)  # fail closed on any corrupted signed record
        signed_rows.append((draft, record))
    if not signed_rows:
        return None
    # Do not silently downgrade to an earlier pilot if the newest is invalid.
    signed_rows.sort(key=lambda item: item[1]["release"], reverse=True)
    latest = signed_rows[0]
    if sha256 is not None and latest[1]["sha256"] != sha256:
        return None
    return latest



def pilot_selected_source(draft):
    """Which signed release should this one-account Bootstrap pilot receive?"""
    if _pilot_record(draft) is None:
        raise InvalidPrivateRelease("Original piloto nao publicado")
    source = (draft.get("meta") or {}).get("pilot_update_source", "original")
    if source not in ("original", "protected"):
        raise InvalidPrivateRelease("Canal piloto invalido")
    return source


def select_pilot_source(db, *, draft_id, source, selected_by):
    """Owner-only switch, with no new public endpoint or unsigned downloads."""
    if not pilot_original_enabled(selected_by):
        raise InvalidPrivateRelease("Teste individual desativado")
    if source not in ("original", "protected"):
        raise InvalidPrivateRelease("Escolha original ou protegido")
    try:
        draft_id = str(UUID(str(draft_id)))
    except (TypeError, ValueError) as exc:
        raise InvalidPrivateRelease("Rascunho de teste invalido") from exc
    rows = (db.table(DRAFTS).select(
        "id,module_id,version,status,sha256,size_bytes,storage_path,meta"
    ).eq("id", draft_id).limit(2).execute().data or [])
    if len(rows) != 1:
        raise InvalidPrivateRelease("Original piloto nao encontrado")
    draft = rows[0]
    pilot_selected_source(draft)
    latest = find_pilot_original(db, draft["module_id"])
    if latest is None or latest[0]["id"] != draft_id:
        raise InvalidPrivateRelease("Selecione o original piloto mais recente")
    if source == "protected":
        from modules.hype_mod_private_releases import find_private_release
        if find_private_release(db, draft["module_id"]) is None:
            raise InvalidPrivateRelease("Nenhum protegido aprovado e assinado foi publicado")
    meta = dict(draft.get("meta") or {})
    meta["pilot_update_source"] = source
    saved = (db.table(DRAFTS).update({"meta": meta})
             .eq("id", draft_id).eq("status", draft["status"])
             .execute().data or [])
    if len(saved) != 1:
        raise InvalidPrivateRelease("Nao foi possivel alterar o teste")
    return {"module_id": draft["module_id"], "source": source}



def download_pilot_original(db, draft):
    """Read private original, check metadata/hash and return only authenticated."""
    _safe_draft(draft)
    assert_private_bucket(db.storage)
    raw = db.storage.from_(BUCKET).download(draft["storage_path"])
    if not isinstance(raw, bytes) or len(raw) != draft["size_bytes"]:
        raise InvalidPrivateRelease("Tamanho do original nao confere")
    validate_binary(raw, expected_sha=draft["sha256"])
    report = inspect_original(raw)
    if (report["module_id"] != draft["module_id"] or
            report["version"] != draft["version"] or
            report["size_bytes"] != draft["size_bytes"]):
        raise InvalidPrivateRelease("Metadados Fabric do original divergentes")
    return io.BytesIO(raw)


def publish_pilot_original(db, *, draft_id, manifest_bytes, published_by):
    """Explicit admin-only, *offline signed* original. No protection is required."""
    if not pilot_original_enabled(published_by):
        raise InvalidPrivateRelease("Piloto restrito a uma conta nao esta habilitado")
    if not isinstance(manifest_bytes, bytes) or not 50 <= len(manifest_bytes) <= 16384:
        raise InvalidPrivateRelease("Manifesto .properties assinado obrigatorio")
    try:
        manifest = manifest_bytes.decode("ascii")
        draft_id = str(UUID(str(draft_id)))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise InvalidPrivateRelease("Manifesto ou ID invalido") from exc
    releases = re.findall(r"(?m)^release=([1-9][0-9]{0,8})$", manifest)
    if len(releases) != 1:
        raise InvalidPrivateRelease("Numero de release ausente ou repetido")
    release = int(releases[0])
    rows = (db.table(DRAFTS)
            .select("id,module_id,version,status,sha256,size_bytes,storage_path,meta")
            .eq("id", draft_id).limit(2).execute().data or [])
    if len(rows) != 1:
        raise InvalidPrivateRelease("Original nao encontrado")
    draft = rows[0]
    _safe_draft(draft)
    if (draft.get("meta") or {}).get("pilot_original"):
        raise InvalidPrivateRelease("Este original ja foi publicado no piloto")
    parse_signed_manifest(
        manifest, module_id=draft["module_id"], version=draft["version"],
        release=release, sha256=draft["sha256"],
        size_bytes=draft["size_bytes"],
    )
    # Integrity verification happens again when serving the bytes.
    download_pilot_original(db, draft)
    existing = find_pilot_original(db, draft["module_id"])
    if existing and release <= existing[1]["release"]:
        raise InvalidPrivateRelease("Release piloto deve ser maior que a anterior")
    meta = dict(draft.get("meta") or {})
    meta["pilot_original"] = {
        "release": release, "manifest": manifest,
        "published_by": published_by,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    meta["pilot_update_source"] = "original"
    saved = (db.table(DRAFTS).update({"meta": meta})
             .eq("id", draft_id).eq("status", draft["status"])
             .execute().data or [])
    if len(saved) != 1:
        raise InvalidPrivateRelease("Versao mudou; atualize a Central e tente novamente")
    return {"module_id": draft["module_id"], "release": release,
            "sha256": draft["sha256"], "draft_id": draft_id}
