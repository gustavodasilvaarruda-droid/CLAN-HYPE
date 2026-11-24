"""Verificacoes de prioridade da fila do HYPE Client sem tocar na producao."""
import unittest
from pathlib import Path

SQL = Path(__file__).resolve().parents[1] / "sql" / "20261124_hype_client_priority_queue.sql"


class HypeClientPriorityQueueTests(unittest.TestCase):
    def test_original_client_tem_prioridade_e_lock_atomico(self):
        source = SQL.read_text(encoding="utf-8").lower()
        self.assertIn("when j.module_id = 'hypeclient' then 0 else 1", source)
        self.assertIn("j.requested_at", source)
        self.assertIn("for update skip locked", source)
        self.assertIn("where j.status = 'queued'", source)
        self.assertIn("set status = 'running'", source)

    def test_rpc_continua_privado_para_worker(self):
        source = SQL.read_text(encoding="utf-8").lower()
        self.assertIn("security invoker", source)
        self.assertIn("revoke all on function public.hype_claim_mod_protection_job() from public, anon, authenticated", source)
        self.assertIn("grant execute on function public.hype_claim_mod_protection_job() to service_role", source)

if __name__ == "__main__":
    unittest.main()
