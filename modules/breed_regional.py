"""Catálogo das formas regionais e regras de Pokémon-alvo do Breed.

Uma forma regional tem ID de Pokémon próprio (ex.: Vulpix Alola 10103) mas
compartilha o species_id com a espécie original (Vulpix 37).

Um Pokémon bebê não reproduz diretamente, porém pode ser produzido pelos
breeders a partir de uma evolução compatível. Isso NÃO libera outros
Pokémon com Egg Group 'no-eggs', lendários ou míticos.
"""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def regional_forms():
    file = Path(__file__).resolve().parents[1] / 'static' / 'breed_regional_forms.json'
    data = json.loads(file.read_text(encoding='utf-8'))
    valid_regions = {'alola', 'galar', 'hisui', 'paldea'}
    found = {}
    for x in data.get('forms', []):
        fid, sid, name, region = int(x['id']), int(x['species_id']), str(x['name']), str(x['region'])
        if not fid >= 10000 or sid <= 0 or region not in valid_regions or fid in found:
            raise ValueError('Catálogo regional inválido ou com IDs repetidos')
        found[fid] = {'id': fid, 'species_id': sid, 'name': name, 'region': region}
    return found


def regional_form(pokemon_id):
    return regional_forms().get(int(pokemon_id))


def breed_species_id(pokemon_id):
    form = regional_form(pokemon_id)
    return form['species_id'] if form else int(pokemon_id)


def pokemon_form_valid(pokemon_id, name):
    """Não aceitar ID de Mega/forma não cadastrada nem nome regional adulterado."""
    fid = int(pokemon_id)
    form = regional_form(fid)
    if form:
        return str(name or '').strip().lower() == form['name']
    return 0 < fid < 10000


def breed_target_allowed(is_baby, is_legendary, is_mythical, no_eggs):
    # Bebe é uma exceção SOMENTE como resultado do pedido; não como progenitor.
    return not (is_legendary or is_mythical) and (is_baby or not no_eggs)


def form_display_name(name, region=None):
    name = str(name or '').strip()
    if region:
        suffix = '-' + region
        if name.endswith(suffix):
            return name[:-len(suffix)].replace('-', ' ').title() + ' (' + region.title() + ')'
        if region == 'paldea' and '-paldea-' in name:
            base, style = name.split('-paldea-', 1)
            return base.replace('-', ' ').title() + ' (Paldea - ' + style.replace('-', ' ').title() + ')'
    return name.replace('-', ' ').title()
