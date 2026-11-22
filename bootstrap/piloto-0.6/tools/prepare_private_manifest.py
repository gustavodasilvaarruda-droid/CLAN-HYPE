#!/usr/bin/env python3
"""OFFLINE manifest DRAFT for one exact protected JAR. Never signs, uploads or deploys."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile, BadZipFile

IDS = frozenset(("hype_pokedex", "hype_breed_calculator",
                 "hype_battlefield", "hype_battle_ai"))
FIELDS = ("release", "version", "url", "sha256", "size",
          "minecraft", "mod_id", "channel")
BASE = "https://clan-hype.onrender.com/api/hype/v1/updates/mods"

def unsigned_manifest(file: Path, release: int, expected_sha: str) -> str:
    if not 1 <= release <= 999999999:
        raise ValueError("Invalid release number")
    file = file.resolve(strict=True)
    size = file.stat().st_size
    if not 1000 <= size <= 10*1024*1024:
        raise ValueError("JAR outside 1 KB - 10 MB limit")
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    if (not re.fullmatch(r"[a-f0-9]{64}", expected_sha)
            or sha != expected_sha):
        raise ValueError("Not the exact reviewed protected candidate SHA")
    with ZipFile(file) as zipfile:
        entries = zipfile.infolist()
        if len(entries) > 8000 or len({x.filename for x in entries}) != len(entries):
            raise ValueError("Invalid or duplicate ZIP entries")
        if sum(x.file_size for x in entries) > 300*1024*1024:
            raise ValueError("ZIP uncompressed size too large")
        meta_info = zipfile.getinfo("fabric.mod.json")
        if meta_info.file_size > 8192:
            raise ValueError("Fabric metadata too large")
        meta = json.loads(zipfile.read(meta_info))
    if not isinstance(meta, dict):
        raise ValueError("Invalid Fabric metadata")
    mod_id, version = meta.get("id"), meta.get("version")
    if mod_id not in IDS:
        raise ValueError("Mod not in restricted HYPE allowlist")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,120}", version):
        raise ValueError("Invalid Fabric version")
    depends = meta.get("depends")
    if not isinstance(depends, dict) or depends.get("minecraft") != "1.21.1":
        raise ValueError("Only Minecraft 1.21.1 builds supported")
    fields = {
        "release": str(release), "version": version,
        "url": f"{BASE}/{mod_id}/{sha}.jar",
        "sha256": sha, "size": str(size), "minecraft": "1.21.1",
        "mod_id": mod_id, "channel": "stable"
    }
    return "".join(f"{name}={fields[name]}\n" for name in FIELDS)

def main() -> int:
    p = argparse.ArgumentParser(description="HYPE unsigned manifest draft, offline ONLY")
    p.add_argument("jar", type=Path, help="Exact locally stored protected JAR")
    p.add_argument("--release", type=int, required=True)
    p.add_argument("--expected-protected-sha", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    try:
        content = unsigned_manifest(a.jar, a.release, a.expected_protected_sha)
        if a.out.exists():
            raise ValueError("Output exists; refusing to overwrite")
        a.out.write_text(content, encoding="ascii", newline="\n")
        print("UNSIGNED test-only draft produced:", a.out)
        print("NO signature or admin approval. Never publish this as a valid release.")
        return 0
    except (OSError, ValueError, KeyError, BadZipFile, json.JSONDecodeError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
