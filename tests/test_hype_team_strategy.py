"""Testes da análise automática HYPE: times importados, inventados e sem papel manual."""
from copy import deepcopy
from pathlib import Path
import ast
import unittest

from jinja2 import Environment, FileSystemLoader
from modules.hype_team_strategy import analisar_estrategia

ROOT = Path(__file__).resolve().parents[1]


def pokemon(name, item, ability, moves, evs, nature=''):
    return {'pokemon': name, 'item': item, 'ability': ability, 'moves': moves,
            'evs': evs, 'ivs': {'atk': 0}, 'nature': nature, 'papel': ''}


class StrategyAnalysisTests(unittest.TestCase):
    def sun_team(self):
        return [
            pokemon('Charizard', 'Charizardite Y', 'Drought',
                    ['Flamethrower', 'Solar Beam', 'Focus Blast', 'Roost'],
                    {'spa': 252, 'spd': 4, 'spe': 252}, 'Timid'),
            pokemon('Venusaur', 'Life Orb', 'Chlorophyll',
                    ['Giga Drain', 'Sludge Bomb', 'Weather Ball', 'Growth'],
                    {'spa': 252, 'spd': 4, 'spe': 252}, 'Modest'),
            pokemon('Garchomp', 'Rocky Helmet', 'Rough Skin',
                    ['Earthquake', 'Scale Shot', 'Fire Fang', 'Swords Dance'],
                    {'atk': 252, 'spd': 4, 'spe': 252}, 'Jolly'),
            pokemon('Rotom-Wash', 'Leftovers', 'Levitate',
                    ['Volt Switch', 'Hydro Pump', 'Will-O-Wisp', 'Pain Split'],
                    {'hp': 252, 'def': 200, 'spe': 56}, 'Bold'),
            pokemon('Ferrothorn', 'Leftovers', 'Iron Barbs',
                    ['Stealth Rock', 'Leech Seed', 'Power Whip', 'Knock Off'],
                    {'hp': 252, 'def': 252, 'spd': 4}, 'Impish'),
            pokemon('Excadrill', 'Heavy-Duty Boots', 'Mold Breaker',
                    ['Earthquake', 'Iron Head', 'Rapid Spin', 'Toxic'],
                    {'atk': 252, 'spd': 4, 'spe': 252}, 'Jolly'),
        ]

    def test_sun_team_infers_each_role_without_manual_papel(self):
        team = self.sun_team()
        untouched = deepcopy(team)
        a = analisar_estrategia(team, 'gen9nationaldexou')
        self.assertEqual(team, untouched, 'O motor nunca pode modificar os sets.')
        self.assertIn('Sol', a['estrategia'])
        self.assertEqual(len(a['funcoes']), 6)
        roles = {m['pokemon']: ' | '.join(m['funcoes']) for m in a['funcoes']}
        self.assertIn('Ativador do sol', roles['Charizard'])
        self.assertEqual(a['funcoes'][0]['pokemon_exibicao'], 'Charizard Mega Y')
        self.assertIn('Aproveita sol', roles['Venusaur'])
        self.assertIn('Atacante físico', roles['Garchomp'])
        self.assertIn('Pivô', roles['Rotom-Wash'])
        self.assertIn('Colocador de hazards', roles['Ferrothorn'])
        self.assertIn('Removedor de hazards', roles['Excadrill'])
        self.assertTrue(any('física e especial' in x for x in a['fortes']))
        self.assertTrue(any('Hydro Pump' not in x and 'Água' in x for x in a['riscos']))
        self.assertTrue(any('Ferrothorn' in x and 'Fogo' in x for x in a['riscos']))
        self.assertTrue(any('Stealth Rock' in x for x in a['riscos']))
        self.assertTrue(any('Excadrill' in x for x in a['plano']))
        self.assertTrue(any('Venusaur' in x for x in a['sinergias']))

    def test_mega_y_drought_is_detected_from_item_even_with_pre_mega_ability(self):
        team = self.sun_team()
        team[0]['ability'] = 'Blaze'
        a = analisar_estrategia(team)
        self.assertIn('Sol', a['estrategia'])
        self.assertIn('Ativador do sol', a['funcoes'][0]['funcoes'])
        self.assertIn('IV 0 Atk', ' | '.join(a['funcoes'][0]['evidencias']))
        self.assertEqual(team[0]['ability'], 'Blaze')

    def test_rain_team_is_detected_without_hardcoded_species(self):
        team = [
            pokemon('Pelipper', 'Damp Rock', 'Drizzle',
                    ['Hurricane', 'U-turn', 'Roost', 'Defog'], {'hp': 252, 'def': 252}),
            pokemon('Barraskewda', 'Choice Band', 'Swift Swim',
                    ['Liquidation', 'Flip Turn', 'Close Combat', 'Aqua Jet'],
                    {'atk': 252, 'spe': 252}),
            pokemon('Swampert', 'Leftovers', 'Torrent',
                    ['Earthquake', 'Stealth Rock', 'Protect', 'Flip Turn'],
                    {'hp': 252, 'def': 252}),
        ]
        a = analisar_estrategia(team)
        self.assertIn('Chuva', a['estrategia'])
        self.assertTrue(any('Barraskewda' in x for x in a['sinergias']))
        self.assertIn('Pivô', a['funcoes'][0]['funcoes'])
        self.assertIn('Aproveita chuva', a['funcoes'][1]['funcoes'])
        self.assertTrue(a['plano'])

    def test_unfamiliar_and_manual_mislabel_do_not_force_archetype(self):
        team = [
            pokemon('Zoroark', 'Focus Sash', 'Illusion',
                    ['Nasty Plot', 'Dark Pulse', 'Flamethrower'], {'spa': 252, 'spe': 252}),
            pokemon('Ditto', 'Choice Scarf', 'Imposter',
                    ['Transform'], {'hp': 252}),
        ]
        team[0]['papel'] = 'Hazard Setter'
        a = analisar_estrategia(team, 'gen9anything')
        self.assertEqual(a['estrategia'], 'Ofensiva com setup')
        self.assertFalse(any('Colocador de hazards' in m['funcoes'] for m in a['funcoes']))
        self.assertEqual(len(a['funcoes']), 2)

    def test_empty_and_malformed_slots_are_safe(self):
        self.assertEqual(analisar_estrategia(None)['funcoes'], [])
        self.assertEqual(analisar_estrategia([{}, None, {'pokemon': ''}])['funcoes'], [])
        self.assertEqual(len(analisar_estrategia([
            {'pokemon': 'Pikachu', 'evs': {'spa': 'not a number'}, 'moves': []}
        ])['funcoes']), 1)

    def test_preview_route_and_templates_are_wired_and_compile(self):
        module = (ROOT / 'modules/competitive_features.py').read_text(encoding='utf-8')
        ast.parse(module)
        self.assertIn("methods=['POST']", module)
        self.assertIn('def previa_estrategia():', module)
        self.assertIn('analisar_estrategia(slots, formato_codigo)', module)
        self.assertIn("'estrategia_inteligente': inteligente", module)
        builder = (ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        report = (ROOT / 'templates/team_analise.html').read_text(encoding='utf-8')
        for fragment in ('id="hypeStrategyPreview"', 'function scheduleStrategyPreview()',
                         'competitive.previa_estrategia', 'X-CSRFToken',
                         'occupied.map(cleanForStorage)', 'strategyElement(',
                         'scheduleStrategyPreview();'):
            self.assertIn(fragment, builder)
        self.assertIn('analise.estrategia_inteligente', report)
        self.assertIn('Função de cada Pokémon', report)
        self.assertIn('hype_team_strategy.css', report)
        for template in ('team_builder.html', 'team_analise.html'):
            env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')),
                              autoescape=True)
            self.assertIsNotNone(env.get_template(template))


if __name__ == '__main__':
    unittest.main()
