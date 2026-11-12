"""Análise estratégica automática e explicável dos sets HYPE.

As conclusões são heurísticas por itens, habilidades, golpes e EVs — não uma IA
generativa, previsão de vitória ou substituto do TeamValidator do Showdown.
Nunca modifica o time fornecido.
"""
from collections import Counter
import re

from modules.hype_tournament_formats import obter_especie_showdown


def _id(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())


def _num(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _first(items):
    return items[0] if items else None


HAZARD_MOVES = {'stealthrock', 'spikes', 'toxicspikes', 'stickyweb', 'ceaselessedge', 'stoneaxe'}
REMOVE_MOVES = {'rapidspin', 'defog', 'mortalspin', 'tidyup', 'courtchange'}
PIVOT_MOVES = {'uturn', 'voltswitch', 'flipturn', 'partingshot', 'chillyreception', 'teleport'}
SETUP_MOVES = {'swordsdance', 'nastyplot', 'calmmind', 'dragondance', 'bulkup',
               'quiverdance', 'shellsmash', 'growth', 'agility', 'irondefense',
               'amnesia', 'cosmicpower', 'bellydrum', 'shiftgear', 'workup',
               'tailglow', 'coil', 'geomancy', 'filletaway'}
RECOVERY_MOVES = {'recover', 'roost', 'slackoff', 'softboiled', 'synthesis',
                  'moonlight', 'morningsun', 'wish', 'rest', 'shoreup',
                  'strengthsap', 'milkdrink', 'healorder', 'lifedew', 'painsplit'}
STATUS_MOVES = {'willowisp', 'thunderwave', 'toxic', 'leechseed', 'encore',
                'haze', 'taunt', 'knockoff', 'roar', 'whirlwind', 'yawn',
                'glare', 'spore', 'trick', 'trickroom', 'tailwind', 'screens',
                'reflect', 'lightscreen', 'auroraveil', 'substitute', 'protect'}
SPEED_MOVES = {'tailwind', 'trickroom', 'icywind', 'electroweb', 'thunderwave',
               'stickyweb', 'agility', 'dragondance', 'quiverdance', 'rapidspin'}
SUN_SETTERS = {'drought', 'desolateland'}
RAIN_SETTERS = {'drizzle', 'primordialsea'}
SAND_SETTERS = {'sandstream'}
SNOW_SETTERS = {'snowwarning'}
SUN_ABILITIES = {'chlorophyll', 'solarpower', 'protosynthesis', 'leafguard', 'flowergift'}
RAIN_ABILITIES = {'swiftswim', 'raindish', 'hydration', 'dryskin'}
SAND_ABILITIES = {'sandrush', 'sandforce', 'sandveil'}
SNOW_ABILITIES = {'slushrush', 'icebody', 'snowcloak'}
PHYSICAL_MOVES = {'earthquake', 'scaleshot', 'firefang', 'powerwhip', 'knockoff',
                  'ironhead', 'rapidspin', 'dragonclaw', 'flareblitz', 'closecombat',
                  'outrage', 'playrough', 'extremespeed', 'suckerpunch', 'grassyglide',
                  'surgingstrikes', 'headlongrush', 'stoneedge', 'bulletpunch',
                  'shadowclaw', 'poltergeist', 'firstimpression', 'aquajet', 'iciclecrash'}
SPECIAL_MOVES = {'flamethrower', 'solarBeam'.lower(), 'focusblast',
                 'gigadrain', 'sludgebomb', 'weatherball', 'hydropump',
                 'voltswitch', 'dracometeor', 'thunderbolt', 'icebeam',
                 'surf', 'moonblast', 'shadowball', 'psychic', 'fireblast',
                 'scorchingsands', 'hurricane', 'thunder', 'energyball',
                 'makeitrain', 'earthpower', 'darkpulse', 'leafstorm'}
NON_ATTACKING = HAZARD_MOVES | SETUP_MOVES | RECOVERY_MOVES | (
    STATUS_MOVES - {'knockoff'}) | {'sunnyday', 'raindance', 'sandstorm',
                                    'snowscape', 'defog', 'courtchange', 'tidyup'}
OFFENSIVE_ITEMS = {'lifeorb', 'choiceband', 'choicespecs', 'choicescarf',
                   'expertbelt', 'muscleband', 'wiseglasses', 'boosterenergy'}
DEFENSIVE_ITEMS = {'leftovers', 'rockyhelmet', 'eviolite', 'assaultvest',
                   'blacksludge', 'sitrusberry', 'heavydutyboots'}
PT_TYPES = {'fire':'Fogo', 'water':'Água', 'rock':'Pedra', 'ground':'Terra',
            'grass':'Planta', 'electric':'Elétrico', 'flying':'Voador',
            'ice':'Gelo', 'bug':'Inseto', 'dragon':'Dragão', 'steel':'Aço',
            'poison':'Veneno', 'normal':'Normal', 'fighting':'Lutador',
            'psychic':'Psíquico', 'ghost':'Fantasma', 'dark':'Sombrio',
            'fairy':'Fada'}


def _species_data(slot):
    name = str(slot.get('pokemon') or '')
    item = _id(slot.get('item'))
    if _id(name) == 'charizard' and item in {'charizarditex', 'charizarditey'}:
        name = 'Charizard-Mega-' + item[-1].upper()
    elif _id(name) == 'mewtwo' and item in {'mewtwonitex', 'mewtwonitey'}:
        name = 'Mewtwo-Mega-' + item[-1].upper()
    elif item.endswith('ite') and _id(name) not in {'giratina'}:
        # Outras formas Mega são buscadas pela forma oficial; se não existir,
        # conservamos os tipos da espécie original.
        potential = obter_especie_showdown(name + '-Mega')
        if potential:
            return potential
    return obter_especie_showdown(name) or {}


def _slot_info(slot):
    name = str(slot.get('pokemon') or '').strip()[:90]
    moves = {_id(m) for m in (slot.get('moves') or []) if isinstance(m, str)}
    ability = _id(slot.get('ability'))
    item = _id(slot.get('item'))
    evs = slot.get('evs') if isinstance(slot.get('evs'), dict) else {}
    atk, spa, spe = (_num(evs.get(key)) for key in ('atk', 'spa', 'spe'))
    hp, defe, spd = (_num(evs.get(key)) for key in ('hp', 'def', 'spd'))
    nature = _id(slot.get('nature'))
    meta = _species_data(slot)
    types = [str(t).lower() for t in meta.get('types', [])] or [
        str(t).lower() for t in (slot.get('tipos') or []) if isinstance(t, str)]
    physical = len(moves & PHYSICAL_MOVES)
    special = len(moves & SPECIAL_MOVES)
    scores = Counter()
    evidence = {}
    def mark(role, value, detail):
        scores[role] += value
        evidence.setdefault(role, []).append(detail)

    if spa >= 160 and spa > atk:
        mark('Atacante especial', 3, 'investimento alto em Ataque Especial')
    if atk >= 160 and atk > spa:
        mark('Atacante físico', 3, 'investimento alto em Ataque')
    if special >= 2 and special > physical:
        mark('Atacante especial', 2, 'golpes especiais na build')
    if physical >= 2 and physical > special:
        mark('Atacante físico', 2, 'golpes físicos na build')
    if item == 'choicespecs':
        mark('Atacante especial', 3, 'Choice Specs')
    elif item == 'choiceband':
        mark('Atacante físico', 3, 'Choice Band')
    if item == 'lifeorb' and (atk >= 160 or spa >= 160):
        mark('Atacante ofensivo', 1, 'Life Orb amplia o dano')
    if moves & HAZARD_MOVES:
        mark('Colocador de hazards', 5, 'usa ' + ', '.join(sorted(moves & HAZARD_MOVES)))
    if moves & REMOVE_MOVES:
        mark('Removedor de hazards', 5, 'usa ' + ', '.join(sorted(moves & REMOVE_MOVES)))
    if moves & PIVOT_MOVES:
        mark('Pivô', 5, 'possui golpe de reposicionamento')
    if moves & SETUP_MOVES:
        mark('Setup / condição de vitória', 4, 'pode aumentar atributos antes de atacar')
    if (hp >= 180 or defe >= 180 or spd >= 180):
        mark('Suporte defensivo', 3, 'EVs investidos em resistência')
    if moves & RECOVERY_MOVES and (hp >= 180 or defe >= 180 or spd >= 180):
        mark('Suporte defensivo', 2, 'recuperação de HP')
    if moves & STATUS_MOVES:
        mark('Utilidade / controle', 2, 'golpes de suporte ou status')
    if spe >= 180 and (atk >= 160 or spa >= 160 or item == 'choicescarf'):
        mark('Atacante rápido', 3, 'investimento ofensivo e de Velocidade')
    if item == 'choicescarf':
        mark('Controle de velocidade', 4, 'Choice Scarf')
    if moves & SPEED_MOVES:
        mark('Controle de velocidade', 2, 'golpes que influenciam a velocidade')
    weather = set()
    if ability in SUN_SETTERS or 'sunnyday' in moves:
        weather.add('sol')
        mark('Ativador do sol', 6, 'Drought/sol ou Sunny Day')
    if ability in RAIN_SETTERS or 'raindance' in moves:
        weather.add('chuva')
        mark('Ativador da chuva', 6, 'Drizzle/chuva ou Rain Dance')
    if ability in SAND_SETTERS or 'sandstorm' in moves:
        weather.add('areia')
        mark('Ativador de areia', 6, 'Sand Stream ou Sandstorm')
    if ability in SNOW_SETTERS or 'snowscape' in moves:
        weather.add('neve')
        mark('Ativador de neve', 6, 'Snow Warning ou Snowscape')
    beneficiary = ('sol' if ability in SUN_ABILITIES else
                   'chuva' if ability in RAIN_ABILITIES else
                   'areia' if ability in SAND_ABILITIES else
                   'neve' if ability in SNOW_ABILITIES else '')
    if beneficiary:
        mark('Aproveita ' + beneficiary, 4, 'habilidade ' + str(slot.get('ability') or ''))
    if not scores:
        mark('Função a confirmar', 1, 'o set tem poucos sinais para uma classificação segura')
    # Funções múltiplas, mas sem forçar o papel escolhido manualmente.
    roles = [key for key, _ in scores.most_common(3)]
    guide = []
    if weather:
        guide.append('Ative ' + '/'.join(sorted(weather)) +
                     ' em um momento seguro para aproveitar o clima.')
    if moves & HAZARD_MOVES:
        guide.append('Coloque hazards quando puder forçar uma troca do adversário.')
    if moves & REMOVE_MOVES:
        guide.append('Guarde uma oportunidade para remover hazards do seu campo.')
    if moves & PIVOT_MOVES:
        guide.append('Use os golpes de troca para posicionar um aliado com segurança.')
    if moves & SETUP_MOVES:
        guide.append('Busque um turno favorável para usar o golpe de setup, sem se expor desnecessariamente.')
    if beneficiary:
        guide.append('Priorize a entrada enquanto ' + beneficiary + ' estiver ativo.')
    if not guide and ('Atacante físico' in roles or 'Atacante especial' in roles):
        guide.append('Entre em campo após uma troca favorável e pressione com seus melhores golpes.')
    if not guide:
        guide.append('Avalie os confrontos favoráveis antes de expor este Pokémon.')
    offensive = (spa >= 160 or atk >= 160 or physical >= 2 or special >= 2 or
                 item in OFFENSIVE_ITEMS)
    defensive = (hp >= 180 or defe >= 180 or spd >= 180 or
                 item in DEFENSIVE_ITEMS and not offensive)
    return {
        'pokemon': name,
        'item': str(slot.get('item') or ''),
        'ability': str(slot.get('ability') or ''),
        'tipos': types,
        'funcoes': roles,
        'evidencias': [piece for key in roles for piece in evidence[key]][:5],
        'como_jogar': ' '.join(guide[:3]),
        'ofensivo': offensive, 'defensivo': defensive,
        '_moves': moves, '_item': item, '_ability': ability,
        '_weather': weather, '_beneficiary': beneficiary,
        '_physical': (atk >= 160 or physical >= 2 or item == 'choiceband'),
        '_special': (spa >= 160 or special >= 2 or item == 'choicespecs'),
        '_speed': (spe >= 180 or item == 'choicescarf' or bool(moves & SPEED_MOVES)),
        '_hazards': bool(moves & HAZARD_MOVES),
        '_removal': bool(moves & REMOVE_MOVES),
        '_pivot': bool(moves & PIVOT_MOVES),
        '_setup': bool(moves & SETUP_MOVES),
    }


def analisar_estrategia(slots, formato_codigo=''):
    """Gera diagnóstico contextual em português. Não escreve nem altera sets."""
    if not isinstance(slots, list):
        slots = []
    team = [_slot_info(s) for s in slots[:6] if isinstance(s, dict) and s.get('pokemon')]
    if not team:
        return {'estilo': 'Time vazio', 'estrategia': 'Adicione Pokémon para analisar.',
                'resumo': 'A análise aparece automaticamente após montar ou importar uma equipe.',
                'funcoes': [], 'fortes': [], 'riscos': [], 'sinergias': [],
                'melhorias': [], 'plano': [], 'formato_codigo': str(formato_codigo or '')[:90]}

    weather = Counter(w for s in team for w in s['_weather'])
    benefits = Counter(s['_beneficiary'] for s in team if s['_beneficiary'])
    active_weather = weather.most_common(1)[0][0] if weather else ''
    labels = {'sol':'Sun Offense / Sol', 'chuva':'Rain Offense / Chuva',
              'areia':'Sand / Areia', 'neve':'Snow / Neve'}
    offense = sum(s['ofensivo'] for s in team)
    defense = sum(s['defensivo'] for s in team)
    has_physical = any(s['_physical'] for s in team)
    has_special = any(s['_special'] for s in team)
    setters = [s for s in team if active_weather in s['_weather']] if active_weather else []
    beneficiaries = [s for s in team if s['_beneficiary'] == active_weather]
    hazards = [s for s in team if s['_hazards']]
    removers = [s for s in team if s['_removal']]
    pivots = [s for s in team if s['_pivot']]
    setup = [s for s in team if s['_setup']]
    speed = [s for s in team if s['_speed'] or s['_beneficiary'] == active_weather]
    fortes, riscos, sinergias, melhorias, plano = [], [], [], [], []
    if offense >= 3 and defense >= 2:
        estilo = 'Ofensivo balanceado'
    elif offense >= 3:
        estilo = 'Ofensivo'
    elif defense >= 3 and offense <= 2:
        estilo = 'Defensivo / Balance'
    elif offense and defense:
        estilo = 'Balanceado'
    else:
        estilo = 'Misto / em construção'
    estrategia = labels.get(active_weather, 'Composição personalizada')
    if not active_weather and defense >= 4 and offense <= 2:
        estrategia = 'Defensive Balance / Stall'
    elif not active_weather and setup and offense >= 3:
        estrategia = 'Ofensiva com setup'
    elif not active_weather and hazards and offense >= 3:
        estrategia = 'Ofensiva com hazards'
    if active_weather and beneficiaries:
        fortes.append('Sinergia de ' + active_weather + ': ' +
                      ', '.join(s['pokemon'] for s in setters[:2]) +
                      ' ativa(m) o clima para ' +
                      ', '.join(s['pokemon'] for s in beneficiaries[:3]) + '.')
        sinergias.append('A habilidade de ' +
                        ', '.join(s['pokemon'] for s in beneficiaries[:3]) +
                        ' aproveita o clima criado por ' +
                        ', '.join(s['pokemon'] for s in setters[:2]) + '.')
    elif active_weather:
        riscos.append('Há um ativador de ' + active_weather +
                      ', mas não foi detectado um aproveitador direto do clima nas habilidades.')
    if len(weather) > 1:
        riscos.append('O time ativa climas diferentes; uma entrada pode cancelar a estratégia climática anterior.')
    if has_physical and has_special:
        fortes.append('Pressão ofensiva física e especial: dificulta que uma única parede segure todos os atacantes.')
    elif offense >= 2:
        riscos.append('A ofensiva parece concentrada em um lado; paredes especializadas podem dificultar a partida.')
    if hazards and removers:
        fortes.append('Controle de campo completo: há colocação e remoção de hazards.')
    elif hazards:
        fortes.append('Possui pressão com hazards para punir trocas do adversário.')
        riscos.append('Há hazards ofensivos, mas não foi detectado golpe de remoção próprio.')
    elif removers:
        fortes.append('Possui remoção de hazards para proteger entradas e trocas.')
    else:
        riscos.append('Não foi detectada remoção de hazards (ex.: Rapid Spin ou Defog).')
    if pivots:
        fortes.append('Há opções de pivot para colocar atacantes em campo sem perder tanta pressão.')
    if speed:
        fortes.append('Há recursos de velocidade ou de controle de turnos identificados nas builds.')
    else:
        riscos.append('Não foi identificado controle de velocidade; ameaças rápidas exigem posicionamento cuidadoso.')
    if setup and (pivots or hazards):
        sinergias.append('Pivôs/hazards podem criar oportunidades de setup para ' +
                        ', '.join(s['pokemon'] for s in setup[:2]) + '.')
    if active_weather == 'sol':
        weakened_water = [s['pokemon'] for s in team if s['_moves'] & {
            'hydropump', 'surf', 'scald', 'waterfall', 'liquidation', 'aquajet', 'flipturn'}]
        if weakened_water:
            riscos.append('Sob o sol, golpes de Água perdem potência: atenção a ' +
                          ', '.join(weakened_water) + '.')
        exposed = [s['pokemon'] for s in team if
                   s['tipos'].count('grass') and s['tipos'].count('steel')]
        if exposed:
            riscos.append('No sol, ' + ', '.join(exposed) +
                          ' fica ainda mais vulnerável a golpes de Fogo (fraqueza 4×).')
    if active_weather == 'chuva':
        weakened_fire = [s['pokemon'] for s in team if s['_moves'] & {
            'flamethrower', 'fireblast', 'overheat', 'flareblitz', 'firefang'}]
        if weakened_fire:
            riscos.append('Na chuva, golpes de Fogo perdem potência: atenção a ' +
                          ', '.join(weakened_fire) + '.')
    charizards = [s for s in team if s['pokemon'].casefold().startswith('charizard')]
    if charizards:
        riscos.append('Charizard recebe dano muito alto de Stealth Rock ao entrar '
                      '(50% sem proteção ou alteração de tipo); priorize controlar o campo.')
        if not removers:
            melhorias.append('Inclua uma forma confiável de remover Stealth Rock para ajudar Charizard.')
    if not pivots and offense >= 2:
        melhorias.append('Considere um golpe de pivot para criar entradas seguras para os atacantes.')
    if active_weather and not beneficiaries:
        melhorias.append('Avalie se vale aproveitar o clima com uma habilidade ou golpe específico.')
    if not removers and not charizards:
        melhorias.append('Considere remoção de hazards se o formato e o elenco permitirem.')
    if not has_physical and len(team) >= 3:
        melhorias.append('Avalie adicionar pressão física contra paredes especiais.')
    if not has_special and len(team) >= 3:
        melhorias.append('Avalie adicionar pressão especial contra paredes físicas.')

    if hazards:
        plano.append('Início: use ' + ', '.join(s['pokemon'] for s in hazards[:2]) +
                     ' para colocar hazards quando o confronto permitir.')
    elif pivots:
        plano.append('Início: use ' + pivots[0]['pokemon'] +
                     ' para reconhecer o adversário e ganhar posicionamento.')
    else:
        plano.append('Início: escolha um lead favorável ao adversário, sem sacrificar sua condição de vitória.')
    if removers and charizards:
        plano.append('Preparação: procure remover Stealth Rock com ' +
                     ', '.join(s['pokemon'] for s in removers[:2]) +
                     ' antes de entrar com Charizard.')
    if active_weather and setters:
        plano.append('Meio da batalha: ative ' + active_weather + ' com ' +
                     setters[0]['pokemon'] +
                     (' e posicione ' + beneficiaries[0]['pokemon'] +
                      ' para aproveitar os turnos de clima.' if beneficiaries else
                      ', preservando o ativador para turnos decisivos.'))
    elif pivots:
        plano.append('Meio da batalha: aproveite o pivot de ' + pivots[0]['pokemon'] +
                     ' para criar turnos seguros.')
    if setup:
        plano.append('Final: avalie oportunidades de setup com ' +
                     ', '.join(s['pokemon'] for s in setup[:2]) +
                     ', depois de enfraquecer as principais respostas do adversário.')
    elif beneficiaries:
        plano.append('Final: preserve ' + beneficiaries[0]['pokemon'] +
                     ' para aproveitar a última janela favorável de clima.')
    else:
        plano.append('Final: preserve o atacante com melhor confronto contra os Pokémon restantes.')
    resumo = ('Perfil ' + estilo.lower() + ' com foco em ' + estrategia.lower() +
              '. Funções identificadas pelas configurações efetivas dos sets, '
              'não pelos papéis preenchidos manualmente.')
    return {
        'estilo': estilo, 'estrategia': estrategia, 'resumo': resumo,
        'funcoes': [{k: v for k, v in s.items() if not k.startswith('_')}
                   for s in team],
        'fortes': fortes[:6], 'riscos': riscos[:7],
        'sinergias': sinergias[:5], 'melhorias': melhorias[:5],
        'plano': plano[:5], 'formato_codigo': str(formato_codigo or '')[:90],
    }
