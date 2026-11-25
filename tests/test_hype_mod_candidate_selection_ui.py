"""The owner sends one JAR; no original/protected pairing remains in the UI."""
import unittest
from pathlib import Path
from jinja2 import Environment

PAGE = Path(__file__).resolve().parents[1] / "templates" / "admin_hype_mod_releases.html"

class OneJarSelectionTests(unittest.TestCase):
    def test_single_fabric_jar_input_and_grouping(self):
        html = PAGE.read_text(encoding="utf-8")
        Environment().parse(html)
        self.assertIn('id="hpub-unified-upload-form"', html)
        self.assertEqual(html.count('name="jar"'), 1)
        self.assertIn("drafts|groupby('module_id')", html)
        self.assertIn("mod_release_library_download", html)
        self.assertNotIn("mod_release_protected_upload", html)
        self.assertNotIn("hpub-quick-target", html)

if __name__ == "__main__":
    unittest.main()
