"""Explicit, offline-signed publication of protected, approved private HYPE mods.

This helper NEVER obfuscates, signs a manifest, grants permissions or toggles
distribution flags. It publishes one reviewed protected JAR per module. Until
an atomic switch/rollback is available, replacing an active release is denied.
"""
import re
from uuid import UUID

from modules import hype_signed_release as signed
from modules.hype_mod_private_releases import (
    BASE_URL, BUCKET, DRAFTS, TABLE, InvalidPrivateRelease,
    _approved_candidate, parse_signed_manifest,
)
from modules.hype_mod_staging import (
    assert_private_bucket, inspect_original, check_candidate_compatibility,
    validate_binary,
)

MAX_MANIFEST_BYTES = 16384


def validate_private_publication(db, *, draft_id, manifest_bytes, published_by):
    """Return a validated INSERT row; no writes, no use of any private key."""
    if not isinstance(published_by, str) or not published_by.strip():
        raise InvalidPrivateRelease("Administrador nao identificado")
    try:
        draft_id = str(UUID(str(draft_id)))
    except (TypeError, ValueError) as exc:
        raise InvalidPrivateRelease("Identificador de rascunho invalido") from exc
    if not isinstance(manifest_bytes, bytes) or not 50 <= len(manifest_bytes) <= MAX_MANIFEST_BYTES:
        raise InvalidPrivateRelease("Manifesto assinado ausente ou fora do limite")
    try:
        manifest = manifest_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise InvalidPrivateRelease("Manifesto precisa ser ASCII") from exc

    drafts = (db.table(DRAFTS)
              .select("id,module_id,version,status,sha256,storage_path,meta")
              .eq("id", draft_id).limit(2).execute().data or [])
    if len(drafts) != 1:
        raise InvalidPrivateRelease("Rascunho nao encontrado ou ambiguo")
    draft = drafts[0]
    protected = (draft.get("meta") or {}).get("protected") or {}
    module_id = draft.get("module_id")
    sha = protected.get("sha256")
    size = protected.get("size_bytes")
    path = protected.get("storage_path")
    candidate = {
        "module_id": module_id, "draft_id": draft_id,
        "version": draft.get("version"), "sha256": sha,
        "size_bytes": size, "storage_path": path,
    }
    _approved_candidate(db, candidate)  # all four game tests and static audit
    values = {}
    for line in manifest.splitlines():
        if "=" not in line:
            raise InvalidPrivateRelease("Linha de assinatura invalida")
        name, value = line.split("=", 1)
        if name in values:
            raise InvalidPrivateRelease("Campo duplicado")
        values[name] = value
    release_string = values.get("release", "")
    if not re.fullmatch(r"[1-9][0-9]{0,8}", release_string):
        raise InvalidPrivateRelease("Sequencia de release invalida")
    release = int(release_string)
    parse_signed_manifest(manifest, module_id=module_id,
                          version=draft.get("version"), release=release,
                          sha256=sha, size_bytes=size)

    # Verify both archived artifacts and private bucket AGAIN at publish time.
    try:
        assert_private_bucket(db.storage)
    except RuntimeError as exc:
        raise InvalidPrivateRelease("Bucket privado nao verificado") from exc
    original = db.storage.from_(BUCKET).download(draft["storage_path"])
    binary = db.storage.from_(BUCKET).download(path)
    validate_binary(original, expected_sha=draft["sha256"])
    validate_binary(binary, expected_sha=sha)
    if len(binary) != size:
        raise InvalidPrivateRelease("Tamanho do protegido nao confere")
    check_candidate_compatibility(original, binary)
    meta = inspect_original(binary)
    if (meta["module_id"] != module_id or meta["version"] != draft["version"]
            or meta["size_bytes"] != size):
        raise InvalidPrivateRelease("Metadados Fabric divergentes")

    active = (db.table(TABLE).select("release")
              .eq("module_id", module_id).eq("status", "published")
              .limit(1).execute().data or [])
    previous = (db.table(TABLE).select("release,status")
                .eq("module_id", module_id)
                .order("release", desc=True).limit(1).execute().data or [])
    if active or (previous and release <= int(previous[0]["release"])):
        # No unsafe nontransactional swap; database unique index is a final guard.
        raise InvalidPrivateRelease("Ja existe versao ativa ou release nao crescente. Troca atomica pendente.")
    return {
        "module_id": module_id,
        "release": release,
        "draft_id": draft_id,
        "version": draft["version"],
        "sha256": sha,
        "size_bytes": size,
        "storage_path": path,
        "manifest": manifest,
        "status": "published",
        "published_by": published_by.strip(),
    }


def publish_first_private_release(db, *, draft_id, manifest_bytes, published_by):
    """ONE initial active release, explicit admin-only call; DB constraints fail closed."""
    row = validate_private_publication(
        db, draft_id=draft_id, manifest_bytes=manifest_bytes,
        published_by=published_by)
    result = db.table(TABLE).insert(row).execute()
    if not result.data:
        raise InvalidPrivateRelease("Nao foi possivel registrar a release privada")
    return row
