"""One-save multi-JAR uploads and grouped mod files in the owner UI."""
import unittest
from pathlib import Path
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "templates" / "admin_hype_mod_releases.html"
CSS = ROOT / "static" / "hype_publish_center.css"
JS = ROOT / "static" / "hype_publish_center.js"

class MinimalModLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")

    def test_template_is_valid(self):
        Environment().parse(self.html)
        self.assertIn("Meus <em>Mods</em>", self.html)

    def test_exactly_one_upload_and_no_mode_selector(self):
        self.assertEqual(self.html.count('name="jar"'), 1)
        self.assertIn('id="hpub-unified-upload-form"', self.html)
        self.assertIn('id="hpub-quick-file"', self.html)
        self.assertIn("mod_release_upload", self.html)
        self.assertIn("multiple>", self.html)
        self.assertIn("hpub-batch-toolbar", self.html)
        self.assertIn("hpub-save-batch", self.html)
        self.assertIn("hpub-batch-select", self.html)
        self.assertIn('name="csrf_token"', self.html)
        for old in ("hpub-mode-picker", "hpub-quick-target", "hpub-quick-protected",
                    "mod_release_protected_upload", "mod_release_request_protection"):
            with self.subTest(old=old):
                self.assertNotIn(old, self.html)

    def test_files_organize_by_mod_and_download_privately(self):
        self.assertIn("drafts|groupby('module_id')", self.html)
        self.assertIn("item.original_filename", self.html)
        self.assertIn("item.version", self.html)
        self.assertIn("mod_release_library_download", self.html)
        self.assertIn("hpub-older-files", self.html)
        self.assertIn("mod_release_delete", self.html)
        self.assertIn("item.bootstrap_active", self.html)
        self.assertIn("item.bootstrap_duplicate", self.html)
        self.assertIn("Ativo no Bootstrap", self.html)
        self.assertIn("Apagar cópia repetida", self.html)
        self.assertIn("confirm_duplicate_retire", self.html)
        self.assertIn("confirm_live_retire", self.html)
        self.assertIn("delete_active", self.html)
        self.assertIn("Apagar e retirar do Bootstrap", self.html)

    def test_no_status_or_publication_wizard_visible(self):
        for old in ("status</", "hpub-publishing-tools",
                    "hpub-summary", "hpub-flow", "hpub-publishing-tools",
                    "manifest", "confirm_release", "owner_pilot_enabled",
                    "mod_release_publish", "JAR protegido", "hpub-stepper"):
            with self.subTest(old=old):
                self.assertNotIn(old, self.html)

    def test_js_checks_jars_and_uses_ajax_without_reloads(self):
        self.assertIn("maxBytes = 10 * 1024 * 1024", self.js)
        self.assertIn("file.size > maxBytes", self.js)
        self.assertIn("event.preventDefault()", self.js)
        self.assertIn("fetch(", self.js)
        self.assertIn("await refreshLibrary()", self.js)
        self.assertIn("X-HYPE-BATCH", self.js)
        self.assertIn("csrf_token", self.js)
        self.assertIn("confirm_duplicate_retire", self.js)
        self.assertIn("confirm_live_retire", self.js)
        self.assertIn("delete_active", self.js)
        self.assertIn("Send and publish replacements first", self.js)
        self.assertIn("window.confirm(", self.js)
        self.assertNotIn("sessionStorage", self.js)
        self.assertNotIn("window.location.reload(", self.js)
        self.assertNotIn("location.href =", self.js)

    def test_compact_mobile_design(self):
        self.assertIn("hpub-folder", self.css)
        self.assertIn("hpub-jar-entry", self.css)
        self.assertIn("max-width:560px", self.css)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("focus-visible", self.css)
        self.assertIn("hpub-js-enhanced", self.css)
        self.assertIn("hpub-batch-controls", self.css)
        self.assertIn("hpub-status-active", self.css)
        self.assertIn("hpub-status-copy", self.css)

    def test_download_is_owner_only_and_sha_checked(self):
        src = (ROOT / "modules" / "hype_mod_staging.py").read_text(encoding="utf-8")
        route = src.split("def mod_release_library_download(draft_id):")[1].split(
            '    @bp.get("/admin/modulos/releases/original-teste/', 1)[0]
        self.assertIn("admin_only()", route)
        self.assertIn("assert_private_bucket", route)
        self.assertIn("validate_binary(binary, expected_sha=sha)", route)
        self.assertIn("private, no-store", route)

if __name__ == "__main__":
    unittest.main()
