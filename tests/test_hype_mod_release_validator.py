"""Unit checks for the pure JAR validator and fail-closed bucket check."""
import ast
import hashlib
import io
import json
import stat
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, BadZipFile
import pytest

SOURCE = Path(__file__).parents[1] / "modules" / "hype_mod_staging.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
keep = [n for n in tree.body
        if (isinstance(n, ast.ClassDef) and n.name == "InvalidJar")
        or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name in {"inspect_original", "assert_private_bucket"})]
code = compile(ast.fix_missing_locations(ast.Module(body=keep, type_ignores=[])),
               str(SOURCE), "exec")
ns = {
    "BUCKET": "hype-mod-originals", "MAX_UPLOAD": 10 * 1024 * 1024,
    "MAX_ENTRIES": 8000, "MAX_UNCOMPRESSED": 300 * 1024 * 1024,
    "IDS": {"hype_pokedex": "HYPE Pokédex", "hypeclient": "HYPE Client"},
    "ZipFile": ZipFile, "BadZipFile": BadZipFile,
    "hashlib": hashlib, "io": io, "json": json,
    "stat": stat, "OSError": OSError, "EOFError": EOFError,
    "RuntimeError": RuntimeError, "UnicodeError": UnicodeError,
}
exec(code, ns)
inspect_original = ns["inspect_original"]
assert_private_bucket = ns["assert_private_bucket"]
InvalidJar = ns["InvalidJar"]


def jar(*, id="hype_pokedex", version="2.0.0", extra=None, depends=None):
    b = io.BytesIO()
    with ZipFile(b, "w") as z:
        z.writestr("fabric.mod.json", json.dumps({
            "id": id, "version": version, "depends": depends or {"minecraft": "1.21.1"}
        }))
        z.writestr("mod/Example.class", b"\xca\xfe\xba\xbe")
        if extra:
            z.writestr(extra, b"bad")
    return b.getvalue()


def test_inspect_normal_fabric_jar():
    result = inspect_original(jar())
    assert result["module_id"] == "hype_pokedex"
    assert result["version"] == "2.0.0"
    assert result["requires_client"] is False
    assert len(result["sha256"]) == 64


@pytest.mark.parametrize("id", ["hype_auto_ovo_updater", "hype_battle_royale", [], None])
def test_reject_unregistered_or_broken_ids(id):
    with pytest.raises(InvalidJar):
        inspect_original(jar(id=id))


@pytest.mark.parametrize("path", ["../steal.jar", "/etc/passwd", "bad\\path"])
def test_reject_unsafe_zip_paths(path):
    with pytest.raises(InvalidJar):
        inspect_original(jar(extra=path))


def test_reject_bad_zip_and_oversize():
    with pytest.raises(InvalidJar):
        inspect_original(b"this is not a JAR")
    with pytest.raises(InvalidJar):
        inspect_original(b"x" * (10 * 1024 * 1024 + 1))


class Bucket:
    def __init__(self, public):
        self.public = public


class Storage:
    def __init__(self, bucket):
        self.bucket = bucket
    def get_bucket(self, name):
        assert name == "hype-mod-originals"
        return self.bucket


def test_bucket_must_be_known_private():
    assert_private_bucket(Storage(Bucket(False)))
    assert_private_bucket(Storage({"public": False}))
    for bucket in (None, {}, Bucket(None), Bucket(True), {"public": True}):
        with pytest.raises(RuntimeError):
            assert_private_bucket(Storage(bucket))
