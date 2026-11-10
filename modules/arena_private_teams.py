"""Primeira integração de equipes privadas da Arena HYPE 3.0.

Validação conservadora: verifica estrutura e proibições resumidas do preset.
NÃO substitui o validador oficial de legalidade do Pokémon Showdown e nunca
autoriza inscrição/aprovação automática.
"""
import re
from modules.hype_tournament_formats import obter_formato

STATS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')

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


def validar_equipe_basica(slots, codigo_formato):
    """Lista erros sem declarar legalidade completa. Exige 6 sets completos."""
    formato = obter_formato(codigo_formato)
    if not formato:
        return ['Formato não cadastrado para revisão de equipes.']
    tamanho = int(formato.get('tamanho_equipe') or 6)
    if not isinstance(slots, list) or len(slots) != tamanho:
        return [f'O time desse formato precisa conter exatamente {tamanho} Pokémon.']

    banidos = {_chave(p) for p in formato.get('pokemons_proibidos', ())}
    golpes_banidos = {_chave(m) for m in formato.get('golpes_proibidos', ())}
    itens_banidos = {_chave(m) for m in formato.get('itens_proibidos', ())}
    usados = set()
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
        if formato.get('species_clause', True) and chave in usados:
            erros.append(f'Slot {indice}: espécies repetidas não são permitidas.')
        usados.add(chave)

        item = str(slot.get('item') or '').strip()
        item_id = _chave(item)
        if item_id in BOLAS_CAPTURA:
            erros.append(f'Slot {indice}: {item} é uma Poké Ball de captura e não está disponível na Arena HYPE.')
        if item_id in itens_banidos:
            erros.append(f'Slot {indice}: o item {item} é proibido no formato.')
        base = chave.split('mega')[0] if 'mega' in chave else chave
        if item_id in MEGA_STONE_OWNERS and base != MEGA_STONE_OWNERS[item_id]:
            erros.append(f'Slot {indice}: {item} não corresponde à espécie {especie}.')
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
        if mecanica == 'mega' and base == 'rayquaza':
            erros.append(f'Slot {indice}: Mega Rayquaza é proibido neste formato.')
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
