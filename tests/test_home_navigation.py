"""Regressões da navegação da home HYPE em desktop e mobile.

Testes estáticos: não dependem de banco de dados nem das credenciais do Render.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HomeNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        cls.styles = (ROOT / "static" / "home_navigation_fix.css").read_text(encoding="utf-8")
        cls.service_worker = (ROOT / "static" / "service-worker.js").read_text(encoding="utf-8")

    def test_welcome_is_inline_not_fullscreen_overlay(self):
        self.assertIn('class="hype-home-welcome"', self.home)
        self.assertIn('id="guestOnboarding" hidden', self.home)
        self.assertNotIn('onboarding-overlay guest-onboarding', self.home)
        self.assertIn('.hype-home-welcome[hidden]', self.styles)

    def test_guest_private_links_explain_login(self):
        for route in ("painel", "breed", "painel_reino"):
            with self.subTest(route=route):
                self.assertIn("href=\"{{url_for('%s')}}" % route, self.home)
        self.assertIn("data-hype-auth", self.home)
        self.assertIn("openRequiredArea(link.dataset.hypeAuth", self.home)
        self.assertIn("abrirModal('login')", self.home)

    def test_pwa_does_not_silently_return_home_for_other_routes(self):
        self.assertNotIn("caches.match('/')", self.service_worker)
        self.assertIn("event.request.mode === 'navigate'", self.service_worker)
        self.assertIn("status: 503", self.service_worker)


if __name__ == "__main__":
    unittest.main()
