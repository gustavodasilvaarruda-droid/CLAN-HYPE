"""Testes isolados do calendário das casas: não inicializa Flask nem Supabase."""
import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")


class TestReinoCasasDomingo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = ast.parse(SOURCE)
        fn = next(n for n in root.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_reino_proximo_domingo")
        module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
        cls.scope = {"datetime": datetime, "timedelta": timedelta, "HYPE_TZ": timezone(timedelta(hours=-3))}
        exec(compile(module, "<reino-domingo>", "exec"), cls.scope)

    def domingo(self, dia):
        return self.scope["_reino_proximo_domingo"](dia)

    def test_sabado_vence_amanha(self):
        self.assertEqual(self.domingo(date(2026, 11, 7)), date(2026, 11, 8))

    def test_segunda_vence_no_proximo_domingo(self):
        self.assertEqual(self.domingo(date(2026, 11, 9)), date(2026, 11, 15))

    def test_entrada_no_domingo_nao_cobra_na_hora(self):
        self.assertEqual(self.domingo(date(2026, 11, 8)), date(2026, 11, 15))

    def test_calendario_somente_casas(self):
        self.assertIn("if tipo == 'casa' else datetime.now(timezone.utc).date()", SOURCE)
        self.assertIn("'proximo_vencimento':_reino_proximo_domingo().isoformat()", SOURCE)
        self.assertIn("if ocupante and not membro_hype_ativo(ocupante)", SOURCE)

    def test_migracao_isolada_das_casas(self):
        sql = (ROOT / "supabase/migrations/20261107_reino_casas_domingo.sql").read_text()
        self.assertIn("FROM public.contratos_casas", sql)
        self.assertNotIn("UPDATE public.contratos_lojas", sql)
        self.assertIn("ON CONFLICT (tipo_unidade, contrato_id, referencia_vencimento) DO NOTHING", sql)
        self.assertIn("hype-casas-domingo-0900-brasilia", sql)
        self.assertIn("0 12 * * 0", sql)


if __name__ == "__main__":
    unittest.main()
