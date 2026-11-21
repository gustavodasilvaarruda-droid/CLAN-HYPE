"""Regressões de segurança da distribuição autenticada de mods HYPE."""
import hashlib
import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.exceptions import HTTPException

from modules.hype_mod_distribution import (
    bucket_private, enabled, fetch_verified_jar, permitted, latest,
)


class Storage:
    def __init__(self, payload, public=False):
        self.payload = payload
        self.public = public

    def get_bucket(self, name):
        return {"public": self.public}

    def from_(self, name):
        return self

    def download(self, path):
        return self.payload


class TestDistributionSecurity(unittest.TestCase):
    def test_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(enabled())

    def test_bucket_must_be_private(self):
        bucket_private(Storage(b"ok", False))
        with self.assertRaises(RuntimeError):
            bucket_private(Storage(b"ok", True))

    def test_sha256_checked_on_every_download(self):
        app = Flask("test_distribution")
        payload = b"example jar bytes"
        release = {
            "module_id": "hypeclient",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "storage_path": "hypeclient/" + hashlib.sha256(payload).hexdigest() + ".jar",
            "size_bytes": len(payload),
        }
        with app.test_request_context("/mods/hypeclient/baixar"):
            good = Mock()
            good.storage = Storage(payload)
            response = fetch_verified_jar(good, release)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(), payload)

            bad = Mock()
            bad.storage = Storage(b"changed bytes")
            with self.assertRaises(HTTPException) as error:
                fetch_verified_jar(bad, release)
            self.assertEqual(error.exception.code, 503)

    def test_fail_closed_without_database(self):
        self.assertEqual(permitted(None, "test@example.com", lambda email: True), set())


if __name__ == "__main__":
    unittest.main()
