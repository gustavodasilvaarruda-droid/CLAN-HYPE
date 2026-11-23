"""Testes offline: fila privada e worker nao publicam releases."""
import hashlib
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules.hype_mod_protection_queue import JOBS, jobs_for_drafts, queue_protection, queue_after_upload
from modules.hype_mod_staging import BUCKET, TABLE, InvalidJar
from services.hype_mod_protection_worker import (
    ProtectionError, _load_draft, _protector_argv, _run_protector,
)

SHA = "a" * 64
BASE_PATH = f"hype_pokedex/{'b'*32}/{SHA}.jar"


class FakeStorage:
    def __init__(self):
        self.public = False

    def get_bucket(self, bucket):
        assert bucket == BUCKET
        return {"public": self.public}


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.method = "read"
        self.payload = None

    def select(self, *_args):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self.method = "insert"
        self.payload = dict(payload)
        return self

    def update(self, payload):
        self.method = "update"
        self.payload = dict(payload)
        return self

    def execute(self):
        rows = self.db.rows[self.table]
        matching = [row for row in rows if all(row.get(k) == v for k, v in self.filters)]
        if self.method == "insert":
            new = dict(self.payload)
            new["id"] = "job-1"
            rows.append(new)
            return SimpleNamespace(data=[new])
        if self.method == "update":
            for row in matching:
                row.update(self.payload)
            return SimpleNamespace(data=matching)
        return SimpleNamespace(data=matching)


class FakeDB:
    def __init__(self):
        self.storage = FakeStorage()
        self.rows = {
            TABLE: [{
                "id": 21, "module_id": "hype_pokedex", "version": "2.0",
                "status": "aguardando_protecao", "sha256": SHA,
                "storage_path": BASE_PATH, "meta": {},
            }],
            JOBS: [],
        }

    def table(self, name):
        return FakeQuery(self, name)


class ProtectionQueueTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()

    def test_usa_original_ja_guardado_sem_publicar(self):
        job_id = queue_protection(self.db, "21", "admin@example.com")
        self.assertEqual(job_id, "job-1")
        record = self.db.rows[JOBS][0]
        self.assertEqual(record["status"], "queued")
        self.assertEqual(record["original_sha256"], SHA)
        self.assertEqual(record["draft_id"], "21")
        self.assertEqual(self.db.rows[TABLE][0]["status"], "aguardando_protecao")
        self.assertNotIn("protected", self.db.rows[TABLE][0]["meta"])

    def test_nao_enfileira_duplicado(self):
        queue_protection(self.db, "21", "admin@example.com")
        with self.assertRaises(InvalidJar):
            queue_protection(self.db, "21", "admin@example.com")

    def test_pode_repetir_apos_falha(self):
        queue_protection(self.db, "21", "admin@example.com")
        self.db.rows[JOBS][0]["status"] = "failed"
        self.assertEqual(queue_protection(self.db, "21", "admin@example.com"), "job-1")
        self.assertEqual(self.db.rows[JOBS][0]["status"], "queued")

    def test_aceita_original_em_teste_sem_candidato(self):
        self.db.rows[TABLE][0]["status"] = "em_teste"
        job = queue_protection(self.db, "21", "admin@example.com")
        self.assertEqual(job, "job-1")
        self.assertEqual(self.db.rows[TABLE][0]["status"], "em_teste")
        self.assertEqual(_load_draft(self.db, {
            "job_draft_id": "21", "job_sha256": SHA,
        })["status"], "em_teste")

    def test_nao_aceita_candidato_ja_registrado(self):
        self.db.rows[TABLE][0]["status"] = "em_teste"
        self.db.rows[TABLE][0]["meta"] = {"protected": {"sha256": "b" * 64}}
        with self.assertRaises(InvalidJar):
            queue_protection(self.db, "21", "admin@example.com")

    def test_nao_aceita_versao_aprovada(self):
        self.db.rows[TABLE][0]["status"] = "pronto_para_aprovacao"
        with self.assertRaises(InvalidJar):
            queue_protection(self.db, "21", "admin@example.com")

    def test_rejeita_bucket_publico(self):
        self.db.storage.public = True
        with self.assertRaises(RuntimeError):
            queue_protection(self.db, "21", "admin@example.com")
        self.assertEqual(self.db.rows[JOBS], [])

    def test_rejeita_caminho_fora_do_bucket_esperado(self):
        self.db.rows[TABLE][0]["storage_path"] = "../segredos.jar"
        with self.assertRaises(InvalidJar):
            queue_protection(self.db, "21", "admin@example.com")

    def test_status_e_vinculado_ao_id_do_rascunho(self):
        queue_protection(self.db, "21", "admin@example.com")
        self.assertEqual(jobs_for_drafts(self.db)["21"]["status"], "queued")

    def test_worker_confere_exatamente_o_path(self):
        job = {"job_draft_id": "21", "job_sha256": SHA}
        draft = _load_draft(self.db, job)
        self.assertEqual(draft["storage_path"], BASE_PATH)
        self.db.rows[TABLE][0]["storage_path"] = "hype_pokedex/extra/../segredo.jar"
        with self.assertRaises(ProtectionError):
            _load_draft(self.db, job)


class AutoQueueAfterUploadTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()

    def test_auto_upload_enfileira_original_sem_publicar(self):
        job_id = queue_after_upload(self.db, {"id": 21}, "admin@example.com", enabled=True)
        self.assertEqual(job_id, "job-1")
        self.assertEqual(self.db.rows[JOBS][0]["status"], "queued")
        self.assertEqual(self.db.rows[TABLE][0]["status"], "aguardando_protecao")
        self.assertNotIn("protected", self.db.rows[TABLE][0]["meta"])

    def test_modo_desativado_nao_enfileira(self):
        self.assertIsNone(queue_after_upload(self.db, {"id": 21}, "admin@example.com"))
        self.assertEqual(self.db.rows[JOBS], [])

    def test_falha_de_identificador_nao_cria_job(self):
        with self.assertRaises(RuntimeError):
            queue_after_upload(self.db, {}, "admin@example.com", enabled=True)
        self.assertEqual(self.db.rows[JOBS], [])

    def test_mesmo_arquivo_nao_gera_job_duplicado(self):
        queue_after_upload(self.db, {"id": 21}, "admin@example.com", enabled=True)
        with self.assertRaises(InvalidJar):
            queue_after_upload(self.db, {"id": 21}, "admin@example.com", enabled=True)
        self.assertEqual(len(self.db.rows[JOBS]), 1)

    def test_bucket_publico_impede_enfileiramento(self):
        self.db.storage.public = True
        with self.assertRaises(RuntimeError):
            queue_after_upload(self.db, {"id": 21}, "admin@example.com", enabled=True)
        self.assertEqual(self.db.rows[JOBS], [])


class WorkerConfigurationTests(unittest.TestCase):
    def test_worker_exige_configuracao_explicita(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProtectionError):
                _protector_argv()

    def test_worker_rejeita_comando_shell_ou_sem_placeholders(self):
        with patch.dict(os.environ, {
            "HYPE_MOD_PROTECTOR_ARGV_JSON": '["sh", "-c", "echo"]'
        }):
            with self.assertRaises(ProtectionError):
                _protector_argv()

    def test_worker_nao_aceita_saida_inexistente(self):
        with patch("services.hype_mod_protection_worker.subprocess.run") as run:
            with self.assertRaises(ProtectionError):
                _run_protector(b"arquivo de teste", ["/bin/true", "{input}", "{output}"])
            run.assert_called_once()
            self.assertFalse(run.call_args.kwargs["shell"])
            self.assertNotIn("HYPE_WORKER_SUPABASE_SERVICE_KEY", run.call_args.kwargs["env"])


class ReleaseSafetySourceTests(unittest.TestCase):
    def test_fila_nao_assina_nem_publica(self):
        base = Path(__file__).resolve().parents[1]
        worker = (base / "services" / "hype_mod_protection_worker.py").read_text()
        staging = (base / "modules" / "hype_mod_staging.py").read_text()
        sql = (base / "sql" / "20261123_hype_mod_protection_queue.sql").read_text()
        self.assertIn('HYPE_MOD_PROTECTION_WORKER_ENABLED', worker)
        self.assertIn('HYPE_MOD_PROTECTION_QUEUE_ENABLED', staging)
        self.assertIn('admin_only()', staging)
        self.assertIn('HYPE_MOD_PRIVATE_PUBLISH_ENABLED', staging)
        self.assertIn('security invoker', sql.lower())
        self.assertIn('revoke all', sql.lower())
        self.assertIn('hype_finish_mod_protection_draft', sql)
        self.assertIn("and d.status in ('aguardando_protecao', 'em_teste')", sql)
        self.assertIn("not (coalesce(d.meta, '{}'::jsonb) ? 'protected')", sql)
        self.assertIn("db.rpc(\"hype_finish_mod_protection_draft\"", worker)


if __name__ == "__main__":
    unittest.main()
