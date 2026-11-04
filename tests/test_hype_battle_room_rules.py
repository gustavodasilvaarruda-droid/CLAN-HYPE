import unittest
from modules.battle_room_rules import players, both_ready, agreed_winner


class BattleRoomRulesTests(unittest.TestCase):
    def setUp(self):
        self.match = {'jogador1_email': 'a@example.org', 'jogador2_email': 'b@example.org'}
        self.states = {
            'a@example.org': {'pronto': True, 'vencedor_reportado_email': 'a@example.org'},
            'b@example.org': {'pronto': True, 'vencedor_reportado_email': 'a@example.org'},
        }

    def test_two_players_confirm_winner(self):
        self.assertEqual(players(self.match), ('a@example.org', 'b@example.org'))
        self.assertTrue(both_ready(self.match, self.states))
        self.assertEqual(agreed_winner(self.match, self.states), 'a@example.org')

    def test_disagreement_never_finalizes(self):
        self.states['b@example.org']['vencedor_reportado_email'] = 'b@example.org'
        self.assertIsNone(agreed_winner(self.match, self.states))

    def test_both_must_be_ready(self):
        self.states['b@example.org']['pronto'] = False
        self.assertIsNone(agreed_winner(self.match, self.states))

    def test_invalid_winner_never_finalizes(self):
        for value in ['c@example.org', None]:
            self.states['a@example.org']['vencedor_reportado_email'] = value
            self.states['b@example.org']['vencedor_reportado_email'] = value
            self.assertIsNone(agreed_winner(self.match, self.states))

    def test_bye_and_duplicate_player_do_not_accept_results(self):
        for second in (None, 'a@example.org'):
            match = dict(self.match, jogador2_email=second)
            self.assertEqual(players(match), ())
            self.assertFalse(both_ready(match, self.states))
            self.assertIsNone(agreed_winner(match, self.states))


if __name__ == '__main__':
    unittest.main()
