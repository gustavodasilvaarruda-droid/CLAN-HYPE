"""Check that Fabric entrypoints and updater survive protected-build staging."""
import io
import json
import hashlib
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from modules.hype_mod_build_checks import (
    UnsafeBuild, check_fabric_classes, check_candidate_compatibility,
)
from modules.hype_mod_staging import audit_candidate_pair, InvalidJar, InvalidRelease


def fake_jar(*, version="R7.19-TEST", body=b"original", entrypoint=True, valid_magic=True):
    raw = io.BytesIO()
    meta = {
        "schemaVersion": 1,
        "id": "hypeclient",
        "version": version,
        "depends": {"minecraft": "1.21.1"},
        "entrypoints": {"client": ["br.clanhype.client.HypeClient"]},
    }
    with ZipFile(raw, "w", ZIP_DEFLATED) as archive:
        archive.writestr("fabric.mod.json", json.dumps(meta))
        if entrypoint:
            archive.writestr("br/clanhype/client/HypeClient.class",
                             (bytes.fromhex("CAFEBABE") if valid_magic else b"broken") + b"class")
        archive.writestr("br/clanhype/client/update/HypeAutoUpdateClient.class",
                         bytes.fromhex("CAFEBABE") + b"update")
        archive.writestr("internal/version.txt", body)
    return raw.getvalue()


class ProtectedBuildChecksTests(unittest.TestCase):
    def test_original_fabric_entrypoints_verified(self):
        report = check_fabric_classes(fake_jar())
        self.assertEqual(report["entrypoints_checked"], 1)
        self.assertFalse(report["obfuscation_verified"])
        self.assertFalse(report["game_test_verified"])

    def test_missing_entrypoint_rejected(self):
        with self.assertRaises(UnsafeBuild):
            check_fabric_classes(fake_jar(entrypoint=False))

    def test_bad_class_magic_rejected(self):
        with self.assertRaises(UnsafeBuild):
            check_fabric_classes(fake_jar(valid_magic=False))

    def test_noop_candidate_rejected(self):
        data = fake_jar()
        with self.assertRaises(UnsafeBuild):
            check_candidate_compatibility(data, data)

    def test_compatible_candidate_is_still_not_proven_obfuscated(self):
        source = fake_jar()
        other = fake_jar(body=b"candidate")
        report = check_candidate_compatibility(source, other)
        self.assertFalse(report["obfuscation_verified"])

    def test_static_preflight_binds_report_to_stored_candidate(self):
        original = fake_jar()
        candidate = fake_jar(body=b"candidate")
        digest = hashlib.sha256(candidate).hexdigest()
        draft = {
            "module_id": "hypeclient", "version": "R7.19-TEST",
            "sha256": hashlib.sha256(original).hexdigest(),
            "meta": {"protected": {"sha256": digest, "size_bytes": len(candidate)}},
        }
        report = audit_candidate_pair(original, candidate, draft)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["candidate_sha256"], digest)
        self.assertEqual(report["checks"]["updater"], "passed")
        with self.assertRaises(InvalidRelease):
            audit_candidate_pair(original, fake_jar(body=b"tampered"), draft)
        with self.assertRaises(InvalidJar):
            audit_candidate_pair(original, candidate, {**draft, "version": "wrong"})

    def test_changed_fabric_version_rejected(self):
        with self.assertRaises(UnsafeBuild):
            check_candidate_compatibility(fake_jar(), fake_jar(version="another"))


if __name__ == "__main__":
    unittest.main()
