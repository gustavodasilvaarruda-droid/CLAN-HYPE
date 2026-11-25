"""The library accepts independent Fabric JARs and groups them by mod ID."""
from pathlib import Path
import unittest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_hype_mod_releases.html"


class UnifiedModUploadTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")

    def test_jinja_template_parses(self):
        Environment().parse(self.source)

    def test_only_one_upload_field(self):
        self.assertEqual(self.source.count('name="jar"'), 1)
        self.assertIn('id="hpub-unified-upload-form"', self.source)
        self.assertIn("url_for('hype_mod_admin.mod_release_upload')", self.source)
        self.assertNotIn("mod_release_protected_upload", self.source)
        self.assertNotIn("hpub-quick-target", self.source)

    def test_every_file_is_automatically_grouped_by_fabric_id(self):
        self.assertIn("drafts|groupby('module_id')", self.source)
        self.assertIn('data-hpub-mod-group', self.source)
        self.assertIn('data-hpub-file-card="{{ item.id }}"', self.source)
        self.assertIn("mod_release_library_download", self.source)
        self.assertIn("item.original_filename", self.source)

    def test_publishing_is_separate_and_signed(self):
        self.assertIn('id="hpub-publishing-tools"', self.source)
        self.assertIn("mod_release_publish_private", self.source)
        self.assertIn("mod_release_publish", self.source)
        self.assertIn("name=\"manifest\"", self.source)
        self.assertIn("name=\"confirm_release\"", self.source)

if __name__ == "__main__":
    unittest.main()
