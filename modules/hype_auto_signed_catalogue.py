"""Opt-in HYPE Client bootstrap catalog signed by a Render-held Ed25519 secret.

Only owner-uploaded HYPE Client JARs in the private admin library are eligible.
The signed catalog and its JAR URL remain OFF until both independent switches
are deliberately enabled after a Bootstrap pilot. No keys enter source control.
"""
import base64
import hashlib
import json
import os
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, load_pem_private_key,
)

from modules import hype_signed_release as signed
from modules.hype_mod_catalog import (
    CATALOGUE_BASE_URL, verify_signed_catalogue,
)
from modules.hype_mod_staging import BUCKET, TABLE, inspect_original


class AutoCatalogUnavailable(ValueError):
    """No eligible, valid uploaded JAR or compatible signer is available."""


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
    if not isinstance(row, dict) or row.get("module_id") != "hypeclient":
        return False
    if row.get("status") != "aguardando_protecao":
        return False
    if not isinstance(row.get("meta"), dict) or row["meta"].get("library_upload") is not True:
        return False
    version, sha, path, size = (
        row.get("version"), row.get("sha256"),
        row.get("storage_path"), row.get("size_bytes"),
    )
    if not isinstance(version, str) or not signed.VERSION.fullmatch(version):
        return False
    if not isinstance(sha, str) or not signed.SHA.fullmatch(sha):
        return False
    if type(size) is not int or not 1000 <= size <= 10 * 1024 * 1024:
        return False
    if not isinstance(path, str) or not re.fullmatch(
        r"hypeclient/[a-f0-9]{32}/" + re.escape(sha) + r"\.jar", path
    ):
        return False
    return True


def _uploaded_rows(db):
    try:
        return (db.table(TABLE)
                .select("module_id,version,sha256,size_bytes,storage_path,status,meta,created_at")
                .eq("module_id", "hypeclient")
                .order("created_at", desc=True).limit(250)
                .execute().data or [])
    except Exception as exc:
        raise AutoCatalogUnavailable("Biblioteca de JARs indisponivel") from exc


def latest_uploaded_client(db):
    """Only direct admin uploads, never old rejected pilot records or candidates."""
    for row in _uploaded_rows(db):
        if _eligible(row):
            return row
    raise AutoCatalogUnavailable("Nenhum HYPE Client enviado esta elegivel")


def signed_catalog_for_uploaded_client(db):
    """Produce the exact canonical JSON signed with the pinned Ed25519 key."""
    row = latest_uploaded_client(db)
    key = _load_signing_key()
    sha = row["sha256"]
    unsigned = {
        "schema": 1,
        "minecraft": "1.21.1",
        "channel": "stable",
        "mods": [{
            "id": "hypeclient",
            "version": row["version"],
            "sha256": sha,
            "size": row["size_bytes"],
            "url": f"{CATALOGUE_BASE_URL}hypeclient/{sha}.jar",
            "required": True,
            "depends_on": [],
        }],
    }
    canonical = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    result = dict(unsigned, signature=base64.b64encode(key.sign(canonical)).decode("ascii"))
    raw = json.dumps(
        result, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    verify_signed_catalogue(raw)
    return raw


def uploaded_client_binary(db, sha256):
    """Proxy only the hash-matching admin upload from private storage."""
    if not isinstance(sha256, str) or not signed.SHA.fullmatch(sha256):
        raise AutoCatalogUnavailable("Hash de JAR invalido")
    rows = _uploaded_rows(db)
    row = next((item for item in rows if _eligible(item) and item["sha256"] == sha256), None)
    if row is None:
        raise AutoCatalogUnavailable("JAR solicitado nao esta na biblioteca autorizada")
    try:
        raw = db.storage.from_(BUCKET).download(row["storage_path"])
        if not isinstance(raw, bytes) or len(raw) != row["size_bytes"]:
            raise ValueError("Tamanho do arquivo nao corresponde ao catalogo")
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("SHA-256 nao corresponde")
        report = inspect_original(raw)
        if (report["module_id"] != "hypeclient"
                or report["version"] != row["version"]
                or report["size_bytes"] != row["size_bytes"]):
            raise ValueError("Metadados do Fabric nao correspondem")
        return raw
    except Exception as exc:
        raise AutoCatalogUnavailable("JAR de download invalido ou indisponivel") from exc
