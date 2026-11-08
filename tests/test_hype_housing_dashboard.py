"""Regressões das casas HYPE no painel de membros e cargos."""
import ast
from pathlib import Path
import unittest
from modules.hype_housing_status import preencher_situacao_moradia

ROOT = Path(__file__).resolve().parents[1]


class TestHypeMoradia(unittest.TestCase):
    def test_casa_com_contrato_ativo(self):
        usuarios = [{'email': 'A@HYPE.COM ', 'hype_ativo': True},
                    {'email': 'b@hype.com', 'hype_ativo': True},
                    {'email': 'c@hype.com', 'hype_ativo': False}]
        casas = [{'id': 1, 'codigo': 'CASA-01', 'ativa': True,
                  'ocupante_email': 'a@hype.com', 'status': 'ocupada'},
                 {'id': 2, 'codigo': 'CASA-02', 'ativa': True,
                  'ocupante_email': None, 'status': 'disponivel'}]
        contratos = [{'casa_id': 1, 'usuario_email': 'a@hype.com', 'status': 'ativo'}]
        resumo = preencher_situacao_moradia(usuarios, casas, contratos)
        self.assertEqual(resumo['total'], 2)
        self.assertEqual(resumo['com_casa'], 1)
        self.assertEqual(resumo['sem_casa'], 1)
        self.assertEqual(resumo['disponiveis'], 1)
        self.assertEqual(usuarios[0]['moradia_nome'], 'CASA-01')
        self.assertEqual(usuarios[1]['moradia_status'], 'sem_casa')
        self.assertEqual(usuarios[2]['moradia_status'], 'fora_cla')

    def test_contrato_e_casa_inconsistentes_vao_para_revisao(self):
        usuarios = [{'email': 'a@hype.com', 'hype_ativo': True}]
        casas = [{'id': 1, 'codigo': 'A', 'ativa': True,
                  'ocupante_email': 'a@hype.com', 'status': 'ocupada'}]
        contratos = [{'casa_id': 2, 'usuario_email': 'a@hype.com', 'status': 'ativo'}]
        resumo = preencher_situacao_moradia(usuarios, casas, contratos)
        self.assertEqual(resumo['verificar'], 1)
        self.assertEqual(resumo['com_casa'], 0)

    def test_falha_de_consulta_nao_inventa_ausencia(self):
        usuarios = [{'email': 'a@hype.com', 'hype_ativo': True}]
        resumo = preencher_situacao_moradia(usuarios, None, [])
        self.assertFalse(resumo['ok'])
        self.assertEqual(usuarios[0]['moradia_status'], 'indisponivel')

    def test_somente_hype_precisa_de_casa_e_nao_ha_mutacoes(self):
        app_code = (ROOT / 'app.py').read_text(encoding='utf-8')
        tree = ast.parse(app_code)
        for name in ('admin_cargos', 'admin_membros_hype'):
            fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name)
            code = ast.get_source_segment(app_code, fn)
            self.assertIn('_carregar_moradia_admin(usuarios)', code)
        for name in ('admin_cargos.html', 'admin_membros_hype.html'):
            html = (ROOT / 'templates' / name).read_text(encoding='utf-8')
            self.assertIn('data-housing=', html)
            self.assertIn('data-filter-housing', html)
            self.assertIn('hype_moradia_resumo.html', html)


if __name__ == '__main__':
    unittest.main()
