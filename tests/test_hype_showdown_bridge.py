"""Contrato da integração com o TeamValidator, sem depender do Node na CI."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.hype_showdown_bridge import validar_time_showdown

ROOT = Path(__file__).resolve().parents[1]


def team():
    return [{
        'pokemon': 'Metagross', 'item': 'Metagrossite',
        'ability': 'Clear Body', 'nature': 'Jolly',
        'mecanica': 'mega', 'moves': ['Meteor Mash','Zen Headbutt','Bullet Punch','Earthquake'],
        'evs': {k: (252 if k in ('atk', 'spe') else 0) for k in ('hp','atk','def','spa','spd','spe')},
        'ivs': {k: 31 for k in ('hp','atk','def','spa','spd','spe')},
        'tera_type': '',
    }]


class TestBridge(unittest.TestCase):
    def test_requires_registered_format(self):
        self.assertEqual(validar_time_showdown(team(), 'other-random-format')['status'], 'illegal')

    def test_missing_node_must_not_claim_legal(self):
        with patch('modules.hype_showdown_bridge.shutil.which', return_value=None):
            response = validar_time_showdown(team(), 'gen9nationaldexubers')
        self.assertEqual(response['status'], 'unavailable')

    def test_official_rejection_blocks_and_reports_errors(self):
        with patch('modules.hype_showdown_bridge.shutil.which', return_value='/usr/bin/node'), \
             patch('modules.hype_showdown_bridge.Path.is_dir', return_value=True), \
             patch('modules.hype_showdown_bridge.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps({
                'status':'illegal','errors':['Metagross cannot learn a forbidden move']
            }), '')
            result = validar_time_showdown(team(), 'gen9nationaldexubers')
            self.assertEqual(result['status'], 'illegal')
            self.assertIn('cannot learn', result['errors'][0])
            args = json.loads(run.call_args.kwargs['input'])
            self.assertEqual(args['format'], 'gen9nationaldexubers')
            self.assertEqual(args['slots'][0]['pokemon'], 'Metagross')
            self.assertEqual(args['slots'][0]['item'], 'Metagrossite')
            self.assertNotIn('SUPABASE_SERVICE_ROLE_KEY', run.call_args.kwargs['env'])
            self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_official_success_stays_review_only(self):
        with patch('modules.hype_showdown_bridge.shutil.which', return_value='/usr/bin/node'), \
             patch('modules.hype_showdown_bridge.Path.is_dir', return_value=True), \
             patch('modules.hype_showdown_bridge.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '{"status":"legal","errors":[]}', '')
            self.assertEqual(validar_time_showdown(team(), 'gen9nationaldexubers')['status'], 'legal')
        event = (ROOT / 'modules/events_v26.py').read_text(encoding='utf-8')
        self.assertIn("resultado_oficial = validar_time_showdown(equipe, codigo)", event)
        self.assertIn("resultado_oficial['status'] == 'illegal'", event)
        self.assertIn("'status': 'aguardando_verificacao'", event)

    def test_invalid_output_and_timeouts_fail_closed(self):
        with patch('modules.hype_showdown_bridge.shutil.which', return_value='/usr/bin/node'), \
             patch('modules.hype_showdown_bridge.Path.is_dir', return_value=True), \
             patch('modules.hype_showdown_bridge.subprocess.run', side_effect=subprocess.TimeoutExpired(['node'], 12)):
            self.assertEqual(validar_time_showdown(team(), 'gen9ou')['status'], 'unavailable')

    def test_little_cup_uses_level_five_when_old_slot_has_no_level(self):
        with patch('modules.hype_showdown_bridge.shutil.which', return_value='/usr/bin/node'), \
             patch('modules.hype_showdown_bridge.Path.is_dir', return_value=True), \
             patch('modules.hype_showdown_bridge.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '{"status":"illegal","errors":["Equipe incompleta"]}', '')
            validar_time_showdown(team(), 'gen9lc')
            payload = json.loads(run.call_args.kwargs['input'])
            self.assertEqual(payload['slots'][0]['level'], 5)

    def test_node_script_and_dependency_are_declared(self):
        js = (ROOT / 'scripts/hype_showdown_validate.cjs').read_text(encoding='utf-8')
        package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
        self.assertIn("require('pokemon-showdown')", js)
        self.assertIn('validateTeam(team)', js)
        self.assertEqual(package['dependencies']['pokemon-showdown'], '0.11.11')


if __name__ == '__main__':
    unittest.main()
