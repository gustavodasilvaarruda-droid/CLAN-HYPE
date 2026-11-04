import os
import unittest
from pathlib import Path
from unittest.mock import patch

from jinja2 import Environment
from modules.hype_battle_service import get_battle_client


class BattleRoomServiceTests(unittest.TestCase):
    def tearDown(self):
        get_battle_client.cache_clear()

    def test_service_fails_closed_without_privileged_key(self):
        get_battle_client.cache_clear()
        with patch.dict(os.environ, {
            'SUPABASE_URL': 'https://example.supabase.co',
            'SUPABASE_SERVICE_ROLE_KEY': '',
        }):
            self.assertIsNone(get_battle_client())

    def test_service_fails_closed_without_url(self):
        get_battle_client.cache_clear()
        with patch.dict(os.environ, {
            'SUPABASE_URL': '',
            'SUPABASE_SERVICE_ROLE_KEY': 'fake',
        }):
            self.assertIsNone(get_battle_client())

    def test_template_compiles_and_does_not_expose_player_emails_as_values(self):
        template = Path('templates/sala_batalha.html').read_text(encoding='utf-8')
        Environment().parse(template)
        self.assertIn('name="vencedor_slot"', template)
        self.assertNotIn('name="vencedor_email"', template)
        self.assertNotIn('value="{{partida.jogador1_email}}"', template)
        self.assertNotIn('value="{{partida.jogador2_email}}"', template)
        self.assertIn('sala_disponivel', template)


if __name__ == '__main__':
    unittest.main()
