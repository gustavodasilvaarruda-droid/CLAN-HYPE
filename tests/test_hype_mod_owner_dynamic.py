"""Dynamic Fabric IDs exist only in the private authenticated owner pilot."""
import hashlib
import io
import json
import unittest
import uuid
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_STORED

from modules.hype_mod_staging import inspect_original, InvalidJar
from modules.hype_mod_owner_pilot import (
    valid_owner_mod_id, _valid_original, list_owner_pilots,
    InvalidPrivateRelease,
)

NEW_ID = "hype_new_module_2026"


def new_jar(mod_id=NEW_ID):
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_STORED) as jar:
        jar.writestr("fabric.mod.json", json.dumps({
            "id": mod_id, "version": "1.0.0-dev",
            "depends": {"minecraft": "1.21.1"}
        }))
        jar.writestr("br/clanhype/module/Entry.class", b"X" * 2048)
    return stream.getvalue()


def draft(mod_id=NEW_ID, release=1):
    raw = new_jar(mod_id)
    sha = hashlib.sha256(raw).hexdigest()
    return {
        "id": str(uuid.uuid4()), "module_id": mod_id, "version": "1.0.0-dev",
        "status": "em_teste", "sha256": sha, "size_bytes": len(raw),
        "storage_path": f"{mod_id}/{'b'*32}/{sha}.jar",
        "meta": {"owner_pilot": {"release": release}},
    }


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *args):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "hype_mod_release_drafts"
        return _Table(self.rows)


class DynamicOwnerPilotTests(unittest.TestCase):
    def test_no_registration_required_for_owner_only_fabric_id(self):
        self.assertTrue(valid_owner_mod_id(NEW_ID))
        self.assertTrue(valid_owner_mod_id("hype_pokedex"))
        self.assertFalse(valid_owner_mod_id("hypebootstrap"))
        self.assertFalse(valid_owner_mod_id("../secrets"))
        self.assertFalse(valid_owner_mod_id("evil;drop"))
        self.assertFalse(valid_owner_mod_id("X"*65))

    def test_public_inspection_remains_allowlisted(self):
        raw = new_jar()
        with self.assertRaises(InvalidJar):
            inspect_original(raw)
        result = inspect_original(raw, allow_dynamic=True)
        self.assertEqual(result["module_id"], NEW_ID)
        self.assertEqual(result["version"], "1.0.0-dev")

    def test_privately_published_custom_id_is_validated(self):
        row = draft()
        self.assertEqual(_valid_original(row), row["id"])
        row["module_id"] = "../unsafe"
        with self.assertRaises(InvalidPrivateRelease):
            _valid_original(row)

    def test_dynamic_catalogue_chooses_latest_publication(self):
        first = draft(release=1)
        second = draft(release=2)
        pokedex = draft(mod_id="hype_pokedex", release=1)
        results = list_owner_pilots(_DB([first, second, pokedex]))
        self.assertEqual(len(results), 2)
        found = {record["id"]: record["release"] for _draft, record in results}
        self.assertEqual(found[NEW_ID], 2)
        self.assertEqual(found["hype_pokedex"], 1)

    def test_corrupted_owner_record_fails_closed(self):
        row = draft()
        row["meta"]["owner_pilot"]["release"] = 0
        with self.assertRaises(InvalidPrivateRelease):
            list_owner_pilots(_DB([row]))


if __name__ == "__main__":
    unittest.main()
