"""Regressão da FK entre torneios e formatos sem conexão real com Supabase."""
import ast
import unittest
from pathlib import Path
from unittest.mock import Mock

APP = Path(__file__).resolve().parents[1] / "app.py"


def _helper_isolado():
    arvore = ast.parse(APP.read_text(encoding="utf-8"))
    funcao = next(
        node for node in arvore.body
        if isinstance(node, ast.FunctionDef) and node.name == "_garantir_formato_preset_no_banco"
    )
    supabase = Mock()
    namespace = {"supabase": supabase}
    exec(compile(ast.Module(body=[funcao], type_ignores=[]), str(APP), "exec"), namespace)
    return namespace[funcao.name], supabase


def _preset():
    return {
        "codigo": "gen9lc",
        "nome": "Geração 9 · LC",
        "tamanho_equipe": 6,
        "species_clause": True,
        "item_clause": False,
        "permite_tera": True,
    }


class ArenaFormatosFKTests(unittest.TestCase):
    def test_formato_existente_nao_e_sobrescrito(self):
        helper, db = _helper_isolado()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"codigo": "gen9lc"}
        ]
        helper(_preset())
        db.table.return_value.upsert.assert_not_called()

    def test_novo_preset_e_cadastrado_para_fk(self):
        helper, db = _helper_isolado()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        helper(_preset())
        args, kwargs = db.table.return_value.upsert.call_args
        self.assertEqual(args[0]["codigo"], "gen9lc")
        self.assertEqual(args[0]["nome"], "Geração 9 · LC")
        self.assertEqual(args[0]["max_pokemon"], 6)
        self.assertTrue(args[0]["permite_tera"])
        self.assertEqual(kwargs, {"on_conflict": "codigo", "ignore_duplicates": True})
        db.table.return_value.upsert.return_value.execute.assert_called_once_with()

    def test_criacao_verifica_fk_antes_de_inserir_torneio(self):
        src = APP.read_text(encoding="utf-8")
        bloco = src.split("def criar_torneio():", 1)[1].split("@app.route(", 1)[0]
        self.assertLess(
            bloco.index("_garantir_formato_preset_no_banco(preset)"),
            bloco.index("supabase.table('torneios').insert(")
        )


if __name__ == "__main__":
    unittest.main()
