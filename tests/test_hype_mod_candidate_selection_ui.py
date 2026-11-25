"""The publication page must let admins select the correct archived original."""
from pathlib import Path
import unittest

from jinja2 import Environment


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "admin_hype_mod_releases.html"


class CandidateSelectionTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")

    def test_jinja_template_parses(self):
        Environment().parse(self.source)

    def test_archived_original_can_be_selected_for_protected_upload(self):
        self.assertIn('id="hpub-quick-target"', self.source)
        self.assertIn('name="draft_id" required', self.source)
        self.assertIn("item.status in ('aguardando_protecao','em_teste')", self.source)
        self.assertIn('value="em_teste">Marcar como em teste (não instala)', self.source)

    def test_candidate_upload_keeps_explicit_association(self):
        self.assertIn('id="hpub-quick-target"', self.source)
        self.assertIn('id="hpub-quick-protected"', self.source)
        self.assertIn("and not (item.meta or {}).get('protected')", self.source)
        self.assertIn("url_for('hype_mod_admin.mod_release_protected_upload')", self.source)

    def test_unnecessary_candidate_reuse_form_is_removed(self):
        self.assertNotIn('id="hpub-reuse-protected"', self.source)
        self.assertNotIn('id="existing_original"', self.source)
        self.assertNotIn('id="existing_candidate"', self.source)
        javascript = (TEMPLATE.parents[1] / "static" / "hype_publish_center.js").read_text(encoding="utf-8")
        self.assertNotIn("existingCandidate", javascript)

    def test_review_never_defaults_to_approval(self):
        self.assertIn('value="" selected disabled>Selecione...', self.source)
        self.assertIn("item.status == 'em_teste' and candidate", self.source)
        self.assertIn("item.status == 'pronto_para_aprovacao'", self.source)
        self.assertIn('name="candidate_sha256"', self.source)

    def test_publish_remains_separate_action(self):
        self.assertIn('id="private_draft"', self.source)
        self.assertIn('data-hpub-client-action=', self.source)
        self.assertIn("url_for('hype_mod_admin.mod_release_publish')", self.source)
        self.assertIn("url_for('hype_mod_admin.mod_release_review')", self.source)


if __name__ == "__main__":
    unittest.main()
