"""Regression checks for the compact HYPE publication center.

All upload/release authorizations remain server-side, never in JavaScript.
"""
import unittest
from pathlib import Path
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "templates" / "admin_hype_mod_releases.html"
CSS = ROOT / "static" / "hype_publish_center.css"
JS = ROOT / "static" / "hype_publish_center.js"


class PublishCenterUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")

    def test_template_syntax(self):
        Environment().parse(self.html)

    def test_simple_main_actions_no_four_step_wizard(self):
        for marker in ('id="hpub-quick"', 'id="hpub-library-title"',
                       'id="hpub-publish"', 'id="hpub-private-test"',
                       'id="hpub-protected-release"', 'hpub-file-review',
                       'data-hpub-mode="original"', 'data-hpub-mode="protected"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertNotIn('data-hpub-stage=', self.html)
        self.assertNotIn('id="hpub-advanced"', self.html)
        self.assertNotIn('hpub-stepper', self.html)
        self.assertIn("hype_publish_center.js", self.html)
        self.assertIn("hype_publish_center.css", self.html)

    def test_required_protected_release_approval_is_preserved(self):
        endpoints = (
            "mod_release_upload",
            "mod_release_protected_upload",
            "mod_release_review",
            "mod_release_verify",
            "mod_release_publish",
            "mod_release_publish_private",
            "mod_release_publish_original_pilot",
            "mod_release_select_test_channel",
            "mod_release_delete",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertIn("hype_mod_admin." + endpoint, self.html)
        self.assertIn('name="candidate_sha256"', self.html)
        for name in ('test_game_launch', 'test_menus',
                     'test_server_connection', 'test_no_crashes'):
            self.assertIn('name="' + name + '"', self.html)
        self.assertIn('name="confirm_release"', self.html)
        self.assertIn('name="confirm_pilot"', self.html)
        self.assertGreaterEqual(self.html.count('name="csrf_token"'), 6)

    def test_private_upload_is_distinct_from_private_bootstrap_release(self):
        self.assertIn("mod_release_original_test_download", self.html)
        self.assertIn("{% if pilot_original_enabled %}", self.html)
        self.assertIn("{% if private_publish_enabled %}", self.html)
        self.assertIn("{% if publish_enabled %}", self.html)
        self.assertIn("{% if staging_enabled %}", self.html)
        self.assertIn("Teste no Bootstrap indisponível", self.html)
        self.assertIn("manifesto ed25519", self.html.lower())

    def test_javascript_keeps_quick_upload_working_without_wizard(self):
        self.assertIn("function chooseMode(type)", self.js)
        self.assertIn("if (!selected || selected.disabled) return false", self.js)
        self.assertIn("[data-hpub-select-protected]", self.js)
        self.assertIn("[data-hpub-new-version]", self.js)
        self.assertIn("[data-hpub-publish-original]", self.js)
        self.assertIn("[data-hpub-publish-protected]", self.js)
        self.assertNotIn("sessionStorage", self.js)
        self.assertNotIn("data-hpub-stage", self.js)

    def test_responsive_and_accessible(self):
        self.assertIn('aria-label="Tipo de arquivo"', self.html)
        self.assertIn("aria-pressed", self.js)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("@media(max-width:430px)", self.css)
        self.assertIn(".hpub-file-review", self.css)


if __name__ == "__main__":
    unittest.main()
