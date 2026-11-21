"""Verification contract for the HYPE Client auto-updater (R7.19).

Only the *public* Ed25519 key is in this module. Never place a signing
private key in the repository, browser, or a Minecraft mod.
"""
import base64
import hashlib
import re
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_der_public_key

PUBLIC_KEY_DER_B64 = "MCowBQYDK2VwAyEARuMdCP0sz0PgfWc8aUMTHmElRH1jpCmE84gZojUY34k="
FIELDS = ("release", "version", "url", "sha256", "size", "minecraft", "mod_id", "channel")
ROOT_URL = "https://clan-hype.onrender.com/hype-updates/releases/"
RELEASE_FILE = re.compile(r"hypeclient-r([1-9][0-9]{0,8})\.jar\Z", re.ASCII)
SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
VERSION = re.compile(r"[A-Za-z0-9._+-]{1,120}\Z", re.ASCII)


class InvalidRelease(ValueError):
    pass


def verify_signed_manifest(content, *, version, sha256, size_bytes):
    """Validate the exact canonical fields verified by the shipped Java client.

    The uploaded manifest must contain one simple key=value line per field,
    plus exactly one signature. Reject Java Properties escape syntax to avoid
    a discrepancy between the server's and client's parsers.
    """
    if not isinstance(content, bytes) or not (50 <= len(content) <= 16384):
        raise InvalidRelease("Manifesto vazio ou grande demais.")
    try:
        payload = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise InvalidRelease("O manifesto deve usar ASCII simples.") from exc

    parsed = {}
    for line in payload.splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise InvalidRelease("Linha de manifesto inválida.")
        key, value = line.split("=", 1)
        if key not in (*FIELDS, "signature") or key in parsed or not value or value.strip() != value:
            raise InvalidRelease("Campos duplicados ou inválidos no manifesto.")
        if any(c in value for c in "\\\r\n\t") or len(value) > 2000:
            raise InvalidRelease("Caracteres inválidos no manifesto.")
        parsed[key] = value

    if set(parsed) != set((*FIELDS, "signature")):
        raise InvalidRelease("Faltam campos obrigatórios no manifesto.")
    try:
        release = int(parsed["release"])
        advertised_size = int(parsed["size"])
    except ValueError as exc:
        raise InvalidRelease("Release ou tamanho inválidos.") from exc
    if not (1 <= release <= 999999999) or str(release) != parsed["release"]:
        raise InvalidRelease("Número da release inválido.")
    if not (1000 <= advertised_size <= 67108864) or advertised_size != size_bytes:
        raise InvalidRelease("Tamanho não corresponde ao JAR.")
    if not VERSION.fullmatch(parsed["version"]) or parsed["version"] != version:
        raise InvalidRelease("Versão não corresponde ao JAR.")
    if not SHA.fullmatch(parsed["sha256"]) or parsed["sha256"] != sha256:
        raise InvalidRelease("Hash não corresponde ao JAR.")
    if parsed["minecraft"] != "1.21.1" or parsed["mod_id"] != "hypeclient" or parsed["channel"] != "stable":
        raise InvalidRelease("Canal ou plataforma incompatível.")
    filename = f"hypeclient-r{release}.jar"
    if parsed["url"] != ROOT_URL + filename:
        raise InvalidRelease("URL fora do endereço oficial da atualização.")
    canonical = "".join(f"{key}={parsed[key]}\n" for key in FIELDS).encode("utf-8")
    try:
        sig = base64.b64decode(parsed["signature"], validate=True)
        if len(sig) != 64:
            raise InvalidRelease("Assinatura Ed25519 com tamanho inválido.")
        key = load_der_public_key(base64.b64decode(PUBLIC_KEY_DER_B64))
        key.verify(sig, canonical)
    except (ValueError, InvalidSignature, TypeError) as exc:
        raise InvalidRelease("Assinatura digital inválida para este HYPE Client.") from exc
    return {"release": release, "version": version, "sha256": sha256,
            "size_bytes": size_bytes, "filename": filename, "content": payload}


def validate_binary(raw, *, expected_sha):
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise InvalidRelease("Arquivo de atualização não corresponde ao SHA-256 aprovado.")
