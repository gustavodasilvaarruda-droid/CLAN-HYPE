"""Arena HYPE 3.0 — testes sem acesso ao Supabase de produção."""
import ast
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from modules.arena_private_teams import codigo_formato_do_torneio, validar_equipe_basica
from modules.hype_tournament_formats import obter_formato, regulamento_congelado

ROOT = Path(__file__).resolve().parents[1]


def equipe_valida():
    especies = ['Dialga', 'Palkia', 'Kyogre', 'Groudon', 'Lugia', 'Ho-Oh']
    return [
        {
            'pokemon': p,
            'ability': 'Pressure', 'nature': 'Timid',
            'item': 'Leftovers',
            'moves': ['Recover', 'Protect', 'Rest', 'Sleep Talk'],
            'evs': {k: 0 for k in ('hp','atk','def','spa','spd','spe')},
            'ivs': {k: 31 for k in ('hp','atk','def','spa','spd','spe')}
        }
        for p in especies
    ]


class TestArenaPrivateTeams(unittest.TestCase):
    def test_snapshot_format_has_precise_id(self):
        regras = regulamento_congelado(obter_formato('gen9nationaldexubers'))
        self.assertEqual(codigo_formato_do_torneio(regras), 'gen9nationaldexubers')
        self.assertIsNone(codigo_formato_do_torneio('Torneio livre'))
        self.assertIsNone(codigo_formato_do_torneio('Identificador Pokémon Showdown: inv4lid'))

    def test_six_complete_sets_pass_preliminary_check(self):
        self.assertEqual(validar_equipe_basica(equipe_valida(), 'gen9nationaldexubers'), [])

    def test_reject_banned_species_moves_duplicates_and_bad_evs(self):
        slots = equipe_valida()
        slots[0]['pokemon'] = 'Shedinja'
        slots[1]['moves'][0] = 'Assist'
        slots[2]['moves'][1] = 'Baton Pass'
        slots[3]['pokemon'] = 'Kyogre'
        slots[4]['evs']['atk'] = 300
        slots[5]['ability'] = ''
        msgs = ' '.join(validar_equipe_basica(slots, 'gen9nationaldexubers'))
        for item in ('Shedinja', 'Assist', 'Baton Pass', 'repetidas', 'EVS', 'habilidade'):
            self.assertIn(item, msgs)
        self.assertTrue(validar_equipe_basica(slots[:5], 'gen9nationaldexubers'))

    def test_national_dex_ubers_bans_and_mechanics(self):
        team = equipe_valida()
        team[0]['pokemon'] = 'Miraidon'
        self.assertTrue(any('Miraidon' in e for e in validar_equipe_basica(team, 'gen9nationaldexubers')))
        team[0]['pokemon'] = 'Dialga'
        team[0]['mecanica'] = 'dynamax'
        self.assertTrue(any('dynamax' in e for e in validar_equipe_basica(team, 'gen9nationaldexubers')))
        team[0]['mecanica'] = 'tera'
        team[0]['tera_type'] = 'Fire'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexubers'), [])
        team[0]['pokemon'] = 'Metagross'
        team[0]['mecanica'] = 'mega'
        team[0]['item'] = 'Metagrossite'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexubers'), [])
        team[0]['item'] = 'Abomasite'
        self.assertTrue(any('não corresponde' in e for e in validar_equipe_basica(team, 'gen9nationaldexubers')))
        team[0]['pokemon'] = 'Gengar'
        team[0]['item'] = 'Gengarite'
        self.assertTrue(any('AG' in e for e in validar_equipe_basica(team, 'gen9nationaldexubers')))

    def test_catalogue_gen9_lc_natdex_and_team_sizes(self):
        from modules.hype_tournament_formats import formatos_disponiveis
        catalogo = {f['codigo']: f for f in formatos_disponiveis()}
        self.assertGreaterEqual(len(catalogo), 20)
        for code in ('gen9ou','gen9ubers','gen9lc','gen9nationaldex',
                     'gen9nationaldexubers','gen9nationaldexag','gen9doublesou'):
            self.assertIn(code,catalogo)
            self.assertIn('Identificador Pokémon Showdown: '+code, catalogo[code]['regulamento'])
            self.assertFalse(catalogo[code]['validacao_completa'])
        self.assertEqual(catalogo['gen9lc']['nivel_maximo'],5)
        self.assertEqual(catalogo['gen91v1']['tamanho_equipe'],3)
        self.assertTrue(validar_equipe_basica(equipe_valida(), 'gen91v1'))
        trio = equipe_valida()[:3]
        for slot, especie in zip(trio, ('Metagross', 'Garchomp', 'Venusaur')):
            slot['pokemon'] = especie
        self.assertEqual(validar_equipe_basica(trio, 'gen91v1'), [])

    def test_tera_separated_and_special_format_restrictions(self):
        slots=equipe_valida()
        slots[0]['pokemon']='Metagross'
        slots[0]['mecanica']='mega'
        slots[0]['item']='Metagrossite'
        slots[0]['tera_ativa']=True
        slots[0]['tera_type']='Fairy'
        self.assertTrue(any('não pode Terastalizar' in e for e in
                            validar_equipe_basica(slots, 'gen9nationaldexubers')))
        slots[0]['tera_ativa']=False
        self.assertEqual(validar_equipe_basica(slots, 'gen9nationaldexubers'), [])

    def test_never_automatically_confirms_registration(self):
        app = (ROOT / 'app.py').read_text(encoding='utf-8')
        events = (ROOT / 'modules/events_v26.py').read_text(encoding='utf-8')
        ast.parse(app)
        ast.parse(events)
        target = app[app.index('def inscrever_torneio('):app.index('@app.route(',app.index('def inscrever_torneio('))]
        self.assertIn("if codigo_formato_do_torneio(torneio.get('regras')):", target)
        self.assertIn("return redirect(url_for('events26.equipes_torneio'", target)
        target_events = events[events.index('def equipes_torneio('):events.index('def admin_equipes_torneio(')]
        self.assertNotIn("table('inscricoes_torneio').insert", target_events)
        self.assertIn("'status': 'aguardando_verificacao'", target_events)
        self.assertIn("time.get('publico')", target_events)

    def test_tournament_team_format_is_enforced_on_server(self):
        # Não permite enviar OU para um torneio National Dex Ubers e
        # não expõe no seletor times privados de outros formatos.
        events = (ROOT / 'modules/events_v26.py').read_text(encoding='utf-8')
        builder = (ROOT / 'modules/expansion_features.py').read_text(encoding='utf-8')
        view = (ROOT / 'templates/arena_torneio_equipes.html').read_text(encoding='utf-8')
        self.assertIn("str(time.get('formato_codigo') or '').strip().lower() != codigo", events)
        self.assertIn("str(t.get('formato_codigo') or '').lower() == codigo", events)
        self.assertIn('time_selecionado_id=selecionado', events)
        self.assertIn('team_id=time_salvo_id', builder)
        self.assertIn('time.id == time_selecionado_id', view)
        self.assertIn('{{tamanho_equipe}} Pokémon', view)

    def test_every_tournament_format_has_consistent_teamsize(self):
        from modules.hype_tournament_formats import formatos_disponiveis
        formats = formatos_disponiveis()
        self.assertGreaterEqual(len(formats), 28)
        for f in formats:
            with self.subTest(format=f['codigo']):
                self.assertEqual(f['geracao'], 9)
                self.assertEqual(f['showdown'], f['codigo'])
                self.assertTrue(1 <= f['tamanho_equipe'] <= 6)
                for flag in ('permite_mega', 'permite_zmove', 'permite_tera', 'permite_dynamax'):
                    self.assertIsInstance(f[flag], bool)
                self.assertFalse(f['validacao_completa'])
        self.assertTrue(any(f['codigo'] == 'gen9lc' and f['nivel_maximo'] == 5
                            for f in formats))

    def test_admin_only_and_owner_isolation(self):
        events = (ROOT / 'modules/events_v26.py').read_text(encoding='utf-8')
        admin = events[events.index('def admin_equipes_torneio('):events.index("    @bp.route('/admin/eventos/",events.index('def admin_equipes_torneio('))]
        self.assertIn('if not admin_ok():', admin)
        user = events[events.index('def equipes_torneio('):events.index('def admin_equipes_torneio(')]
        self.assertIn('usuario_email=email', user)
        self.assertIn("str(time.get('usuario_email') or '').lower() != email", user)

    def test_private_schema_and_audit(self):
        sql = (ROOT / 'supabase/migrations/20261110_arena_3_equipes_privadas.sql').read_text(encoding='utf-8')
        self.assertIn('ENABLE ROW LEVEL SECURITY', sql)
        self.assertIn('REVOKE ALL', sql)
        self.assertIn('CREATE TRIGGER trg_historico_equipes_arena', sql)
        self.assertIn('UNIQUE(torneio_id, usuario_email, slot)', sql)

    def test_templates_compile_and_keep_legacy_enrollment(self):
        env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')), autoescape=True)
        for name in ('torneio_detalhe.html', 'arena_torneio_equipes.html',
                     'admin_arena_equipes.html'):
            self.assertIsNotNone(env.get_template(name))
        detail = (ROOT / 'templates/torneio_detalhe.html').read_text(encoding='utf-8')
        self.assertIn("url_for('events26.equipes_torneio'", detail)
        self.assertIn("url_for('inscrever_torneio'", detail)
        self.assertIn('pode_ver_equipes', detail)


if __name__ == '__main__':
    unittest.main()
