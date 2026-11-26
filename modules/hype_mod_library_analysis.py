"""Read-only inventory and owner export for a private Fabric mod JAR.

This analyzes a verified private upload. It never publishes, executes, or
extracts classes onto the server filesystem. An archive is only returned to
the same authenticated administrator who may download the original JAR.
"""
from __future__ import annotations

import io
import json
from collections import Counter
from zipfile import ZIP_STORED, ZipFile


def _dependencies(metadata, key):
    value = metadata.get(key)
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, requirement in sorted(value.items()):
        if not isinstance(name, str):
            continue
        if isinstance(requirement, str):
            result[name] = requirement[:200]
        elif isinstance(requirement, list):
            result[name] = [part[:200] for part in requirement[:20] if isinstance(part, str)]
    return result


def report_for_verified_jar(binary, record, inspected):
    """Summarize validated bytes. Caller MUST check auth, SHA and Fabric ID first."""
    with ZipFile(io.BytesIO(binary), "r") as jar:
        metadata = json.loads(jar.read("fabric.mod.json"))
        names = jar.namelist()

    class_names = sorted(name for name in names if name.endswith(".class"))
    package_counts = Counter(
        name.rpartition("/")[0].replace("/", ".")
        for name in class_names
    )
    mixins = metadata.get("mixins") or []
    if not isinstance(mixins, list):
        mixins = []
    mixin_files = [
        entry[:200] for entry in mixins if isinstance(entry, str)
    ][:30]
    entrypoints = metadata.get("entrypoints")
    if not isinstance(entrypoints, dict):
        entrypoints = {}

    return {
        "schema": 1,
        "type": "hype_private_static_jar_inspection",
        "mod": {
            "fabric_id": inspected["module_id"],
            "name": inspected["name"],
            "version": inspected["version"],
            "filename": record.get("original_filename") or "",
            "sha256": inspected["sha256"],
            "size_bytes": inspected["size_bytes"],
            "uploaded_at": record.get("created_at") or None,
        },
        "fabric": {
            "minecraft": inspected["compatibility"]["minecraft"],
            "fabricloader": inspected["compatibility"]["fabricloader"],
            "cobblemon": inspected["compatibility"]["cobblemon"],
            "java": inspected["compatibility"]["java"],
            "depends": _dependencies(metadata, "depends"),
            "recommends": _dependencies(metadata, "recommends"),
            "breaks": _dependencies(metadata, "breaks"),
            "entrypoint_groups": sorted(str(key)[:100] for key in entrypoints),
            "mixins": mixin_files,
            "has_mixins": inspected["has_mixins"],
            "requires_hype_client": inspected["requires_client"],
        },
        "archive": {
            "total_entries": len(names),
            "class_count": len(class_names),
            "resource_count": sum(1 for name in names if not name.endswith(".class") and not name.endswith("/")),
            "class_files_sample": class_names[:80],
            "top_java_packages": [
                {"name": name, "classes": count}
                for name, count in package_counts.most_common(25)
            ],
        },
        "scope": "Static metadata and class inventory only; no JAR execution, decompilation, runtime permission check, or Minecraft compatibility guarantee.",
    }


def build_private_analysis_package(binary, report):
    """Create a local export; do not write back to Storage or any release table."""
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        archive.writestr("original.jar", binary)
        archive.writestr(
            "analise.json",
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
    return output.getvalue()
