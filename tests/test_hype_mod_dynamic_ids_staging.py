"""As duas tabelas de entrada precisam aceitar novos mods sem liberar distribuicao."""
import unittest
from pathlib import Path

SQL=(Path(__file__).resolve().parents[1] / "sql" / "20261124_hype_mod_dynamic_ids_staging.sql")


class DynamicModIdsStagingTests(unittest.TestCase):
    def test_drafts_e_fila_aceitam_mods_novos(self):
        sql=SQL.read_text(encoding="utf-8").lower()
        self.assertIn("alter table public.hype_mod_release_drafts",sql)
        self.assertIn("alter table public.hype_mod_protection_jobs",sql)
        self.assertEqual(sql.count("module_id ~ '^[a-z][a-z0-9_]{1,63}$'"),2)
        self.assertEqual(sql.count("module_id <> 'hypebootstrap'"),2)

    def test_nenhuma_modificacao_na_distribuicao_publica(self):
        sql=SQL.read_text(encoding="utf-8").lower()
        self.assertNotIn("hype_mod_published_releases",sql)
        self.assertNotIn("hype_mod_restricted_releases",sql)
        self.assertNotIn("storage.buckets",sql)
        self.assertNotIn("insert into",sql)
if __name__ == "__main__":
    unittest.main()
