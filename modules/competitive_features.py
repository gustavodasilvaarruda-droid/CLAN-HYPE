from flask import Blueprint, render_template, request, redirect, url_for, flash, session


def create_competitive_blueprint(supabase, login_required, safe_table, is_admin, registrar_log, criar_notificacao):
    bp = Blueprint('competitive', __name__)

    def email_atual():
        return session.get('usuario_email')

    def tem_permissao_competitivo():
        if is_admin():
            return True
        email = email_atual()
        if not email:
            return False
        usuarios = safe_table('usuarios_clan', 'cargo', email=email)
        if not usuarios:
            return False
        perms = safe_table('permissoes_cargos', '*', cargo_id=usuarios[0].get('cargo'))
        return bool(perms and perms[0].get('pode_gerenciar_competitivo'))

    def analisar_time(time):
        slots = time.get('slots') or []
        formato_codigo = time.get('formato_codigo')
        formato = None
        if formato_codigo:
            rows = safe_table('formatos_competitivos', '*', codigo=formato_codigo)
            formato = rows[0] if rows else None

        avisos, ok, coach = [], [], []
        pokemons = [str(s.get('pokemon') or '').strip() for s in slots if s.get('pokemon')]
        itens = [str(s.get('item') or '').strip() for s in slots if s.get('item')]
        papeis = [str(s.get('papel') or '').strip().casefold() for s in slots if s.get('papel')]

        limite = int((formato or {}).get('max_pokemon') or 6)
        if len(pokemons) > limite:
            avisos.append(f'O formato permite no máximo {limite} Pokémon, mas o time possui {len(pokemons)}.')
        elif len(pokemons) < limite:
            avisos.append(f'O time ainda possui {limite - len(pokemons)} slot(s) livre(s) para este formato.')
        else:
            ok.append('Quantidade de Pokémon compatível com o formato.')

        if (formato or {}).get('species_clause'):
            norm = [x.casefold() for x in pokemons]
            if any(norm.count(x) > 1 for x in set(norm)):
                avisos.append('Species Clause: existem Pokémon repetidos no time.')
            else:
                ok.append('Species Clause atendida.')

        if (formato or {}).get('item_clause'):
            norm_itens = [x.casefold() for x in itens if x]
            if any(norm_itens.count(x) > 1 for x in set(norm_itens)):
                avisos.append('Item Clause: existem itens repetidos no time.')
            else:
                ok.append('Item Clause atendida.')

        categorias = {
            'ofensiva': ('sweeper', 'atacante', 'breaker', 'wallbreaker', 'setup', 'ofensivo'),
            'suporte': ('suporte', 'support', 'cleric', 'pivot', 'screen', 'redirecionamento'),
            'velocidade': ('speed control', 'controle de velocidade', 'tailwind', 'trick room', 'scarf'),
            'defensiva': ('wall', 'tank', 'defensivo', 'defesa', 'bulky'),
            'hazards': ('hazard', 'rocks', 'stealth rock', 'spikes', 'toxic spikes'),
            'remocao': ('removal', 'defog', 'rapid spin', 'remoção', 'remocao'),
        }
        texto_papeis = ' | '.join(papeis)
        cobertura = {nome: any(chave in texto_papeis for chave in chaves) for nome, chaves in categorias.items()}
        if cobertura['ofensiva']:
            ok.append('Há pelo menos um papel ofensivo declarado.')
        else:
            avisos.append('Nenhum papel ofensivo foi declarado nos slots.')
        if cobertura['suporte']:
            ok.append('Há suporte/pivot declarado.')
        else:
            avisos.append('Considere declarar pelo menos um papel de suporte/pivot.')

        # Validação dos sets no estilo de um teambuilder competitivo.
        for s in slots:
            nome = str(s.get('pokemon') or 'Pokémon')
            evs = s.get('evs') if isinstance(s.get('evs'), dict) else {}
            try:
                total_evs = sum(max(0, int(v or 0)) for v in evs.values())
            except (TypeError, ValueError):
                total_evs = 0
            if total_evs > 510:
                avisos.append(f'{nome}: EVs somam {total_evs}; o limite padrão é 510.')
            elif total_evs:
                ok.append(f'{nome}: distribuição de EVs registrada ({total_evs}/510).')
            moves = [m for m in (s.get('moves') or []) if str(m).strip()]
            if len(moves) < 4:
                avisos.append(f'{nome}: possui {len(moves)}/4 golpes preenchidos.')

        mecanicas = [str(s.get('mecanica') or 'nenhuma').lower() for s in slots]
        regras_mecanica = {
            'mega': 'permite_mega',
            'zmove': 'permite_zmove',
            'tera': 'permite_tera',
            'dynamax': 'permite_dynamax',
        }
        for mecanica, campo in regras_mecanica.items():
            qtd = mecanicas.count(mecanica)
            if qtd and formato and not formato.get(campo, False):
                avisos.append(f'O formato selecionado não permite {mecanica.upper()}, mas o time usa essa mecânica.')
            elif qtd:
                ok.append(f'{mecanica.upper()} habilitado e usado em {qtd} slot(s).')
        if sum(1 for x in mecanicas if x in regras_mecanica) > 1:
            coach.append('Seu time usa mais de uma mecânica especial. Confirme se o regulamento permite combinar essas mecânicas na mesma equipe.')

        # Matriz defensiva por tipos. Usa apenas os tipos salvos pelo editor visual.
        chart = {
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
        tipos_atacantes = list(chart.keys())
        fraquezas, resistencias = {}, {}
        for atk in tipos_atacantes:
            fracos = resistentes = 0
            for s in slots:
                mult = 1.0
                for defesa in (s.get('tipos') or []):
                    mult *= chart.get(str(defesa).lower(), {}).get(atk, 1)
                if mult > 1:
                    fracos += 1
                elif mult < 1:
                    resistentes += 1
            if fracos:
                fraquezas[atk] = fracos
            if resistentes:
                resistencias[atk] = resistentes

        fraquezas_ordenadas = sorted(fraquezas.items(), key=lambda x: (-x[1], x[0]))
        resist_ordenadas = sorted(resistencias.items(), key=lambda x: (-x[1], x[0]))
        for tipo, qtd in fraquezas_ordenadas[:3]:
            if qtd >= 3:
                avisos.append(f'Fraqueza coletiva: {qtd} Pokémon são vulneráveis a {tipo.title()}.')
        if resist_ordenadas:
            tipo, qtd = resist_ordenadas[0]
            coach.append(f'Uma das melhores coberturas defensivas do time é contra {tipo.title()}, com {qtd} resistência(s)/imunidade(s) registradas.')

        if cobertura['hazards'] and cobertura['remocao']:
            coach.append('Você declarou pressão de hazards e também remoção: isso dá flexibilidade para controlar o campo durante a partida.')
        elif cobertura['hazards'] and not cobertura['remocao']:
            coach.append('Seu time pressiona com hazards, mas não declarou remoção. Tome cuidado contra equipes que também empilham hazards.')
        elif not cobertura['hazards'] and cobertura['remocao']:
            coach.append('Você possui remoção de hazards, mas não declarou hazards próprios; isso favorece um plano mais reativo ou ofensivo.')

        if cobertura['velocidade']:
            coach.append('Há controle de velocidade declarado. Tente preservá-lo para o meio/final da partida, quando revenge kills ficam mais importantes.')
        else:
            coach.append('Não foi identificado controle de velocidade. Times rápidos ou setup sweepers podem exigir posicionamento mais cuidadoso.')

        if cobertura['ofensiva'] and cobertura['suporte']:
            coach.append('A composição mostra funções ofensivas e de suporte. Use pivôs/suportes para criar entradas seguras para seus atacantes e preservar a condição de vitória.')
        elif cobertura['ofensiva']:
            coach.append('O time parece mais agressivo. Evite trocas passivas e tente manter pressão para não dar turnos gratuitos ao adversário.')
        else:
            coach.append('O time aparenta ser mais defensivo ou ainda está incompleto. Defina claramente quem será sua condição de vitória antes de finalizar a equipe.')

        return {
            'formato': formato,
            'avisos': avisos,
            'ok': ok,
            'coach': coach,
            'total_pokemon': len(pokemons),
            'cobertura_papeis': cobertura,
            'fraquezas_tipos': fraquezas_ordenadas,
            'resistencias_tipos': resist_ordenadas,
        }

    @bp.route('/pokedex-competitiva')
    def pokedex_competitiva():
        termo = (request.args.get('q') or '').strip().casefold()
        papel = (request.args.get('papel') or '').strip().casefold()
        tier = (request.args.get('tier') or '').strip().casefold()
        rows = [x for x in safe_table('pokedex_competitiva') if x.get('publicado', True)]
        if termo:
            rows = [x for x in rows if termo in str(x.get('pokemon') or '').casefold()
                    or termo in str(x.get('resumo') or '').casefold()
                    or termo in str(x.get('tipo1') or '').casefold()
                    or termo in str(x.get('tipo2') or '').casefold()]
        if papel:
            rows = [x for x in rows if papel in str(x.get('papeis') or '').casefold()]
        if tier:
            rows = [x for x in rows if tier == str(x.get('tier') or '').casefold()]
        rows.sort(key=lambda x: (x.get('pokemon') or '').casefold())
        tiers = sorted({str(x.get('tier')).strip() for x in safe_table('pokedex_competitiva') if x.get('publicado', True) and x.get('tier')}, key=str.casefold)
        return render_template('pokedex_competitiva.html', registros=rows, q=request.args.get('q', ''), papel=request.args.get('papel', ''), tier=request.args.get('tier', ''), tiers=tiers)

    @bp.route('/pokedex-competitiva/<int:registro_id>')
    def pokedex_detalhe(registro_id):
        rows = safe_table('pokedex_competitiva', '*', id=registro_id)
        if not rows or not rows[0].get('publicado', True):
            flash('Registro competitivo não encontrado.', 'erro')
            return redirect(url_for('competitive.pokedex_competitiva'))
        pokemon = rows[0]
        builds = [x for x in safe_table('builds_pokemon')
                  if x.get('publicado') and str(x.get('pokemon') or '').casefold() == str(pokemon.get('pokemon') or '').casefold()]
        builds.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        return render_template('pokedex_competitiva_detalhe.html', pokemon=pokemon, builds=builds)

    @bp.route('/admin/pokedex-competitiva', methods=['GET', 'POST'])
    @login_required
    def admin_pokedex_competitiva():
        if not tem_permissao_competitivo():
            return redirect(url_for('painel'))
        if request.method == 'POST':
            pokemon = (request.form.get('pokemon') or '').strip()
            if not pokemon:
                flash('Informe o nome do Pokémon.', 'erro')
                return redirect(url_for('competitive.admin_pokedex_competitiva'))
            dex_id = request.form.get('dex_id') or None
            try:
                dex_id = int(dex_id) if dex_id else None
            except ValueError:
                dex_id = None
            data = {
                'pokemon': pokemon,
                'dex_id': dex_id,
                'tipo1': (request.form.get('tipo1') or '').strip() or None,
                'tipo2': (request.form.get('tipo2') or '').strip() or None,
                'tier': (request.form.get('tier') or '').strip() or None,
                'resumo': (request.form.get('resumo') or '').strip() or None,
                'papeis': (request.form.get('papeis') or '').strip() or None,
                'pontos_fortes': (request.form.get('pontos_fortes') or '').strip() or None,
                'pontos_fracos': (request.form.get('pontos_fracos') or '').strip() or None,
                'parceiros': (request.form.get('parceiros') or '').strip() or None,
                'matchups': (request.form.get('matchups') or '').strip() or None,
                'legalidade': (request.form.get('legalidade') or '').strip() or None,
                'imagem_url': (request.form.get('imagem_url') or '').strip() or None,
                'publicado': request.form.get('publicado') == 'on',
                'atualizado_por': email_atual(),
            }
            try:
                existentes = [x for x in safe_table('pokedex_competitiva', 'id,pokemon')
                              if str(x.get('pokemon') or '').casefold() == pokemon.casefold()]
                if existentes:
                    supabase.table('pokedex_competitiva').update(data).eq('id', existentes[0]['id']).execute()
                    registro_id, acao = existentes[0]['id'], 'editar'
                else:
                    res = supabase.table('pokedex_competitiva').insert(data).execute()
                    registro_id, acao = (res.data or [{}])[0].get('id'), 'criar'
                registrar_log(acao, 'pokedex_competitiva', 'pokemon', registro_id, {'pokemon': pokemon})
                flash('Pokédex competitiva atualizada.', 'sucesso')
            except Exception as e:
                flash(f'Erro ao salvar: {e}', 'erro')
            return redirect(url_for('competitive.admin_pokedex_competitiva'))
        registros = sorted(safe_table('pokedex_competitiva'), key=lambda x: (x.get('pokemon') or '').casefold())
        return render_template('admin_pokedex_competitiva.html', registros=registros)

    @bp.route('/admin/tiers-competitivos', methods=['GET', 'POST'])
    @login_required
    def admin_tiers_competitivos():
        if not tem_permissao_competitivo():
            return redirect(url_for('painel'))

        if request.method == 'POST':
            acao = (request.form.get('acao') or 'salvar').strip().lower()
            try:
                pokemon_id = int(request.form.get('pokemon_id') or 0)
            except ValueError:
                pokemon_id = 0
            formato_codigo = (request.form.get('formato_codigo') or '').strip()

            if not pokemon_id or not formato_codigo:
                flash('Escolha o Pokémon e o formato.', 'erro')
                return redirect(url_for('competitive.admin_tiers_competitivos'))

            if acao == 'excluir':
                try:
                    supabase.table('tiers_pokemon_formato').delete().eq('pokemon_id', pokemon_id).eq('formato_codigo', formato_codigo).execute()
                    registrar_log('excluir', 'tiers_pokemon_formato', 'pokemon', pokemon_id, {'formato': formato_codigo})
                    flash('Tier específico removido.', 'sucesso')
                except Exception as e:
                    flash(f'Erro ao remover tier: {e}', 'erro')
                return redirect(url_for('competitive.admin_tiers_competitivos', formato=formato_codigo))

            tier = (request.form.get('tier') or '').strip()
            observacao = (request.form.get('observacao') or '').strip() or None
            if not tier:
                flash('Informe o tier.', 'erro')
                return redirect(url_for('competitive.admin_tiers_competitivos', formato=formato_codigo))

            pokemons = safe_table('pokedex_competitiva', 'id,pokemon', id=pokemon_id)
            formatos = safe_table('formatos_competitivos', 'codigo,nome', codigo=formato_codigo)
            if not pokemons or not formatos:
                flash('Pokémon ou formato inválido.', 'erro')
                return redirect(url_for('competitive.admin_tiers_competitivos'))

            data = {
                'pokemon_id': pokemon_id,
                'formato_codigo': formato_codigo,
                'tier': tier,
                'observacao': observacao,
                'atualizado_por': email_atual(),
            }
            try:
                supabase.table('tiers_pokemon_formato').upsert(
                    data, on_conflict='pokemon_id,formato_codigo'
                ).execute()
                registrar_log('salvar', 'tiers_pokemon_formato', 'pokemon', pokemon_id, data)
                flash('Tier por formato atualizado.', 'sucesso')
            except Exception as e:
                flash(f'Erro ao salvar tier: {e}', 'erro')
            return redirect(url_for('competitive.admin_tiers_competitivos', formato=formato_codigo))

        formato_filtro = (request.args.get('formato') or '').strip()
        pokemons = sorted(
            [x for x in safe_table('pokedex_competitiva') if x.get('publicado', True)],
            key=lambda x: (x.get('pokemon') or '').casefold()
        )
        formatos = sorted(
            [x for x in safe_table('formatos_competitivos') if x.get('ativo', True)],
            key=lambda x: (x.get('nome') or '').casefold()
        )
        mappings = safe_table('tiers_pokemon_formato')
        if formato_filtro:
            mappings = [x for x in mappings if x.get('formato_codigo') == formato_filtro]
        pokemon_by_id = {x.get('id'): x for x in pokemons}
        formato_by_codigo = {x.get('codigo'): x for x in formatos}
        for row in mappings:
            row['_pokemon'] = (pokemon_by_id.get(row.get('pokemon_id')) or {}).get('pokemon') or f"#{row.get('pokemon_id')}"
            row['_formato'] = (formato_by_codigo.get(row.get('formato_codigo')) or {}).get('nome') or row.get('formato_codigo')
        mappings.sort(key=lambda x: (str(x.get('_formato') or '').casefold(), str(x.get('_pokemon') or '').casefold()))
        return render_template(
            'admin_tiers_competitivos.html', pokemons=pokemons, formatos=formatos,
            mappings=mappings, formato_filtro=formato_filtro
        )

    @bp.route('/admin/formatos-competitivos', methods=['GET', 'POST'])
    @login_required
    def admin_formatos():
        if not tem_permissao_competitivo():
            return redirect(url_for('painel'))
        if request.method == 'POST':
            codigo = (request.form.get('codigo') or '').strip().lower().replace(' ', '_')
            nome = (request.form.get('nome') or '').strip()
            try:
                max_pokemon = max(1, min(6, int(request.form.get('max_pokemon') or 6)))
            except ValueError:
                max_pokemon = 6
            if not codigo or not nome:
                flash('Informe código e nome do formato.', 'erro')
            elif not all(c.isalnum() or c == '_' for c in codigo):
                flash('O código do formato deve usar somente letras, números e _.', 'erro')
            else:
                data = {
                    'codigo': codigo,
                    'nome': nome,
                    'descricao': (request.form.get('descricao') or '').strip() or None,
                    'max_pokemon': max_pokemon,
                    'species_clause': request.form.get('species_clause') == 'on',
                    'item_clause': request.form.get('item_clause') == 'on',
                    'permite_mega': request.form.get('permite_mega') == 'on',
                    'permite_zmove': request.form.get('permite_zmove') == 'on',
                    'permite_tera': request.form.get('permite_tera') == 'on',
                    'permite_dynamax': request.form.get('permite_dynamax') == 'on',
                    'regras': (request.form.get('regras') or '').strip() or None,
                    'ativo': request.form.get('ativo') == 'on',
                }
                try:
                    supabase.table('formatos_competitivos').upsert(data, on_conflict='codigo').execute()
                    registrar_log('salvar', 'formatos_competitivos', 'formato', codigo, data)
                    flash('Formato competitivo salvo.', 'sucesso')
                except Exception as e:
                    flash(f'Erro ao salvar formato: {e}', 'erro')
            return redirect(url_for('competitive.admin_formatos'))
        formatos = sorted(safe_table('formatos_competitivos'), key=lambda x: (x.get('nome') or '').casefold())
        return render_template('admin_formatos_competitivos.html', formatos=formatos)

    @bp.route('/builds-pokemon/<int:build_id>/favoritar', methods=['POST'])
    @login_required
    def favoritar_build(build_id):
        email = email_atual()
        builds = safe_table('builds_pokemon', 'id,publicado', id=build_id)
        if not builds or not builds[0].get('publicado'):
            flash('Build não encontrada.', 'erro')
            return redirect(url_for('final.builds_pokemon'))
        fav = safe_table('builds_favoritos', '*', usuario_email=email, build_id=build_id)
        try:
            if fav:
                supabase.table('builds_favoritos').delete().eq('usuario_email', email).eq('build_id', build_id).execute()
                flash('Build removida dos favoritos.', 'sucesso')
            else:
                supabase.table('builds_favoritos').insert({'usuario_email': email, 'build_id': build_id}).execute()
                flash('Build adicionada aos favoritos.', 'sucesso')
        except Exception as e:
            flash(f'Não foi possível atualizar favoritos: {e}', 'erro')
        return redirect(request.referrer or url_for('final.builds_pokemon'))

    @bp.route('/meus-favoritos')
    @login_required
    def meus_favoritos():
        favs = safe_table('builds_favoritos', '*', usuario_email=email_atual())
        ids = {x.get('build_id') for x in favs}
        builds = [x for x in safe_table('builds_pokemon') if x.get('id') in ids and x.get('publicado')]
        builds.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        return render_template('builds_favoritos.html', builds=builds)

    @bp.route('/team-builder/<int:team_id>/analisar')
    @login_required
    def analisar_team(team_id):
        rows = safe_table('times_pokemon', '*', id=team_id)
        if not rows:
            flash('Time não encontrado.', 'erro')
            return redirect(url_for('expansion.team_builder'))
        time = rows[0]
        if time.get('usuario_email') != email_atual() and not time.get('publico') and not is_admin():
            flash('Você não tem acesso a este time.', 'erro')
            return redirect(url_for('expansion.team_builder'))
        analise = analisar_time(time)
        return render_template('team_analise.html', time=time, analise=analise)

    return bp
