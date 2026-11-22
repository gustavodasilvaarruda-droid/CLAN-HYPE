"""Signed, read-only catalogue contract for future HYPE multi-mod bootstrap clients.

V1 is deliberately separate from the legacy single-Client manifest. Reading a
catalogue does NOT publish JARs, install mods or enable automatic distribution.
Only a trusted offline signer may produce an accepted Ed25519 signature.
"""
import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_der_public_key

from modules import hype_signed_release as signed

CATALOGUE_BASE_URL = "https://clan-hype.onrender.com/hype-updates/mods/"
MODULE_IDS = frozenset({
    "hypeclient", "hype_pokedex", "hype_breed_calculator",
    "hype_battlefield", "hype_battle_ai",
})
MAX_CATALOGUE_BYTES = 256 * 1024


class InvalidCatalogue(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCatalogue("Chave JSON repetida no catálogo.")
        result[key] = value
    return result


def verify_signed_catalogue(raw):
    """Verify canonical signed JSON, strict module allowlist and dependency graph.

    Envelope: {"schema":1,"minecraft":"1.21.1","channel":"stable",
      "mods":[{"id":...,"version":...,"sha256":...,"size":...,
               "url":...,"required":true,"depends_on":[...]}],
      "signature":"BASE64_ED25519"}

    The signature covers UTF-8 JSON of the entire envelope excluding
    'signature', using sort_keys=True, separators=(',', ':'), ensure_ascii=True.
    The bootstrap client MUST independently verify this same contract, hashes,
    and signatures; it must never trust server-side verification alone.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_CATALOGUE_BYTES:
        raise InvalidCatalogue("Catálogo ausente ou grande demais.")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise InvalidCatalogue("JSON do catálogo inválido.") from exc

    if not isinstance(document, dict) or set(document) != {
        "schema", "minecraft", "channel", "mods", "signature"
    }:
        raise InvalidCatalogue("Estrutura do catálogo inválida.")
    if type(document["schema"]) is not int or document["schema"] != 1:
        raise InvalidCatalogue("Versão de esquema incompatível.")
    if document["minecraft"] != "1.21.1" or document["channel"] != "stable":
        raise InvalidCatalogue("Plataforma ou canal incompatível.")

    mods = document["mods"]
    if not isinstance(mods, list) or not 1 <= len(mods) <= len(MODULE_IDS):
        raise InvalidCatalogue("Lista de mods inválida.")
    seen = set()
    dependencies = {}
    for item in mods:
        if not isinstance(item, dict) or set(item) != {
            "id", "version", "sha256", "size", "url", "required", "depends_on"
        }:
            raise InvalidCatalogue("Campos de mod incompletos ou desconhecidos.")
        mod_id = item["id"]
        version = item["version"]
        sha = item["sha256"]
        size = item["size"]
        deps = item["depends_on"]
        if not isinstance(mod_id, str) or mod_id not in MODULE_IDS or mod_id in seen:
            raise InvalidCatalogue("Mod desconhecido ou duplicado.")
        if not isinstance(version, str) or not signed.VERSION.fullmatch(version):
            raise InvalidCatalogue("Versão de mod inválida.")
        if not isinstance(sha, str) or not signed.SHA.fullmatch(sha):
            raise InvalidCatalogue("SHA-256 de mod inválido.")
        if type(size) is not int or not 1000 <= size <= 64 * 1024 * 1024:
            raise InvalidCatalogue("Tamanho de mod inválido.")
        if type(item["required"]) is not bool:
            raise InvalidCatalogue("Campo obrigatório inválido.")
        if item["url"] != f"{CATALOGUE_BASE_URL}{mod_id}/{sha}.jar":
            raise InvalidCatalogue("URL de mod não é oficial ou não corresponde ao hash.")
        if (not isinstance(deps, list)
                or any(not isinstance(dep, str) or dep not in MODULE_IDS for dep in deps)
                or len(deps) != len(set(deps)) or mod_id in deps):
            raise InvalidCatalogue("Dependências internas inválidas.")
        dependencies[mod_id] = deps
        seen.add(mod_id)

    if "hypeclient" not in seen or not next(
        m["required"] for m in mods if m["id"] == "hypeclient"
    ):
        raise InvalidCatalogue("O bootstrap HYPE Client deve ser obrigatório.")
    if any(dep not in seen for deps in dependencies.values() for dep in deps):
        raise InvalidCatalogue("Dependência interna ausente do catálogo.")

    visiting, done = set(), set()

    def visit(mod_id):
        if mod_id in visiting:
            raise InvalidCatalogue("Dependências internas formam um ciclo.")
        if mod_id in done:
            return
        visiting.add(mod_id)
        for dep in dependencies[mod_id]:
            visit(dep)
        visiting.remove(mod_id)
        done.add(mod_id)

    for mod_id in dependencies:
        visit(mod_id)

    try:
        signature_value = document["signature"]
        if not isinstance(signature_value, str) or len(signature_value) > 128:
            raise InvalidCatalogue("Assinatura ausente ou inválida.")
        signature = base64.b64decode(signature_value, validate=True)
        if len(signature) != 64:
            raise InvalidCatalogue("Assinatura Ed25519 com tamanho inválido.")
        unsigned = {k: v for k, v in document.items() if k != "signature"}
        canonical = json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        key = load_der_public_key(
            base64.b64decode(signed.PUBLIC_KEY_DER_B64, validate=True)
        )
        key.verify(signature, canonical)
    except (ValueError, InvalidSignature, TypeError) as exc:
        raise InvalidCatalogue("Assinatura digital do catálogo inválida.") from exc
    return document
