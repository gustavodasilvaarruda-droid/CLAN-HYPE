"""Offline ProGuard adapter for Fabric 1.21.1 HYPE JARs.

IMPORTANT: The adapter is not a proof of runtime compatibility. Run only
inside an isolated worker. The ProGuard installation and runtime library JARs
are provisioned and pinned OUTSIDE the public repository. No credentials are
used here. Never upload ProGuard mappings or original JARs to CI.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import BadZipFile, ZipFile

# All user-provided configuration values are quoted for ProGuard config output.
# Avoid injection from path characters the configuration format could interpret.
JAVA_CLASS = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$", re.ASCII)
MAX_LIBRARY_FILES = 256


class AdapterError(ValueError):
    pass


def _name(value):
    if not isinstance(value, str) or not JAVA_CLASS.fullmatch(value):
        raise AdapterError("Invalid class name in Fabric metadata.")
    return value


def _safe_path(path):
    path = Path(path).resolve(strict=True)
    if any(c in str(path) for c in ("\n", "\r", "'", '"', "(", ")", ";")):
        raise AdapterError("Unsafe character in ProGuard path.")
    return str(path)


def _library_files(library_dirs):
    files = []
    for raw in library_dirs:
        directory = Path(raw).resolve(strict=True)
        if not directory.is_dir():
            raise AdapterError("External runtime libraries must be directories.")
        for child in sorted(directory.iterdir()):
            if child.is_symlink():
                raise AdapterError("Runtime library symlinks are not allowed.")
            if child.suffix in (".jar", ".jmod") and child.is_file():
                files.append(str(child))
    if not files or len(files) > MAX_LIBRARY_FILES:
        raise AdapterError("Provide between 1 and 256 local dependency JARs/JMODs.")
    return files


def _mixin_config_classes(archive, metadata):
    """Resolve Mixin plugin and class names without rewriting resource strings."""
    keep = set()
    files = metadata.get("mixins") or []
    if not isinstance(files, list):
        raise AdapterError("Unsupported Fabric mixins metadata.")
    for item in files:
        name = item if isinstance(item, str) else item.get("config") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.endswith(".json"):
            raise AdapterError("Unsupported Mixin declaration.")
        try:
            config = json.loads(archive.read(name))
        except (KeyError, ValueError) as exc:
            raise AdapterError("Invalid or missing Mixin config.") from exc
        if not isinstance(config, dict):
            raise AdapterError("Invalid Mixin config object.")
        pkg = config.get("package")
        if not isinstance(pkg, str) or not JAVA_CLASS.fullmatch(pkg):
            raise AdapterError("Mixin config requires a valid package.")
        plugin = config.get("plugin")
        if plugin:
            keep.add(_name(plugin))
        for group in ("mixins", "client", "server"):
            values = config.get(group) or []
            if not isinstance(values, list):
                raise AdapterError("Invalid Mixin class list.")
            for value in values:
                if not isinstance(value, str):
                    raise AdapterError("Invalid Mixin class name.")
                keep.add(_name(pkg + "." + value))
    return keep


def inspect_fabric_keep_classes(jar_bytes):
    """Preserve all Fabric runtime entrypoints, Mixin classes and service providers."""
    try:
        with ZipFile(io.BytesIO(jar_bytes)) as archive:
            metadata = json.loads(archive.read("fabric.mod.json"))
            if not isinstance(metadata, dict):
                raise AdapterError("Invalid Fabric metadata.")
            keep = _mixin_config_classes(archive, metadata)
            entrypoints = metadata.get("entrypoints") or {}
            if not isinstance(entrypoints, dict):
                raise AdapterError("Invalid Fabric entrypoints.")
            for values in entrypoints.values():
                if not isinstance(values, list):
                    raise AdapterError("Invalid entrypoint list.")
                for item in values:
                    value = item if isinstance(item, str) else item.get("value") if isinstance(item, dict) else None
                    if not isinstance(value, str):
                        raise AdapterError("Invalid entrypoint.")
                    keep.add(_name(value.split("::", 1)[0]))
            # HYPE Client's updater uses a stable hook referenced elsewhere.
            if metadata.get("id") == "hypeclient":
                keep.add("br.clanhype.client.update.HypeAutoUpdateClient")
            for name in archive.namelist():
                if name.startswith("META-INF/services/") and not name.endswith("/"):
                    for row in archive.read(name).decode("utf-8").splitlines():
                        provider = row.split("#", 1)[0].strip()
                        if provider:
                            keep.add(_name(provider))
            paths = set(archive.namelist())
            for name in keep:
                if name.replace(".", "/") + ".class" not in paths:
                    raise AdapterError("Referenced Fabric or service class is missing.")
            return tuple(sorted(keep))
    except (BadZipFile, OSError, UnicodeError, KeyError, ValueError) as exc:
        if isinstance(exc, AdapterError):
            raise
        raise AdapterError("Invalid Fabric JAR or metadata.") from exc


def config_text(input_file, output_file, libraries, keep):
    lines = [
        "-injars '" + _safe_path(input_file) + "'",
        "-outjars '" + str(Path(output_file).resolve()) + "'",
        "-dontshrink", "-dontoptimize", "-dontpreverify",
        "-keepdirectories",
        "-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod,Exceptions,MethodParameters",
        # Public APIs may be called by other mods; never rename their signatures.
        "-keep public class * { public *; }",
        # Mixin methods and methods/fields on Fabric bootstrap classes use reflection.
        "-keep @org.spongepowered.asm.mixin.Mixin class * { *; }",
    ]
    for path in libraries:
        lines.append("-libraryjars '" + _safe_path(path) + "'")
    for cls in keep:
        lines.append("-keep class " + _name(cls) + " { *; }")
    return "\n".join(lines) + "\n"


def _validate_output(original, candidate):
    """Fail when a tool only repackages the JAR, or alters loader metadata."""
    with ZipFile(io.BytesIO(original)) as a, ZipFile(io.BytesIO(candidate)) as b:
        a_names, b_names = set(a.namelist()), set(b.namelist())
        for name in a_names:
            if name == "fabric.mod.json" or name.endswith(".mixins.json") or name.endswith(".accesswidener") or name.startswith("META-INF/services/"):
                if name not in b_names or a.read(name) != b.read(name):
                    raise AdapterError("Protected JAR modified a Fabric runtime resource.")
        old_classes = {name: a.read(name) for name in a_names if name.endswith(".class")}
        new_classes = {name: b.read(name) for name in b_names if name.endswith(".class")}
        if not old_classes or not new_classes:
            raise AdapterError("Protected JAR is missing Java classes.")
        if old_classes == new_classes:
            raise AdapterError("No Java bytecode or class names changed; protection not proven.")


def protect(input_file, output_file, executable, library_dirs):
    source = Path(input_file).resolve(strict=True)
    target = Path(output_file).resolve()
    binpath = Path(_safe_path(executable))
    if not binpath.is_file() or binpath.is_symlink():
        raise AdapterError("ProGuard executable is unavailable.")
    if not source.is_file() or source == target or target.exists():
        raise AdapterError("Invalid source or output path.")
    original = source.read_bytes()
    keep = inspect_fabric_keep_classes(original)
    libraries = _library_files(library_dirs)
    with tempfile.TemporaryDirectory(prefix="hype-proguard-config-") as directory:
        config = Path(directory) / "rules.pro"
        config.write_text(config_text(source, target, libraries, keep), encoding="utf-8")
        config.chmod(0o600)
        subprocess.run(
            [str(binpath), "@" + str(config)], timeout=165, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "HOME": str(directory), "LANG": "C.UTF-8"},
        )
    if not target.is_file() or target.is_symlink():
        raise AdapterError("ProGuard did not produce a regular JAR.")
    _validate_output(original, target.read_bytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proguard-bin", required=True)
    parser.add_argument("--library-dir", action="append", required=True)
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    try:
        protect(args.input, args.output, args.proguard_bin, args.library_dir)
    except (AdapterError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print("Protection blocked: verify ProGuard and runtime libraries in the isolated worker.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
