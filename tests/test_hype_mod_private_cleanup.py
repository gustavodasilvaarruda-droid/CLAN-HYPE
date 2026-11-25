"""Admin-only cleanup of unused private Fabric JAR drafts."""
import os
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from flask import Blueprint, Flask

from modules.hype_mod_staging import register_mod_release_routes


class Storage:
    def __init__(self):
        self.public = False
        self.removed = []

    def get_bucket(self, name):
        assert name == "hype-mod-originals"
        return {"public": self.public}

    def from_(self, name):
        assert name == "hype-mod-originals"
        return self

    def remove(self, paths):
        self.removed.extend(paths)
        return paths


class Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.is_delete = False

    def select(self, *_fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, _count):
        return self

    def delete(self):
        self.is_delete = True
        return self

    def execute(self):
        if self.table == "hype_mod_release_drafts":
            source = self.db.drafts
        elif self.table == "hype_mod_published_releases":
            source = self.db.published
        elif self.table == "hype_mod_restricted_releases":
            source = self.db.restricted
        elif self.table == "hype_mod_protection_jobs":
            source = self.db.jobs
        else:
            raise AssertionError(self.table)
        rows = [r for r in source if all(r.get(key) == value for key, value in self.filters)]
        if self.is_delete:
            for row in rows:
                source.remove(row)
        return SimpleNamespace(data=[row.copy() for row in rows])


class Database:
    def __init__(self):
        self.drafts = []
        self.published = []
        self.restricted = []
        self.jobs = []
        self.storage = Storage()

    def table(self, name):
        return Query(self, name)


class PrivateCleanupTests(unittest.TestCase):
    def setUp(self):
        flag = patch.dict(os.environ, {"HYPE_MOD_STAGING_ENABLED": "1",
                                        "HYPE_MOD_PUBLISH_ENABLED": "0"})
        flag.start()
        self.addCleanup(flag.stop)
        self.db = Database()
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        bp = Blueprint("hype_mod_admin", __name__)

        @bp.get("/admin/modulos")
        def painel():
            return "ok"

        register_mod_release_routes(bp, lambda: True, None, self.db)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()
        self.draft_id = str(uuid4())
        self.sha = "a" * 64
        self.original = f"hypeclient/{uuid4().hex}/{self.sha}.jar"
        self.db.drafts.append({
            "id": self.draft_id, "module_id": "hypeclient",
            "version": "TEST-1", "status": "aguardando_protecao",
            "sha256": self.sha, "storage_path": self.original, "meta": {},
        })

    def login(self):
        with self.client.session_transaction() as sess:
            sess["usuario_email"] = "admin@example.com"

    def delete(self, draft_id=None, confirmed=True):
        return self.client.post("/admin/modulos/releases/excluir", data={
            "draft_id": draft_id or self.draft_id,
            "confirm_delete": "yes" if confirmed else "no",
        })

    def test_admin_authentication_required(self):
        self.assertEqual(self.delete().status_code, 403)
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_pending_draft_deleted_without_touching_other_objects(self):
        self.login()
        second = dict(self.db.drafts[0], id=str(uuid4()),
                      storage_path=f"hypeclient/{uuid4().hex}/{self.sha}.jar")
        self.db.drafts.append(second)
        self.assertEqual(self.delete().status_code, 302)
        self.assertEqual(self.db.drafts, [second])
        self.assertEqual(self.db.storage.removed, [self.original])

    def test_rejected_draft_deletes_its_protected_candidate_too(self):
        self.login()
        self.db.drafts[0]["status"] = "rejeitado"
        sha = "b" * 64
        protected = f"hypeclient/{self.draft_id}/protected/{uuid4().hex}/{sha}.jar"
        self.db.drafts[0]["meta"] = {"protected": {
            "sha256": sha, "storage_path": protected,
        }}
        self.assertEqual(self.delete().status_code, 302)
        self.assertEqual(self.db.storage.removed, [self.original, protected])

    def test_testing_and_approved_builds_are_not_deleted(self):
        self.login()
        for status in ("em_teste", "pronto_para_aprovacao"):
            with self.subTest(status=status):
                self.db.drafts[0]["status"] = status
                self.assertEqual(self.delete().status_code, 302)
                self.assertEqual(len(self.db.drafts), 1)
                self.assertEqual(self.db.storage.removed, [])

    def test_published_reference_blocks_even_rejected_draft(self):
        self.login()
        self.db.drafts[0]["status"] = "rejeitado"
        self.db.published.append({"release": 2, "draft_id": self.draft_id,
                                  "storage_path": "other/path.jar", "status": "disabled"})
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_owner_pilot_original_must_not_be_deleted(self):
        self.login()
        self.db.drafts[0]["meta"] = {"owner_pilot": {"release": 1}}
        self.db.jobs.append({"id": "job-test", "draft_id": self.draft_id,
                             "status": "queued"})
        self.assertEqual(self.delete().status_code, 302)
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(len(self.db.jobs), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_rejected_owner_pilot_can_be_withdrawn_and_deleted(self):
        self.login()
        self.db.drafts[0]["status"] = "rejeitado"
        self.db.drafts[0]["meta"] = {
            "owner_pilot": {"release": 1, "published_by": "admin@example.com"}
        }
        self.db.jobs.append({"id": "job-stale", "draft_id": self.draft_id, "status": "queued"})
        response = self.client.post("/admin/modulos/releases/excluir", data={
            "draft_id": self.draft_id,
            "confirm_delete": "yes",
            "confirm_owner_pilot_retire": "yes",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.drafts, [])
        self.assertEqual(self.db.jobs, [])
        self.assertEqual(self.db.storage.removed, [self.original])

    def test_owner_pilot_requires_explicit_retirement_and_same_publisher(self):
        self.login()
        self.db.drafts[0]["status"] = "rejeitado"
        self.db.drafts[0]["meta"] = {
            "owner_pilot": {"release": 1, "published_by": "other@example.com"}
        }
        self.client.post("/admin/modulos/releases/excluir", data={
            "draft_id": self.draft_id,
            "confirm_delete": "yes",
            "confirm_owner_pilot_retire": "yes",
        })
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])
        self.db.drafts[0]["meta"]["owner_pilot"]["published_by"] = "admin@example.com"
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_owner_pilot_referenced_or_running_remains_immutable(self):
        self.login()
        self.db.drafts[0]["status"] = "rejeitado"
        self.db.drafts[0]["meta"] = {
            "owner_pilot": {"release": 1, "published_by": "admin@example.com"}
        }
        payload = {
            "draft_id": self.draft_id, "confirm_delete": "yes",
            "confirm_owner_pilot_retire": "yes",
        }
        self.db.restricted.append({
            "release": 1, "draft_id": self.draft_id,
            "storage_path": self.original, "status": "disabled",
        })
        self.client.post("/admin/modulos/releases/excluir", data=payload)
        self.assertEqual(len(self.db.drafts), 1)
        self.db.restricted.clear()
        self.db.jobs.append({
            "id": "job-running", "draft_id": self.draft_id, "status": "running",
        })
        self.client.post("/admin/modulos/releases/excluir", data=payload)
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_restricted_catalog_preserved_even_when_disabled(self):
        self.login()
        for match in ("draft", "storage"):
            with self.subTest(match=match):
                self.db.drafts[0]["status"] = "rejeitado"
                self.db.restricted[:] = [{
                    "release": 1,
                    "draft_id": self.draft_id if match == "draft" else str(uuid4()),
                    "storage_path": "another/path.jar" if match == "draft" else self.original,
                    "status": "disabled",
                }]
                self.assertEqual(self.delete().status_code, 302)
                self.assertEqual(len(self.db.drafts), 1)
                self.assertEqual(self.db.storage.removed, [])
        self.db.restricted.clear()

    def test_idle_linked_jobs_can_be_deleted_with_pending_draft(self):
        self.login()
        for status in ("queued", "failed", "completed"):
            with self.subTest(status=status):
                self.db.storage.removed.clear()
                self.db.drafts[:] = [{
                    "id": self.draft_id, "module_id": "hypeclient",
                    "version": "TEST-1", "status": "aguardando_protecao",
                    "sha256": self.sha, "storage_path": self.original, "meta": {},
                }]
                self.db.jobs[:] = [{"id": "job-test", "draft_id": self.draft_id,
                                    "status": status}]
                self.assertEqual(self.delete().status_code, 302)
                self.assertEqual(self.db.drafts, [])
                self.assertEqual(self.db.jobs, [])
                self.assertEqual(self.db.storage.removed, [self.original])

    def test_running_job_blocks_deletion(self):
        self.login()
        self.db.jobs[:] = [{"id": "job-test", "draft_id": self.draft_id,
                            "status": "running"}]
        self.assertEqual(self.delete().status_code, 302)
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(len(self.db.jobs), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_rejected_with_failed_job_can_be_deleted(self):
        self.login()
        self.db.drafts[0]["status"] = "rejeitado"
        self.db.jobs[:] = [{"id": "job-test", "draft_id": self.draft_id,
                            "status": "failed"}]
        self.assertEqual(self.delete().status_code, 302)
        self.assertEqual(self.db.drafts, [])
        self.assertEqual(self.db.jobs, [])
        self.assertEqual(self.db.storage.removed, [self.original])

    def test_published_reference_prevents_job_cancellation(self):
        self.login()
        self.db.jobs[:] = [{"id": "job-test", "draft_id": self.draft_id,
                            "status": "queued"}]
        self.db.published.append({"release": 2, "draft_id": self.draft_id,
                                  "storage_path": "old.jar", "status": "disabled"})
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(len(self.db.jobs), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_published_storage_path_blocks_cleanup(self):
        self.login()
        self.db.published.append({"release": 2, "draft_id": "other",
                                  "storage_path": self.original, "status": "disabled"})
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_public_bucket_or_unsafe_paths_are_rejected(self):
        self.login()
        self.db.storage.public = True
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.db.storage.public = False
        self.db.drafts[0]["storage_path"] = "../escape.jar"
        self.delete()
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])

    def test_upload_timestamp_shown_in_brasilia_time(self):
        fmt = self.app.jinja_env.filters["hype_br_datetime"]
        self.assertEqual(fmt("2026-11-22T10:45:00+00:00"), "22/11/2026 às 07:45")
        self.assertEqual(fmt("2026-11-22T10:45:00Z"), "22/11/2026 às 07:45")
        self.assertEqual(fmt(None), "Data não disponível")
        self.assertEqual(fmt("inválido"), "Data não disponível")

    def test_release_catalog_uses_uuid_fk_for_private_drafts(self):
        # Production draft IDs are UUID; mismatched bigint migration prevented
        # creation of this catalog and blocked all otherwise safe deletions.
        schema = (Path(__file__).resolve().parents[1] / "sql" /
                  "20261121_hype_mod_published_releases.sql").read_text(encoding="utf-8")
        self.assertIn("draft_id uuid not null unique references public.hype_mod_release_drafts(id)", schema)
        self.assertIn("on delete restrict", schema)
        self.assertIn("enable row level security", schema)
        self.assertIn("revoke all on public.hype_mod_published_releases from anon, authenticated", schema)

    def test_requires_explicit_confirmation_and_valid_id(self):
        self.login()
        self.delete(confirmed=False)
        self.delete(draft_id="../foo")
        self.assertEqual(len(self.db.drafts), 1)
        self.assertEqual(self.db.storage.removed, [])


if __name__ == "__main__":
    unittest.main()
