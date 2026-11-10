"""Regressões do Team Builder: formatos, itens e privacidade do torneio."""
import ast
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from modules.arena_private_teams import validar_equipe_basica
from modules.hype_tournament_formats import obter_formato

ROOT = Path(__file__).resolve().parents[1]


class TestHypeTeamBuilderUX(unittest.TestCase):
    def test_builder_route_parses_and_locks_tournament_format(self):
        source = (ROOT / 'modules/expansion_features.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn('for preset in formatos_disponiveis():', source)
        self.assertIn("codigo_formato_do_torneio(torneio.get('regras'))", source)
        self.assertIn('formato_codigo = torneio_formato_codigo or', source)
        self.assertIn('torneio_formato_codigo=torneio_formato_codigo', source)

    def test_template_compiles_and_shows_visual_search(self):
        env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')), autoescape=True)
        self.assertIsNotNone(env.get_template('team_builder.html'))
        template = (ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        for marker in ('id="itemSelectedIcon"', 'id="itemOptions"',
                       'id="pokemonOptions"', 'role="combobox"',
                       'id="formatSelect"', 'name="torneio_id"'):
            self.assertIn(marker, template)
        self.assertNotIn("fetch('https://pokeapi.co/api/v2/item?limit=2500')", template)
        self.assertIn('hype_team_builder_modern.css', template)
        self.assertIn('disabled aria-label="Formato fixo do torneio"', template)
        # Exportação em texto Showdown, sem afirmar aprovação automática.
        for marker in ('id="exportShowdownBtn"', 'id="showdownExportText"',
                       'exportShowdownText()', "rows.push('EVs: '+ev)",
                       'A exportação não comprova a legalidade da equipe'):
            self.assertIn(marker, template)
        for marker in ('evRemaining', 'limitEvInput', 'selectableItems', 'data-edit-build', 'data-preview-build', 'data-duplicate-build', 'id="teraEnabled"', 'recommendedItems', 'teamSize', 'refreshMegaDisplay'):
            self.assertIn(marker, template)

    def test_inline_javascript_parses_in_node_when_available(self):
        if not shutil.which('node'):
            self.skipTest('Node indisponível neste ambiente')
        template=(ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        js=template.split('<script>',1)[1].split('</script>',1)[0]
        js=re.sub(r'{{[^{}]*}}', 'null', js)
        result=subprocess.run(['node','--check'], input=js, text=True,
                              capture_output=True, timeout=12)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_tournament_format_is_frozen_after_private_team(self):
        app=(ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("'formato_codigo': preset['codigo'] if preset else", app)
        bloco=app[app.index('def editar_torneio('):app.index('def participantes_torneio(',app.index('def editar_torneio('))]
        self.assertIn("preset_atual = codigo_formato_do_torneio",bloco)
        self.assertIn("_safe_table('arena_torneio_equipes', 'id', torneio_id=item_id)",bloco)
        self.assertIn("if not estrutura_bloqueada and not preset_atual:",bloco)

    def test_capture_balls_denied_and_legitimate_items_left_alone(self):
        data = []
        for p in ('Dialga', 'Palkia', 'Kyogre', 'Groudon', 'Lugia', 'Ho-Oh'):
            data.append({
                'pokemon': p, 'ability': 'Pressure', 'nature': 'Timid',
                'item': 'Leftovers',
                'moves': ['Recover', 'Protect', 'Rest', 'Sleep Talk'],
                'evs': {k: 0 for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')},
                'ivs': {k: 31 for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')}
            })
        self.assertIsNotNone(obter_formato('gen9nationaldexubers'))
        self.assertEqual(validar_equipe_basica(data, 'gen9nationaldexubers'), [])
        data[0]['item'] = 'Master Ball'
        errors = validar_equipe_basica(data, 'gen9nationaldexubers')
        self.assertTrue(any('Master Ball' in error for error in errors))
        data[0]['item'] = 'Ultra Ball'
        self.assertTrue(any('Ultra Ball' in e for e in validar_equipe_basica(data, 'gen9nationaldexubers')))
        data[0]['item'] = 'Light Ball'
        self.assertEqual(validar_equipe_basica(data, 'gen9nationaldexubers'), [])


if __name__ == '__main__':
    unittest.main()
