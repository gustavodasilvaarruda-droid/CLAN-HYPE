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
    if not isinstance(slots, list) or len(slots) != 6:
        return ['O time precisa conter exatamente seis Pokémon.']

    banidos = {_chave(p) for p in formato.get('pokemons_proibidos', ())}
    golpes_banidos = {_chave(m) for m in formato.get('golpes_proibidos', ())}
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
        if chave in usados:
            erros.append(f'Slot {indice}: espécies repetidas não são permitidas.')
        usados.add(chave)

        item = str(slot.get('item') or '').strip()
        if _chave(item) in BOLAS_CAPTURA:
            erros.append(f'Slot {indice}: {item} é uma Poké Ball de captura e não está disponível na Arena HYPE.')
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
