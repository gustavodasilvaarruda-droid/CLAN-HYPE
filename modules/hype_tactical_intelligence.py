"""Motor de inteligência tática HYPE v3.

Usa snapshot compacto do Pokémon Showdown para atributos e metadados de golpes.
A análise não altera builds. Dano apresentado é uma estimativa condicionada
para golpes simples em Singles, SEM se passar pelo Damage Calculator oficial.
"""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import json
import math
import re

from modules.hype_tournament_formats import obter_especie_showdown, obter_formato


@lru_cache(maxsize=1)
def dex():
    source = Path(__file__).resolve().parents[1] / 'data' / 'hype_strategy_battle_dex.json'
    with source.open(encoding='utf-8') as handle:
        return json.load(handle)


def _id(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())


def _num(value, default=0, low=0, high=999):
    try:
        result = int(value)
        return max(low, min(high, result))
    except (TypeError, ValueError, OverflowError):
        return default


NATURES = {
    'adamant':('atk','spa'), 'bold':('def','atk'),
    'brave':('atk','spe'), 'calm':('spd','atk'),
    'careful':('spd','spa'), 'hasty':('spe','def'),
    'impish':('def','spa'), 'jolly':('spe','spa'),
    'lax':('def','spd'), 'lonely':('atk','def'),
    'mild':('spa','def'), 'modest':('spa','atk'),
    'naive':('spe','spd'), 'naughty':('atk','spd'),
    'quiet':('spa','spe'), 'rash':('spa','spd'),
    'relaxed':('def','spe'), 'sassy':('spd','spe'),
    'timid':('spe','atk'),
}
STATS=('hp','atk','def','spa','spd','spe')
TYPES=('normal','fire','water','electric','grass','ice','fighting','poison',
       'ground','flying','psychic','bug','rock','ghost','dragon','dark','steel','fairy')
# Tipagem defensiva completa 18x18: attack_type -> defesa (composição multiplicativa).
DEFENSE={
'normal':{'fighting':2,'ghost':0},
'fire':{'water':2,'ground':2,'rock':2,'fire':.5,'grass':.5,'ice':.5,'bug':.5,'steel':.5,'fairy':.5},
'water':{'electric':2,'grass':2,'fire':.5,'water':.5,'ice':.5,'steel':.5},
'electric':{'ground':2,'electric':.5,'flying':.5,'steel':.5},
'grass':{'fire':2,'ice':2,'poison':2,'flying':2,'bug':2,'water':.5,'electric':.5,'grass':.5,'ground':.5},
'ice':{'fire':2,'fighting':2,'rock':2,'steel':2,'ice':.5},
'fighting':{'flying':2,'psychic':2,'fairy':2,'bug':.5,'rock':.5,'dark':.5},
'poison':{'ground':2,'psychic':2,'grass':.5,'fighting':.5,'poison':.5,'bug':.5,'fairy':.5},
'ground':{'water':2,'grass':2,'ice':2,'poison':.5,'rock':.5,'electric':0},
'flying':{'electric':2,'ice':2,'rock':2,'grass':.5,'fighting':.5,'bug':.5,'ground':0},
'psychic':{'bug':2,'ghost':2,'dark':2,'fighting':.5,'psychic':.5},
'bug':{'fire':2,'flying':2,'rock':2,'grass':.5,'fighting':.5,'ground':.5},
'rock':{'water':2,'grass':2,'fighting':2,'ground':2,'steel':2,'normal':.5,'fire':.5,'poison':.5,'flying':.5},
'ghost':{'ghost':2,'dark':2,'poison':.5,'bug':.5,'normal':0,'fighting':0},
'dragon':{'ice':2,'dragon':2,'fairy':2,'fire':.5,'water':.5,'electric':.5,'grass':.5},
'dark':{'fighting':2,'bug':2,'fairy':2,'ghost':.5,'dark':.5,'psychic':0},
'steel':{'fire':2,'fighting':2,'ground':2,'normal':.5,'grass':.5,'ice':.5,'flying':.5,'psychic':.5,'bug':.5,'rock':.5,'dragon':.5,'steel':.5,'fairy':.5,'poison':0},
'fairy':{'poison':2,'steel':2,'fighting':.5,'bug':.5,'dark':.5,'dragon':0},
}
TYPE_NAMES={'normal':'Normal','fire':'Fogo','water':'Água','electric':'Elétrico',
            'grass':'Planta','ice':'Gelo','fighting':'Lutador','poison':'Veneno',
            'ground':'Terra','flying':'Voador','psychic':'Psíquico','bug':'Inseto',
            'rock':'Pedra','ghost':'Fantasma','dragon':'Dragão','dark':'Sombrio',
            'steel':'Aço','fairy':'Fada'}
IMMUNITIES={
    'levitate':{'ground'}, 'eartheater':{'ground'},
    'flashfire':{'fire'}, 'waterabsorb':{'water'}, 'stormdrain':{'water'},
    'dryskin':{'water'}, 'voltabsorb':{'electric'}, 'lightningrod':{'electric'},
    'motordrive':{'electric'}, 'sapsipper':{'grass'},
}
SUN_SETTERS={'drought','desolateland','sunnyday'}
RAIN_SETTERS={'drizzle','primordialsea','raindance'}
SAND_SETTERS={'sandstream','sandstorm'}
SNOW_SETTERS={'snowwarning','snowscape'}
CLIMATE_ABILITIES={
    'sun':{'chlorophyll','solarpower','protosynthesis','leafguard','flowergift'},
    'rain':{'swiftswim','raindish','hydration','dryskin'},
    'sand':{'sandrush','sandforce','sandveil'},
    'snow':{'slushrush','icebody','snowcloak'},
}
SPEED_BOOSTS={'sun':'chlorophyll','rain':'swiftswim','sand':'sandrush','snow':'slushrush'}
HAZARDS={'stealthrock','spikes','toxicspikes','stickyweb','ceaselessedge','stoneaxe'}
REMOVE={'rapidspin','defog','mortalspin','tidyup','courtchange'}
PIVOTS={'voltswitch','uturn','flipturn','partingshot','chillyreception','teleport'}
SETUP={'swordsdance','nastyplot','calmmind','dragondance','growth','shellsmash',
       'bulkup','quiverdance','shiftgear','agility','coil','irondefense',
       'bellydrum','geomancy','workup','tailglow'}
VAR_POWER={'acrobatics','assurance','beatup','brine','bodypress','counter',
           'electroball','endeavor','eruption','facade','ficklebeam','flail',
           'foulplay','frustration','gyroball','heatcrash','hex','knockoff',
           'lastrespects','lowkick','magnitude','mirrorcoat','naturalgift',
           'payback','powertrip','present','psywave','punishment','ragefist',
           'return','reversal','storedpower','terablast','trumpcard',
           'venoshock','waterspout','weatherball','wringout'}
MULTIHIT={'scaleshot','tripleaxel','surgingstrikes','iciclespear','rockblast',
          'bulletseed','populationbomb','bonerush','pinmissile','armthrust',
          'doubleslap','furyattack','furycutter','dualwingbeat'}
NON_DAMAGE={'fissure','guillotine','horndrill','sheercold','dragonrage','sonicboom',
            'nightshade','seismictoss','superfang','endeavor','finalgambit'}


def _form(slot):
    name=str(slot.get('pokemon') or '').strip()[:90]
    item=_id(slot.get('item'))
    original=_id(name)
    if original in {'charizard','mewtwo'} and item in {
        'charizarditex','charizarditey','mewtwonitex','mewtwonitey'} and item.startswith(original):
        return name+'-Mega-'+item[-1].upper()
    if item.endswith('ite') and not original.endswith('mega'):
        candidate=name+'-Mega'
        if _id(candidate) in dex()['species'] and item.startswith(original[:min(5,len(original))]):
            return candidate
    return name


def _ability(slot):
    name=_id(_form(slot))
    if name=='charizardmegay':return 'drought'
    if name=='charizardmegax':return 'toughclaws'
    if name=='venusaurmega':return 'thickfat'
    if name=='garchompmega':return 'sandforce'
    return _id(slot.get('ability'))


def _types(slot):
    form=_form(slot)
    meta=obter_especie_showdown(form) or obter_especie_showdown(slot.get('pokemon')) or {}
    ts=[str(x).lower() for x in meta.get('types',[]) if str(x).lower() in TYPES]
    if ts:return ts[:2]
    return [str(x).lower() for x in (slot.get('tipos') or []) if
            isinstance(x,str) and x.lower() in TYPES][:2]


def _base(slot):
    data=dex()['species']
    formkey=_id(_form(slot))
    if formkey in data:return data[formkey], 'Showdown'
    basekey=_id(slot.get('pokemon'))
    if basekey in data:return data[basekey], 'Showdown'
    # Forma desconhecida: não inventar stats a partir de base_stats cliente.
    return None, 'Indisponível'


def _level(slot):
    return _num(slot.get('level',100),100,1,100)


def _stats(slot):
    base,origin=_base(slot)
    if base is None:return None,origin
    ev=slot.get('evs') if isinstance(slot.get('evs'),dict) else {}
    iv=slot.get('ivs') if isinstance(slot.get('ivs'),dict) else {}
    level=_level(slot)
    nature=_id(slot.get('nature'))
    plus,minus=NATURES.get(nature,('', ''))
    numbers={}
    for key in STATS:
        b=base[key]
        e=_num(ev.get(key),0,0,252)
        i=_num(iv.get(key,31),31,0,31)
        raw=math.floor((2*b+i+math.floor(e/4))*level/100)
        if key=='hp':
            numbers[key]=raw+level+10 if b!=1 else 1
        else:
            stat=raw+5
            mod=1.1 if key==plus else .9 if key==minus else 1
            numbers[key]=math.floor(stat*mod)
    return numbers,origin


def _weather(slots):
    kinds=Counter()
    for s in slots:
        moves={_id(m) for m in s.get('moves',[]) if isinstance(m,str)}
        ability=_ability(s)
        if ability in SUN_SETTERS or 'sunnyday' in moves:kinds['sun']+=1
        if ability in RAIN_SETTERS or 'raindance' in moves:kinds['rain']+=1
        if ability in SAND_SETTERS or 'sandstorm' in moves:kinds['sand']+=1
        if ability in SNOW_SETTERS or 'snowscape' in moves:kinds['snow']+=1
    return kinds.most_common(1)[0][0] if kinds else ''


def _speed(slot,stats,weather=''):
    value=stats['spe']
    ability=_ability(slot)
    if weather and SPEED_BOOSTS.get(weather)==ability:value*=2
    if _id(slot.get('item'))=='choicescarf':value=math.floor(value*1.5)
    return value


def _type_multiplier(attack,defender,ignore_ability=False,as_tera=False):
    attack=str(attack or '').lower()
    ts=_types(defender)
    if as_tera and defender.get('tera_ativa'):
        tera=str(defender.get('tera_type') or '').lower()
        if tera in TYPES:ts=[tera]
    if not ts or attack not in TYPES:return None
    mult=1.
    for typ in ts:mult*=DEFENSE.get(typ,{}).get(attack,1)
    ability=_ability(defender)
    item=_id(defender.get('item'))
    if not ignore_ability and attack in IMMUNITIES.get(ability,set()):
        return 0.
    if attack=='ground' and item=='airballoon':
        return 0.
    if not ignore_ability and ability=='thickfat' and attack in {'fire','ice'}:
        mult*=.5
    if not ignore_ability and ability=='heatproof' and attack=='fire':
        mult*=.5
    if not ignore_ability and ability=='dryskin' and attack=='fire':
        mult*=1.25
    return mult


def _get_move(move):
    return dex()['moves'].get(_id(move))


def _attack_type(move,weather=''):
    key=_id(move)
    if key=='weatherball' and weather:
        return {'sun':'fire','rain':'water','sand':'rock','snow':'ice'}[weather]
    m=_get_move(move)
    return m['t'] if m else ''


def _damage(attacker,defender,move,weather=''):
    """Faixa ILUSTRATIVA de dano de um ataque simples, com premissas explícitas."""
    m=_get_move(move)
    key=_id(move)
    if not m or m['p']<=0 or m['c'] not in {'P','S'} or key in (VAR_POWER|MULTIHIT|NON_DAMAGE):
        return None
    a,_=_stats(attacker);d,_=_stats(defender)
    if a is None or d is None:return None
    type_name=_attack_type(move,weather)
    ability=_ability(attacker)
    item=_id(attacker.get('item'))
    mult=_type_multiplier(type_name,defender,ignore_ability=(ability=='moldbreaker'))
    if mult is None:return None
    if mult==0:
        return {'move':str(move),'tipo':type_name,'min_pct':0.,'max_pct':0.,
                'alvo':str(defender.get('pokemon')),'imune':True,'resultado':'Imune'}
    if m['c']=='P':
        attack_stat=a['atk']
        defense_stat=d['def']
        if item=='choiceband':attack_stat=math.floor(attack_stat*1.5)
        if ability in {'hugepower','purepower'}:attack_stat*=2
    else:
        attack_stat=a['spa']
        defense_stat=d['spd']
        if item=='choicespecs':attack_stat=math.floor(attack_stat*1.5)
    if defense_stat<=0:return None
    level=_level(attacker)
    power=m['p']
    if ability=='technician' and power<=60:power=math.floor(power*1.5)
    base=math.floor(math.floor((2*level/5+2)*power*attack_stat/defense_stat)/50)+2
    stab=2 if ability=='adaptability' else 1.5
    stab=stab if type_name in _types(attacker) else 1.
    weather_mod=1.
    if weather in {'sun','rain'}:
        if weather=='sun':weather_mod=1.5 if type_name=='fire' else 0.5 if type_name=='water' else 1.
        else:weather_mod=1.5 if type_name=='water' else 0.5 if type_name=='fire' else 1.
    # Hydro Steam é exceção de clima e outros moves de potência variável
    # não devem receber números sem o motor oficial.
    if key in {'hydrosteam','solarbeam','solarblade'} and weather=='rain':
        return None
    if key=='hydrosteam' and weather=='sun':return None
    item_mod=1.3 if item=='lifeorb' else 1.2 if item=='expertbelt' and mult>1 else 1.
    # Falta ao cálculo integral: terastalização, condições de HP, telas, terreno,
    # crítico, spread de duplas, habilidades especiais de atacante/alvo.
    minimum=math.floor(base*.85*stab*weather_mod*mult*item_mod)
    maximum=math.floor(base*stab*weather_mod*mult*item_mod)
    hp=d['hp']
    if hp<=0:return None
    low=round(100*minimum/hp,1);high=round(100*maximum/hp,1)
    desc=('OHKO possível nesta estimativa' if high>=100 else
          '2HKO possível nesta estimativa' if high>=50 else
          'Dano baixo/moderado nesta estimativa')
    return {'move':str(move),'tipo':type_name,'min_pct':low,'max_pct':high,
            'alvo':str(defender.get('pokemon')),'imune':False,'resultado':desc}


def _interactions(slots,weather):
    results=[]
    def add(kind,title,reason,who):
        results.append({'tipo':kind,'titulo':title,'explicacao':reason,'pokemon':who})
    for s in slots:
        name=str(s.get('pokemon'))
        item=_id(s.get('item'))
        ability=_ability(s)
        moves=[str(m) for m in (s.get('moves') or []) if isinstance(m,str)]
        names={_id(m) for m in moves}
        stat,_=_stats(s)
        ev=s.get('evs') if isinstance(s.get('evs'),dict) else {}
        atk=_num(ev.get('atk'));spa=_num(ev.get('spa'))
        status=[m for m in moves if (meta:=_get_move(m)) and meta['c']=='T']
        if item=='assaultvest' and status:
            add('alerta','Assault Vest impede golpes de status',
                name+' tem '+', '.join(status[:3])+', que não podem ser selecionados com Assault Vest.',name)
        if item in {'choicescarf','choiceband','choicespecs'}:
            setup=[m for m in moves if _id(m) in SETUP]
            if setup:
                add('alerta','Item Choice conflita com setup',
                    name+' utiliza '+str(s.get('item'))+' e '+', '.join(setup[:2])+
                    '. O item trava em um único golpe até trocar; use com cautela.',name)
            if item=='choicespecs' and atk>=160 and spa<160:
                add('alerta','Choice Specs em atacante físico',
                    'O item fortalece apenas golpes especiais, mas '+name+' investe mais EVs em Ataque.',name)
            if item=='choiceband' and spa>=160 and atk<160:
                add('alerta','Choice Band em atacante especial',
                    'O item fortalece apenas golpes físicos, mas '+name+' investe mais EVs em Ataque Especial.',name)
        if item=='lifeorb' and stat is not None:
            add('informacao','Life Orb: bônus com custo de HP',
                name+' ganha bônus de dano, mas normalmente perde 10% do HP ao causar dano.',name)
        if item=='rockyhelmet' and ability=='roughskin':
            add('positivo','Rough Skin + Rocky Helmet',
                name+' pune duas vezes um golpe de contato recebido.',name)
        if item in {'charizarditey','charizarditex'} and _id(name)=='charizard':
            add('positivo','Mega Stone e forma reconhecidas',
                name+' usa Charizardite '+item[-1].upper()+
                ': as estatísticas, tipagem e habilidades da Mega foram consideradas.',name)
        if item=='heavydutyboots':
            add('positivo','Heavy-Duty Boots',
                name+' ignora danos e efeitos de hazards ao entrar, enquanto mantém o item.',name)
        if item=='eviolite':
            meta=obter_especie_showdown(name) or {}
            if not meta.get('evos'):
                add('alerta','Eviolite pode não ter efeito',
                    name+' não possui evolução posterior no catálogo consultado.',name)
        if weather=='sun':
            if 'hydropump' in names or 'surf' in names or 'scald' in names:
                add('alerta','Golpe de Água prejudicado pelo sol',
                    name+' tem ataque de Água normalmente reduzido pela metade no sol.',name)
            if 'grass' in _types(s) and 'steel' in _types(s):
                add('alerta','Planta/Aço fica exposto no sol',
                    name+' tem fraqueza 4× a Fogo, e o sol fortalece golpes de Fogo.',name)
            if ability=='chlorophyll':
                add('positivo','Chlorophyll dobra Speed',
                    name+' dobra a Speed no sol, sem gastar turno usando Agility.',name)
            if 'solarbeam' in names:
                add('positivo','Solar Beam sem carregar',
                    name+' consegue usar Solar Beam no mesmo turno enquanto o sol estiver ativo.',name)
            if 'growth' in names:
                add('positivo','Growth fortalecido no sol',
                    name+' ganha +2 estágios de Ataque e Ataque Especial com Growth sob o sol.',name)
        if weather=='rain' and ('flamethrower' in names or 'fireblast' in names):
            add('alerta','Fogo enfraquecido na chuva',
                name+' tem golpes de Fogo normalmente reduzidos pela metade na chuva.',name)
        if 'trickroom' in names and _num(ev.get('spe'))>=180:
            add('alerta','Trick Room e investimento de Speed',
                name+' possui Speed EVs altos: mover-se primeiro fora de Trick Room pode conflitar com a estratégia.',name)
        if stat and item=='choicescarf' and stat['spe']<80:
            add('informacao','Choice Scarf em Pokémon lento',
                name+' recebe aumento de Speed, mas compare com alvos concretos antes de contar com revenge kill.',name)
    return results[:20]


def _type_matrix(slots):
    rows=[]
    for attack in TYPES:
        weak=[];resist=[];immune=[];neutral=[]
        for s in slots:
            number=_type_multiplier(attack,s)
            if number is None:continue
            name=str(s.get('pokemon') or '')
            if number==0:immune.append(name)
            elif number>1:weak.append(name)
            elif number<1:resist.append(name)
            else:neutral.append(name)
        rows.append({'tipo':attack,'nome':TYPE_NAMES[attack],
                     'fracos':len(weak),'resistem':len(resist),'imunes':len(immune),
                     'neutros':len(neutral),'nomes_fracos':weak[:6],
                     'nomes_resistem':resist[:6],'nomes_imunes':immune[:6]})
    rows.sort(key=lambda x:(-x['fracos'],x['resistem']+x['imunes'],x['nome']))
    return rows


def _offensive(slots,weather):
    rows=Counter()
    for s in slots:
        for move in (s.get('moves') or []):
            meta=_get_move(move)
            if not meta or meta['p']<1 or meta['c'] not in {'P','S'}:continue
            typ=_attack_type(move,weather)
            if typ:rows[typ]+=1
    return [{'tipo':typ,'nome':TYPE_NAMES.get(typ,typ),'golpes':amount}
            for typ,amount in rows.most_common()]


def _benchmark_threats(slots,format_code,defensive):
    # Referências de matchup fixas, NÃO ranking de uso do metagame.
    candidates=[
        ('Great Tusk','ground','Earthquake'),('Iron Valiant','fairy','Moonblast'),
        ('Dragapult','ghost','Shadow Ball'),('Weavile','ice','Ice Spinner'),
        ('Gholdengo','steel','Make It Rain'),('Landorus-Therian','ground','Earthquake'),
        ('Kingambit','dark','Kowtow Cleave'),('Volcarona','fire','Flamethrower'),
        ('Raging Bolt','electric','Thunderbolt'),('Urshifu-Rapid-Strike','water','Surging Strikes'),
        ('Heatran','fire','Magma Storm'),('Kyurem','ice','Ice Beam'),
    ]
    fmt=obter_formato(format_code) if format_code else None
    nd='nationaldex' in str(format_code)
    seen={_id(s.get('pokemon')) for s in slots}
    rows=[]
    for name,typ,move in candidates:
        if _id(name) in seen:continue
        meta=obter_especie_showdown(name)
        if not meta:continue
        if fmt and not nd:
            if meta.get('nonstandard') in {'Past','Future','CAP','Custom','Unobtainable'}:
                continue
            bans={_id(x) for x in fmt.get('pokemons_proibidos',[])}
            if _id(name) in bans:continue
        vals=[(_type_multiplier(typ,s),str(s.get('pokemon'))) for s in slots]
        affected=[mon for mult,mon in vals if mult is not None and mult>1]
        answers=[mon for mult,mon in vals if mult is not None and mult<1]
        if not affected:continue
        score=len(affected)*2-len(answers)
        rows.append({'pokemon':name,'tipo_ameaca':TYPE_NAMES.get(typ,typ),
                     'golpe_exemplo':move,'expostos':affected,'respostas_por_tipo':answers,
                     'risco':'alto' if score>=4 else 'moderado',
                     'explicacao':(str(len(affected))+' integrante(s) são vulneráveis a golpes do tipo '+
                                  TYPE_NAMES.get(typ,typ)+'. Trata-se de referência de matchup; '
                                  'item, habilidade e golpes reais do adversário podem mudar o resultado.'),
                     '_score':score})
    rows.sort(key=lambda x:(-x['_score'],x['pokemon']))
    return [{k:v for k,v in row.items() if k!='_score'} for row in rows[:6]]


def _duels(slots,opponents,weather):
    matches=[]
    for enemy in opponents:
        enemy_name=str(enemy.get('pokemon'))
        best=None
        for ally in slots:
            for move in (ally.get('moves') or []):
                sample=_damage(ally,enemy,move,weather)
                if sample and not sample['imune']:
                    if best is None or sample['max_pct']>best['max_pct']:
                        best={**sample,'atacante':str(ally.get('pokemon'))}
        if best:
            best['contra']=enemy_name
            matches.append(best)
    return matches[:6]


def analisar_avancado(slots,formato_codigo='',adversario=None):
    """Sinaliza fatos mecânicos e oferece estimativas condicionais de Singles."""
    slots=[x for x in (slots or [])[:6] if isinstance(x,dict) and x.get('pokemon')]
    adversario=[x for x in (adversario or [])[:6] if isinstance(x,dict) and x.get('pokemon')]
    weather=_weather(slots)
    climate={'sun':'Sol','rain':'Chuva','sand':'Areia','snow':'Neve','':'Sem clima dominante'}[weather]
    attrib=[]
    speeders=[]
    missing=[]
    for slot in slots:
        stats,source=_stats(slot)
        name=str(slot.get('pokemon'))
        if stats:
            effective=_speed(slot,stats,weather)
            row={'pokemon':name,'forma':_form(slot),'nivel':_level(slot),
                 'nature':str(slot.get('nature') or 'Neutra / não informada'),
                 'base_stats':_base(slot)[0],'stats':stats,'speed_efetiva':effective,
                 'speed_condicao':('Sob '+climate.lower()+' (quando ativo)' if weather else
                                  'Sem clima ativo; Choice Scarf se equipado'),
                 'fonte':source}
            attrib.append(row)
            speeders.append((effective,name))
        else:missing.append(name)
    defense=_type_matrix(slots)
    weak=[x for x in defense if x['fracos']>=3]
    synergy=_interactions(slots,weather)
    offense=_offensive(slots,weather)
    current_risks=[]
    if adversario:
        opposing_weather=_weather(adversario)
        if opposing_weather and opposing_weather!=weather:
            current_risks.append('O adversário pode ativar um clima diferente e interromper a sua estratégia. '
                                 'A ordem das entradas em campo define qual clima prevalece.')
    tera_cenarios=[]
    for slot in slots:
        if not slot.get('tera_ativa') or str(slot.get('tera_type') or '').lower() not in TYPES:
            continue
        improved=[];worsened=[]
        for typ in TYPES:
            current=_type_multiplier(typ,slot)
            transformed=_type_multiplier(typ,slot,as_tera=True)
            if current is None or transformed is None:continue
            if transformed<current:improved.append(TYPE_NAMES[typ])
            if transformed>current:worsened.append(TYPE_NAMES[typ])
        tera_cenarios.append({'pokemon':str(slot.get('pokemon')),
                              'tera':str(slot.get('tera_type')),
                              'melhorias':improved,'riscos':worsened,
                              'nota':'Condição hipotética: a terastalização não é assumida ativa.'})

    if weak:
        current_risks.append('Concentração de vulnerabilidades: '+
                             ', '.join(x['nome']+' ('+str(x['fracos'])+')' for x in weak[:4])+'.')
    if not offense:
        current_risks.append('Não foram identificados golpes ofensivos com potência conhecida.')
    if missing:
        current_risks.append('Base stats indisponíveis para: '+', '.join(missing[:4])+'.')
    if not any({_id(m) for m in s.get('moves',[])} & REMOVE for s in slots):
        current_risks.append('Nenhum golpe de remoção de hazards identificado.')
    if weather:
        current_risks.append('Velocidades condicionais assumem '+climate.lower()+
                             ' ativo; o adversário pode alterar ou encerrar o clima.')
    recommendations=[]
    for entry in synergy:
        if entry['tipo']=='alerta':
            recommendations.append({'titulo':entry['titulo'],'explicacao':entry['explicacao']})
    for typ in weak[:2]:
        if not typ['imunes'] and not typ['resistem']:
            recommendations.append({'titulo':'Cobertura defensiva contra '+typ['nome'],
                'explicacao':'Há '+str(typ['fracos'])+' vulnerabilidades a '+typ['nome']+
                             ' e nenhuma resistência/imunidade entre os membros identificados.'})
    threat=_benchmark_threats(slots,formato_codigo,defense)
    duel=_duels(slots,adversario,weather) if adversario else []
    inbound=_duels(adversario,slots,weather) if adversario else []
    return {
        'fonte':'Pokémon Showdown · snapshot local de base stats e movimentos',
        'clima':climate, 'clima_codigo':weather,
        'atributos':attrib,'defesa_tipos':defense,'cobertura_ofensiva':offense,
        'interacoes':synergy,'ameacas_referencia':threat,'confrontos':duel,
        'confrontos_recebidos':inbound,'tera_cenarios':tera_cenarios,
        'recomendacoes':recommendations[:8],'riscos_estruturais':current_risks[:8],
        'adversarios':len(adversario),'velocidade_top':[
            {'pokemon':name,'velocidade':speed} for speed,name in
            sorted(speeders,reverse=True)[:5]],
        'nota_dano':('Estimativa simplificada de Singles para golpes de potência fixa; '
                     'considera nível, EV, IV, Nature, tipo, STAB, clima ativo, Choice e Life Orb '
                     'nos casos implementados. Não considera todos os efeitos de habilidade, '
                     'terreno, screens, spread, críticos, multi-hit, boosts ou condições especiais. '
                     'Não substitui o Damage Calculator/TeamValidator oficial.'),
        'nota_tera':'Defesas partem do tipo atual; Terastalização é condicional e não presumida ativa.',
        'nota_ameacas':'Ameaças são referências ilustrativas por tipo, não ranking atualizado de uso do formato.',
    }
