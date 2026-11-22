"""Offline signing never accepts a key unrelated to the installed client."""
import base64
import io
import json
import os
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from modules import hype_manifest_signer as signer
from modules import hype_signed_release as verifier


def example_jar(version="R7.19-ALPHA7-PREVIEW10.0.42-CHAVE-TESTE1"):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as z:
        z.writestr("fabric.mod.json", json.dumps({
            "id": "hypeclient", "version": version,
            "depends": {"minecraft": "1.21.1"},
        }))
        z.writestr("br/clanhype/client/HypeClient.class", os.urandom(2048))
    return stream.getvalue()


class OfflineManifestSignerTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        der = self.key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        key_b64 = base64.b64encode(der).decode()
        for module in (signer, verifier):
            patcher = patch.object(module, "PUBLIC_KEY_DER_B64", key_b64)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_signature_matches_server_verifier(self):
        jar = example_jar()
        manifest = signer.sign_manifest(jar, self.key, 42)
        self.assertEqual(manifest.count(b"signature="), 1)
        self.assertIn(b"release=42\n", manifest)
        self.assertEqual(
            verifier.verify_signed_manifest(
                manifest, version="R7.19-ALPHA7-PREVIEW10.0.42-CHAVE-TESTE1",
                sha256=__import__("hashlib").sha256(jar).hexdigest(), size_bytes=len(jar)
            )["release"], 42
        )

    def test_other_private_key_cannot_sign_for_current_client(self):
        with self.assertRaisesRegex(ValueError, "incompatível"):
            signer.sign_manifest(example_jar(), Ed25519PrivateKey.generate(), 42)

    def test_release_and_mod_metadata_validation(self):
        for release in (0, -2, 1000000000):
            with self.assertRaises(ValueError):
                signer.sign_manifest(example_jar(), self.key, release)
        with self.assertRaisesRegex(ValueError, "Versão Fabric"):
            signer.sign_manifest(example_jar("bad version"), self.key, 42)


if __name__ == "__main__":
    unittest.main()
