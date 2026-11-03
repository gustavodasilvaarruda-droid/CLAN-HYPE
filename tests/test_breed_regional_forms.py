"""Regressões da etapa 1 do Breed: formas regionais e bebês.

Roda sem importar o Flask e sem acessar Supabase ou internet.
Valida as funções REAIS de app.py usando AST e fontes PokéAPI simuladas.
"""
import ast
import io
import json
from functools import lru_cache
from pathlib import Path
import unittest
from unittest.mock import Mock

from modules.breed_regional import (
    regional_forms, regional_form, breed_species_id, pokemon_form_valid,
    breed_target_allowed, form_display_name,
)


APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'


def extracted(name, globals_dict):
    tree = ast.parse(APP_PATH.read_text(encoding='utf-8'))
    func = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name)
    namespace = dict(globals_dict, lru_cache=lru_cache)
    code = compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])),
                   str(APP_PATH), 'exec')
    exec(code, namespace)
    return namespace[name]


class BreedRegionalCatalogTests(unittest.TestCase):
    def test_all_four_regions_and_unique_ids(self):
        forms = regional_forms()
        self.assertGreaterEqual(len(forms), 55)
        self.assertEqual(set(f['region'] for f in forms.values()),
                         {'alola', 'galar', 'hisui', 'paldea'})
        self.assertEqual(len(forms), len(set(forms)))

    def test_known_forms_and_species_id(self):
        for fid, species, name in (
            (10103, 37, 'vulpix-alola'),
            (10173, 222, 'corsola-galar'),
            (10238, 570, 'zorua-hisui'),
            (10253, 194, 'wooper-paldea'),
            (10250, 128, 'tauros-paldea-combat-breed')
        ):
            with self.subTest(name=name):
                self.assertEqual(breed_species_id(fid), species)
                self.assertEqual(regional_form(fid)['name'], name)
                self.assertTrue(pokemon_form_valid(fid, name))

    def test_cannot_spoof_form_or_choose_mega(self):
        self.assertFalse(pokemon_form_valid(10103, 'vulpix'))
        self.assertFalse(pokemon_form_valid(10103, 'vulpix-hisui'))
        self.assertFalse(pokemon_form_valid(10034, 'charizard-mega-x'))
        self.assertTrue(pokemon_form_valid(37, 'vulpix'))

    def test_display_name_marks_region(self):
        self.assertEqual(form_display_name('vulpix-alola', 'alola'), 'Vulpix (Alola)')
        self.assertIn('Paldea', form_display_name('tauros-paldea-blaze-breed', 'paldea'))

    def test_babies_target_allowed_but_other_no_eggs_are_not(self):
        self.assertTrue(breed_target_allowed(True, False, False, True))
        self.assertTrue(breed_target_allowed(False, False, False, False))
        self.assertFalse(breed_target_allowed(False, False, False, True))
        self.assertFalse(breed_target_allowed(True, True, False, True))
        self.assertFalse(breed_target_allowed(True, False, True, True))


class BreedBackendRuleTests(unittest.TestCase):
    def species_rule(self, data, expected_id):
        seen = []
        def fake_open(url, timeout=4):
            seen.append(url)
            self.assertIn(f'/pokemon-species/{expected_id}/', url)
            class Response:
                def __enter__(self): return self
                def __exit__(self, *_): return False
                def read(self): return json.dumps(data).encode('utf-8')
            return Response()
        fn = extracted('_pokeapi_species_rule', {
            'urlopen': fake_open, 'json': json,
            'breed_species_id': breed_species_id,
            'breed_target_allowed': breed_target_allowed,
            '_pokeapi_csv': lambda _: [],
        })
        return fn, seen

    def test_regional_uses_original_species_not_form_id(self):
        rule, seen = self.species_rule({
            'egg_groups': [{'name': 'field'}], 'is_baby': False,
            'is_legendary': False, 'is_mythical': False, 'gender_rate': 4,
        }, 37)
        out = rule(10103)
        self.assertTrue(out['breedavel'])
        self.assertEqual(len(seen), 1)

    def test_baby_pichu_allowed_although_no_eggs(self):
        rule, _ = self.species_rule({
            'egg_groups': [{'name': 'no-eggs'}], 'is_baby': True,
            'is_legendary': False, 'is_mythical': False, 'gender_rate': 4,
        }, 172)
        out = rule(172)
        self.assertTrue(out['breedavel'])
        self.assertTrue(out['is_baby'])

    def test_legendary_and_other_nonbreeders_rejected(self):
        for legend, mythical, baby in ((True, False, False), (False, True, False),
                                       (False, False, False)):
            with self.subTest(legend=legend, mythical=mythical):
                rule, _ = self.species_rule({
                    'egg_groups': [{'name': 'no-eggs'}], 'is_baby': baby,
                    'is_legendary': legend, 'is_mythical': mythical,
                    'gender_rate': -1,
                }, 144)
                self.assertFalse(rule(144)['breedavel'])

    def test_fail_closed_when_both_sources_offline(self):
        def dead(*_args, **_kwargs): raise OSError('offline')
        rule = extracted('_pokeapi_species_rule', {
            'urlopen': dead, 'json': json,
            'breed_species_id': breed_species_id,
            'breed_target_allowed': breed_target_allowed,
            '_pokeapi_csv': lambda _: [],
        })
        self.assertIsNone(rule(10103))

    def rule(self, species, bans=()):
        # O registro de preço é simulado; a função de regra real é extraída de app.py.
        return extracted('regra_breed_pokemon', {
            'pokemon_form_valid': pokemon_form_valid, 'breed_species_id': breed_species_id,
            'regional_form': regional_form, '_safe_table': lambda *_args, **_kw:
                [{'pokemon': x, 'ativo': True} for x in bans],
            'classificar_pokemon_preco': lambda _id: {
                'so_com_ditto': False, 'categoria': 'comum',
                'categoria_label': 'Comum'
            },
            '_pokeapi_species_rule': lambda _id: dict(species),
        })

    def test_baby_can_be_requested_and_is_identified(self):
        r = self.rule({
            'breedavel': True, 'is_baby': True, 'is_legendary': False,
            'is_mythical': False, 'egg_groups': ['no-eggs'], 'nome': 'pichu',
        })(172, 'pichu')
        self.assertTrue(r['breedavel'])
        self.assertTrue(r['is_baby'])
        self.assertIn('evoluções', r['nota_bebe'])

    def test_legendary_form_galar_remains_blocked(self):
        r = self.rule({
            'breedavel': False, 'is_baby': False, 'is_legendary': True,
            'is_mythical': False, 'egg_groups': ['no-eggs'],
            'nome': 'articuno',
        })(10169, 'articuno-galar')
        self.assertFalse(r['breedavel'])
        self.assertEqual(r['categoria_bloqueio'], 'legendary')

    def test_manual_base_species_ban_applies_to_alola(self):
        r = self.rule({
            'breedavel': True, 'is_baby': False, 'is_legendary': False,
            'is_mythical': False, 'egg_groups': ['field'], 'nome': 'vulpix',
        }, ['vulpix'])(10103, 'vulpix-alola')
        self.assertFalse(r['breedavel'])
        self.assertEqual(r['categoria_bloqueio'], 'manual')

    def test_wrong_form_name_denied_before_looking_up_price(self):
        r = self.rule({})(10103, 'vulpix-galar')
        self.assertFalse(r['breedavel'])
        self.assertEqual(r['categoria_bloqueio'], 'forma_invalida')


class BreedFrontendSelectionTests(unittest.TestCase):
    def test_step_preview_nodes_are_iterated_as_collections(self):
        # Regression: querySelector returns one element, not a NodeList.
        src = (Path(__file__).resolve().parents[1] / 'templates/breed.html').read_text(encoding='utf-8')
        self.assertIn("$('.selectedPokemonArt').forEach", src)
        self.assertIn("$('.selectedPokemonName').forEach", src)
        self.assertNotIn("$" + "('.selectedPokemonArt').forEach", src.replace("$(", "COLLECTION("))
        self.assertNotIn("$" + "('.selectedPokemonName').forEach", src.replace("$(", "COLLECTION("))

    def test_next_button_unblocks_before_optional_pokeapi_metadata(self):
        src = (Path(__file__).resolve().parents[1] / 'templates/breed.html').read_text(encoding='utf-8')
        selection = src.split('async function selectPokemon(', 1)[1].split('function renderDetail(', 1)[0]
        self.assertIn('if(!info.breedavel)', selection)
        self.assertIn("$('#pokemonNext').disabled=false", selection)
        self.assertIn('enrichPokemonInfoClient(id,info).then(', selection)
        self.assertNotIn('await enrichPokemonInfoClient(', selection)


if __name__ == '__main__':
    unittest.main()
