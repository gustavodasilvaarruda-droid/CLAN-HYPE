"""Primeira integração de equipes privadas da Arena HYPE 3.0.

Validação conservadora: verifica estrutura e proibições resumidas do preset.
NÃO substitui o validador oficial de legalidade do Pokémon Showdown e nunca
autoriza inscrição/aprovação automática.
"""
import re
from modules.hype_tournament_formats import obter_formato, obter_especie_showdown

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



# Banlists explícitas de cláusulas de validação no rulesets.ts do Pokémon
# Showdown (consultado em 2026-11-11). O snapshot possui o nome da cláusula,
# mas não expande automaticamente o que ela proíbe: fazê-lo aqui evita brechas.
_CLAUSULAS_BANS = {
    'sleepmovesclause': {
        'golpes': ('Dark Void', 'Grass Whistle', 'Hypnosis', 'Lovely Kiss',
                   'Sing', 'Sleep Powder', 'Spore', 'Yawn'),
    },
    'evasionabilitiesclause': {
        'habilidades': ('Sand Veil', 'Snow Cloak'),
    },
    'evasionitemsclause': {
        'itens': ('Bright Powder', 'Lax Incense'),
    },
    'evasionmovesclause': {
        'golpes': ('Acupressure', 'Minimize', 'Double Team'),
    },
    'accuracymovesclause': {
        'golpes': ('Flash', 'Kinesis', 'Leaf Tornado', 'Mirror Shot',
                   'Mud Bomb', 'Mud-Slap', 'Muddy Water', 'Night Daze',
                   'Octazooka', 'Sand Attack', 'Smokescreen'),
    },
    'ohkoclause': {
        'golpes': ('Fissure', 'Guillotine', 'Horn Drill', 'Sheer Cold'),
    },
}


def _bans_de_clausulas(formato):
    """Expande banlists simples; cláusulas de batalha continuam no Showdown."""
    resultado = {'golpes': set(), 'itens': set(), 'habilidades': set()}
    regras = (*formato.get('clausulas', ()), *formato.get('regras_showdown', ()))
    existentes = {_chave(regra) for regra in regras if not str(regra).strip().startswith('!')}
    if 'evasionclause' in existentes:
        existentes.update(('evasionabilitiesclause', 'evasionitemsclause', 'evasionmovesclause'))
    for clausula in existentes:
        for grupo, nomes in _CLAUSULAS_BANS.get(clausula, {}).items():
            resultado[grupo].update(_chave(x) for x in nomes)
    return resultado


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
    tier = meta.get(coluna) or meta.get('tier') or ''
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



# Itens de formas que precisam permanecer equipados durante a batalha.
# Itens-chave de fusão (Reins of Unity, DNA Splicers etc.) não são held items.
_PLATES_ARCEUS = {
    'bug': 'insectplate', 'dark': 'dreadplate', 'dragon': 'dracoplate',
    'electric': 'zapplate', 'fairy': 'pixieplate', 'fighting': 'fistplate',
    'fire': 'flameplate', 'flying': 'skyplate', 'ghost': 'spookyplate',
    'grass': 'meadowplate', 'ground': 'earthplate', 'ice': 'icicleplate',
    'poison': 'toxicplate', 'psychic': 'mindplate', 'rock': 'stoneplate',
    'steel': 'ironplate', 'water': 'splashplate',
}
_ITENS_FORMA = {
    'kyogreprimal': 'blueorb', 'groudonprimal': 'redorb',
    'ogerponhearthflame': 'hearthflamemask',
    'ogerponwellspring': 'wellspringmask',
    'ogerponcornerstone': 'cornerstonemask',
}


def item_obrigatorio_forma(especie):
    """Retorna o ID normalizado do held item exigido por esta forma."""
    codigo = _chave(especie)
    if codigo.startswith('arceus'):
        return _PLATES_ARCEUS.get(codigo[6:], '')
    return _ITENS_FORMA.get(codigo, '')


def _especie_base_clause(especie):
    """Species Clause compara a espécie-base, não a grafia de cada forma."""
    meta = obter_especie_showdown(especie)
    return _id_especie(meta.get('base') or meta.get('n') or especie) if meta else _id_especie(especie)


def _tipos_monotype(slot):
    """Interseção de tipos do Pokémon e de sua Mega/Ultra forma, como no Showdown."""
    meta = obter_especie_showdown(slot.get('pokemon'))
    if not meta or not meta.get('types'):
        return set()
    tipos = {_chave(t) for t in meta['types']}
    item_id = _chave(slot.get('item'))
    especie_id = _chave(slot.get('pokemon'))
    base_id = _chave(meta.get('base') or meta.get('n') or slot.get('pokemon'))
    if MEGA_STONE_OWNERS.get(item_id) == base_id:
        forma = base_id + 'mega' + (item_id[-1] if item_id in ('charizarditex', 'charizarditey') else '')
        mega = obter_especie_showdown(forma)
        if mega and mega.get('types'):
            tipos.intersection_update(_chave(t) for t in mega['types'])
    if item_id == 'ultranecroziumz' and base_id == 'necrozma':
        ultra = obter_especie_showdown('necrozmaultra')
        if ultra and ultra.get('types'):
            tipos.intersection_update(_chave(t) for t in ultra['types'])
    return tipos


def _exige_tipo_comum(formato):
    regras = (*formato.get('clausulas', ()), *formato.get('regras_showdown', ()))
    return any(_chave(regra) == 'sametypeclause' for regra in regras)


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
    clausulas = _bans_de_clausulas(formato)
    golpes_banidos = {_chave(m) for m in formato.get('golpes_proibidos', ())} | clausulas['golpes']
    itens_banidos = {_chave(m) for m in formato.get('itens_proibidos', ())} | clausulas['itens']
    habilidades_banidas = {_chave(m) for m in formato.get('habilidades_proibidas', ())} | clausulas['habilidades']
    usados = set()
    itens_usados = set()
    tipos_em_comum = None
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
        especie_clausula = _especie_base_clause(especie)
        if formato.get('species_clause', True) and especie_clausula in usados:
            erros.append(f'Slot {indice}: espécies repetidas (incluindo formas diferentes) não são permitidas.')
        usados.add(especie_clausula)
        if _exige_tipo_comum(formato) and chave:
            tipos = _tipos_monotype(slot)
            if tipos_em_comum is None:
                tipos_em_comum = tipos
            else:
                tipos_em_comum.intersection_update(tipos)

        nivel_max = int(formato.get('nivel_maximo') or 100)
        nivel = slot.get('level', 5 if formato.get('little_cup') else 100)
        if type(nivel) is not int or not 1 <= nivel <= nivel_max:
            erros.append(f'Slot {indice}: nível fora do limite de {nivel_max} do formato.')
        elif formato.get('little_cup') and nivel != 5:
            erros.append(f'Slot {indice}: Little Cup exige nível 5.')
        item = str(slot.get('item') or '').strip()
        item_id = _chave(item)
        if item_id in BOLAS_CAPTURA:
            erros.append(f'Slot {indice}: {item} é uma Poké Ball de captura e não está disponível na Arena HYPE.')
        if item_id in itens_banidos:
            erros.append(f'Slot {indice}: o item {item} é proibido no formato.')
        if item_id and formato.get('item_clause'):
            if item_id in itens_usados:
                erros.append(f'Slot {indice}: Item Clause não permite repetir {item}.')
            itens_usados.add(item_id)
        item_exigido = item_obrigatorio_forma(especie)
        if item_exigido and item_id != item_exigido:
            erros.append(f'Slot {indice}: {especie} precisa equipar o item de sua forma ({item_exigido}).')
        if item_id in MEGA_STONE_OWNERS and not formato.get('permite_mega', False):
            erros.append(f'Slot {indice}: Mega Stones não são permitidas neste formato.')
        if item_id.endswith('z') and item_id not in ('') and not formato.get('permite_zmove', False):
            erros.append(f'Slot {indice}: Z-Crystals não são permitidos neste formato.')
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
    if _exige_tipo_comum(formato) and not tipos_em_comum:
        erros.insert(0, 'Monotype (Same Type Clause): todos os Pokémon precisam compartilhar pelo menos um tipo; inclua as mudanças de tipagem por Mega Evolution.')
    return erros[:25]
