"""Regressões da Central HYPE v2: envio único, Client prioritário e controle explícito.

Verificações de interface: não disparam uploads, proteção ou publicação.
"""
import unittest
from pathlib import Path

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_hype_mod_releases.html"
JS = ROOT / "static" / "hype_publish_center.js"
CSS = ROOT / "static" / "hype_publish_center.css"


class PublishCenterV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = TEMPLATE.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")

    def test_template_jinja_is_valid(self):
        Environment().parse(self.template)

    def test_one_original_upload_is_primary_action(self):
        source = self.template
        self.assertEqual(source.count("url_for('hype_mod_admin.mod_release_upload')"), 1)
        self.assertIn('id="hpub-quick-original"', source)
        self.assertIn("Enviar original e preparar proteção", source)
        self.assertIn('id="hpub-manual-tools"', source)
        self.assertIn('data-hpub-upload-panel="protected" hidden', source)
        self.assertIn("O processamento só acontece quando o worker estiver ativo", source)

    def test_client_is_visibly_prioritized(self):
        source = self.template
        self.assertIn('id="hpub-priority-title">HYPE Client', source)
        self.assertIn("selectattr('module_id','equalto','hypeclient')", source)
        self.assertIn('hpub-client-label', source)
        self.assertIn('data-hpub-version-module="{{ item.module_id }}"', source)

    def test_publish_remains_separate_and_requires_approval(self):
        source = self.template
        self.assertIn('id="hpub-publishing-tools"', source)
        self.assertIn('id="hpub-protected-release"', source)
        self.assertIn('id="hpub-unified-release-form"', source)
        self.assertIn('name="confirm_release" value="yes" required', source)
        self.assertIn('name="candidate_sha256"', source)
        self.assertIn('name="test_game_launch"', source)
        self.assertIn('name="test_no_crashes"', source)
        self.assertIn('name="csrf_token"', source)

    def test_worker_status_is_visible_and_never_claimed_finished_on_upload(self):
        source = self.template
        self.assertIn('job.status == \'queued\'', source)
        self.assertIn('job.status == \'running\'', source)
        self.assertIn('job.status == \'failed\'', source)
        self.assertIn('Proteção', source)
        self.assertIn('hpub-card-track', source)

    def test_navigation_opens_collapsed_areas_before_focus(self):
        self.assertIn("manualPanel.open = type === 'protected'", self.js)
        self.assertIn("publishing.open = true", self.js)
        self.assertIn('type="submit"', self.template)
        self.assertNotIn("sessionStorage", self.js)

    def test_dark_responsive_design(self):
        self.assertIn('.hpub-priority', self.css)
        self.assertIn('.hpub-flow', self.css)
        self.assertIn('.hpub-publish-disclosure', self.css)
        self.assertIn('@media(max-width:430px)', self.css)


if __name__ == "__main__":
    unittest.main()
