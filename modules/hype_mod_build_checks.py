"""Fail-closed, static preflight for HYPE Fabric releases.

This checker cannot prove obfuscation, absence of malicious code or runtime
compatibility. Protected builds require a separate, trusted build process.
"""
import io
import json
from zipfile import ZipFile


class UnsafeBuild(ValueError):
    pass


def check_fabric_classes(raw):
    """Verify the Fabric bootstrap declarations refer to real Java classes."""
    with ZipFile(io.BytesIO(raw)) as archive:
        paths = set(archive.namelist())
        metadata = json.loads(archive.read("fabric.mod.json"))
        entrypoints = metadata.get("entrypoints") or {}
        if not isinstance(entrypoints, dict):
            raise UnsafeBuild("Entrypoints Fabric inválidos.")
        checked = 0
        for items in entrypoints.values():
            if not isinstance(items, list):
                raise UnsafeBuild("Lista de entrypoints Fabric inválida.")
            for item in items:
                value = item if isinstance(item, str) else item.get("value") if isinstance(item, dict) else None
                if not isinstance(value, str) or not value:
                    raise UnsafeBuild("Entrypoint Fabric inválido.")
                cls = value.split("::", 1)[0]
                path = cls.replace(".", "/") + ".class"
                if path not in paths:
                    raise UnsafeBuild("Classe de inicialização Fabric ausente: " + cls)
                if archive.read(path)[:4] != bytes.fromhex("CAFEBABE"):
                    raise UnsafeBuild("Classe de inicialização Java corrompida.")
                checked += 1
        if metadata.get("id") == "hypeclient" and (
            "br/clanhype/client/update/HypeAutoUpdateClient.class" not in paths
        ):
            raise UnsafeBuild("Atualizador automático HYPE ausente.")
        for k in ("mixins", "accessWidener"):
            refs = metadata.get(k) or []
            refs = [refs] if isinstance(refs, str) else refs
            if not isinstance(refs, list):
                raise UnsafeBuild("Metadados Fabric inválidos: " + k)
            for ref in refs:
                if not isinstance(ref, str) or ref not in paths:
                    raise UnsafeBuild("Recurso Fabric ausente: " + str(ref))
        return {"entrypoints_checked": checked, "updater_present": metadata.get("id") == "hypeclient",
                "obfuscation_verified": False, "game_test_verified": False}


def check_candidate_compatibility(original, candidate):
    """Check a protected candidate without silently accepting changed entrypoints."""
    with ZipFile(io.BytesIO(original)) as old, ZipFile(io.BytesIO(candidate)) as new:
        a = json.loads(old.read("fabric.mod.json"))
        b = json.loads(new.read("fabric.mod.json"))
    for field in ("id", "version", "depends", "entrypoints", "mixins", "accessWidener"):
        if a.get(field) != b.get(field):
            raise UnsafeBuild("Build candidato alterou " + field + " do Fabric.")
    if original == candidate:
        raise UnsafeBuild("Build candidato é idêntico ao original.")
    return check_fabric_classes(candidate)
