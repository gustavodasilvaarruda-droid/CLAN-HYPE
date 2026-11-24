"""Owner-only development JAR channel. NEVER used for signed player releases."""
import io
import os
import re
from datetime import datetime, timezone
from uuid import UUID

from modules.hype_mod_pilot_original import pilot_original_enabled
from modules.hype_mod_private_releases import BUCKET, DRAFTS, MAX_BYTES, InvalidPrivateRelease
from modules.hype_mod_staging import assert_private_bucket, inspect_original
from modules.hype_mod_update_access import MOD_TO_SITE_MODULE
from modules.hype_signed_release import SHA, VERSION, validate_binary

OWNER_IDS = frozenset((*MOD_TO_SITE_MODULE, "hypeclient"))  # Legacy player release IDs stay fixed.
OWNER_MOD_ID = re.compile(r"[a-z][a-z0-9_-]{1,63}\\Z")


def valid_owner_mod_id(mod_id):
    """Allow new Fabric IDs only for the authenticated owner pilot, never public release."""
    return isinstance(mod_id, str) and mod_id != "hypebootstrap" and OWNER_MOD_ID.fullmatch(mod_id) is not None
BASE_URL = "https://clan-hype.onrender.com/api/hype/v1/updates/owner-pilot/mods/"


def owner_pilot_enabled(email=None):
    enabled = os.getenv("HYPE_MOD_OWNER_PILOT_ENABLED", "").strip().lower() in ("1", "true", "yes")
    return enabled and pilot_original_enabled(email)


def _valid_original(draft):
    if not isinstance(draft, dict):
        raise InvalidPrivateRelease("Rascunho de teste invalido")
    try:
        draft_id = str(UUID(str(draft["id"])))
    except (TypeError, ValueError, KeyError) as exc:
        raise InvalidPrivateRelease("ID invalido") from exc
    mod_id, sha = draft.get("module_id"), draft.get("sha256")
    size, path, version = draft.get("size_bytes"), draft.get("storage_path"), draft.get("version")
    if (not valid_owner_mod_id(mod_id)
            or draft.get("status") not in ("aguardando_protecao", "em_teste", "pronto_para_aprovacao")
            or not isinstance(version, str) or not VERSION.fullmatch(version)
            or not isinstance(sha, str) or not SHA.fullmatch(sha)
            or type(size) is not int or not 1000 <= size <= MAX_BYTES
            or not isinstance(path, str)
            or not re.fullmatch(rf"{re.escape(mod_id)}/[a-f0-9]{{32}}/{sha}\.jar", path)):
        raise InvalidPrivateRelease("JAR original nao elegivel ao canal privado")
    return draft_id


def _record(draft):
    _valid_original(draft)
    owner = (draft.get("meta") or {}).get("owner_pilot")
    if not isinstance(owner, dict):
        return None
    release = owner.get("release")
    if type(release) is not int or not 1 <= release <= 999999999:
        raise InvalidPrivateRelease("Numero de release do piloto invalido")
    return {
        "id": draft["module_id"], "version": draft["version"],
        "release": release, "sha256": draft["sha256"],
        "size": draft["size_bytes"],
        "url": f"{BASE_URL}{draft['module_id']}/{draft['sha256']}.jar",
    }


def find_owner_pilot(db, mod_id, sha256=None):
    if not valid_owner_mod_id(mod_id):
        return None
    if sha256 is not None and (not isinstance(sha256, str) or not SHA.fullmatch(sha256)):
        return None
    rows = (db.table(DRAFTS)
            .select("id,module_id,version,status,sha256,size_bytes,storage_path,meta")
            .eq("module_id", mod_id).order("created_at", desc=True)
            .limit(500).execute().data or [])
    valid = [(row, _record(row)) for row in rows if (row.get("meta") or {}).get("owner_pilot")]
    if not valid:
        return None
    valid.sort(key=lambda item: item[1]["release"], reverse=True)
    latest = valid[0]
    if sha256 is not None and latest[1]["sha256"] != sha256:
        return None
    return latest


def list_owner_pilots(db):
    """Dynamic owner-only release catalogue from private, published originals."""
    rows = (db.table(DRAFTS)
            .select("id,module_id,version,status,sha256,size_bytes,storage_path,meta")
            .order("created_at", desc=True).limit(1000).execute().data or [])
    chosen = {}
    for draft in rows:
        if not (draft.get("meta") or {}).get("owner_pilot"):
            continue
        record = _record(draft)  # Corrupted record blocks catalogue; fail closed.
        mod_id = record["id"]
        if mod_id not in chosen or record["release"] > chosen[mod_id][1]["release"]:
            chosen[mod_id] = (draft, record)
    if len(chosen) > 100:
        raise InvalidPrivateRelease("O piloto atingiu o limite de modulos")
    return [chosen[mod_id] for mod_id in sorted(chosen)]


def download_owner_pilot(db, draft):
    _valid_original(draft)
    assert_private_bucket(db.storage)
    data = db.storage.from_(BUCKET).download(draft["storage_path"])
    if not isinstance(data, bytes) or len(data) != draft["size_bytes"]:
        raise InvalidPrivateRelease("Tamanho do original nao confere")
    validate_binary(data, expected_sha=draft["sha256"])
    inspected = inspect_original(data, allow_dynamic=True)
    if (inspected["module_id"] != draft["module_id"]
            or inspected["version"] != draft["version"]
            or inspected["size_bytes"] != draft["size_bytes"]):
        raise InvalidPrivateRelease("JAR Fabric original nao corresponde ao registro")
    return io.BytesIO(data)


def publish_owner_pilot(db, *, draft_id, published_by):
    if not owner_pilot_enabled(published_by):
        raise InvalidPrivateRelease("Canal individual de homologacao desativado")
    try:
        draft_id = str(UUID(str(draft_id)))
    except (TypeError, ValueError) as exc:
        raise InvalidPrivateRelease("ID invalido") from exc
    rows = (db.table(DRAFTS)
            .select("id,module_id,version,status,sha256,size_bytes,storage_path,meta")
            .eq("id", draft_id).limit(2).execute().data or [])
    if len(rows) != 1:
        raise InvalidPrivateRelease("Original nao encontrado")
    draft = rows[0]
    _valid_original(draft)
    if (draft.get("meta") or {}).get("owner_pilot"):
        raise InvalidPrivateRelease("Essa versao ja foi publicada no teste privado")
    download_owner_pilot(db, draft)
    last = find_owner_pilot(db, draft["module_id"])
    release = (last[1]["release"] + 1) if last else 1
    if release > 999999999:
        raise InvalidPrivateRelease("Limite de releases atingido")
    meta = dict(draft.get("meta") or {})
    meta["owner_pilot"] = {
        "release": release, "published_at": datetime.now(timezone.utc).isoformat(),
        "published_by": published_by,
    }
    saved = (db.table(DRAFTS).update({"meta": meta})
             .eq("id", draft_id).eq("status", draft["status"])
             .execute().data or [])
    if len(saved) != 1:
        raise InvalidPrivateRelease("O arquivo mudou; atualize o painel e tente novamente")
    return {"draft_id": draft_id, "module_id": draft["module_id"],
            "sha256": draft["sha256"], "release": release}
