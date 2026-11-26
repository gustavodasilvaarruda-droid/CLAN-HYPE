"""Signed public multi-mod catalogue derived from admin's simple Fabric JAR uploads.

The uploader is restricted to administrators. Eligible uploaded JARs are
immutable private-storage objects; their *distribution* is public once the
two Render switches have been enabled. The Ed25519 key remains a Render secret.
Do not use this public channel for entitlement-restricted modules.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, load_der_public_key, load_pem_private_key,
)

from modules import hype_signed_release as signed
from modules.hype_mod_catalog import CATALOGUE_BASE_URL
from modules.hype_mod_staging import BUCKET, TABLE, inspect_original

MOD_ID = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z", re.ASCII)
MAX_MODS = 100
MAX_CATALOGUE_BYTES = 256 * 1024
RELEASE_STATES = frozenset(("aguardando_protecao", "em_teste", "pronto_para_aprovacao"))
# The authenticated admin's valid library upload is the distribution decision.
# Filenames and Fabric versions may contain PILOTO, TESTE, ALPHA, BETA, etc.
# Never infer an opt-out from user-provided text: preserve the owner's choice.
def _safe_public_build(row):
    filename, version = row.get("original_filename"), row.get("version")
    return (isinstance(filename, str)
            and filename.lower().endswith(".jar")
            and "/" not in filename and chr(92) not in filename
            and isinstance(version, str))


class AutoCatalogUnavailable(ValueError):
    pass


def _canonical(data):
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _load_signing_key():
    encoded = os.getenv("HYPE_AUTO_SIGNING_PRIVATE_KEY_PEM_B64", "").strip()
    if not encoded:
        raise AutoCatalogUnavailable("Chave de assinatura ausente")
    try:
        key = load_pem_private_key(base64.b64decode(encoded, validate=True), password=None)
        expected = base64.b64decode(signed.PUBLIC_KEY_DER_B64, validate=True)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Algoritmo de assinatura inesperado")
        actual = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        if actual != expected:
            raise ValueError("A chave privada nao corresponde ao Bootstrap")
        return key
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AutoCatalogUnavailable("Chave de assinatura invalida ou incompativel") from exc


def _eligible(row):
    if not isinstance(row, dict):
        return False
    mod_id, version, sha, path, size = (
        row.get("module_id"), row.get("version"), row.get("sha256"),
        row.get("storage_path"), row.get("size_bytes"),
    )
    if row.get("status") not in RELEASE_STATES or not _safe_public_build(row):
        return False
    if not isinstance(row.get("meta"), dict) or row["meta"].get("library_upload") is not True:
        return False
    if not isinstance(mod_id, str) or not MOD_ID.fullmatch(mod_id):
        return False
    if mod_id == "hypebootstrap":
        return False  # The running updater never attempts to replace itself.
    if not isinstance(version, str) or not signed.VERSION.fullmatch(version):
        return False
    if not isinstance(sha, str) or not signed.SHA.fullmatch(sha):
        return False
    if type(size) is not int or not 1000 <= size <= 10 * 1024 * 1024:
        return False
    if not isinstance(path, str) or not re.fullmatch(
        re.escape(mod_id) + r"/[a-f0-9]{32}/" + sha + r"\.jar", path
    ):
        return False
    return True


def _uploaded_rows(db):
    try:
        return (db.table(TABLE)
                .select("module_id,version,sha256,size_bytes,storage_path,status,meta,original_filename,created_at")
                .order("created_at", desc=True)
                .limit(1000)
                .execute().data or [])
    except Exception as exc:
        raise AutoCatalogUnavailable("Biblioteca de JARs indisponivel") from exc


def latest_uploaded_mods(db):
    """One latest eligible library upload per Fabric mod ID, newest first."""
    result = []
    seen = set()
    for row in _uploaded_rows(db):
        if _eligible(row) and row["module_id"] not in seen:
            result.append(row)
            seen.add(row["module_id"])
        if len(result) > MAX_MODS:
            raise AutoCatalogUnavailable("Excesso de mods no catalogo")
    return result


def latest_uploaded_client(db):
    for row in latest_uploaded_mods(db):
        if row["module_id"] == "hypeclient":
            return row
    raise AutoCatalogUnavailable("Nenhum HYPE Client enviado esta elegivel")


def verify_auto_catalogue(raw):
    """Independently verify the signed schema and public immutable URLs.

    This relaxed multi-mod contract is specifically for Bootstrap 1.5+.
    Legacy HYPE Client and owner-only update endpoints remain unchanged.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_CATALOGUE_BYTES:
        raise AutoCatalogUnavailable("Catalogo invalido")
    def unique_pairs(pairs):
        obj = {}
        for name, value in pairs:
            if name in obj:
                raise AutoCatalogUnavailable("Campo duplicado no catalogo")
            obj[name] = value
        return obj
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise AutoCatalogUnavailable("JSON do catalogo invalido") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema", "minecraft", "channel", "mods", "signature"
    }:
        raise AutoCatalogUnavailable("Campos do catalogo invalidos")
    if (type(document["schema"]) is not int or document["schema"] != 1
            or document["minecraft"] != "1.21.1"
            or document["channel"] != "stable"):
        raise AutoCatalogUnavailable("Plataforma ou canal incompativel")
    mods = document["mods"]
    if not isinstance(mods, list) or len(mods) > MAX_MODS:
        raise AutoCatalogUnavailable("Lista de mods invalida")
    seen = set()
    for mod in mods:
        if not isinstance(mod, dict) or set(mod) != {
            "id", "version", "sha256", "size", "url", "required", "depends_on"
        }:
            raise AutoCatalogUnavailable("Campos de mod invalidos")
        m, v, h, size = mod["id"], mod["version"], mod["sha256"], mod["size"]
        if (not isinstance(m, str) or not MOD_ID.fullmatch(m) or m == "hypebootstrap"
                or m in seen or not isinstance(v, str) or not signed.VERSION.fullmatch(v)
                or not isinstance(h, str) or not signed.SHA.fullmatch(h)
                or type(size) is not int or not 1000 <= size <= 64 * 1024 * 1024
                or type(mod["required"]) is not bool or not mod["required"]
                or mod["depends_on"] != []
                or mod["url"] != f"{CATALOGUE_BASE_URL}{m}/{h}.jar"):
            raise AutoCatalogUnavailable("Metadados de mod invalidos")
        seen.add(m)
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    try:
        signature = base64.b64decode(document["signature"], validate=True)
        if len(signature) != 64:
            raise ValueError("Assinatura com tamanho invalido")
        key = load_der_public_key(base64.b64decode(signed.PUBLIC_KEY_DER_B64, validate=True))
        key.verify(signature, _canonical(unsigned))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise AutoCatalogUnavailable("Assinatura Ed25519 invalida") from exc
    return document


def signed_catalog_for_uploaded_mods(db):
    mods = []
    for row in latest_uploaded_mods(db):
        sha = row["sha256"]
        mods.append({
            "id": row["module_id"], "version": row["version"],
            "sha256": sha, "size": row["size_bytes"],
            "url": f"{CATALOGUE_BASE_URL}{row['module_id']}/{sha}.jar",
            "required": True, "depends_on": [],
        })
    unsigned = {
        "schema": 1, "minecraft": "1.21.1", "channel": "stable", "mods": mods,
    }
    key = _load_signing_key()
    signature = base64.b64encode(key.sign(_canonical(unsigned))).decode("ascii")
    result = _canonical(dict(unsigned, signature=signature))
    verify_auto_catalogue(result)
    return result


def signed_catalog_for_uploaded_client(db):
    """Compatibility name retained for existing handlers and tests."""
    return signed_catalog_for_uploaded_mods(db)


def uploaded_mod_binary(db, mod_id, sha256):
    """Serve only the currently selected version; validate bytes and Fabric ID."""
    if (not isinstance(mod_id, str) or not MOD_ID.fullmatch(mod_id)
            or not isinstance(sha256, str) or not signed.SHA.fullmatch(sha256)):
        raise AutoCatalogUnavailable("ID ou hash de JAR invalido")
    row = next(
        (r for r in latest_uploaded_mods(db)
         if r["module_id"] == mod_id and r["sha256"] == sha256),
        None,
    )
    if row is None:
        raise AutoCatalogUnavailable("JAR nao listado no catalogo atual")
    try:
        raw = db.storage.from_(BUCKET).download(row["storage_path"])
        if not isinstance(raw, bytes) or len(raw) != row["size_bytes"]:
            raise ValueError("Tamanho do arquivo nao corresponde ao catalogo")
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("SHA-256 nao corresponde")
        report = inspect_original(raw)
        if (report["module_id"] != mod_id
                or report["version"] != row["version"]
                or report["size_bytes"] != row["size_bytes"]):
            raise ValueError("Metadados Fabric nao correspondem")
        return raw
    except Exception as exc:
        raise AutoCatalogUnavailable("JAR de download invalido ou indisponivel") from exc


def uploaded_client_binary(db, sha256):
    """Compatibility helper for the original single-HYPE-Client test suite."""
    return uploaded_mod_binary(db, "hypeclient", sha256)
