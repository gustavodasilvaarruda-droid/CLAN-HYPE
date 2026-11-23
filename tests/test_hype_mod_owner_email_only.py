"""Restricao de toda a Central de Releases no rollout individual."""
import os
import unittest
from unittest.mock import patch

from flask import Blueprint, Flask
from modules.hype_mod_staging import register_mod_release_routes


OWNER = "gustavodasilvaarruda@gmail.com"
DRAFT_ID = "c957d4c1-15e4-4b43-af6d-5d5cc4dc6d97"


class OwnerReleaseCenterTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {
            "HYPE_PRIVATE_MOD_ROLLOUT_SCOPE": "single",
            "HYPE_PRIVATE_MOD_TESTER_EMAIL": OWNER,
            "HYPE_MOD_STAGING_ENABLED": "0",
            "HYPE_MOD_ORIGINAL_TEST_DOWNLOAD_ENABLED": "0",
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        app = Flask(__name__)
        app.secret_key = "local-test-secret"
        bp = Blueprint("hype_mod_admin", __name__)
        register_mod_release_routes(bp, lambda: True, None, db=None)
        app.register_blueprint(bp)
        self.client = app.test_client()

    def as_user(self, email, path, method="GET"):
        with self.client.session_transaction() as sess:
            sess["usuario_email"] = email
        return self.client.open(path, method=method)

    def test_other_admin_cannot_enter_release_center(self):
        self.assertEqual(
            self.as_user("other-admin@example.com", "/admin/modulos/releases").status_code,
            403,
        )

    def test_other_admin_cannot_download_original(self):
        path = f"/admin/modulos/releases/original-teste/{DRAFT_ID}"
        self.assertEqual(
            self.as_user("other-admin@example.com", path).status_code, 403
        )

    def test_other_admin_cannot_publish_or_upload(self):
        self.assertEqual(
            self.as_user("other-admin@example.com",
                         "/admin/modulos/releases/publicar-privado", method="POST").status_code,
            403,
        )

    def test_owner_passes_identity_gate_but_no_file_is_published(self):
        # 404 confirms the owner passed admin_only and hit a disabled endpoint.
        path = f"/admin/modulos/releases/original-teste/{DRAFT_ID}"
        self.assertEqual(self.as_user(OWNER.upper(), path).status_code, 404)

    def test_missing_config_fails_closed_for_owner(self):
        with patch.dict(os.environ, {"HYPE_PRIVATE_MOD_TESTER_EMAIL": ""}):
            self.assertEqual(
                self.as_user(OWNER, "/admin/modulos/releases").status_code, 403
            )


if __name__ == "__main__":
    unittest.main()
