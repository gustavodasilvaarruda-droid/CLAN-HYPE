"""Verificações estáticas da moderação privada (sem tocar em torneios reais)."""
import ast
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


class ArenaInscricoesAdminTest(unittest.TestCase):
    def test_events_routes_compile_and_require_admin(self):
        events = source('modules/events_v26.py')
        ast.parse(events)
        for route in ('admin_revisar_equipe', 'admin_pagamento_torneio',
                      'admin_confirmar_inscricao_torneio'):
            self.assertIn('def ' + route + '(', events)
            body = events[events.index('def ' + route + '('):]
            body = body.split("\n    @bp.route(", 1)[0]
            self.assertIn('if not admin_ok():', body, route)
            self.assertIn("methods=['POST']", events[:events.index('def ' + route)])
        self.assertIn('revisao_aberta(torneio)', events)
        self.assertIn('validar_equipe_basica(equipe.get(', events)
        self.assertIn("'status': novo_status", events)
        self.assertIn("'motivo_revisao': motivo or None", events)

    def test_confirmation_only_uses_database_transaction(self):
        events = source('modules/events_v26.py')
        confirm = events[events.index('def admin_confirmar_inscricao_torneio('):]
        confirm = confirm.split("\n    @bp.route(", 1)[0]
        self.assertIn("supabase.rpc('hype_arena_confirmar_inscricao'", confirm)
        self.assertNotIn(".table('inscricoes_torneio').insert", confirm)
        self.assertIn("resultado == 'inscricao_confirmada'", confirm)

    def test_sql_locks_capacity_and_keeps_teams_private(self):
        sql = source('supabase/migrations/20261110_arena_aprovacao_inscricoes.sql')
        for statement in ('FOR UPDATE', "status <> 'aprovado'",
                          "('confirmado', 'dispensado')",
                          'limite_participantes', 'ON CONFLICT ON CONSTRAINT',
                          'inscricao_torneio_unica', 'inscricao_confirmada_em',
                          'ENABLE ROW LEVEL SECURITY', 'REVOKE ALL',
                          'SECURITY INVOKER', 'GRANT EXECUTE', 'TO service_role'):
            self.assertIn(statement, sql)
        self.assertIn('registrar_historico_controle_arena', sql)

    def test_templates_compile_and_protect_actions(self):
        env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')), autoescape=True)
        for name in ('admin_arena_equipes.html', 'arena_torneio_equipes.html',
                     'admin_conteudo.html', 'torneio_detalhe.html'):
            self.assertIsNotNone(env.get_template(name))
        page = source('templates/admin_arena_equipes.html')
        for control in ('Aprovar time', 'Enviar correção ao jogador',
                        'Confirmar pagamento', 'Sem cobrança',
                        'Confirmar inscrição oficial', 'csrf_token',
                        'pode_revisar', 'not pronto'):
            self.assertIn(control, page)
        self.assertIn('motivo_revisao', source('templates/arena_torneio_equipes.html'))
        self.assertIn('Revisar times e aprovar inscrições',
                      source('templates/admin_conteudo.html'))

    def test_team_submission_not_automatically_registered(self):
        events = source('modules/events_v26.py')
        user = events[events.index('def equipes_torneio('):
                      events.index("def admin_equipes_torneio(")]
        self.assertIn("'status': 'aguardando_verificacao'", user)
        self.assertIn('esta_inscrito = bool(safe_table', user)
        self.assertIn('not esta_inscrito', user)
        self.assertIn('times do torneio estão bloqueados',
                      source('templates/arena_torneio_equipes.html'))
        self.assertNotIn("table('inscricoes_torneio').insert", user)
        self.assertNotIn("hype_arena_confirmar_inscricao", user)


if __name__ == '__main__':
    unittest.main()
