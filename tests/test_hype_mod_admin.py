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


if __name__ == "__main__":
    unittest.main()
