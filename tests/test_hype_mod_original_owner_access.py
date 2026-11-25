"""Acesso do proprietario ao JAR original: deve falhar fechado."""
import unittest
from pathlib import Path

from modules.hype_mod_staging import original_owner_authorized


class HypeOriginalOwnerAccessTests(unittest.TestCase):
    def test_owner_email_autenticado(self):
        env = {"HYPE_MOD_ORIGINAL_OWNER_EMAIL": "owner@example.com"}
        self.assertTrue(original_owner_authorized("OWNER@example.com", env))
        self.assertFalse(original_owner_authorized("admin2@example.com", env))
        self.assertFalse(original_owner_authorized("owner@example.com.evil", env))
        self.assertFalse(original_owner_authorized("á@example.com", env))
        self.assertFalse(original_owner_authorized(12345, env))

    def test_sem_configuracao_nunca_libera(self):
        self.assertFalse(original_owner_authorized("owner@example.com", {}))
        self.assertFalse(original_owner_authorized(None, {}))
        self.assertFalse(original_owner_authorized("", {"HYPE_MOD_ORIGINAL_OWNER_EMAIL": "owner@example.com"}))

    def test_download_confere_sessao_e_permissao_no_servidor(self):
        src = (Path(__file__).resolve().parents[1] / "modules" / "hype_mod_staging.py").read_text(encoding="utf-8")
        route = src.split("def mod_release_original_test_download(draft_id):",1)[1].split('@bp.get("/admin/modulos/releases")',1)[0]
        self.assertIn("admin_only()",route)
        self.assertIn('original_owner_authorized(session.get("usuario_email"))',route)
        self.assertIn("abort(403)",route)
        self.assertIn("read_original_for_admin_test(db, draft_id)",route)
        self.assertIn('Cache-Control"] = "private, no-store, max-age=0"',route)
        self.assertNotIn("get('usuario_email', request",route)


if __name__ == "__main__":
    unittest.main()
