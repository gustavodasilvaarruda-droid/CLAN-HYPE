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

    def test_select_archived_original_before_upload(self):
        self.assertIn('id="original_to_test"', self.source)
        self.assertIn('name="status" value="em_teste"', self.source)
        self.assertIn('name="draft_id" required', self.source)
        self.assertIn("drafts|selectattr('status', 'equalto', 'aguardando_protecao')", self.source)

    def test_candidate_upload_is_explicitly_linked_to_testing_original(self):
        self.assertIn('id="protected_target"', self.source)
        self.assertIn('id="protected_jar"', self.source)
        self.assertIn("drafts|selectattr('status', 'equalto', 'em_teste')", self.source)
        self.assertIn("if not (item.meta or {}).get('protected')", self.source)
        self.assertIn("url_for('hype_mod_admin.mod_release_protected_upload')", self.source)


    def test_stored_candidate_can_be_reused_safely(self):
        self.assertIn('id="existing_original"', self.source)
        self.assertIn('id="existing_candidate"', self.source)
        self.assertIn('name="source_id" required', self.source)
        self.assertIn("url_for('hype_mod_admin.mod_release_link_existing')", self.source)
        self.assertIn('opt.dataset.sha !== src.dataset.sha', self.source)

    def test_review_never_defaults_to_invalid_or_approval_action(self):
        self.assertIn('value="" selected disabled>Selecione uma decisão', self.source)
        self.assertIn("elif item.status == 'pronto_para_aprovacao'", self.source)
        self.assertIn("elif item.status == 'em_teste' and candidate", self.source)
        self.assertIn('Aguardando candidato', self.source)

    def test_publish_remains_separate_action(self):
        self.assertIn('id="draft_publish"', self.source)
        self.assertIn("url_for('hype_mod_admin.mod_release_publish')", self.source)
        self.assertIn("url_for('hype_mod_admin.mod_release_review')", self.source)


if __name__ == "__main__":
    unittest.main()
