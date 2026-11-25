"""Regression tests for the owner-only unified HYPE mod file library."""
import unittest
from pathlib import Path
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "templates" / "admin_hype_mod_releases.html"
CSS = ROOT / "static" / "hype_publish_center.css"
JS = ROOT / "static" / "hype_publish_center.js"


class UnifiedModLibraryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")

    def test_valid_template_and_mod_groups(self):
        Environment().parse(self.html)
        self.assertIn("Biblioteca de <em>Mods</em>", self.html)
        self.assertIn("drafts|groupby('module_id')", self.html)
        self.assertIn('data-hpub-mod-group', self.html)
        self.assertIn('data-hpub-file-card="{{ item.id }}"', self.html)
        self.assertIn("{{ item.version }}", self.html)
        self.assertIn("item.original_filename", self.html)

    def test_one_jar_upload_and_no_protected_picker(self):
        self.assertEqual(self.html.count("mod_release_upload')"), 1)
        self.assertEqual(self.html.count('name="jar"'), 1)
        self.assertIn('id="hpub-unified-upload-form"', self.html)
        self.assertIn('id="hpub-quick-file"', self.html)
        self.assertIn('accept=".jar,application/java-archive"', self.html)
        for absent in ('data-hpub-mode="original"', 'data-hpub-mode="protected"',
                       'hpub-quick-protected', 'hpub-quick-target',
                       'mod_release_protected_upload', 'Vincular protegido',
                       'Enviar JAR original'):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, self.html)

    def test_private_download_is_a_separate_action_from_distribution(self):
        self.assertIn("mod_release_library_download", self.html)
        self.assertIn("Baixar para teste", self.html)
        self.assertIn("mod_release_publish_owner_pilot", self.html)
        self.assertIn("mod_release_publish_private", self.html)
        self.assertIn("mod_release_publish", self.html)
        self.assertIn('name="confirm_pilot"', self.html)
        self.assertIn('name="confirm_release"', self.html)
        self.assertIn('name="manifest"', self.html)
        self.assertIn('name="csrf_token"', self.html)

    def test_upload_is_not_automatic_protection_or_publication(self):
        self.assertIn("Arquivos ficam em armazenamento privado", self.html)
        self.assertIn("sem processamento ou publicação automática", self.html)
        self.assertIn("hpub-publishing-tools", self.html)

    def test_search_filters_group_and_file(self):
        for token in ('[data-hpub-mod-group]', '[data-hpub-file-card]',
                      "group.hidden = !hasVisibleFile", 'filterLibrary()',
                      "fileInput?.addEventListener('change'"):
            self.assertIn(token, self.js)
        self.assertIn(".hpub-mod-group[hidden],.hpub-file-card[hidden]", self.css)
        self.assertIn(".hpub-mod-files", self.css)

    def test_size_and_file_validation(self):
        self.assertIn("file.size > limit", self.js)
        self.assertIn("file.name.toLowerCase().endsWith('.jar')", self.js)
        self.assertIn("event.preventDefault()", self.js)
        self.assertIn('id="hpub-upload-progress"', self.html)
        self.assertNotIn("sessionStorage", self.js)

    def test_responsive_controls_and_accessibility(self):
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('role="search"', self.html)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("@media(max-width:480px)", self.css)
        self.assertIn(":focus-visible", self.css)

    def test_signature_gate_and_private_storage_remain_server_side(self):
        staging = (ROOT / "modules" / "hype_mod_staging.py").read_text(encoding="utf-8")
        self.assertIn("admin_only()", staging)
        self.assertIn("assert_private_bucket(db.storage)", staging)
        self.assertIn("def mod_release_library_download(draft_id):", staging)
        self.assertIn('response.headers["Cache-Control"] = "private, no-store, max-age=0"', staging)
        self.assertIn('request.form.get("solicitar_protecao") == "yes"', staging)
        self.assertIn("Ed25519", self.html)
        self.assertNotIn("service_role", self.html)


if __name__ == "__main__":
    unittest.main()
