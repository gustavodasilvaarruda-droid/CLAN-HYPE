"""Sign HYPE Client release manifests *offline* with the existing Ed25519 key.

Run only on a trusted computer, never inside the Flask web server or CI.
The private key never leaves the machine; this module never generates keys.
Example:
  python -m modules.hype_manifest_signer --jar PROTECTED.jar \
    --private-key /secure/hype-release-key.pem --release 43 \
    --output manifest.properties
"""
import argparse
import base64
import hashlib
import io
import json
from getpass import getpass
from pathlib import Path
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, load_pem_private_key,
)

from modules.hype_signed_release import (
    FIELDS, PUBLIC_KEY_DER_B64, ROOT_URL, VERSION,
    verify_signed_manifest,
)


def sign_manifest(jar: bytes, private_key: Ed25519PrivateKey, release: int) -> bytes:
    """Return a signed manifest only if the private key matches shipped clients."""
    if not isinstance(release, int) or not 1 <= release <= 999999999:
        raise ValueError("Release deve ser um inteiro entre 1 e 999999999.")
    if not 1000 <= len(jar) <= 10 * 1024 * 1024:
        raise ValueError("JAR não respeita o limite de tamanho do staging.")
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("A chave deve ser uma chave privada Ed25519.")
    actual_public = private_key.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    if actual_public != base64.b64decode(PUBLIC_KEY_DER_B64, validate=True):
        raise ValueError(
            "Chave privada incompatível com a chave pública do HYPE Client já instalado."
        )
    try:
        with ZipFile(io.BytesIO(jar)) as archive:
            metadata = json.loads(archive.read("fabric.mod.json"))
            if archive.testzip() is not None:
                raise ValueError("JAR ZIP corrompido.")
    except (KeyError, json.JSONDecodeError, OSError) as exc:
        raise ValueError("JAR não contém metadados Fabric válidos.") from exc
    if metadata.get("id") != "hypeclient":
        raise ValueError("O arquivo precisa ser o HYPE Client.")
    version = metadata.get("version")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("Versão Fabric incompatível com o contrato de publicação.")
    if (metadata.get("depends") or {}).get("minecraft") != "1.21.1":
        raise ValueError("O HYPE Client deve declarar Minecraft 1.21.1.")
    values = {
        "release": str(release), "version": version,
        "url": ROOT_URL + f"hypeclient-r{release}.jar",
        "sha256": hashlib.sha256(jar).hexdigest(), "size": str(len(jar)),
        "minecraft": "1.21.1", "mod_id": "hypeclient", "channel": "stable",
    }
    canonical = "".join(f"{field}={values[field]}\n" for field in FIELDS).encode("ascii")
    signature = base64.b64encode(private_key.sign(canonical)).decode("ascii")
    document = canonical + f"signature={signature}\n".encode("ascii")
    verify_signed_manifest(
        document, version=version, sha256=values["sha256"], size_bytes=len(jar)
    )
    return document


def main():
    parser = argparse.ArgumentParser(description="Assinador offline HYPE Client (Ed25519).")
    parser.add_argument("--jar", required=True, type=Path, help="JAR protegido testado")
    parser.add_argument("--private-key", required=True, type=Path, help="Chave Ed25519 original PEM, local")
    parser.add_argument("--release", required=True, type=int, help="Número maior que o publicado")
    parser.add_argument("--output", required=True, type=Path, help="Novo manifesto .properties")
    args = parser.parse_args()
    if args.output.suffix != ".properties":
        parser.error("O arquivo de saída deve terminar em .properties")
    if args.output.exists():
        parser.error("O manifesto de saída já existe: não sobrescrever uma release.")
    pem = args.private_key.read_bytes()
    try:
        key = load_pem_private_key(pem, password=None)
    except TypeError:
        password = getpass("Senha da chave privada PEM (não será exibida): ").encode()
        key = load_pem_private_key(pem, password=password)
    document = sign_manifest(args.jar.read_bytes(), key, args.release)
    args.output.write_bytes(document)
    print(f"Manifesto assinado criado: {args.output}")
    print("Verifique a versão aprovada e o hash no Painel Admin ANTES de publicar.")


if __name__ == "__main__":
    main()
