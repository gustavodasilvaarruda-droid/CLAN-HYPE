"""Testes estáticos de segurança e renderização da Arena HYPE v2.

Não acessam o Supabase de produção e não removem dados.
"""
import ast
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from modules.hype_tournament_formats import formatos_disponiveis, obter_formato, regulamento_congelado

ROOT = Path(__file__).resolve().parents[1]


class ArenaHypeV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.app_ast = ast.parse(cls.app_source)
        cls.events_source = (ROOT / "modules/events_v26.py").read_text(encoding="utf-8")
        cls.events_ast = ast.parse(cls.events_source)

    def function(self, name):
        return next(node for node in self.app_ast.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)

    def test_python_modules_parse(self):
        self.assertIsInstance(self.app_ast, ast.Module)
        self.assertIsInstance(self.events_ast, ast.Module)

    def test_admin_actions_require_security_checks(self):
        for name in ("editar_torneio", "excluir_torneio"):
            source = ast.get_source_segment(self.app_source, self.function(name))
            self.assertIn("_pode_administrar_conteudo()", source)
            self.assertIn("tem_permissao('pode_gerenciar_torneios')", source)
        delete = ast.get_source_segment(self.app_source, self.function("excluir_torneio"))
        self.assertIn("confirmar_titulo", delete)
        self.assertIn("ranking_processado", delete)
        self.assertIn("registrar_log(", delete)

    def test_enrollment_needs_explicit_acceptance(self):
        enrol = ast.get_source_segment(self.app_source, self.function("inscrever_torneio"))
        self.assertIn("aceito_regras", enrol)
        self.assertIn("status_torneio", enrol)
        self.assertIn("limite_participantes", enrol)
        listing = (ROOT / "templates/torneios.html").read_text(encoding="utf-8")
        self.assertNotIn("url_for('inscrever_torneio'", listing)
        detail = (ROOT / "templates/torneio_detalhe.html").read_text(encoding="utf-8")
        self.assertIn('name="aceito_regras"', detail)
        self.assertIn("meus_confrontos", detail)

    def test_tournament_status_cannot_fake_a_final(self):
        section = self.events_source[
            self.events_source.index("def admin_torneio_v26("):
            self.events_source.index("@bp.route('/admin/live/replays/criar'")
        ]
        self.assertIn("status == 'finalizado' and status_atual != 'finalizado'", section)
        self.assertIn("if status == 'inscricoes' and tem_chave:", section)

    def test_presets_keep_rules_in_server_side_snapshot(self):
        catalog = formatos_disponiveis()
        self.assertTrue(catalog)
        preset = obter_formato("gen9nationaldexubers")
        self.assertEqual(preset["geracao"], 9)
        rules = regulamento_congelado(preset)
        self.assertIn("Shedinja", rules)
        self.assertIn("Assist", rules)
        self.assertIn("Baton Pass", rules)
        self.assertIn("validação", rules)
        self.assertIn("regulamento", catalog[0])
        self.assertIsNone(obter_formato("invalid-format"))
        with self.assertRaises(ValueError):
            regulamento_congelado({"codigo": "invalid-format"})

    def test_creation_uses_catalog_not_browser_rules(self):
        source = ast.get_source_segment(self.app_source, self.function("criar_torneio"))
        self.assertIn("regulamento_congelado(preset)", source)
        self.assertIn("obter_formato(codigo_preset)", source)
        self.assertIn("tem_permissao('pode_gerenciar_torneios')", source)
        ui = (ROOT / "templates/admin_conteudo.html").read_text(encoding="utf-8")
        self.assertIn('name="formato_preset"', ui)
        self.assertIn('data-arena-preview', ui)
        js = (ROOT / "static/hype_arena_presets.js").read_text(encoding="utf-8")
        self.assertIn("rules.readOnly = true", js)
        self.assertIn("preview.replaceChildren()", js)

    def test_templates_compile(self):
        env = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=True)
        env.filters["data_br"] = lambda value: value
        for template in ("admin_conteudo.html", "torneios.html",
                         "torneio_detalhe.html", "hype_app_base.html"):
            with self.subTest(template=template):
                self.assertIsNotNone(env.get_template(template))

    def test_admin_ui_has_edit_and_delete_confirmation(self):
        ui = (ROOT / "templates/admin_conteudo.html").read_text(encoding="utf-8")
        self.assertIn("url_for('editar_torneio'", ui)
        self.assertIn("url_for('excluir_torneio'", ui)
        self.assertIn('name="confirmar_titulo"', ui)
        self.assertIn("confirm('Confirma EXCLUIR", ui)
        self.assertIn("t.tem_chave", ui)


if __name__ == "__main__":
    unittest.main()
