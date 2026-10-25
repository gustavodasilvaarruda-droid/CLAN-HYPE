import unittest
from datetime import datetime, timezone
from flask import Flask

from modules.hype_mod_admin import calcular_periodo, create_hype_mod_admin_blueprint

AGORA = datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc)


class TestPeriodoPermissoes(unittest.TestCase):
    def test_sem_prazo(self):
        inicio, fim = calcular_periodo("", "sem_prazo", "", "", agora=AGORA)
        self.assertEqual(inicio, AGORA.isoformat())
        self.assertIsNone(fim)

    def test_horas(self):
        inicio, fim = calcular_periodo("", "horas", "3", "", agora=AGORA)
        self.assertEqual(fim, "2026-10-19T00:00:00+00:00")

    def test_dias(self):
        _, fim = calcular_periodo("", "dias", "14", "", agora=AGORA)
        self.assertEqual(fim, "2026-11-01T21:00:00+00:00")

    def test_semanas(self):
        _, fim = calcular_periodo("", "semanas", "2", "", agora=AGORA)
        self.assertEqual(fim, "2026-11-01T21:00:00+00:00")

    def test_mes_ultimo_dia(self):
        inicio, fim = calcular_periodo("2027-01-31T12:00", "meses", "1", "")
        self.assertEqual(inicio, "2027-01-31T15:00:00+00:00")
        self.assertEqual(fim, "2027-02-28T15:00:00+00:00")

    def test_intervalo_brasilia(self):
        inicio, fim = calcular_periodo("2026-10-18T19:00", "intervalo", "", "2026-10-20T19:00")
        self.assertEqual(inicio, "2026-10-18T22:00:00+00:00")
        self.assertEqual(fim, "2026-10-20T22:00:00+00:00")

    def test_sem_fim_invalido(self):
        with self.assertRaises(ValueError):
            calcular_periodo("", "intervalo", "", "", agora=AGORA)

    def test_fim_anterior(self):
        with self.assertRaises(ValueError):
            calcular_periodo("2026-10-19T12:00", "intervalo", "", "2026-10-18T12:00")

    def test_duracao_invalida(self):
        with self.assertRaises(ValueError):
            calcular_periodo("", "anos", "1", "", agora=AGORA)

    def test_quantidade_invalida(self):
        with self.assertRaises(ValueError):
            calcular_periodo("", "dias", "0", "", agora=AGORA)
        with self.assertRaises(ValueError):
            calcular_periodo("", "meses", "121", "", agora=AGORA)


class TestPainelAdmin(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "teste"
        self.app.register_blueprint(
            create_hype_mod_admin_blueprint(
                db=None, login_required=lambda fn: fn,
                is_admin=lambda: False,
                registrar_log=lambda *args, **kwargs: None,
            )
        )
        self.client = self.app.test_client()

    def test_sem_permissao_nao_consulta_banco(self):
        resp = self.client.get("/admin/modulos")
        self.assertEqual(resp.status_code, 403)

    def test_sem_permissao_nao_altera_estado(self):
        resp = self.client.post("/admin/modulos/hype_battle_ai/estado", data={"estado": "ativo"})
        self.assertEqual(resp.status_code, 403)

    def test_sem_permissao_nao_concede_acesso(self):
        resp = self.client.post("/admin/modulos/hype_battle_ai/usuario", data={
            "usuario_email": "teste@exemplo.com", "decisao": "permitir", "duracao": "sem_prazo"
        })
        self.assertEqual(resp.status_code, 403)



class TestCliqueModulo(unittest.TestCase):
    def test_painel_admin_tem_link_para_modulos(self):
        from pathlib import Path
        base = Path(__file__).resolve().parents[1]
        page = (base / "templates/admin_dashboard_geral.html").read_text(encoding="utf-8")
        self.assertIn("url_for('hype_mod_admin.painel')", page)

    def test_cabecalho_do_modulo_abre_formularios(self):
        from pathlib import Path
        base = Path(__file__).resolve().parents[1]
        page = (base / "templates/admin_hype_modulos.html").read_text(encoding="utf-8")
        self.assertIn('<details class="hmod-card" id="modulo-{{ m.codigo }}">', page)
        self.assertIn('<summary class="hmod-heading">', page)
        self.assertIn('alvo.open = true', page)

    def test_salvar_retorna_ao_modulo_editado(self):
        from types import SimpleNamespace

        class FakeQuery:
            def __init__(self):
                self.updated = None
            def select(self, *_args): return self
            def eq(self, *_args): return self
            def limit(self, *_args): return self
            def update(self, value):
                self.updated = value
                return self
            def execute(self):
                return SimpleNamespace(data=[{"codigo": "battle_ai", "nome": "IA", "estado": "ativo"}])

        fake = FakeQuery()
        class FakeDB:
            def table(self, name):
                self.name = name
                return fake

        app = Flask(__name__)
        app.secret_key = "teste"
        app.register_blueprint(create_hype_mod_admin_blueprint(
            db=FakeDB(), login_required=lambda fn: fn,
            is_admin=lambda: True, registrar_log=lambda *args, **kwargs: None,
        ))
        response = app.test_client().post(
            "/admin/modulos/battle_ai/estado", data={"estado": "manutencao"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("#modulo-battle_ai"))
        self.assertEqual(fake.updated, {"estado": "manutencao"})


class TestRenderizacaoModulos(unittest.TestCase):
    """Exercita GET administrativo de verdade (nao apenas a checagem de permissao)."""

    def _criar_app(self, dados, falhar=False):
        from pathlib import Path
        from types import SimpleNamespace
        from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

        class Query:
            def __init__(self, tabela):
                self.tabela = tabela
            def select(self, *args): return self
            def limit(self, *args): return self
            def execute(self):
                if falhar:
                    raise RuntimeError("Tabela ausente no Supabase")
                return SimpleNamespace(data=list(dados.get(self.tabela, [])))

        class DB:
            def table(self, tabela):
                return Query(tabela)

        app = Flask(__name__)
        app.secret_key = "teste"
        templates = Path(__file__).resolve().parents[1] / "templates"
        app.jinja_loader = ChoiceLoader([
            DictLoader({"hype_app_base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(str(templates)),
        ])
        app.jinja_env.globals["url_for"] = lambda *args, **kwargs: "/teste"
        app.jinja_env.globals["csrf_token"] = lambda: "teste-csrf"
        app.jinja_env.filters["data_br"] = lambda v: str(v)
        app.register_blueprint(create_hype_mod_admin_blueprint(
            DB(), login_required=lambda fn: fn,
            is_admin=lambda: True, registrar_log=lambda *args, **kwargs: None,
        ))
        return app

    def test_get_sem_tabelas_exibe_aviso_sem_error500(self):
        client = self._criar_app({}, falhar=True).test_client()
        resp = client.get("/admin/modulos")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[:400])
        self.assertIn("migra", resp.get_data(as_text=True).lower())

    def test_get_com_modulo_real_e_formularios_sem_error500(self):
        dados = {
            "hype_modulos": [{
                "codigo": "hype_pokedex",
                "nome": "Pokédex",
                "descricao": "Atributos e formas",
                "estado": "ativo",
                "versao": "1.0",
                "visivel": True,
                "ordem": 1,
            }],
            "cargos": [{"id": "lider", "nome_cargo": "Líder"}],
            "hype_modulos_grupos": [{"modulo_codigo": "hype_pokedex", "cargo_id": "lider"}],
            "hype_modulos_acessos": [],
        }
        resp = self._criar_app(dados).test_client().get("/admin/modulos")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[:400])
        self.assertIn("Pokédex", resp.get_data(as_text=True))
        self.assertIn("modulo-hype_pokedex", resp.get_data(as_text=True))

if __name__ == "__main__":
    unittest.main()
