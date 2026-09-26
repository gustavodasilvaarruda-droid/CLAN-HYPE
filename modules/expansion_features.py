from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_from_directory
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
import json
import os


def create_expansion_blueprint(supabase, login_required, safe_table, is_admin, registrar_log,
                               parse_valor, criar_notificacao):
    bp = Blueprint('expansion', __name__)

    def email_atual():
        return session.get('usuario_email')

    def config_dict():
        return {x.get('chave'): (x.get('valor') or '') for x in safe_table('configuracoes_site')}

    def youtube_embed_url(url):
        url = (url or '').strip()
        if not url:
            return None
        try:
            p = urlparse(url)
            host = (p.netloc or '').lower().replace('www.', '')
            vid = None
            if host == 'youtu.be':
                vid = p.path.strip('/').split('/')[0]
            elif host in ('youtube.com', 'm.youtube.com'):
                if p.path == '/watch':
                    vid = parse_qs(p.query).get('v', [None])[0]
                elif p.path.startswith('/live/') or p.path.startswith('/shorts/') or p.path.startswith('/embed/'):
                    partes = [x for x in p.path.split('/') if x]
                    if len(partes) >= 2:
                        vid = partes[1]
            if vid:
                return f'https://www.youtube.com/embed/{vid}?autoplay=0&rel=0'
        except Exception:
            pass
        return None

    def tem_permissao_extra(chave):
        if is_admin():
            return True
        rows = safe_table('usuarios_clan', 'cargo', email=email_atual())
        if not rows:
            return False
        perms = safe_table('permissoes_cargos', '*', cargo_id=rows[0].get('cargo'))
        return bool(perms and perms[0].get(chave))

    def saldo_usuario(email):
        saldo = 0
        for t in safe_table('transacoes_hype', '*', usuario_email=email):
            valor = int(t.get('valor') or 0)
            saldo += valor if t.get('tipo') == 'entrada' else -valor
        return saldo

    def registrar_transacao(usuario_email, tipo, categoria, descricao, valor,
                            origem_tipo=None, origem_id=None, contraparte_email=None,
                            chave_unica=None, criado_por=None):
        if not usuario_email or tipo not in ('entrada', 'saida'):
            return False
        try:
            data = {
                'usuario_email': usuario_email,
                'tipo': tipo,
                'categoria': categoria or 'geral',
                'descricao': descricao or categoria or 'Movimentação HYPE',
                'valor': max(0, int(valor or 0)),
                'origem_tipo': origem_tipo,
                'origem_id': origem_id,
                'contraparte_email': contraparte_email,
                'criado_por': criado_por or email_atual(),
                'chave_unica': chave_unica,
            }
            supabase.table('transacoes_hype').insert(data).execute()
            return True
        except Exception as e:
            # Chave única repetida significa que a transação já foi registrada.
            if chave_unica and ('duplicate' in str(e).lower() or 'unique' in str(e).lower()):
                return False
            print(f'[transacoes_hype] {e}')
            return False

    @bp.app_context_processor
    def contexto_expansao():
        cfg = config_dict()
        live_ativo = str(cfg.get('youtube_live_ativo', '')).lower() in ('1', 'true', 'on', 'sim', 'yes')
        embed = youtube_embed_url(cfg.get('youtube_live_url')) if live_ativo else None
        mostrar_tour = False
        if email_atual():
            try:
                rows = safe_table('usuarios_clan', 'onboarding_concluido', email=email_atual())
                mostrar_tour = bool(rows and not rows[0].get('onboarding_concluido'))
            except Exception:
                mostrar_tour = False
        return {
            'hype_live_ativo': live_ativo and bool(embed),
            'hype_live_embed_url': embed,
            'hype_live_titulo': cfg.get('youtube_live_titulo') or 'HYPE Live',
            'mostrar_tour_hype': mostrar_tour,
        }

    @bp.route('/onboarding/concluir', methods=['POST'])
    @login_required
    def onboarding_concluir():
        try:
            supabase.table('usuarios_clan').update({
                'onboarding_concluido': True,
                'onboarding_concluido_em': datetime.now(timezone.utc).isoformat()
            }).eq('email', email_atual()).execute()
            flash('Introdução concluída. Bem-vindo à experiência HYPE!', 'sucesso')
        except Exception as e:
            flash(f'Não foi possível concluir a introdução: {e}', 'erro')
        return redirect(url_for('painel'))

    @bp.route('/live')
    def hype_live():
        cfg = config_dict()
        ativo = str(cfg.get('youtube_live_ativo', '')).lower() in ('1', 'true', 'on', 'sim', 'yes')
        return render_template(
            'hype_live.html',
            titulo=cfg.get('youtube_live_titulo') or 'HYPE Live',
            youtube_url=cfg.get('youtube_live_url') or '',
            embed_url=youtube_embed_url(cfg.get('youtube_live_url')) if ativo else None,
            ativo=ativo,
        )

    @bp.route('/reino/mapa')
    @login_required
    def mapa_reino():
        casas = [x for x in safe_table('casas_reino') if x.get('ativa', True) and x.get('status') != 'desativada']
        lojas = [x for x in safe_table('lojas_reino') if x.get('ativa', True) and x.get('status') != 'desativada']
        setores = {}
        for c in casas:
            setor = c.get('setor') or 'Distrito sem nome'
            setores.setdefault(setor, {'casas': [], 'lojas': []})['casas'].append(c)
        for l in lojas:
            setor = l.get('setor') or 'Distrito sem nome'
            setores.setdefault(setor, {'casas': [], 'lojas': []})['lojas'].append(l)
        setores = dict(sorted(setores.items(), key=lambda x: x[0].lower()))
        return render_template('mapa_reino.html', setores=setores)

    @bp.route('/economia')
    @login_required
    def economia_usuario():
        email = email_atual()
        transacoes = sorted(
            safe_table('transacoes_hype', '*', usuario_email=email),
            key=lambda x: x.get('created_at') or '', reverse=True
        )
        entradas = sum(int(x.get('valor') or 0) for x in transacoes if x.get('tipo') == 'entrada')
        saidas = sum(int(x.get('valor') or 0) for x in transacoes if x.get('tipo') == 'saida')
        return render_template('economia.html', transacoes=transacoes, entradas=entradas, saidas=saidas, saldo=entradas-saidas)

    @bp.route('/admin')
    @bp.route('/admin/dashboard')
    @login_required
    def admin_dashboard():
        if not is_admin():
            return redirect(url_for('painel'))

        usuarios = safe_table('usuarios_clan')
        membros = [x for x in safe_table('membros_hype') if x.get('ativo')]
        breeds = safe_table('pedidos_breed')
        casas = [x for x in safe_table('casas_reino') if x.get('ativa', True)]
        lojas = [x for x in safe_table('lojas_reino') if x.get('ativa', True)]
        eventos = [x for x in safe_table('eventos') if x.get('publicado', True)]
        torneios = [x for x in safe_table('torneios') if x.get('publicado', True)]
        trans = safe_table('transacoes_hype')
        pokemon_catalogo = safe_table('precos_pokemon')

        casas_ocupadas = sum(x.get('status') == 'ocupada' for x in casas)
        lojas_ocupadas = sum(x.get('status') == 'ocupada' for x in lojas)
        stats = {
            'usuarios': len(usuarios),
            'membros': len(membros),
            'pokemon_catalogo': len(pokemon_catalogo),
            'breed_total': len(breeds),
            'breed_pendentes': sum(x.get('status') == 'pendente' for x in breeds),
            'breed_pagamento': sum(x.get('status') == 'aguardando_pagamento' for x in breeds),
            'breed_producao': sum(x.get('status') in ('em_producao', 'em_andamento') for x in breeds),
            'breed_entregues': sum(x.get('status') == 'entregue' for x in breeds),
            'valor_breed_entregue': sum(int(x.get('preco_total') or 0) for x in breeds if x.get('status') == 'entregue'),
            'casas_total': len(casas),
            'casas_ocupadas': casas_ocupadas,
            'casas_pct': round((casas_ocupadas / len(casas)) * 100) if casas else 0,
            'lojas_total': len(lojas),
            'lojas_ocupadas': lojas_ocupadas,
            'lojas_pct': round((lojas_ocupadas / len(lojas)) * 100) if lojas else 0,
            'eventos': len(eventos),
            'torneios': len(torneios),
            'movimentado': sum(int(x.get('valor') or 0) for x in trans),
        }

        logs = sorted(safe_table('logs_admin'), key=lambda x: x.get('created_at') or '', reverse=True)[:8]
        ultimos_breeds = sorted(breeds, key=lambda x: x.get('created_at') or '', reverse=True)[:6]

        agenda = []
        for e in eventos:
            agenda.append({'tipo': 'Evento', 'titulo': e.get('titulo'), 'data': e.get('data_evento'), 'status': 'Publicado'})
        for t in torneios:
            agenda.append({'tipo': 'Torneio', 'titulo': t.get('titulo'), 'data': t.get('data_torneio'), 'status': 'Inscrições abertas' if t.get('inscricoes_abertas') else 'Programado'})
        agenda = sorted(agenda, key=lambda x: x.get('data') or '')[:5]

        # Série real de adesões HYPE dos últimos 6 meses. Não inventa números quando não há histórico.
        hoje = datetime.now(timezone.utc).date()
        meses = []
        for deslocamento in range(5, -1, -1):
            ano = hoje.year
            mes = hoje.month - deslocamento
            while mes <= 0:
                mes += 12
                ano -= 1
            meses.append((ano, mes))
        crescimento = []
        for ano, mes in meses:
            total = 0
            for m in membros:
                try:
                    entrada = datetime.fromisoformat(str(m.get('entrou_em')).replace('Z', '+00:00')).date()
                    if (entrada.year, entrada.month) <= (ano, mes):
                        total += 1
                except Exception:
                    pass
            crescimento.append({'label': f'{mes:02d}/{str(ano)[2:]}', 'valor': total})

        return render_template(
            'admin_dashboard_geral.html', stats=stats, logs=logs,
            ultimos_breeds=ultimos_breeds, agenda=agenda, crescimento=crescimento
        )

    @bp.route('/admin/economia', methods=['GET', 'POST'])
    @login_required
    def admin_economia():
        if not tem_permissao_extra('pode_gerenciar_economia'):
            return redirect(url_for('painel'))
        if request.method == 'POST':
            alvo = (request.form.get('usuario_email') or '').strip().lower()
            tipo = request.form.get('tipo') or 'entrada'
            categoria = (request.form.get('categoria') or 'ajuste').strip()[:80]
            descricao = (request.form.get('descricao') or 'Ajuste administrativo').strip()[:500]
            valor = parse_valor(request.form.get('valor'))
            if not safe_table('usuarios_clan', 'email', email=alvo):
                flash('Usuário não encontrado.', 'erro')
            elif tipo not in ('entrada', 'saida') or valor < 0:
                flash('Movimentação inválida.', 'erro')
            else:
                registrar_transacao(alvo, tipo, categoria, descricao, valor, origem_tipo='admin')
                registrar_log('transacao_manual', 'economia', 'usuario', alvo, {'tipo': tipo, 'categoria': categoria, 'valor': valor})
                flash('Movimentação registrada no extrato.', 'sucesso')
            return redirect(url_for('expansion.admin_economia'))

        usuarios = sorted(safe_table('usuarios_clan', 'email,nick_jogo'), key=lambda x: (x.get('nick_jogo') or '').lower())
        transacoes = sorted(safe_table('transacoes_hype'), key=lambda x: x.get('created_at') or '', reverse=True)[:300]
        por_usuario = []
        for u in usuarios:
            por_usuario.append({**u, 'saldo': saldo_usuario(u.get('email'))})
        return render_template('admin_economia.html', usuarios=usuarios, transacoes=transacoes, por_usuario=por_usuario)

    @bp.route('/admin/economia/cobrar-alugueis', methods=['POST'])
    @login_required
    def cobrar_alugueis():
        if not tem_permissao_extra('pode_gerenciar_economia'):
            return redirect(url_for('painel'))
        hoje = datetime.now(timezone.utc).date()
        total = 0
        for tabela, prefixo, origem, id_key in [
            ('contratos_casas', 'Casa', 'aluguel_casa', 'casa_id'),
            ('contratos_lojas', 'Loja', 'aluguel_loja', 'loja_id'),
        ]:
            for c in safe_table(tabela, '*', status='ativo'):
                venc = c.get('proximo_vencimento')
                if not venc:
                    continue
                try:
                    data_venc = datetime.fromisoformat(str(venc)[:10]).date()
                except Exception:
                    continue
                if data_venc > hoje:
                    continue
                valor = int(c.get('valor_semanal') or 0)
                chave = f'{origem}:{c.get("id")}:{data_venc.isoformat()}'
                if registrar_transacao(
                    c.get('usuario_email'), 'saida', origem,
                    f'{prefixo} - aluguel semanal vencido em {data_venc.isoformat()}', valor,
                    origem_tipo=origem, origem_id=c.get(id_key), chave_unica=chave
                ):
                    total += 1
                    novo_venc = data_venc + timedelta(days=7)
                    while novo_venc <= hoje:
                        novo_venc += timedelta(days=7)
                    supabase.table(tabela).update({'proximo_vencimento': novo_venc.isoformat()}).eq('id', c.get('id')).execute()
                    criar_notificacao(
                        c.get('usuario_email'), 'Aluguel registrado',
                        f'Foi registrado no seu extrato o aluguel semanal de {prefixo.lower()} no valor de {valor}.',
                        'info', url_for('expansion.economia_usuario')
                    )
        registrar_log('cobrar_alugueis', 'economia', detalhes={'registros': total})
        flash(f'{total} cobrança(s) de aluguel registrada(s).', 'sucesso')
        return redirect(url_for('expansion.admin_economia'))

    @bp.route('/team-builder', methods=['GET', 'POST'])
    @login_required
    def team_builder():
        email = email_atual()
        formatos = sorted([x for x in safe_table('formatos_competitivos') if x.get('ativo', True)], key=lambda x: (x.get('nome') or '').casefold())
        edit_id = request.args.get('editar', type=int)
        editing_team = None
        if edit_id:
            rows_edit = safe_table('times_pokemon', '*', id=edit_id)
            if rows_edit and rows_edit[0].get('usuario_email') == email:
                editing_team = rows_edit[0]

        if request.method == 'POST':
            team_id = request.form.get('team_id', type=int)
            nome = (request.form.get('nome') or '').strip()
            formato_codigo = (request.form.get('formato_codigo') or '').strip() or None
            formato_livre = (request.form.get('formato') or '').strip() or None
            formato_row = next((x for x in formatos if x.get('codigo') == formato_codigo), None)
            formato = (formato_row or {}).get('nome') or formato_livre
            descricao = (request.form.get('descricao') or '').strip() or None

            slots = []
            bruto = (request.form.get('slots_json') or '').strip()
            if bruto:
                try:
                    dados = json.loads(bruto)
                    if isinstance(dados, list):
                        for slot in dados[:6]:
                            if not isinstance(slot, dict):
                                continue
                            pokemon = str(slot.get('pokemon') or '').strip()
                            if not pokemon:
                                continue
                            clean = {
                                'pokemon': pokemon[:80],
                                'pokemon_id': slot.get('pokemon_id') if isinstance(slot.get('pokemon_id'), int) else None,
                                'sprite': str(slot.get('sprite') or '').strip()[:500],
                                'tipos': [str(x).strip().lower()[:30] for x in (slot.get('tipos') or []) if str(x).strip()][:2],
                                'item': str(slot.get('item') or '').strip()[:100],
                                'ability': str(slot.get('ability') or '').strip()[:100],
                                'nature': str(slot.get('nature') or '').strip()[:40],
                                'papel': str(slot.get('papel') or '').strip()[:80],
                                'mecanica': str(slot.get('mecanica') or 'nenhuma').strip()[:30],
                                'tera_type': str(slot.get('tera_type') or '').strip()[:30],
                                'observacao': str(slot.get('observacao') or '').strip()[:500],
                                'moves': [str(x).strip()[:100] for x in (slot.get('moves') or []) if str(x).strip()][:4],
                                'evs': slot.get('evs') if isinstance(slot.get('evs'), dict) else {},
                                'ivs': slot.get('ivs') if isinstance(slot.get('ivs'), dict) else {},
                            }
                            slots.append(clean)
                except (ValueError, TypeError):
                    slots = []

            # Compatibilidade com o formulário antigo.
            if not slots:
                for i in range(1, 7):
                    pokemon = (request.form.get(f'pokemon_{i}') or '').strip()
                    if not pokemon:
                        continue
                    slots.append({
                        'pokemon': pokemon,
                        'item': (request.form.get(f'item_{i}') or '').strip(),
                        'papel': (request.form.get(f'papel_{i}') or '').strip(),
                        'observacao': (request.form.get(f'observacao_{i}') or '').strip(),
                    })

            if not nome or not slots:
                flash('Informe o nome do time e pelo menos um Pokémon.', 'erro')
            else:
                payload = {
                    'usuario_email': email,
                    'nome': nome,
                    'formato': formato,
                    'formato_codigo': formato_codigo,
                    'descricao': descricao,
                    'slots': slots,
                    'publico': request.form.get('publico') == 'on'
                }
                existente = safe_table('times_pokemon', '*', id=team_id) if team_id else []
                if existente and existente[0].get('usuario_email') == email:
                    payload.pop('usuario_email', None)
                    supabase.table('times_pokemon').update(payload).eq('id', team_id).execute()
                    flash('Time atualizado no HYPE Team Builder.', 'sucesso')
                else:
                    supabase.table('times_pokemon').insert(payload).execute()
                    flash('Time salvo no HYPE Team Builder.', 'sucesso')
            return redirect(url_for('expansion.team_builder'))

        meus = sorted(safe_table('times_pokemon', '*', usuario_email=email), key=lambda x: x.get('updated_at') or '', reverse=True)
        publicos = sorted([x for x in safe_table('times_pokemon') if x.get('publico') and x.get('usuario_email') != email], key=lambda x: x.get('updated_at') or '', reverse=True)[:20]
        builds_pessoais = sorted(safe_table('builds_pessoais', '*', usuario_email=email), key=lambda x: x.get('updated_at') or x.get('created_at') or '', reverse=True)
        favoritos_rows = safe_table('times_favoritos', '*', usuario_email=email)
        favoritos_ids = [int(x.get('time_id')) for x in favoritos_rows if x.get('time_id') is not None]
        prefill_pokemon = (request.args.get('pokemon') or '').strip()[:80]
        return render_template('team_builder.html', meus_times=meus, times_publicos=publicos, formatos=formatos, builds_pessoais=builds_pessoais, prefill_pokemon=prefill_pokemon, editing_team=editing_team, favoritos_ids=favoritos_ids)

    @bp.route('/team-builder/build/salvar', methods=['POST'])
    @login_required
    def team_builder_salvar_build():
        email = email_atual()
        nome = (request.form.get('nome_build') or '').strip()
        formato_codigo = (request.form.get('formato_codigo') or '').strip() or None
        bruto = (request.form.get('build_json') or '').strip()
        try:
            dados = json.loads(bruto) if bruto else {}
        except (ValueError, TypeError):
            dados = {}
        pokemon = str(dados.get('pokemon') or '').strip()
        if not nome or not pokemon:
            flash('Escolha um Pokémon e dê um nome para salvar a Build.', 'erro')
            return redirect(url_for('expansion.team_builder'))
        clean = {
            'pokemon': pokemon[:80],
            'pokemon_id': dados.get('pokemon_id') if isinstance(dados.get('pokemon_id'), int) else None,
            'sprite': str(dados.get('sprite') or '').strip()[:500],
            'tipos': [str(x).strip().lower()[:30] for x in (dados.get('tipos') or []) if str(x).strip()][:2],
            'item': str(dados.get('item') or '').strip()[:100],
            'ability': str(dados.get('ability') or '').strip()[:100],
            'nature': str(dados.get('nature') or '').strip()[:40],
            'papel': str(dados.get('papel') or '').strip()[:80],
            'mecanica': str(dados.get('mecanica') or 'nenhuma').strip()[:30],
            'tera_type': str(dados.get('tera_type') or '').strip()[:30],
            'observacao': str(dados.get('observacao') or '').strip()[:500],
            'moves': [str(x).strip()[:100] for x in (dados.get('moves') or []) if str(x).strip()][:4],
            'evs': dados.get('evs') if isinstance(dados.get('evs'), dict) else {},
            'ivs': dados.get('ivs') if isinstance(dados.get('ivs'), dict) else {},
        }
        try:
            supabase.table('builds_pessoais').insert({
                'usuario_email': email,
                'nome': nome[:120],
                'pokemon': pokemon[:80],
                'pokemon_id': clean.get('pokemon_id'),
                'formato_codigo': formato_codigo,
                'dados': clean,
            }).execute()
            flash('Build pessoal salva. Ela já pode ser reutilizada em outros times.', 'sucesso')
        except Exception as e:
            flash(f'Não foi possível salvar a Build: {e}', 'erro')
        return redirect(url_for('expansion.team_builder'))

    @bp.route('/team-builder/build/<int:build_id>/excluir', methods=['POST'])
    @login_required
    def team_builder_excluir_build(build_id):
        rows = safe_table('builds_pessoais', '*', id=build_id)
        if rows and (rows[0].get('usuario_email') == email_atual() or is_admin()):
            supabase.table('builds_pessoais').delete().eq('id', build_id).execute()
            flash('Build pessoal removida.', 'sucesso')
        return redirect(url_for('expansion.team_builder'))

    @bp.route('/team-builder/<int:team_id>/duplicar', methods=['POST'])
    @login_required
    def team_builder_duplicar(team_id):
        rows = safe_table('times_pokemon', '*', id=team_id)
        if not rows:
            flash('Time não encontrado.', 'erro')
            return redirect(url_for('expansion.team_builder'))
        origem = rows[0]
        if not origem.get('publico') and origem.get('usuario_email') != email_atual() and not is_admin():
            flash('Esse time não está disponível para duplicação.', 'erro')
            return redirect(url_for('expansion.team_builder'))
        supabase.table('times_pokemon').insert({
            'usuario_email': email_atual(),
            'nome': ('Cópia - ' + str(origem.get('nome') or 'Time'))[:140],
            'formato': origem.get('formato'),
            'formato_codigo': origem.get('formato_codigo'),
            'descricao': origem.get('descricao'),
            'slots': origem.get('slots') or [],
            'publico': False
        }).execute()
        flash('Time duplicado para a sua biblioteca.', 'sucesso')
        return redirect(url_for('expansion.team_builder'))

    @bp.route('/team-builder/<int:team_id>/favoritar', methods=['POST'])
    @login_required
    def team_builder_favoritar(team_id):
        rows = safe_table('times_pokemon', '*', id=team_id)
        if not rows or (not rows[0].get('publico') and rows[0].get('usuario_email') != email_atual()):
            flash('Time não disponível.', 'erro')
            return redirect(url_for('expansion.team_builder'))
        email = email_atual()
        fav = safe_table('times_favoritos', '*', usuario_email=email, time_id=team_id)
        if fav:
            supabase.table('times_favoritos').delete().eq('usuario_email', email).eq('time_id', team_id).execute()
            flash('Time removido dos favoritos.', 'sucesso')
        else:
            supabase.table('times_favoritos').insert({'usuario_email': email, 'time_id': team_id}).execute()
            flash('Time adicionado aos favoritos.', 'sucesso')
        return redirect(url_for('expansion.team_builder'))

    @bp.route('/team-builder/<int:team_id>/excluir', methods=['POST'])
    @login_required
    def team_builder_excluir(team_id):
        rows = safe_table('times_pokemon', '*', id=team_id)
        if rows and (rows[0].get('usuario_email') == email_atual() or is_admin()):
            supabase.table('times_pokemon').delete().eq('id', team_id).execute()
            flash('Time excluído.', 'sucesso')
        return redirect(url_for('expansion.team_builder'))

    @bp.route('/builds-pokemon/<int:build_id>/nova-versao', methods=['POST'])
    @login_required
    def nova_versao_build(build_id):
        rows = safe_table('builds_pokemon', '*', id=build_id)
        if not rows:
            flash('Build não encontrada.', 'erro')
            return redirect(url_for('final.builds_pokemon'))
        atual = rows[0]
        if atual.get('autor_email') != email_atual() and not is_admin():
            flash('Você não pode criar nova versão desta Build.', 'erro')
            return redirect(url_for('final.builds_pokemon'))
        campos = ['pokemon','titulo','nature','ability','evs','ivs','moves','item','estrategia','formato','papel','tipo_tera','explicacao_moves','parceiros','fraquezas_coberturas','legalidade']
        data = {}
        for c in campos:
            valor = request.form.get(c)
            data[c] = (valor.strip() if isinstance(valor, str) else valor) or atual.get(c)
        data.update({
            'autor_email': atual.get('autor_email') or email_atual(),
            'publicado': bool(is_admin()),
            'status_publicacao': 'publicado' if is_admin() else 'em_revisao',
            'versao': int(atual.get('versao') or 1) + 1,
            'revisao_de_id': atual.get('revisao_de_id') or atual.get('id')
        })
        supabase.table('builds_pokemon').insert(data).execute()
        flash('Nova versão criada e enviada para revisão.' if not is_admin() else 'Nova versão publicada.', 'sucesso')
        return redirect(url_for('final.builds_pokemon'))

    @bp.route('/admin/builds/revisao')
    @login_required
    def revisao_builds():
        if not tem_permissao_extra('pode_revisar_builds'):
            return redirect(url_for('painel'))
        pendentes = sorted([x for x in safe_table('builds_pokemon') if x.get('status_publicacao') == 'em_revisao'], key=lambda x: x.get('created_at') or '')
        return render_template('admin_revisao_builds.html', builds=pendentes)

    @bp.route('/admin/builds/<int:build_id>/revisar', methods=['POST'])
    @login_required
    def revisar_build(build_id):
        if not tem_permissao_extra('pode_revisar_builds'):
            return redirect(url_for('painel'))
        acao = request.form.get('acao')
        status = 'publicado' if acao == 'aprovar' else 'rejeitado'
        motivo = (request.form.get('motivo') or '').strip() or None
        rows = safe_table('builds_pokemon', '*', id=build_id)
        if rows:
            supabase.table('builds_pokemon').update({
                'status_publicacao': status,
                'publicado': status == 'publicado',
                'motivo_revisao': motivo,
                'revisado_por': email_atual(),
                'revisado_em': datetime.now(timezone.utc).isoformat()
            }).eq('id', build_id).execute()
            autor = rows[0].get('autor_email')
            if autor:
                criar_notificacao(
                    autor,
                    'Build aprovada' if status == 'publicado' else 'Build precisa de ajustes',
                    f"{rows[0].get('pokemon')} — {rows[0].get('titulo')}: {motivo or status}.",
                    'sucesso' if status == 'publicado' else 'aviso',
                    url_for('final.builds_pokemon')
                )
            registrar_log('revisar_build', 'builds_pokemon', 'build', build_id, {'status': status, 'motivo': motivo})
        return redirect(url_for('expansion.revisao_builds'))

    @bp.route('/manifest.webmanifest')
    def manifest():
        return send_from_directory(os.path.join(bp.root_path, '..', 'static'), 'manifest.webmanifest', mimetype='application/manifest+json')

    @bp.route('/service-worker.js')
    def service_worker():
        return send_from_directory(os.path.join(bp.root_path, '..', 'static'), 'service-worker.js', mimetype='application/javascript')

    return bp
