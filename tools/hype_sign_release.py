"""Prepare an OFFLINE signed HYPE Client update. This NEVER publishes a release.

IMPORTANT: Current HYPE Client has a PINNED Ed25519 verification key.
The signing key must match that embedded public key, or signing fails closed.
Install cryptography in your local release environment only (not Render).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import stat
from pathlib import Path
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

CLIENT_PUBLIC_SPKI_B64 = "MCowBQYDK2VwAyEAmC+/PJEh4q/O+WTqQdR6Z1fQibpKTy9zn0qYcuMQx/o="
CLIENT_PUBLIC_SPKI = base64.b64decode(CLIENT_PUBLIC_SPKI_B64)
OFFICIAL_SITE = "https://clan-hype.onrender.com"
FIELDS = ("release", "version", "url", "sha256", "size", "minecraft", "mod_id", "channel")
MAX_JAR = 10 * 1024 * 1024  # Staging's limit; keep this step consistent
MAX_EXPANDED = 300 * 1024 * 1024
MAX_ENTRIES = 8000


class ReleaseError(ValueError):
    """A release failed a safety or compatibility check."""


def inspect_jar(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".jar":
        raise ReleaseError("Choose a real local .jar file, not a symlink.")
    size = path.stat().st_size
    if not 1000 <= size <= MAX_JAR:
        raise ReleaseError("JAR must be between 1 KB and 10 MiB for this staging process.")
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES:
                raise ReleaseError("Too many ZIP members.")
            seen, expanded = set(), 0
            for entry in entries:
                name = entry.filename
                if (not name or name.startswith("/") or "\\" in name
                    or ".." in name.split("/") or name in seen
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                    raise ReleaseError("Unsafe ZIP member.")
                seen.add(name)
                expanded += entry.file_size
                if expanded > MAX_EXPANDED:
                    raise ReleaseError("JAR expanded data exceeds the safety limit.")
            if "fabric.mod.json" not in seen:
                raise ReleaseError("Not a Fabric mod.")
            if archive.getinfo("fabric.mod.json").file_size > 16384:
                raise ReleaseError("Fabric metadata exceeds client verifier limit.")
            metadata = json.loads(archive.read("fabric.mod.json"))
            if not isinstance(metadata, dict) or metadata.get("id") != "hypeclient":
                raise ReleaseError("Only the HYPE Client can be released with this tool.")
            version = metadata.get("version")
            if not isinstance(version, str) or not 0 < len(version) <= 120:
                raise ReleaseError("Invalid Fabric version.")
            if any(c in version for c in "\r\n\\="):
                raise ReleaseError("Unsupported Fabric version characters.")
            for entry in entries:
                if not entry.is_dir():
                    with archive.open(entry) as stream:
                        for _ in iter(lambda: stream.read(1024 * 1024), b""):
                            pass  # Also validates per-member CRC.
    except (BadZipFile, OSError, EOFError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError("Invalid or damaged Fabric JAR.") from exc
    digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
    return {"version": version, "size": size, "sha256": digest, "mod_id": "hypeclient"}


def canonical(fields: dict) -> bytes:
    # Exactly the field order / trailing newline used by HypeAutoUpdate.canonical().
    for field in FIELDS:
        value = fields.get(field)
        if not isinstance(value, str) or not value or len(value) > 2000:
            raise ReleaseError("Missing or invalid manifest field: " + field)
        if any(c in value for c in "\r\n"):
            raise ReleaseError("Newline in manifest field: " + field)
    if fields["mod_id"] != "hypeclient" or fields["minecraft"] != "1.21.1":
        raise ReleaseError("Manifest targets the wrong client or Minecraft version.")
    if fields["channel"] != "stable":
        raise ReleaseError("Current client only accepts the stable channel.")
    release = fields["release"]
    if not release.isdecimal() or not 1 <= int(release) <= 1000000000:
        raise ReleaseError("Release number must be between 1 and 1000000000.")
    if not re.fullmatch(r"[a-f0-9]{64}", fields["sha256"]):
        raise ReleaseError("Invalid SHA-256.")
    if not fields["size"].isdecimal() or not 1000 <= int(fields["size"]) <= 67108864:
        raise ReleaseError("Invalid JAR size.")
    parsed = urlparse(fields["url"])
    expected_path = "/hype-updates/releases/hypeclient-r" + release + ".jar"
    if (parsed.scheme != "https" or parsed.hostname != "clan-hype.onrender.com"
        or parsed.port is not None or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path != expected_path):
        raise ReleaseError("Release URL must be the official HTTPS update route.")
    return "".join(field + "=" + fields[field] + "\n" for field in FIELDS).encode("utf-8")


def load_matching_private_key(path: Path) -> Ed25519PrivateKey:
    if path.is_symlink() or not path.is_file():
        raise ReleaseError("Private key must be a local file outside the repository.")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (ValueError, TypeError) as exc:
        raise ReleaseError("Expected an unencrypted Ed25519 PEM private key.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ReleaseError("Signing key is not Ed25519.")
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if pub != CLIENT_PUBLIC_SPKI:
        raise ReleaseError(
            "PRIVATE KEY DOES NOT MATCH the public key pinned in the installed "
            "HYPE Client. Do not publish: locate the original matching key or "
            "rebuild/test a new client with an intentional key rotation."
        )
    return key


def prepare(jar: Path, key_path: Path, out_dir: Path, release: int) -> dict:
    if not 1 <= release <= 1000000000:
        raise ReleaseError("Release number outside supported range.")
    info = inspect_jar(jar)
    key = load_matching_private_key(key_path)  # Fail before writing any output.
    fields = {
        "release": str(release),
        "version": info["version"],
        "url": OFFICIAL_SITE + "/hype-updates/releases/hypeclient-r" + str(release) + ".jar",
        "sha256": info["sha256"],
        "size": str(info["size"]),
        "minecraft": "1.21.1",
        "mod_id": "hypeclient",
        "channel": "stable",
    }
    payload = canonical(fields)
    signature = key.sign(payload)
    # Verify locally with the same public key used in the installed client.
    key.public_key().verify(signature, payload)
    manifest = payload + ("signature=" + base64.b64encode(signature).decode("ascii") + "\n").encode("ascii")
    target_jar = out_dir / "releases" / ("hypeclient-r" + str(release) + ".jar")
    target_manifest = out_dir / "manifest.properties"
    if target_jar.exists() or target_manifest.exists():
        raise ReleaseError("Output already exists. Never overwrite a previous signed release.")
    target_jar.parent.mkdir(parents=True, exist_ok=True)
    # This creates only LOCAL release artifacts; no server upload or auto-publish.
    shutil.copyfile(jar, target_jar)
    if hashlib.file_digest(target_jar.open("rb"), "sha256").hexdigest() != info["sha256"]:
        target_jar.unlink(missing_ok=True)
        raise ReleaseError("Copied JAR hash mismatch.")
    target_manifest.write_bytes(manifest)
    return {"jar": str(target_jar), "manifest": str(target_manifest), **info}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--inspect", action="store_true", help="Inspect only; no signing or writing")
    parser.add_argument("--key", type=Path, help="Existing PEM private key matching installed client")
    parser.add_argument("--release", type=int, help="Strictly increasing numeric release id")
    parser.add_argument("--out", type=Path, help="New empty local output directory")
    args = parser.parse_args()
    try:
        if args.inspect:
            print(json.dumps(inspect_jar(args.jar), indent=2))
        else:
            if args.key is None or args.release is None or args.out is None:
                parser.error("Signing requires --key, --release, and --out.")
            print(json.dumps(prepare(args.jar, args.key, args.out, args.release), indent=2))
    except (ReleaseError, OSError) as exc:
        parser.exit(2, "ERROR: " + str(exc) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
