"""Pin the server verifier to the public key in the manually tested client.

Do not put private signing keys or real JAR binaries into this repository.
"""
import base64
import hashlib
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

from modules.hype_signed_release import PUBLIC_KEY_DER_B64


EXPECTED_NEW_KEY_DER_SHA256 = "0eef3a6a125a8efe03b93949e98a8028c3f589317c3c9ec8fe4509b2d31f0cd4"


class HypeClientKeyMigrationTests(unittest.TestCase):
    def test_verifier_uses_new_client_key(self):
        der = base64.b64decode(PUBLIC_KEY_DER_B64, validate=True)
        self.assertEqual(hashlib.sha256(der).hexdigest(), EXPECTED_NEW_KEY_DER_SHA256)
        self.assertIsInstance(load_der_public_key(der), Ed25519PublicKey)

    def test_old_public_key_is_not_used_for_new_releases(self):
        old_key = "MCowBQYDK2VwAyEARuMdCP0sz0PgfWc8aUMTHmElRH1jpCmE84gZojUY34k="
        self.assertNotEqual(PUBLIC_KEY_DER_B64, old_key)


if __name__ == "__main__":
    unittest.main()
