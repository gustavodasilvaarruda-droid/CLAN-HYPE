"""Regression tests for release draft IDs used in the live database."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from flask import Blueprint, Flask

from modules.hype_mod_staging import parse_draft_id, register_mod_release_routes


class DraftQuery:
    def __init__(self, db):
        self.db = db
        self.filters = []
        self.changes = None

    def select(self, *_fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, _count):
        return self

    def update(self, changes):
        self.changes = changes
        return self

    def execute(self):
        row = self.db.draft
        if any(row.get(field) != value for field, value in self.filters):
            return SimpleNamespace(data=[])
        if self.changes is not None:
            row.update(self.changes)
        return SimpleNamespace(data=[row.copy()])


class FakeDatabase:
    def __init__(self, draft_id):
        self.draft = {
            "id": draft_id, "module_id": "hypeclient",
            "status": "aguardando_protecao",
        }

    def table(self, table_name):
        assert table_name == "hype_mod_release_drafts"
        return DraftQuery(self)


class DraftUuidReviewTests(unittest.TestCase):
    def setUp(self):
        flag = patch.dict(os.environ, {
            "HYPE_MOD_STAGING_ENABLED": "1",
            "HYPE_MOD_PUBLISH_ENABLED": "0",
        })
        flag.start()
        self.addCleanup(flag.stop)
        self.draft_id = str(uuid4())
        self.db = FakeDatabase(self.draft_id)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        bp = Blueprint("hype_mod_admin", __name__)

        @bp.get("/admin/modulos")
        def painel():
            return "ok"

        register_mod_release_routes(bp, lambda: True, None, self.db)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()
        with self.client.session_transaction() as user_session:
            user_session["usuario_email"] = "admin@example.com"

    def review(self, status, tested=None, draft_id=None):
        data = {"draft_id": draft_id or self.draft_id, "status": status}
        if tested is not None:
            data["tested"] = tested
        return self.client.post("/admin/modulos/releases/revisar", data=data)

    def test_move_to_testing_does_not_require_checkbox(self):
        response = self.review("em_teste")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.draft["status"], "em_teste")

    def test_approval_requires_game_test_confirmation(self):
        self.db.draft["status"] = "em_teste"
        self.review("pronto_para_aprovacao")
        self.assertEqual(self.db.draft["status"], "em_teste")
        self.review("pronto_para_aprovacao", tested="yes")
        self.assertEqual(self.db.draft["status"], "pronto_para_aprovacao")

    def test_invalid_uuid_never_changes_status(self):
        response = self.review("em_teste", draft_id="not-a-valid-id")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.draft["status"], "aguardando_protecao")

    def test_legacy_bigint_ids_remain_supported(self):
        self.assertEqual(parse_draft_id("42"), 42)
        self.assertEqual(parse_draft_id(self.draft_id), self.draft_id)


if __name__ == "__main__":
    unittest.main()
