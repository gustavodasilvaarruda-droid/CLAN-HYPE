"""Regressões determinísticas do motor de batalha HYPE v3 (sem Supabase)."""
from copy import deepcopy
import unittest

from modules.hype_tactical_intelligence import (
    dex, analisar_avancado, _stats, _speed, _type_multiplier, _damage,
)


def mon(pokemon, item='', ability='', nature='Serious', moves=None,
        evs=None, ivs=None, level=100, tera_type=''):
    return {'pokemon':pokemon, 'item':item, 'ability':ability, 'nature':nature,
            'moves':moves or [],'evs':evs or {},'ivs':ivs or {},
            'level':level,'tera_type':tera_type,
            'tera_ativa':bool(tera_type),'papel':''}


class TacticalIntelligenceTests(unittest.TestCase):
    def test_showdown_compact_catalog_is_consistent(self):
        data=dex()
        self.assertGreaterEqual(len(data['species']), 1400)
        self.assertGreaterEqual(len(data['moves']), 900)
        self.assertEqual(data['species']['charizardmegay']['spa'],159)
        self.assertEqual(data['species']['venusaur']['spe'],80)
        self.assertEqual(data['moves']['flamethrower']['p'],90)
        self.assertEqual(data['moves']['swordsdance']['c'],'T')
        self.assertEqual(data['moves']['flamethrower']['c'],'S')

    def test_stat_formula_mega_and_chlorophyll(self):
        z=mon('Charizard','Charizardite Y','Drought','Timid',
              ['Flamethrower','Solar Beam','Focus Blast','Roost'],
              {'spa':252,'spd':4,'spe':252},{'atk':0})
        venusaur=mon('Venusaur','Life Orb','Chlorophyll','Modest',
                     ['Giga Drain','Sludge Bomb','Weather Ball','Growth'],
                     {'spa':252,'spd':4,'spe':252},{'atk':0})
        zstats,source=_stats(z)
        self.assertEqual(source,'Showdown')
        self.assertEqual(zstats['spa'],417)
        self.assertEqual(zstats['spe'],328)
        vs,_=_stats(venusaur)
        self.assertEqual(vs['spa'],328)
        self.assertEqual(vs['spe'],259)
        self.assertEqual(_speed(venusaur,vs,'sun'),518)
        report=analisar_avancado([z,venusaur],'gen9nationaldexou')
        self.assertEqual(report['clima'],'Sol')
        self.assertEqual(report['atributos'][0]['forma'],'Charizard-Mega-Y')
        self.assertEqual(report['atributos'][1]['speed_efetiva'],518)
        self.assertEqual(venusaur['ability'],'Chlorophyll')

    def test_defense_immunities_and_tera_are_conditional(self):
        rotom=mon('Rotom-Wash','Leftovers','Levitate')
        ferrothorn=mon('Ferrothorn','Leftovers','Iron Barbs')
        garchomp=mon('Garchomp','Rocky Helmet','Rough Skin')
        self.assertEqual(_type_multiplier('ground',rotom),0)
        self.assertEqual(_type_multiplier('fire',ferrothorn),4)
        self.assertEqual(_type_multiplier('ice',garchomp),4)
        self.assertEqual(_type_multiplier('electric',garchomp),0)
        terra=mon('Charizard','Charizardite Y','Drought',tera_type='Water')
        self.assertEqual(_type_multiplier('rock',terra),4)
        self.assertEqual(_type_multiplier('rock',terra,as_tera=True),1)
        self.assertEqual(_type_multiplier('electric',terra,as_tera=True),2)

    def test_item_ability_conflicts_and_synergies(self):
        team=[
            mon('Garchomp','Rocky Helmet','Rough Skin','Jolly',
                ['Earthquake','Swords Dance'],{'atk':252,'spe':252}),
            mon('Ferrothorn','Assault Vest','Iron Barbs','Relaxed',
                ['Stealth Rock','Leech Seed','Power Whip'],{'hp':252,'def':252}),
            mon('Excadrill','Choice Scarf','Mold Breaker','Jolly',
                ['Earthquake','Rapid Spin','Swords Dance'],{'atk':252,'spe':252}),
        ]
        orig=deepcopy(team)
        report=analisar_avancado(team)
        self.assertEqual(orig,team)
        names=[x['titulo'] for x in report['interacoes']]
        self.assertIn('Rough Skin + Rocky Helmet',names)
        self.assertIn('Assault Vest impede golpes de status',names)
        self.assertIn('Item Choice conflita com setup',names)

    def test_damage_ranges_are_bounded_and_conditional(self):
        attacker=mon('Charizard','Charizardite Y','Drought','Timid',
                     ['Flamethrower','Focus Blast'],{'spa':252,'spe':252})
        target=mon('Ferrothorn','Leftovers','Iron Barbs','Impish',
                   ['Stealth Rock'],{'hp':252,'def':252})
        sun=_damage(attacker,target,'Flamethrower','sun')
        dry=_damage(attacker,target,'Flamethrower','')
        self.assertIsNotNone(sun)
        self.assertGreater(sun['max_pct'],dry['max_pct'])
        self.assertGreaterEqual(sun['max_pct'],sun['min_pct'])
        self.assertIsNone(_damage(attacker,target,'Dragon Dance','sun'))
        levitate=mon('Rotom-Wash','Leftovers','Levitate')
        ground=mon('Garchomp','','Rough Skin','Jolly',['Earthquake'],
                   {'atk':252,'spe':252})
        self.assertTrue(_damage(ground,levitate,'Earthquake')['imune'])
        self.assertIsNone(_damage(ground,target,'Scale Shot'))

    def test_tera_conditional_differences_are_reported_separately(self):
        team=[mon('Charizard','Charizardite Y','Drought','Timid',
                  ['Flamethrower'],{'spa':252,'spe':252},tera_type='Water')]
        report=analisar_avancado(team)
        self.assertEqual(len(report['tera_cenarios']),1)
        scenario=report['tera_cenarios'][0]
        self.assertEqual(scenario['tera'],'Water')
        self.assertIn('Pedra',scenario['melhorias'])
        self.assertIn('Planta',scenario['riscos'])
        self.assertIn('hipotética',scenario['nota'])

    def test_custom_opponent_team_renders_factual_duels(self):
        us=[
            mon('Charizard','Charizardite Y','Drought','Timid',
                ['Flamethrower'],{'spa':252,'spe':252}),
            mon('Venusaur','Life Orb','Chlorophyll','Modest',
                ['Giga Drain'],{'spa':252,'spe':252}),
        ]
        enemy=[
            mon('Ferrothorn','Leftovers','Iron Barbs','Impish',
                ['Stealth Rock'],{'hp':252,'def':252}),
            mon('Rotom-Wash','Leftovers','Levitate','Bold',
                ['Volt Switch'],{'hp':252,'def':200}),
        ]
        report=analisar_avancado(us,'gen9nationaldexou',enemy)
        self.assertEqual(report['adversarios'],2)
        self.assertTrue(report['confrontos'])
        self.assertTrue(report['confrontos_recebidos'])
        self.assertTrue(any(c['contra']=='Charizard' for c in report['confrontos_recebidos']))
        self.assertTrue(any(c['contra']=='Ferrothorn' and c['atacante']=='Charizard'
                            for c in report['confrontos']))
        self.assertTrue(report['nota_dano'].startswith('Estimativa simplificada'))

if __name__=='__main__':
    unittest.main()
