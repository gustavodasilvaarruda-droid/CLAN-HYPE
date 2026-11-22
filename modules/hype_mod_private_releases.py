"""Private, authenticated release reads for four HYPE Fabric mods.

This service NEVER signs, approves or publishes releases. A server administrator
must first validate/test a protected candidate and supply an offline Ed25519
signed manifest. No service-role key or private storage URL is sent to clients.
"""
import base64
import io
import re
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_der_public_key

from modules import hype_signed_release as signed
from modules.hype_mod_update_access import MOD_TO_SITE_MODULE
from modules.hype_mod_staging import assert_private_bucket

TABLE = "hype_mod_restricted_releases"
DRAFTS = "hype_mod_release_drafts"
BUCKET = "hype-mod-originals"
BASE_URL = "https://clan-hype.onrender.com/api/hype/v1/updates/mods/"
MAX_BYTES = 10 * 1024 * 1024
REQUIRED_GAME_TESTS = ("game_launch", "menus", "server_connection", "no_crashes")


class InvalidPrivateRelease(ValueError):
    """Published metadata or approval evidence is invalid; fail closed."""


def parse_signed_manifest(content, *, module_id, version, release, sha256, size_bytes):
    """Verify the exact canonical bytes signed using the pinned public key."""
    if not isinstance(content, str) or not 50 <= len(content.encode("utf-8")) <= 16384:
        raise InvalidPrivateRelease("Manifesto privado ausente ou grande demais")
    try:
        raw = content.encode("ascii")
    except UnicodeError as exc:
        raise InvalidPrivateRelease("Manifesto deve ser ASCII") from exc
    fields = {}
    for line in raw.decode("ascii").splitlines():
        if not line or "=" not in line:
            raise InvalidPrivateRelease("Linha de manifesto invalida")
        key, value = line.split("=", 1)
        if (key not in (*signed.FIELDS, "signature") or key in fields or not value
                or value.strip() != value or any(c in value for c in "\\\r\n\t")):
            raise InvalidPrivateRelease("Campo de manifesto invalido ou repetido")
        fields[key] = value
    if set(fields) != set((*signed.FIELDS, "signature")):
        raise InvalidPrivateRelease("Campos obrigatorios ausentes")
    if (type(release) is not int or not 1 <= release <= 999999999
            or type(size_bytes) is not int or not 1000 <= size_bytes <= MAX_BYTES
            or module_id not in MOD_TO_SITE_MODULE
            or not isinstance(version, str) or not signed.VERSION.fullmatch(version)
            or not isinstance(sha256, str) or not signed.SHA.fullmatch(sha256)):
        raise InvalidPrivateRelease("Metadados de release invalidos")
    expected = {
        "release": str(release), "version": version,
        "url": f"{BASE_URL}{module_id}/{sha256}.jar",
        "sha256": sha256, "size": str(size_bytes),
        "minecraft": "1.21.1", "mod_id": module_id, "channel": "stable",
    }
    if any(fields[key] != value for key, value in expected.items()):
        raise InvalidPrivateRelease("Manifesto nao corresponde ao registro privado")
    canonical = "".join(f"{key}={fields[key]}\n" for key in signed.FIELDS).encode("ascii")
    try:
        signature = base64.b64decode(fields["signature"], validate=True)
        if len(signature) != 64:
            raise InvalidPrivateRelease("Assinatura de tamanho invalido")
        key = load_der_public_key(base64.b64decode(signed.PUBLIC_KEY_DER_B64, validate=True))
        key.verify(signature, canonical)
    except (ValueError, InvalidSignature, TypeError) as exc:
        raise InvalidPrivateRelease("Assinatura Ed25519 invalida") from exc
    return expected


def _approved_candidate(db, row):
    """Never serve an original, untested candidate or one with stale review."""
    try:
        draft_id = str(UUID(str(row["draft_id"])))
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidPrivateRelease("Rascunho invalido") from exc
    mod_id, sha = row["module_id"], row["sha256"]
    path = row.get("storage_path")
    path_re = rf"{re.escape(mod_id)}/{re.escape(draft_id)}/protected/[a-f0-9]{{32}}/{sha}\\.jar"
    if not isinstance(path, str) or not re.fullmatch(path_re, path):
        raise InvalidPrivateRelease("Caminho nao aponta para o candidato protegido")
    drafts = (db.table(DRAFTS)
              .select("id,module_id,version,status,meta")
              .eq("id", draft_id).limit(2).execute().data or [])
    if len(drafts) != 1:
        raise InvalidPrivateRelease("Rascunho de aprovacao nao encontrado")
    draft = drafts[0]
    meta = draft.get("meta") or {}
    protected = meta.get("protected") or {}
    automatic = meta.get("automatic_review") or {}
    manual = meta.get("manual_review") or {}
    if (draft.get("module_id") != mod_id
            or draft.get("version") != row.get("version")
            or draft.get("status") != "pronto_para_aprovacao"
            or protected.get("sha256") != sha
            or protected.get("size_bytes") != row.get("size_bytes")
            or protected.get("storage_path") != path
            or automatic.get("status") != "passed"
            or automatic.get("candidate_sha256") != sha
            or manual.get("candidate_sha256") != sha
            or not all(manual.get("checks", {}).get(k) is True for k in REQUIRED_GAME_TESTS)):
        raise InvalidPrivateRelease("Release nao possui revisao completa para este SHA")
    return path


def verify_private_record(db, row):
    if not isinstance(row, dict) or row.get("status") != "published":
        raise InvalidPrivateRelease("Release nao publicada")
    module_id = row.get("module_id")
    if module_id not in MOD_TO_SITE_MODULE:
        raise InvalidPrivateRelease("Modulo restrito desconhecido")
    parsed = parse_signed_manifest(
        row.get("manifest"), module_id=module_id,
        version=row.get("version"), release=row.get("release"),
        sha256=row.get("sha256"), size_bytes=row.get("size_bytes"),
    )
    _approved_candidate(db, row)
    return {
        "id": module_id, "version": parsed["version"],
        "release": row["release"], "sha256": parsed["sha256"],
        "size": row["size_bytes"], "url": parsed["url"],
        "manifest": row["manifest"],
    }


def find_private_release(db, module_id, *, sha256=None):
    """Read only approved published rows, never the public HYPE Client table."""
    if module_id not in MOD_TO_SITE_MODULE:
        return None
    query = (db.table(TABLE)
             .select("module_id,release,draft_id,version,sha256,size_bytes,storage_path,manifest,status")
             .eq("module_id", module_id).eq("status", "published"))
    if sha256 is not None:
        if not isinstance(sha256, str) or not signed.SHA.fullmatch(sha256):
            return None
        query = query.eq("sha256", sha256)
    else:
        query = query.order("release", desc=True)
    rows = query.limit(2).execute().data or []
    if not rows:
        return None
    if sha256 is not None and len(rows) != 1:
        raise InvalidPrivateRelease("SHA duplicado")
    row = rows[0]
    verified = verify_private_record(db, row)
    return row, verified


def download_protected_jar(db, row):
    """Stream bytes through Flask only; do not expose private Storage links."""
    assert_private_bucket(db.storage)
    raw = db.storage.from_(BUCKET).download(row["storage_path"])
    if not isinstance(raw, bytes) or len(raw) != row["size_bytes"]:
        raise InvalidPrivateRelease("Tamanho do JAR protegido nao confere")
    try:
        signed.validate_binary(raw, expected_sha=row["sha256"])
    except signed.InvalidRelease as exc:
        raise InvalidPrivateRelease("Hash do JAR protegido nao confere") from exc
    return io.BytesIO(raw)
