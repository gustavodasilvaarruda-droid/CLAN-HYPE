"""Regression checks for the publication wizard; posting/security stay in Flask."""
import re
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

    def test_four_distinct_guided_stages(self):
        stages = re.findall(r'<section class="hpub-stage" data-hpub-stage="([^"]+)"', self.html)
        self.assertEqual(stages, ["arquivo", "envio", "teste", "publicar"])
        self.assertEqual(self.html.count('data-hpub-goto='), 4)
        self.assertIn("hype_publish_center.js", self.html)
        self.assertIn("hype_publish_center.css", self.html)

    def test_existing_privileged_endpoints_are_preserved(self):
        endpoints = (
            "mod_release_inspect",
            "mod_release_upload",
            "mod_release_review",
            "mod_release_link_existing",
            "mod_release_protected_upload",
            "mod_release_verify",
            "mod_release_publish",
            "mod_release_publish_private",
            "mod_release_delete",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertIn("hype_mod_admin." + endpoint, self.html)
        self.assertGreaterEqual(self.html.count('name="csrf_token"'), 8)
        self.assertIn('name="confirm_release"', self.html)
        self.assertIn("manifesto Ed25519", self.html.replace("Manifesto Ed25519", "manifesto Ed25519"))

    def test_submission_navigates_back_to_appropriate_step(self):
        self.assertIn('sessionStorage.setItem', self.js)
        self.assertIn("form.closest('[data-hpub-stage]')", self.js)
        self.assertIn('root.classList.add(\'hpub-enhanced\')', self.js)
        self.assertIn(".hpub-enhanced .hpub-stage:not(.is-active)", self.css)

    def test_disabled_publication_is_not_unlocked_by_javascript(self):
        self.assertIn("{% if private_publish_enabled %}", self.html)
        self.assertIn("{% if publish_enabled %}", self.html)
        self.assertIn("{% if staging_enabled %}", self.html)
        self.assertIn("if (button && button.disabled) return", self.js)

    def test_accessible_and_responsive(self):
        self.assertIn('aria-label="Etapas da publicação"', self.html)
        self.assertIn("aria-current", self.js)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("@media(max-width:430px)", self.css)


if __name__ == "__main__":
    unittest.main()
