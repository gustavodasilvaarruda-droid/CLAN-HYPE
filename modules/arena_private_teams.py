"""Primeira integração de equipes privadas da Arena HYPE 3.0.

Validação conservadora: verifica estrutura e proibições resumidas do preset.
NÃO substitui o validador oficial de legalidade do Pokémon Showdown e nunca
autoriza inscrição/aprovação automática.
"""
import re
from modules.hype_tournament_formats import obter_formato, obter_especie_showdown

STATS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
TERA_TYPES = frozenset(('normal', 'fire', 'water', 'electric', 'grass', 'ice',
                         'fighting', 'poison', 'ground', 'flying', 'psychic', 'bug',
                         'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy',
                         'stellar'))

# Poké Balls são itens de captura, não opções apropriadas ao Team Builder competitivo.
# Não usa terminações como "-ball": Light Ball e Iron Ball são itens válidos.
BOLAS_CAPTURA = frozenset({
    'pokeball', 'greatball', 'ultraball', 'masterball', 'premierball',
    'healball', 'luxuryball', 'friendball', 'levelball', 'lureball',
    'heavyball', 'loveball', 'moonball', 'fastball', 'sportball',
    'safariball', 'duskball', 'diveball', 'netball', 'nestball',
    'timerball', 'repeatball', 'quickball', 'dreamball', 'beastball',
    'cherishball', 'parkball',
})


# Pedras de Mega Evolução vinculadas à espécie-base. Uma pedra de outra
# espécie não deve aparecer nem ser aceita em um set de torneio.
MEGA_STONE_OWNERS = {
    'abomasite': 'abomasnow', 'absolite': 'absol', 'aerodactylite': 'aerodactyl',
    'aggronite': 'aggron', 'alakazite': 'alakazam', 'altarianite': 'altaria',
    'ampharosite': 'ampharos', 'audinite': 'audino', 'banettite': 'banette',
    'beedrillite': 'beedrill', 'blastoisinite': 'blastoise', 'blazikenite': 'blaziken',
    'cameruptite': 'camerupt', 'charizarditex': 'charizard', 'charizarditey': 'charizard',
    'diancite': 'diancie', 'galladite': 'gallade', 'garchompite': 'garchomp',
    'gardevoirite': 'gardevoir', 'gengarite': 'gengar', 'glalitite': 'glalie',
    'gyaradosite': 'gyarados', 'heracronite': 'heracross', 'houndoominite': 'houndoom',
    'kangaskhanite': 'kangaskhan', 'latiasite': 'latias', 'latiosite': 'latios',
    'lopunnite': 'lopunny', 'lucarionite': 'lucario', 'manectite': 'manectric',
    'mawilite': 'mawile', 'medichamite': 'medicham', 'metagrossite': 'metagross',
    'pinsirite': 'pinsir', 'sablenite': 'sableye', 'salamencite': 'salamence',
    'sceptilite': 'sceptile', 'scizorite': 'scizor', 'sharpedonite': 'sharpedo',
    'slowbronite': 'slowbro', 'steelixite': 'steelix', 'swampertite': 'swampert',
    'tyranitarite': 'tyranitar', 'venusaurite': 'venusaur',
}


def codigo_formato_do_torneio(regras):
    texto = str(regras or '')
    match = re.search(r'^Identificador Pokémon Showdown:\s*([a-z0-9]+)\s*$', texto, re.I | re.M)
    if not match:
        return None
    formato = obter_formato(match.group(1))
    return formato['codigo'] if formato else None


def _chave(texto):
    return re.sub(r'[^a-z0-9]', '', str(texto or '').casefold())


def _id_especie(texto):
    """Trata formas '-Base' como a espécie padrão para os bans explícitos."""
    chave = _chave(texto)
    return chave[:-4] if chave.endswith('base') else chave


def _tier_banida(especie, formato):
    meta = obter_especie_showdown(especie)
    if not meta:
        return None
    modo = formato.get('tipo_batalha')
    coluna = ('nd' if 'nationaldex' in formato['codigo'] else
              'doubles' if modo == 'doubles' else 'tier')
    # Algumas formas (ex.: Arceus-Fairy) não repetem a tier no snapshot.
    # O tier da espécie base continua valendo quando a forma não possui tier própria.
    tier = meta.get(coluna) or meta.get('tier') or ''
    if not tier and meta.get('base'):
        base_meta = obter_especie_showdown(meta['base']) or {}
        tier = base_meta.get(coluna) or base_meta.get('tier') or ''
    banidas = {_chave(b.replace('ND ', '')) for b in formato.get('tiers_proibidos', ())}
    if _chave(tier) in banidas:
        return tier
    return None


def _disponibilidade(especie, formato):
    meta = obter_especie_showdown(especie)
    if not meta:
        return 'não consta no Pokédex do Showdown deste snapshot'
    if not 'nationaldex' in formato['codigo']:
        if meta.get('nonstandard') in ('Past', 'Future', 'Unobtainable', 'CAP', 'LGPE'):
            return 'não está disponível nesta geração/formato'
        if meta.get('tier') == 'Illegal':
            return 'não é legal neste formato de Geração 9'
    if formato.get('little_cup') and (meta.get('prevo') or not meta.get('evos')):
        return 'não atende às condições de Little Cup (primeira evolução com evolução possível)'
    if formato.get('nfe') and (not meta.get('prevo') or not meta.get('evos')):
        return 'não atende às condições de NFE'
    tier = _tier_banida(especie, formato)
    if tier:
        return f'pertence à tier proibida {tier}'
    if _id_especie(especie) in {_id_especie(p) for p in formato.get('pokemons_proibidos', ())}:
        return 'foi banido explicitamente'
    return None



def motivo_pokemon_indisponivel(especie, codigo_formato):
    """Filtro preliminar para a lista visual. Nunca certifica legalidade plena."""
    formato = obter_formato(codigo_formato)
    if not formato:
        return 'formato não cadastrado'
    return _disponibilidade(especie, formato)


def validar_equipe_basica(slots, codigo_formato):
    """Lista erros sem declarar legalidade completa. Exige 6 sets completos."""
    formato = obter_formato(codigo_formato)
    if not formato:
        return ['Formato não cadastrado para revisão de equipes.']
    tamanho = int(formato.get('tamanho_equipe') or 6)
    if not isinstance(slots, list) or len(slots) != tamanho:
        return [f'O time desse formato precisa conter exatamente {tamanho} Pokémon.']

    banidos = {_id_especie(p) for p in formato.get('pokemons_proibidos', ())}
    golpes_banidos = {_chave(m) for m in formato.get('golpes_proibidos', ())}
    itens_banidos = {_chave(m) for m in formato.get('itens_proibidos', ())}
    habilidades_banidas = {_chave(m) for m in formato.get('habilidades_proibidas', ())}
    usados = set()
    itens_usados = set()
    erros = []
    for indice, slot in enumerate(slots, 1):
        if not isinstance(slot, dict):
            erros.append(f'Slot {indice}: dados inválidos.')
            continue
        especie = str(slot.get('pokemon') or '').strip()
        chave = _chave(especie)
        if not chave or len(especie) > 80:
            erros.append(f'Slot {indice}: escolha um Pokémon válido.')
        elif chave in banidos:
            erros.append(f'Slot {indice}: {especie} não é permitido neste formato.')
        else:
            restricao = _disponibilidade(especie, formato)
            if restricao:
                erros.append(f'Slot {indice}: {especie} {restricao}.')
        # Species Clause vale pela espécie nacional, inclusive formas regionais
        # e formas alternativas com nomes diferentes.
        meta_especie = obter_especie_showdown(especie) or {}
        numero_dex = meta_especie.get('num')
        especie_identidade = numero_dex if type(numero_dex) is int and numero_dex > 0 else chave
        if formato.get('species_clause', True) and especie_identidade in usados:
            erros.append(f'Slot {indice}: espécies repetidas não são permitidas.')
        usados.add(especie_identidade)

        nivel_max = int(formato.get('nivel_maximo') or 100)
        nivel = slot.get('level', 5 if formato.get('little_cup') else 100)
        if type(nivel) is not int or not 1 <= nivel <= nivel_max:
            erros.append(f'Slot {indice}: nível fora do limite de {nivel_max} do formato.')
        item = str(slot.get('item') or '').strip()
        item_id = _chave(item)
        if item_id in BOLAS_CAPTURA:
            erros.append(f'Slot {indice}: {item} é uma Poké Ball de captura e não está disponível na Arena HYPE.')
        if item_id in itens_banidos:
            erros.append(f'Slot {indice}: o item {item} é proibido no formato.')
        if formato.get('item_clause') and item_id and item_id in itens_usados:
            erros.append(f'Slot {indice}: Item Clause proíbe itens repetidos.')
        if item_id:
            itens_usados.add(item_id)
        if item_id in MEGA_STONE_OWNERS and not formato.get('permite_mega', False):
            erros.append(f'Slot {indice}: Mega Stones são proibidas neste formato.')
        if item_id.endswith('iumz') and not formato.get('permite_zmove', False):
            erros.append(f'Slot {indice}: Z-Crystals são proibidos neste formato.')
        base = chave.split('mega')[0] if 'mega' in chave else chave
        if item_id in MEGA_STONE_OWNERS and base != MEGA_STONE_OWNERS[item_id]:
            erros.append(f'Slot {indice}: {item} é proibido para {especie}: a pedra não corresponde à espécie.')
        mecanica = _chave(slot.get('mecanica') or 'nenhuma')
        tera_ativa = bool(slot.get('tera_ativa', False)) or mecanica == 'tera'
        if tera_ativa and not formato.get('permite_tera', False):
            erros.append(f'Slot {indice}: Terastalização proibida neste formato.')
        if tera_ativa and mecanica == 'mega':
            erros.append(f'Slot {indice}: a forma Mega não pode Terastalizar.')
        if tera_ativa and not str(slot.get('tera_type') or '').strip():
            erros.append(f'Slot {indice}: escolha um Tera Type.')
        flags = {'mega': 'permite_mega', 'zmove': 'permite_zmove',
                 'tera': 'permite_tera', 'dynamax': 'permite_dynamax'}
        if mecanica not in ('nenhuma', *flags):
            erros.append(f'Slot {indice}: mecânica desconhecida.')
        elif mecanica in flags and not formato.get(flags[mecanica], False):
            erros.append(f'Slot {indice}: a mecânica {mecanica} não é permitida neste formato.')
        if mecanica == 'mega' and (item_id not in MEGA_STONE_OWNERS or
                                   MEGA_STONE_OWNERS.get(item_id) != base):
            erros.append(f'Slot {indice}: Mega Evolução exige a Mega Stone correta.')
        if mecanica == 'mega':
            forma = base + 'mega'
            if item_id in ('charizarditex', 'charizarditey'):
                forma += item_id[-1]
            if (restricao := _disponibilidade(forma, formato)):
                erros.append(f'Slot {indice}: a Mega Evolução de {especie} {restricao}.')
        tera = str(slot.get('tera_type') or '').strip()
        if tera and not formato.get('permite_tera', False):
            erros.append(f'Slot {indice}: Terastalização não é permitida neste formato.')
        if tera and _chave(tera) not in TERA_TYPES:
            erros.append(f'Slot {indice}: Tera Type inválido.')
        if _chave(slot.get('ability')) in habilidades_banidas:
            erros.append(f"Slot {indice}: habilidade {slot.get('ability')} proibida no formato.")
        for campo, rotulo in (('ability', 'habilidade'), ('nature', 'natureza')):
            valor = str(slot.get(campo) or '').strip()
            if not valor or len(valor) > 100:
                erros.append(f'Slot {indice}: informe a {rotulo}.')
        movimentos = slot.get('moves')
        if not isinstance(movimentos, list) or len(movimentos) != 4 or any(not str(x or '').strip() for x in movimentos):
            erros.append(f'Slot {indice}: selecione quatro golpes.')
        else:
            if len({_chave(m) for m in movimentos}) != 4:
                erros.append(f'Slot {indice}: golpes duplicados.')
            for movimento in movimentos:
                if _chave(movimento) in golpes_banidos:
                    erros.append(f'Slot {indice}: o golpe {movimento} é proibido.')
        for campo, limite in (('evs', 252), ('ivs', 31)):
            valores = slot.get(campo)
            if not isinstance(valores, dict):
                erros.append(f'Slot {indice}: {campo.upper()} inválidos.')
                continue
            total = 0
            for stat in STATS:
                valor = valores.get(stat, 0 if campo == 'evs' else 31)
                if type(valor) is not int or not 0 <= valor <= limite:
                    erros.append(f'Slot {indice}: {campo.upper()} de {stat} fora dos limites.')
                else:
                    total += valor
            if campo == 'evs' and total > 510:
                erros.append(f'Slot {indice}: mais de 510 EVs.')
    return erros[:25]
