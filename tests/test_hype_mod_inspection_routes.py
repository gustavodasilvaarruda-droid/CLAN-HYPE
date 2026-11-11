"""Integration smoke checks: admin-only preview never touches storage or DB."""
import io
import json
import os
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from flask import Blueprint, Flask, session
from modules.hype_mod_staging import register_mod_release_routes


def jar_bytes():
    buf = io.BytesIO()
    with ZipFile(buf, "w") as z:
        z.writestr("fabric.mod.json", json.dumps({
            "id": "hype_pokedex", "version": "2.0.0",
            "depends": {"minecraft": "1.21.1"}
        }))
        z.writestr("br/hype/Entry.class", b"abcd")
    return buf.getvalue()


class TestInspectionRoutes(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"HYPE_MOD_STAGING_ENABLED": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)
        app = Flask(__name__)
        app.config.update(SECRET_KEY="test-only", TESTING=True)
        bp = Blueprint("hype_mod_admin", __name__)
        register_mod_release_routes(bp, lambda: bool(session.get("admin")), None)
        app.register_blueprint(bp)
        self.client = app.test_client()

    def test_anonymous_cannot_access_even_get(self):
        self.assertEqual(self.client.get("/admin/modulos/releases").status_code, 403)
        response = self.client.post(
            "/admin/modulos/releases/inspecionar",
            data={"jar": (io.BytesIO(jar_bytes()), "test.jar")}
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_inspection_without_database(self):
        with self.client.session_transaction() as sess:
            sess["usuario_email"] = "admin@example.test"
            sess["admin"] = True
        with patch("modules.hype_mod_staging.render_template", return_value="SAFE") as renderer:
            resp = self.client.get("/admin/modulos/releases")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(renderer.call_args.kwargs["staging_enabled"], False)
            resp = self.client.post(
                "/admin/modulos/releases/inspecionar",
                data={"jar": (io.BytesIO(jar_bytes()), "pokedex.jar")}
            )
            self.assertEqual(resp.status_code, 200)
            report = renderer.call_args.kwargs["report"]
            self.assertEqual(report["module_id"], "hype_pokedex")
            self.assertEqual(report["version"], "2.0.0")
            self.assertIsNone(renderer.call_args.kwargs.get("storage_path"))
        self.assertEqual(self.client.post("/admin/modulos/releases/upload").status_code, 404)


if __name__ == "__main__":
    unittest.main()
