"""Arena HYPE 3.0 — testes sem acesso ao Supabase de produção."""
import ast
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from modules.arena_private_teams import codigo_formato_do_torneio, validar_equipe_basica
from modules.hype_tournament_formats import obter_formato, regulamento_congelado, obter_regras_especie_showdown

ROOT = Path(__file__).resolve().parents[1]


def capacidade(pokemon):
    return obter_regras_especie_showdown(pokemon)['abilities'][0]


def configurar_especie(slot, pokemon):
    slot['pokemon'] = pokemon
    slot['ability'] = capacidade(pokemon)


def equipe_valida():
    especies = ['Dialga', 'Palkia', 'Kyogre', 'Groudon', 'Lugia', 'Ho-Oh']
    return [
        {
            'pokemon': p,
            'ability': capacidade(p), 'nature': 'Timid',
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
        configurar_especie(team[0], 'Metagross')
        team[0]['mecanica'] = 'mega'
        team[0]['item'] = 'Metagrossite'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexubers'), [])
        team[0]['item'] = 'Abomasite'
        self.assertTrue(any('não corresponde' in e for e in validar_equipe_basica(team, 'gen9nationaldexubers')))
        configurar_especie(team[0], 'Gengar')
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
            configurar_especie(slot, especie)
        self.assertEqual(validar_equipe_basica(trio, 'gen91v1'), [])

    def test_tera_separated_and_special_format_restrictions(self):
        slots=equipe_valida()
        configurar_especie(slots[0], 'Metagross')
        slots[0]['mecanica']='mega'
        slots[0]['item']='Metagrossite'
        slots[0]['tera_ativa']=True
        slots[0]['tera_type']='Fairy'
        self.assertTrue(any('não pode Terastalizar' in e for e in
                            validar_equipe_basica(slots, 'gen9nationaldexubers')))
        slots[0]['tera_ativa']=False
        self.assertEqual(validar_equipe_basica(slots, 'gen9nationaldexubers'), [])

    def test_monotype_team_must_share_one_type(self):
        from modules.hype_tournament_formats import obter_especie_showdown
        especies = ['Pelipper', 'Barraskewda', 'Basculegion',
                    'Blastoise', 'Rotom-Wash', 'Quagsire']
        self.assertTrue(all('Water' in obter_especie_showdown(p)['types']
                            for p in especies))
        team = equipe_valida()
        for slot, p in zip(team, especies):
            configurar_especie(slot, p)
        self.assertEqual(validar_equipe_basica(team, 'gen9monotype'), [])
        # Reproduz a imagem do usuário: Venusaur e Charizard quebram o time Água.
        team[0]['pokemon'] = 'Venusaur'
        team[1]['pokemon'] = 'Charizard'
        erros = validar_equipe_basica(team, 'gen9monotype')
        self.assertTrue(any('Monotype' in erro and 'tipo' in erro for erro in erros), erros)

    def test_monotype_different_forms_and_mega_types(self):
        team = equipe_valida()
        for slot, pokemon in zip(team, ('Arcanine', 'Torkoal', 'Infernape',
                                       'Chandelure', 'Skeledirge', 'Charizard')):
            configurar_especie(slot, pokemon)
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexmonotype'), [])
        team[-1]['item'] = 'Charizardite X'
        team[-1]['mecanica'] = 'mega'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexmonotype'), [])
        team[0]['pokemon'] = 'Garchomp'
        self.assertTrue(any('Monotype' in e for e in
                            validar_equipe_basica(team, 'gen9nationaldexmonotype')))

    def test_arceus_primal_ogerpon_required_items(self):
        team = equipe_valida()
        configurar_especie(team[0], 'Arceus-Bug')
        team[0]['item'] = 'Leftovers'
        self.assertTrue(any('item de sua forma' in e for e in
                            validar_equipe_basica(team, 'gen9nationaldexag')))
        team[0]['item'] = 'Insect Plate'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexag'), [])
        configurar_especie(team[1], 'Arceus-Fire')
        team[1]['item'] = 'Flame Plate'
        self.assertTrue(any('espécies repetidas' in e for e in
                            validar_equipe_basica(team, 'gen9nationaldexag')))
        team[1]['pokemon'] = 'Palkia'
        team[1]['item'] = 'Leftovers'
        # A espécie Kyogre original ocupava o slot 3; não duplicar sua forma Primal.
        configurar_especie(team[2], 'Reshiram')
        configurar_especie(team[0], 'Kyogre-Primal')
        team[0]['item'] = 'Leftovers'
        self.assertTrue(any('blueorb' in e for e in
                            validar_equipe_basica(team, 'gen9nationaldexag')))
        team[0]['item'] = 'Blue Orb'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexag'), [])

        team = equipe_valida()
        configurar_especie(team[0], 'Ogerpon-Hearthflame')
        team[0]['item'] = 'Leftovers'
        self.assertTrue(any('hearthflamemask' in e for e in
                            validar_equipe_basica(team, 'gen9ubers')))
        team[0]['item'] = 'Hearthflame Mask'
        self.assertFalse(any('item de sua forma' in e for e in
                             validar_equipe_basica(team, 'gen9ubers')))

    def test_expanded_showdown_clause_bans(self):
        # A lista resumida não possui Sleep Powder e Sand Veil, mas
        # a cláusula herdada pelo formato precisa proibir ambos.
        team = equipe_valida()
        for slot, p in zip(team, ('Charizard','Garchomp','Venusaur','Metagross','Pelipper','Blastoise')):
            configurar_especie(slot, p)
        team[0]['moves'][0] = 'Sleep Powder'
        team[1]['ability'] = 'Sand Veil'
        errors = ' '.join(validar_equipe_basica(team, 'gen9ou'))
        self.assertIn('Sleep Powder', errors)
        self.assertIn('Sand Veil', errors)
        trio = equipe_valida()[:3]
        for slot, p in zip(trio, ('Garchomp', 'Metagross', 'Venusaur')):
            configurar_especie(slot, p)
        for move in ('Fissure', 'Flash', 'Double Team'):
            trio[0]['moves'][0] = move
            self.assertTrue(any(move in e for e in
                                validar_equipe_basica(trio, 'gen9nationaldex1v1')), move)
        slots = equipe_valida()
        slots[0]['item'] = 'Bright Powder'
        self.assertTrue(any('Bright Powder' in e for e in
                            validar_equipe_basica(slots, 'gen9nationaldexubers')))
        slots[0]['item'] = 'Leftovers'
        slots[0]['moves'][0] = 'Acupressure'
        self.assertTrue(any('Acupressure' in e for e in
                            validar_equipe_basica(slots, 'gen9nationaldexubers')))

    def test_lc_exact_level_and_format_mechanics(self):
        team = equipe_valida()
        especies = ['Bulbasaur','Charmander','Squirtle','Pikachu','Mudkip','Turtwig']
        for slot, p in zip(team, especies):
            configurar_especie(slot, p)
            slot['level'] = 5
        # Alguns desta lista podem ser restringidos pela tier; o erro
        # específico de nível não depende da permissividade da espécie.
        team[0]['level'] = 4
        self.assertTrue(any('Little Cup exige nível 5' in e for e in
                            validar_equipe_basica(team, 'gen9lc')))
        team = equipe_valida()
        team[0]['pokemon'] = 'Charizard'
        team[0]['item'] = 'Charizardite X'
        self.assertTrue(any('Mega Stones' in e for e in
                            validar_equipe_basica(team, 'gen9ubers')))
        team[0]['item'] = 'Firium Z'
        self.assertTrue(any('Z-Crystals' in e for e in
                            validar_equipe_basica(team, 'gen9ubers')))

    def test_showdown_item_catalog_rejects_unknown_and_past_in_gen9(self):
        from modules.hype_tournament_formats import obter_item_showdown, itens_showdown
        catalogo = itens_showdown()
        self.assertGreaterEqual(len(catalogo), 550)
        for item in ('leftovers', 'blueorb', 'insectplate',
                     'hearthflamemask', 'wellspringmask', 'cornerstonemask'):
            self.assertIsNotNone(obter_item_showdown(item), item)
        team = equipe_valida()
        team[0]['item'] = 'Fake Legendary Stone'
        self.assertTrue(any('não existe no catálogo' in e for e in
                            validar_equipe_basica(team, 'gen9nationaldexubers')))
        team[0]['item'] = 'Blue Orb'
        self.assertTrue(any('Geração 9 padrão' in e for e in
                            validar_equipe_basica(team, 'gen9ubers')))
        self.assertFalse(any('Geração 9 padrão' in e for e in
                             validar_equipe_basica(team, 'gen9nationaldexubers')))
        source = (ROOT / 'modules/expansion_features.py').read_text(encoding='utf-8')
        template = (ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        self.assertIn('def team_builder_items_snapshot():', source)
        self.assertIn('function bootItemsCatalog()', template)
        self.assertIn('function formatBanIds(kind)', template)

    def test_legacy_teams_show_errors_and_cannot_be_confirmed(self):
        events = (ROOT / 'modules/events_v26.py').read_text(encoding='utf-8')
        self.assertIn("equipe_enviada['regras_alertas']", events)
        self.assertIn("validar_equipe_basica(t.get('equipe'), codigo)", events)
        self.assertIn("' está fora das regras: '", events)
        user_view=(ROOT / 'templates/arena_torneio_equipes.html').read_text(encoding='utf-8')
        admin_view=(ROOT / 'templates/admin_arena_equipes.html').read_text(encoding='utf-8')
        self.assertIn('Time fora das regras do formato', user_view)
        self.assertIn('Corrigir regras antes do envio', user_view)
        self.assertIn('Checagem preliminar reprovada', admin_view)
        self.assertIn('irregularidades == 0', admin_view)


    def test_ability_must_belong_to_species_and_form(self):
        from modules.hype_tournament_formats import obter_regras_especie_showdown
        meta = obter_regras_especie_showdown('Bulbasaur')
        self.assertIn('Overgrow', meta['abilities'])
        self.assertIn('Chlorophyll', meta['abilities'])
        team = equipe_valida()
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexubers'), [])
        team[2]['ability'] = 'Pressure'  # Kyogre usa Drizzle, não Pressure.
        invalid = validar_equipe_basica(team, 'gen9nationaldexubers')
        self.assertTrue(any('habilidade Pressure não pertence a Kyogre' in e
                            and 'Drizzle' in e for e in invalid), invalid)
        team[2]['ability'] = 'Drizzle'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexubers'), [])

    def test_required_form_items_have_showdown_alternatives(self):
        team = equipe_valida()
        configurar_especie(team[0], 'Arceus-Bug')
        team[0]['item'] = 'Buginium Z'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexag'), [])
        team[0]['item'] = 'Insect Plate'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexag'), [])
        team[0]['item'] = 'Leftovers'
        self.assertTrue(any('item de sua forma' in e for e in
                            validar_equipe_basica(team, 'gen9nationaldexag')))
        configurar_especie(team[0], 'Dialga-Origin')
        team[0]['item'] = 'Adamant Crystal'
        self.assertEqual(validar_equipe_basica(team, 'gen9nationaldexag'), [])
        team[0]['item'] = 'Leftovers'
        self.assertTrue(any('adamantcrystal' in e for e in
                            validar_equipe_basica(team, 'gen9nationaldexag')))
        configurar_especie(team[0], 'Zacian-Crowned')
        team[0]['item'] = 'Rusted Sword'
        self.assertFalse(any('item de sua forma' in e for e in
                             validar_equipe_basica(team, 'gen9nationaldexag')))

    def test_meganium_is_not_a_mega_evolution(self):
        team = equipe_valida()
        configurar_especie(team[0], 'Meganium')
        team[0]['item'] = ''
        self.assertFalse(any('Mega' in e for e in
                             validar_equipe_basica(team, 'gen9nationaldexubers')))

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
