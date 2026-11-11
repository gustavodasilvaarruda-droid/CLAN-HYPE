"""Regression tests for safe, admin-only JAR inspection without staging keys."""
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from modules.hype_mod_staging import register_mod_release_routes


def sample_jar():
    stream = io.BytesIO()
    with ZipFile(stream, "w") as jar:
        jar.writestr("fabric.mod.json", json.dumps({
            "id": "hype_pokedex", "version": "2.0-beta",
            "depends": {"minecraft": "1.21.1", "hypeclient": "*"},
        }))
        jar.writestr("hype/Mod.class", b"test-only")
    return stream.getvalue()


class TestSafeInspector(unittest.TestCase):
    def setUp(self):
        self.flag = patch.dict(os.environ, {"HYPE_MOD_STAGING_ENABLED": "0"})
        self.flag.start()
        self.addCleanup(self.flag.stop)
        root = Path(__file__).resolve().parents[1]
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="test")
        app.jinja_loader = ChoiceLoader([
            DictLoader({"hype_app_base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(str(root / "templates")),
        ])
        app.jinja_env.globals["csrf_token"] = lambda: "test-token"
        bp = Blueprint("hype_mod_admin", __name__)

        @bp.get("/admin/modulos")
        def painel():
            return "ok"

        register_mod_release_routes(bp, lambda: True, None)
        app.register_blueprint(bp)
        self.client = app.test_client()

    def login(self):
        with self.client.session_transaction() as session:
            session["usuario_email"] = "admin@example.com"

    def test_requires_admin_session(self):
        self.assertEqual(self.client.get("/admin/modulos/releases").status_code, 403)
        self.assertEqual(
            self.client.post("/admin/modulos/releases/analisar").status_code, 403
        )

    def test_get_available_with_staging_disabled(self):
        self.login()
        response = self.client.get("/admin/modulos/releases")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Analisar arquivo", html)
        self.assertNotIn("Guardar original em privado", html)
        self.assertEqual(
            self.client.post("/admin/modulos/releases/upload").status_code, 404
        )

    def test_inspection_is_in_memory_only(self):
        self.login()
        response = self.client.post(
            "/admin/modulos/releases/analisar",
            data={"jar": (io.BytesIO(sample_jar()), "hype_pokedex.jar")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("hype_pokedex", html)
        self.assertIn("2.0-beta", html)
        self.assertIn("Depende do HYPE Client", html)
        self.assertNotIn("Guardar original em privado", html)

    def test_invalid_jar_shows_error(self):
        self.login()
        response = self.client.post(
            "/admin/modulos/releases/analisar",
            data={"jar": (io.BytesIO(b"bad"), "bad.jar")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("JAR Fabric inválido", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
