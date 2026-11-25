"""Validation of arbitrary future mod IDs in the private, owner-only upload flow."""
import io
import json
import unittest
from zipfile import ZipFile

from modules.hype_mod_staging import InvalidJar, inspect_original, valid_module_id


def fabric_jar(mod_id, name="Future HYPE Mod"):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({
            "schemaVersion": 1,
            "id": mod_id,
            "version": "1.0.0",
            "name": name,
            "depends": {"minecraft": "1.21.1", "fabricloader": ">=0.16"},
        }))
        archive.writestr("mod-content.bin", b"x" * 3000)
    return output.getvalue()


class DynamicOwnerUploadTests(unittest.TestCase):
    def test_new_mod_is_inspected_without_hardcoded_registration(self):
        report = inspect_original(fabric_jar("hype_future_mod"))
        self.assertEqual(report["module_id"], "hype_future_mod")
        self.assertEqual(report["name"], "Future HYPE Mod")
        self.assertEqual(report["version"], "1.0.0")

    def test_existing_ids_remain_accepted(self):
        self.assertEqual(inspect_original(fabric_jar("hypeclient"))["module_id"], "hypeclient")
        self.assertTrue(valid_module_id("hype_battle_ai"))

    def test_bad_or_reserved_module_ids_are_rejected(self):
        for name in ("hypebootstrap", "../private", "UPPER", "x", "x" * 70,
                     "a/b", "x.jar", "com.example.mod", "", None):
            with self.subTest(name=name):
                self.assertFalse(valid_module_id(name))
                if isinstance(name, str):
                    with self.assertRaises(InvalidJar):
                        inspect_original(fabric_jar(name))

    def test_mod_metadata_is_not_sufficient_without_fabric_mod_json(self):
        data = io.BytesIO()
        with ZipFile(data, "w") as archive:
            archive.writestr("x", "not a fabric mod")
        with self.assertRaises(InvalidJar):
            inspect_original(data.getvalue())


if __name__ == "__main__":
    unittest.main()
