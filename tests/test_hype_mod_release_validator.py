"""Unittest checks for isolated ZIP/Fabric validator and private-storage guard."""
import ast
import hashlib
import io
import json
import stat
import unittest
from pathlib import Path
from zipfile import ZipFile, BadZipFile

SOURCE = Path(__file__).parents[1] / "modules" / "hype_mod_staging.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
nodes = [node for node in tree.body
         if isinstance(node, ast.ClassDef) and node.name == "InvalidJar"
         or isinstance(node, ast.FunctionDef)
         and node.name in {"inspect_original", "assert_private_bucket"}]
fragment = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                   str(SOURCE), "exec")
scope = {
    "BUCKET": "hype-mod-originals", "MAX_UPLOAD": 10 * 1024 * 1024,
    "MAX_ENTRIES": 8000, "MAX_UNCOMPRESSED": 300 * 1024 * 1024,
    "IDS": {"hype_pokedex": "HYPE Pokédex", "hypeclient": "HYPE Client"},
    "ZipFile": ZipFile, "BadZipFile": BadZipFile, "hashlib": hashlib,
    "io": io, "json": json, "stat": stat,
}
exec(fragment, scope)
inspect_original = scope["inspect_original"]
assert_private_bucket = scope["assert_private_bucket"]
InvalidJar = scope["InvalidJar"]


def make_jar(mod_id="hype_pokedex", version="2.0", extra=None, depends=None):
    b = io.BytesIO()
    with ZipFile(b, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({
            "id": mod_id, "version": version,
            "depends": depends if depends is not None else {"minecraft": "1.21.1"}
        }))
        archive.writestr("br/hype/Example.class", b"abcd")
        if extra:
            archive.writestr(extra, b"bad")
    return b.getvalue()


class Storage:
    def __init__(self, bucket):
        self.bucket = bucket
    def get_bucket(self, name):
        assert name == "hype-mod-originals"
        return self.bucket


class Bucket:
    def __init__(self, public):
        self.public = public


class TestReleaseValidation(unittest.TestCase):
    def test_good_jar_and_hash(self):
        data = make_jar()
        info = inspect_original(data)
        self.assertEqual(info["module_id"], "hype_pokedex")
        self.assertEqual(info["version"], "2.0")
        self.assertEqual(info["sha256"], hashlib.sha256(data).hexdigest())
        self.assertFalse(info["requires_client"])

    def test_declared_hypeclient_dependency(self):
        info = inspect_original(make_jar(depends={"hypeclient": "*"}))
        self.assertTrue(info["requires_client"])

    def test_reject_unknown_preview_and_malformed_id(self):
        for value in ("hype_auto_ovo_updater", "hype_battle_royale", [], None):
            with self.subTest(value=value), self.assertRaises(InvalidJar):
                inspect_original(make_jar(mod_id=value))

    def test_reject_unsafe_zip_entries(self):
        for path in ("../secret.jar", "/etc/passwd", "bad\\path"):
            with self.subTest(path=path), self.assertRaises(InvalidJar):
                inspect_original(make_jar(extra=path))

    def test_reject_oversized_corrupt_and_bad_depends(self):
        for item in (b"not a jar", b"x" * (10 * 1024 * 1024 + 1),
                     make_jar(depends=["not-dict"])):
            with self.subTest(size=len(item)), self.assertRaises(InvalidJar):
                inspect_original(item)

    def test_bucket_must_be_known_private(self):
        assert_private_bucket(Storage(Bucket(False)))
        assert_private_bucket(Storage({"public": False}))
        for bucket in (None, {}, Bucket(None), Bucket(True), {"public": True}):
            with self.subTest(bucket=bucket), self.assertRaises(RuntimeError):
                assert_private_bucket(Storage(bucket))


if __name__ == "__main__":
    unittest.main()
