from collections import Counter
from flask import Blueprint, render_template, request, redirect, url_for, session


TYPE_ORDER = [
    'normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting', 'poison',
    'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon', 'dark',
    'steel', 'fairy',
]

TYPE_LABELS = {
    'normal': 'Normal', 'fire': 'Fogo', 'water': 'Água', 'electric': 'Elétrico',
    'grass': 'Planta', 'ice': 'Gelo', 'fighting': 'Lutador', 'poison': 'Venenoso',
    'ground': 'Terrestre', 'flying': 'Voador', 'psychic': 'Psíquico', 'bug': 'Inseto',
    'rock': 'Pedra', 'ghost': 'Fantasma', 'dragon': 'Dragão', 'dark': 'Sombrio',
    'steel': 'Aço', 'fairy': 'Fada',
}

TYPE_ALIASES = {
    'fogo': 'fire', 'agua': 'water', 'água': 'water', 'eletrico': 'electric', 'elétrico': 'electric',
    'planta': 'grass', 'grama': 'grass', 'gelo': 'ice', 'lutador': 'fighting', 'luta': 'fighting',
    'venenoso': 'poison', 'veneno': 'poison', 'terrestre': 'ground', 'terra': 'ground',
    'voador': 'flying', 'psiquico': 'psychic', 'psíquico': 'psychic', 'inseto': 'bug',
    'pedra': 'rock', 'fantasma': 'ghost', 'dragao': 'dragon', 'dragão': 'dragon',
    'sombrio': 'dark', 'aco': 'steel', 'aço': 'steel', 'fada': 'fairy',
    'normal': 'normal', 'fire': 'fire', 'water': 'water', 'electric': 'electric', 'grass': 'grass',
    'ice': 'ice', 'fighting': 'fighting', 'poison': 'poison', 'ground': 'ground', 'flying': 'flying',
    'psychic': 'psychic', 'bug': 'bug', 'rock': 'rock', 'ghost': 'ghost', 'dragon': 'dragon',
    'dark': 'dark', 'steel': 'steel', 'fairy': 'fairy',
}

# Relações defensivas: tipo defensor -> multiplicador recebido por tipo atacante.
DEFENSE_CHART = {
    'normal': {'fighting': 2, 'ghost': 0},
    'fire': {'water': 2, 'ground': 2, 'rock': 2, 'fire': .5, 'grass': .5, 'ice': .5, 'bug': .5, 'steel': .5, 'fairy': .5},
    'water': {'electric': 2, 'grass': 2, 'fire': .5, 'water': .5, 'ice': .5, 'steel': .5},
    'electric': {'ground': 2, 'electric': .5, 'flying': .5, 'steel': .5},
    'grass': {'fire': 2, 'ice': 2, 'poison': 2, 'flying': 2, 'bug': 2, 'water': .5, 'electric': .5, 'grass': .5, 'ground': .5},
    'ice': {'fire': 2, 'fighting': 2, 'rock': 2, 'steel': 2, 'ice': .5},
    'fighting': {'flying': 2, 'psychic': 2, 'fairy': 2, 'bug': .5, 'rock': .5, 'dark': .5},
    'poison': {'ground': 2, 'psychic': 2, 'grass': .5, 'fighting': .5, 'poison': .5, 'bug': .5, 'fairy': .5},
    'ground': {'water': 2, 'grass': 2, 'ice': 2, 'poison': .5, 'rock': .5, 'electric': 0},
    'flying': {'electric': 2, 'ice': 2, 'rock': 2, 'grass': .5, 'fighting': .5, 'bug': .5, 'ground': 0},
    'psychic': {'bug': 2, 'ghost': 2, 'dark': 2, 'fighting': .5, 'psychic': .5},
    'bug': {'fire': 2, 'flying': 2, 'rock': 2, 'grass': .5, 'fighting': .5, 'ground': .5},
    'rock': {'water': 2, 'grass': 2, 'fighting': 2, 'ground': 2, 'steel': 2, 'normal': .5, 'fire': .5, 'poison': .5, 'flying': .5},
    'ghost': {'ghost': 2, 'dark': 2, 'poison': .5, 'bug': .5, 'normal': 0, 'fighting': 0},
    'dragon': {'ice': 2, 'dragon': 2, 'fairy': 2, 'fire': .5, 'water': .5, 'electric': .5, 'grass': .5},
    'dark': {'fighting': 2, 'bug': 2, 'fairy': 2, 'ghost': .5, 'dark': .5, 'psychic': 0},
    'steel': {'fire': 2, 'fighting': 2, 'ground': 2, 'normal': .5, 'grass': .5, 'ice': .5, 'flying': .5, 'psychic': .5, 'bug': .5, 'rock': .5, 'dragon': .5, 'steel': .5, 'fairy': .5, 'poison': 0},
    'fairy': {'poison': 2, 'steel': 2, 'fighting': .5, 'bug': .5, 'dark': .5, 'dragon': 0},
}

MOVE_GROUPS = {
    'hazards': {'stealth rock', 'spikes', 'toxic spikes', 'sticky web', 'ceaseless edge', 'stone axe'},
    'remocao': {'rapid spin', 'defog', 'mortal spin', 'tidy up', 'court change'},
    'recovery': {'recover', 'roost', 'soft boiled', 'soft-boiled', 'slack off', 'moonlight', 'synthesis', 'shore up', 'wish', 'rest', 'strength sap', 'morning sun'},
    'pivot': {'u turn', 'u-turn', 'volt switch', 'flip turn', 'parting shot', 'teleport', 'chilly reception'},
    'speed': {'tailwind', 'trick room', 'thunder wave', 'icy wind', 'electroweb', 'sticky web', 'glare', 'nuzzle'},
    'priority': {'extreme speed', 'extremespeed', 'bullet punch', 'mach punch', 'sucker punch', 'aqua jet', 'ice shard', 'shadow sneak', 'vacuum wave', 'jet punch', 'quick attack', 'first impression'},
    'setup': {'swords dance', 'nasty plot', 'dragon dance', 'calm mind', 'quiver dance', 'shell smash', 'bulk up', 'iron defense', 'agility', 'rock polish', 'curse'},
}


def _norm(value):
    return str(value or '').strip().casefold().replace('_', ' ')


def _type_slug(value):
    return TYPE_ALIASES.get(_norm(value), _norm(value))


def _types_from_slot(slot, pokedex_by_name):
    tipos = []
    bruto = slot.get('tipos') or []
    if isinstance(bruto, str):
        bruto = [x.strip() for x in bruto.replace('/', ',').split(',') if x.strip()]
    for t in bruto:
        n = _type_slug(t)
        if n in TYPE_ORDER and n not in tipos:
            tipos.append(n)
    if tipos:
        return tipos[:2]
    row = pokedex_by_name.get(_norm(slot.get('pokemon')))
    if row:
        for key in ('tipo1', 'tipo2'):
            n = _type_slug(row.get(key))
            if n in TYPE_ORDER and n not in tipos:
                tipos.append(n)
    return tipos[:2]


def _types_from_pokedex(row):
    tipos = []
    for key in ('tipo1', 'tipo2'):
        n = _type_slug(row.get(key))
        if n in TYPE_ORDER and n not in tipos:
            tipos.append(n)
    return tipos


def _def_multiplier(defending_types, attacking_type):
    mult = 1.0
    for defesa in defending_types:
        mult *= DEFENSE_CHART.get(defesa, {}).get(attacking_type, 1.0)
    return mult


def _friendly_mult(mult):
    if mult == 0:
        return '0×'
    if mult == .25:
        return '¼×'
    if mult == .5:
        return '½×'
    if mult == 1:
        return '1×'
    if mult == 2:
        return '2×'
    if mult == 4:
        return '4×'
    return f'{mult:g}×'


def _tier_score(tier):
    order = {
        'S+': 0, 'S': 1, 'A+': 2, 'A': 3, 'A-': 4, 'UBER': 5,
        'OU': 6, 'UU': 7, 'RU': 8, 'NU': 9, 'PU': 10, 'B': 11,
        'C': 12, 'D': 13, 'LC': 14, 'UNTIERED': 50, 'SEM TIER': 99,
    }
    return order.get(str(tier or '').strip().upper(), 30)


def create_builders_hub_blueprint(supabase, login_required, safe_table, is_admin):
    bp = Blueprint('buildershub', __name__)

    CATALOGOS = {
        'pokemon': {'titulo': 'Pokémon', 'subtitulo': 'Explore espécies, tipos, habilidades e golpes para começar uma Build.', 'endpoint': 'pokemon', 'icone': '◉'},
        'moves': {'titulo': 'Moves', 'subtitulo': 'Pesquise golpes e consulte poder, precisão, tipo e categoria.', 'endpoint': 'move', 'icone': '✦'},
        'abilities': {'titulo': 'Abilities', 'subtitulo': 'Consulte habilidades e use a informação ao montar seus sets.', 'endpoint': 'ability', 'icone': '◆'},
        'items': {'titulo': 'Items', 'subtitulo': 'Pesquise itens e encontre opções para completar suas Builds.', 'endpoint': 'item', 'icone': '◇'},
        'types': {'titulo': 'Types', 'subtitulo': 'Veja relações entre tipos, fraquezas e resistências.', 'endpoint': 'type', 'icone': '⬡'},
    }

    FORMAT_VISUAL_IDS = [384, 445, 635, 248, 94, 376, 282, 149, 212, 448, 130, 373]

    def _format_visual_rows():
        rows = [dict(x) for x in safe_table('formatos_competitivos') if x.get('ativo', True)]
        rows.sort(key=lambda x: (x.get('nome') or '').casefold())
        for idx, row in enumerate(rows):
            blob = ' '.join([str(row.get('codigo') or ''), str(row.get('nome') or ''), str(row.get('descricao') or '')]).casefold()
            row['_mode'] = 'Doubles' if any(x in blob for x in ('double', '2v2', 'dupla')) else 'Singles'
            if any(x in blob for x in ('hype', 'cc1v1', 'clan', 'clã')):
                row['_family'] = 'HYPE'
            elif any(x in blob for x in ('battle spot', 'oficial', 'official')):
                row['_family'] = 'Oficial'
            elif any(x in blob for x in ('casual', '1v1', '2v2')):
                row['_family'] = 'Casual'
            else:
                row['_family'] = 'Custom'
            dex_id = FORMAT_VISUAL_IDS[idx % len(FORMAT_VISUAL_IDS)]
            row['_art'] = f'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{dex_id}.png'
            row['_index'] = idx
        return rows

    def _format_page_context():
        rows = _format_visual_rows()
        pokedex = [x for x in safe_table('pokedex_competitiva') if x.get('publicado', True)]
        poke_by_name = {_norm(x.get('pokemon')): x for x in pokedex if x.get('pokemon')}
        builds = [dict(x) for x in safe_table('builds_pokemon') if x.get('publicado')]
        builds.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        guias = []
        for build in builds[:8]:
            poke = poke_by_name.get(_norm(build.get('pokemon'))) or {}
            guia = dict(build)
            guia['_image'] = poke.get('imagem_url') or ''
            guias.append(guia)
        destaque = next((x for x in rows if x.get('_family') == 'HYPE'), None) or (rows[0] if rows else None)
        return {
            'formatos': rows,
            'destaque': destaque,
            'guias_relacionados': guias[:4],
            'formatos_count': len(rows),
            'pokedex_count': len(pokedex),
            'builds_count': len(builds),
            'logado': bool(session.get('usuario_email')),
        }

    @bp.route('/hype-builders')
    @bp.route('/builders')
    def hub():
        return render_template('builders_formatos.html', **_format_page_context())

    @bp.route('/hype-builders/catalogo/<categoria>')
    def catalogo(categoria):
        cfg = CATALOGOS.get(categoria)
        if not cfg:
            return redirect(url_for('buildershub.hub'))
        return render_template('builders_catalogo.html', categoria=categoria, cfg=cfg)

    @bp.route('/hype-builders/formatos')
    def formatos():
        return render_template('builders_formatos.html', **_format_page_context())

    @bp.route('/hype-builders/guias')
    def guias():
        rows = [x for x in safe_table('builds_pokemon') if x.get('publicado')]
        termo = (request.args.get('q') or '').strip().casefold()
        if termo:
            rows = [x for x in rows if termo in str(x.get('pokemon') or '').casefold()
                    or termo in str(x.get('titulo') or '').casefold()
                    or termo in str(x.get('formato') or '').casefold()
                    or termo in str(x.get('papel') or '').casefold()]
        rows.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        return render_template('builders_guias.html', builds=rows[:80], q=request.args.get('q', ''))

    def _build_synergy(time):
        pokedex = [x for x in safe_table('pokedex_competitiva') if x.get('publicado', True)]
        pokedex_by_name = {_norm(x.get('pokemon')): x for x in pokedex if x.get('pokemon')}
        slots = [s for s in (time.get('slots') or []) if s.get('pokemon')]
        team_names = {_norm(s.get('pokemon')) for s in slots}
        matrix = []
        summary = {atk: {'weak': 0, 'resist': 0, 'immune': 0, 'neutral': 0, 'severe': 0} for atk in TYPE_ORDER}
        move_names = []
        item_names = []
        role_text = []

        for slot in slots:
            tipos = _types_from_slot(slot, pokedex_by_name)
            cells = []
            for atk in TYPE_ORDER:
                mult = _def_multiplier(tipos, atk) if tipos else 1.0
                if mult == 0:
                    summary[atk]['immune'] += 1
                    state = 'immune'
                elif mult < 1:
                    summary[atk]['resist'] += 1
                    state = 'resist'
                elif mult > 1:
                    summary[atk]['weak'] += 1
                    if mult >= 4:
                        summary[atk]['severe'] += 1
                    state = 'weak4' if mult >= 4 else 'weak'
                else:
                    summary[atk]['neutral'] += 1
                    state = 'neutral'
                cells.append({'type': atk, 'mult': mult, 'label': _friendly_mult(mult), 'state': state})
            matrix.append({'pokemon': slot.get('pokemon'), 'sprite': slot.get('sprite'), 'types': tipos, 'cells': cells, 'item': slot.get('item'), 'role': slot.get('papel')})
            move_names.extend(_norm(m) for m in (slot.get('moves') or []) if str(m or '').strip())
            if slot.get('item'):
                item_names.append(_norm(slot.get('item')))
            if slot.get('papel'):
                role_text.append(_norm(slot.get('papel')))

        summary_rows = []
        for atk in TYPE_ORDER:
            d = summary[atk]
            # risco: muitas fraquezas e poucas respostas defensivas.
            risk = d['weak'] * 2 + d['severe'] * 2 - d['resist'] - d['immune'] * 2
            summary_rows.append({'type': atk, 'label': TYPE_LABELS[atk], **d, 'risk': risk})
        threats = sorted([x for x in summary_rows if x['weak']], key=lambda x: (-x['risk'], -x['weak'], x['label']))
        answers = sorted([x for x in summary_rows if x['resist'] or x['immune']], key=lambda x: (-(x['resist'] + x['immune'] * 2), x['label']))

        normalized_moves = set(move_names)
        role_blob = ' | '.join(role_text)
        detected = {}
        for key, move_set in MOVE_GROUPS.items():
            detected[key] = bool(normalized_moves.intersection(move_set))
        detected['hazards'] = detected['hazards'] or any(x in role_blob for x in ('hazard', 'rocks', 'spikes'))
        detected['remocao'] = detected['remocao'] or any(x in role_blob for x in ('removal', 'remoção', 'remocao', 'spinner', 'defog'))
        detected['pivot'] = detected['pivot'] or 'pivot' in role_blob
        detected['speed'] = detected['speed'] or any(x in role_blob for x in ('speed control', 'velocidade', 'scarf')) or any('choice scarf' == x for x in item_names)
        detected['setup'] = detected['setup'] or any(x in role_blob for x in ('setup', 'sweeper'))
        detected['recovery'] = detected['recovery'] or any(x in role_blob for x in ('wall', 'tank', 'bulky'))

        notes = []
        if len(slots) < 6:
            notes.append(f'O time possui {len(slots)}/6 Pokémon preenchidos; a leitura de sinergia fica mais confiável quando os seis slots estão completos.')
        if threats:
            top = threats[0]
            if top['weak'] >= 3 and top['resist'] + top['immune'] == 0:
                notes.append(f'Alerta alto contra {top["label"]}: {top["weak"]} fraquezas e nenhuma resistência/imunidade registrada.')
            elif top['weak'] >= 3:
                notes.append(f'{top["label"]} pressiona {top["weak"]} membros; preserve suas {top["resist"] + top["immune"]} resposta(s) defensiva(s).')
        if not detected['remocao']:
            notes.append('Não foi identificada remoção de hazards nos moves/papéis salvos. Considere Rapid Spin, Defog ou outra ferramenta compatível com o formato.')
        if not detected['speed']:
            notes.append('Não foi identificado controle de velocidade. Choice Scarf, prioridade, Tailwind, Trick Room ou status de Speed podem cumprir essa função.')
        if detected['hazards'] and detected['pivot']:
            notes.append('Hazards + pivôs foram detectados: essa combinação ajuda a acumular chip damage enquanto você reposiciona o time.')
        if detected['setup'] and not detected['pivot']:
            notes.append('Há ferramenta de setup, mas nenhum pivô foi identificado. Planeje entradas seguras para sua condição de vitória.')
        if not notes:
            notes.append('A estrutura básica está equilibrada nos sinais que o analisador consegue ler dos sets salvos.')

        suggestions = []
        for threat in threats[:3]:
            atk = threat['type']
            candidates = []
            for row in pokedex:
                if _norm(row.get('pokemon')) in team_names:
                    continue
                tipos = _types_from_pokedex(row)
                if not tipos:
                    continue
                mult = _def_multiplier(tipos, atk)
                if mult < 1:
                    candidates.append({
                        'id': row.get('id'), 'pokemon': row.get('pokemon'), 'image': row.get('imagem_url'),
                        'types': tipos, 'tier': row.get('tier') or 'Sem tier', 'mult': mult,
                        'mult_label': _friendly_mult(mult), 'role': row.get('papeis') or '',
                    })
            candidates.sort(key=lambda x: (0 if x['mult'] == 0 else 1, _tier_score(x['tier']), str(x['pokemon']).casefold()))
            if candidates:
                suggestions.append({'type': atk, 'label': threat['label'], 'weak': threat['weak'], 'candidates': candidates[:6]})

        return {
            'matrix': matrix,
            'summary': summary_rows,
            'threats': threats,
            'answers': answers,
            'detected': detected,
            'notes': notes,
            'suggestions': suggestions,
            'types': TYPE_ORDER,
            'type_labels': TYPE_LABELS,
        }

    @bp.route('/hype-builders/sinergia')
    @login_required
    def sinergia():
        email = session.get('usuario_email')
        times = safe_table('times_pokemon', '*', usuario_email=email)
        times.sort(key=lambda x: x.get('updated_at') or x.get('created_at') or '', reverse=True)
        selected_id = request.args.get('team_id', type=int)
        selected = None
        if times:
            selected = next((x for x in times if x.get('id') == selected_id), None) if selected_id else times[0]
        analysis = _build_synergy(selected) if selected else None
        return render_template('builders_sinergia.html', times=times, selected=selected, analysis=analysis, type_labels=TYPE_LABELS)

    @bp.route('/hype-builders/calculadora-dano')
    def calculadora_dano():
        return render_template('builders_dano.html', type_labels=TYPE_LABELS)

    @bp.route('/hype-builders/tier-list')
    def tier_list():
        rows = [x for x in safe_table('pokedex_competitiva') if x.get('publicado', True)]
        formatos = [x for x in safe_table('formatos_competitivos') if x.get('ativo', True)]
        formatos.sort(key=lambda x: (x.get('nome') or '').casefold())

        q = (request.args.get('q') or '').strip().casefold()
        tier_filter = (request.args.get('tier') or '').strip().casefold()
        tipo_filter = (request.args.get('tipo') or '').strip().casefold()
        papel_filter = (request.args.get('papel') or '').strip().casefold()
        formato = (request.args.get('formato') or '').strip()

        tier_map = {}
        if formato:
            for m in safe_table('tiers_pokemon_formato', '*', formato_codigo=formato):
                if m.get('pokemon_id') is not None:
                    tier_map[m.get('pokemon_id')] = m
            rows = [x for x in rows if x.get('id') in tier_map]

        enriched = []
        for row in rows:
            item = dict(row)
            mapping = tier_map.get(row.get('id'))
            item['_tier'] = (mapping or {}).get('tier') or row.get('tier') or 'Sem tier'
            item['_tier_observacao'] = (mapping or {}).get('observacao') or ''
            item['_tipo1_slug'] = _type_slug(row.get('tipo1'))
            item['_tipo2_slug'] = _type_slug(row.get('tipo2'))
            enriched.append(item)

        if q:
            enriched = [x for x in enriched if q in _norm(x.get('pokemon')) or q in _norm(x.get('resumo')) or q in _norm(x.get('papeis'))]
        if tier_filter:
            enriched = [x for x in enriched if tier_filter == _norm(x.get('_tier'))]
        if tipo_filter:
            enriched = [x for x in enriched if tipo_filter in {_type_slug(x.get('tipo1')), _type_slug(x.get('tipo2'))}]
        if papel_filter:
            enriched = [x for x in enriched if papel_filter in _norm(x.get('papeis'))]

        ordem = {'S+': 0, 'S': 1, 'A+': 2, 'A': 3, 'A-': 4, 'UBER': 5, 'OU': 6, 'UU': 7, 'RU': 8, 'NU': 9, 'PU': 10, 'B': 11, 'C': 12, 'D': 13, 'LC': 14, 'UNTIERED': 90, 'SEM TIER': 99}
        grupos = {}
        for row in enriched:
            tier = str(row.get('_tier') or 'Sem tier').strip() or 'Sem tier'
            grupos.setdefault(tier, []).append(row)
        for itens in grupos.values():
            itens.sort(key=lambda x: (x.get('pokemon') or '').casefold())
        grupos = dict(sorted(grupos.items(), key=lambda kv: (ordem.get(kv[0].upper(), 50), kv[0].casefold())))

        all_rows = [x for x in safe_table('pokedex_competitiva') if x.get('publicado', True)]
        all_tiers = sorted({str(x.get('tier')).strip() for x in all_rows if x.get('tier')}, key=lambda x: (_tier_score(x), x.casefold()))
        if formato:
            all_tiers = sorted({str(m.get('tier')).strip() for m in tier_map.values() if m.get('tier')}, key=lambda x: (_tier_score(x), x.casefold()))
        all_types = sorted({_type_slug(x.get('tipo1')) for x in all_rows if _type_slug(x.get('tipo1')) in TYPE_ORDER} | {_type_slug(x.get('tipo2')) for x in all_rows if _type_slug(x.get('tipo2')) in TYPE_ORDER}, key=lambda x: TYPE_ORDER.index(x) if x in TYPE_ORDER else 99)

        return render_template(
            'builders_tier_list.html', grupos=grupos, formatos=formatos, tiers=all_tiers,
            tipos=all_types, type_labels=TYPE_LABELS,
            q=request.args.get('q', ''), tier_filter=request.args.get('tier', ''),
            tipo_filter=request.args.get('tipo', ''), papel_filter=request.args.get('papel', ''),
            formato_filter=formato, total=sum(len(v) for v in grupos.values()),
        )

    return bp
