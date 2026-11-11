from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from modules.arena_private_teams import codigo_formato_do_torneio, validar_equipe_basica
from modules.hype_tournament_formats import obter_formato


def create_events_v26_blueprint(supabase, login_required, safe_table, is_admin, registrar_log, criar_notificacao, battle_db=None):
    bp = Blueprint('events26', __name__)

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
                elif p.path.startswith(('/live/', '/shorts/', '/embed/')):
                    parts = [x for x in p.path.split('/') if x]
                    if len(parts) >= 2:
                        vid = parts[1]
            if vid:
                return f'https://www.youtube.com/embed/{vid}?rel=0'
        except Exception:
            pass
        return None

    def one(table, **filters):
        rows = safe_table(table, '*', **filters)
        return rows[0] if rows else None

    def admin_ok():
        return bool(is_admin())

    @bp.route('/eventos/<int:evento_id>')
    def evento_detalhe(evento_id):
        evento = one('eventos', id=evento_id)
        if not evento or not evento.get('publicado', True):
            flash('Evento não encontrado.', 'erro')
            return redirect(url_for('eventos'))
        participantes = safe_table('inscricoes_evento', '*', evento_id=evento_id)
        resultados = sorted(safe_table('resultados_evento', '*', evento_id=evento_id), key=lambda x: int(x.get('colocacao') or 9999))
        evento['total_inscritos'] = len(participantes)
        evento['usuario_inscrito'] = bool(session.get('usuario_email') and any(x.get('usuario_email') == session.get('usuario_email') for x in participantes))
        replay_embed = youtube_embed_url(evento.get('replay_url'))
        return render_template('evento_detalhe.html', evento=evento, participantes=participantes, resultados=resultados, replay_embed=replay_embed)

    @bp.route('/torneios/<int:torneio_id>')
    def torneio_detalhe(torneio_id):
        torneio = one('torneios', id=torneio_id)
        if not torneio or not torneio.get('publicado', True):
            flash('Torneio não encontrado.', 'erro')
            return redirect(url_for('torneios'))
        participantes = safe_table('inscricoes_torneio', '*', torneio_id=torneio_id)
        partidas = sorted(safe_table('partidas_torneio', '*', torneio_id=torneio_id), key=lambda x: (int(x.get('rodada') or 0), int(x.get('ordem') or 0)))
        # Avatares são exibidos publicamente no perfil; os e-mails não são
        # mostrados na interface. A página continua acessível a não-membros.
        emails = {p.get('usuario_email') for p in participantes}
        perfis = {}
        if emails:
            for perfil in safe_table('usuarios_clan', 'email,nick_jogo,avatar_url'):
                if perfil.get('email') in emails:
                    perfis[perfil['email']] = perfil
        for participante in participantes:
            participante['avatar_url'] = perfis.get(participante.get('usuario_email'), {}).get('avatar_url')
        rodadas = {}
        for p in partidas:
            rodadas.setdefault(int(p.get('rodada') or 1), []).append(p)
        torneio['total_inscritos'] = len(participantes)
        torneio['usuario_inscrito'] = bool(session.get('usuario_email') and any(x.get('usuario_email') == session.get('usuario_email') for x in participantes))
        temporadas = {x.get('id'): x.get('nome') for x in safe_table('temporadas')}
        formatos = {x.get('codigo'): x.get('nome') for x in safe_table('formatos_competitivos')}
        torneio['temporada_nome'] = temporadas.get(torneio.get('temporada_id'))
        torneio['formato_nome_config'] = formatos.get(torneio.get('formato_codigo'))
        torneio['usa_equipes_privadas'] = bool(codigo_formato_do_torneio(torneio.get('regras')))
        avatar_por_email = {email: perfil.get('avatar_url') for email, perfil in perfis.items()}
        replay_embed = youtube_embed_url(torneio.get('replay_url'))
        email_atual = session.get('usuario_email')
        meus_confrontos = [p for p in partidas if email_atual and email_atual in (p.get('jogador1_email'), p.get('jogador2_email'))]
        return render_template('torneio_detalhe.html', torneio=torneio, participantes=participantes,
                               rodadas=rodadas, meus_confrontos=meus_confrontos,
                               avatar_por_email=avatar_por_email, replay_embed=replay_embed,
                               pode_ver_equipes=admin_ok())


    @bp.route('/torneios/<int:torneio_id>/equipes', methods=['GET', 'POST'])
    @login_required
    def equipes_torneio(torneio_id):
        """Envia uma cópia privada de um time já salvo; NÃO confirma inscrição."""
        email = (session.get('usuario_email') or '').strip().lower()
        if not email:
            flash('Entre na sua conta para preparar os times.', 'erro')
            return redirect(url_for('torneios'))
        torneio = one('torneios', id=torneio_id)
        if not torneio or not torneio.get('publicado'):
            flash('Torneio indisponível.', 'erro')
            return redirect(url_for('torneios'))
        codigo = codigo_formato_do_torneio(torneio.get('regras'))
        if not codigo:
            flash('Este torneio ainda não possui um formato compatível com o envio privado.', 'erro')
            return redirect(url_for('events26.torneio_detalhe', torneio_id=torneio_id))
        pode_enviar = bool(torneio.get('inscricoes_abertas') and
                           torneio.get('status_torneio') == 'inscricoes')
        enviados_lista = safe_table('arena_torneio_equipes', '*',
                                   torneio_id=torneio_id, usuario_email=email)
        enviados = {int(t['slot']): t for t in enviados_lista if t.get('slot') is not None}

        if request.method == 'POST':
            if not pode_enviar:
                flash('As inscrições estão fechadas. Nenhum time foi alterado.', 'erro')
                return redirect(url_for('events26.equipes_torneio', torneio_id=torneio_id))
            if request.form.get('aceito_regras') != 'on':
                flash('Leia e aceite o regulamento antes do envio.', 'erro')
                return redirect(url_for('events26.equipes_torneio', torneio_id=torneio_id))
            slot = request.form.get('slot', type=int)
            team_id = request.form.get('team_id', type=int)
            if slot not in (1, 2, 3) or not team_id:
                flash('Selecione um slot e um time válido.', 'erro')
                return redirect(url_for('events26.equipes_torneio', torneio_id=torneio_id))
            atual = enviados.get(slot)
            if atual and atual.get('status') == 'aprovado':
                flash('Um time aprovado não pode ser substituído sem liberação da administração.', 'erro')
                return redirect(url_for('events26.equipes_torneio', torneio_id=torneio_id))
            time = one('times_pokemon', id=team_id)
            if not time or str(time.get('usuario_email') or '').lower() != email or time.get('publico'):
                flash('Use apenas um time privado pertencente à sua conta.', 'erro')
                return redirect(url_for('events26.equipes_torneio', torneio_id=torneio_id))
            if str(time.get('formato_codigo') or '').strip().lower() != codigo:
                flash('Este time pertence a outro formato. Monte ou salve uma equipe no formato deste torneio.', 'erro')
                return redirect(url_for('events26.equipes_torneio', torneio_id=torneio_id))
            equipe = time.get('slots')
            erros = validar_equipe_basica(equipe, codigo)
            if erros:
                flash('Revise o time: ' + ' | '.join(erros[:5]), 'erro')
                return redirect(url_for('events26.equipes_torneio', torneio_id=torneio_id))
            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).isoformat()
            payload = {
                'nome': str(time.get('nome') or 'Time HYPE')[:100],
                'equipe': equipe,
                'formato_codigo': codigo,
                'regras_snapshot': torneio.get('regras') or '',
                'status': 'aguardando_verificacao',
                'enviado_em': timestamp,
                'atualizado_em': timestamp,
            }
            try:
                if atual:
                    supabase.table('arena_torneio_equipes').update(payload).eq('id', atual['id']).eq('torneio_id', torneio_id).eq('usuario_email', email).execute()
                else:
                    payload.update({'torneio_id': torneio_id, 'usuario_email': email, 'slot': slot})
                    supabase.table('arena_torneio_equipes').insert(payload).execute()
                flash(f'Time {slot} enviado em sigilo para conferência. Sua inscrição ainda NÃO está confirmada.', 'sucesso')
            except Exception:
                flash('Não foi possível salvar. A migração de equipes privadas pode estar pendente.', 'erro')
            return redirect(url_for('events26.equipes_torneio', torneio_id=torneio_id))

        # Não exibir times já compartilhados publicamente como opções secretas.
        formato_regras = obter_formato(codigo) or {}
        tamanho_equipe = int(formato_regras.get('tamanho_equipe') or 6)
        meus_times = [t for t in safe_table('times_pokemon', '*', usuario_email=email)
                      if not t.get('publico') and isinstance(t.get('slots'), list)
                      and str(t.get('formato_codigo') or '').lower() == codigo]
        meus_times.sort(key=lambda t: str(t.get('updated_at') or ''), reverse=True)
        selecionado = request.args.get('team_id', type=int)
        if not any(t.get('id') == selecionado for t in meus_times):
            selecionado = None
        return render_template('arena_torneio_equipes.html', torneio=torneio,
                               enviados=enviados, meus_times=meus_times,
                               pode_enviar=pode_enviar, tamanho_equipe=tamanho_equipe,
                               torneio_formato_codigo=codigo, time_selecionado_id=selecionado)

    def revisao_aberta(torneio):
        return bool(torneio and torneio.get('publicado')
                    and torneio.get('inscricoes_abertas')
                    and torneio.get('status_torneio') == 'inscricoes')

    def voltar_revisao(torneio_id):
        return redirect(url_for('events26.admin_equipes_torneio', torneio_id=torneio_id))

    @bp.route('/admin/torneios/<int:torneio_id>/equipes')
    @login_required
    def admin_equipes_torneio(torneio_id):
        """Fila sigilosa por jogador: revisão de cada time, pagamento e inscrição."""
        if not admin_ok():
            flash('Acesso restrito à administração.', 'erro')
            return redirect(url_for('painel'))
        torneio = one('torneios', id=torneio_id)
        if not torneio:
            flash('Torneio não encontrado.', 'erro')
            return redirect(url_for('admin_conteudo'))
        enviados = safe_table('arena_torneio_equipes', '*', torneio_id=torneio_id)
        historico = safe_table('arena_torneio_equipes_historico', '*', torneio_id=torneio_id)
        perfis = {str(u.get('email') or '').lower(): u.get('nick_jogo')
                  for u in safe_table('usuarios_clan', 'email,nick_jogo')}
        controles = {str(c.get('usuario_email') or '').lower(): c
                     for c in safe_table('arena_torneio_inscricoes_controle', '*',
                                         torneio_id=torneio_id)}
        inscritos = {str(i.get('usuario_email') or '').lower()
                     for i in safe_table('inscricoes_torneio', 'usuario_email',
                                         torneio_id=torneio_id)}
        grupos = {}
        for equipe in enviados:
            endereco = str(equipe.get('usuario_email') or '').lower()
            equipe['nick_jogo'] = perfis.get(endereco)
            grupos.setdefault(endereco, []).append(equipe)
        for times in grupos.values():
            times.sort(key=lambda x: int(x.get('slot') or 0))
        historico.sort(key=lambda x: str(x.get('criado_em') or ''), reverse=True)
        pendentes = sum(1 for email, times in grupos.items()
                        if email not in inscritos
                        and (any(t.get('status') != 'aprovado' for t in times)
                             or controles.get(email, {}).get('pagamento_status')
                                not in ('confirmado', 'dispensado')))
        return render_template('admin_arena_equipes.html', torneio=torneio,
                               grupos=grupos, historico=historico,
                               controles=controles, inscritos=inscritos,
                               pendentes=pendentes, pode_revisar=revisao_aberta(torneio))

    @bp.route('/admin/torneios/<int:torneio_id>/equipes/<int:equipe_id>/revisar',
              methods=['POST'])
    @login_required
    def admin_revisar_equipe(torneio_id, equipe_id):
        if not admin_ok():
            flash('Acesso restrito à administração.', 'erro')
            return redirect(url_for('painel'))
        torneio = one('torneios', id=torneio_id)
        if not revisao_aberta(torneio):
            flash('A revisão está fechada para este torneio.', 'erro')
            return voltar_revisao(torneio_id)
        equipe = one('arena_torneio_equipes', id=equipe_id, torneio_id=torneio_id)
        if not equipe or equipe.get('status') == 'aprovado':
            flash('Time não encontrado ou já aprovado; não é possível alterá-lo.', 'erro')
            return voltar_revisao(torneio_id)
        acao = (request.form.get('acao') or '').strip()
        motivo = (request.form.get('motivo') or '').strip()
        if acao == 'aprovar':
            codigo = codigo_formato_do_torneio(torneio.get('regras'))
            if not codigo or equipe.get('formato_codigo') != codigo:
                flash('Formato do time não corresponde ao torneio.', 'erro')
                return voltar_revisao(torneio_id)
            erros = validar_equipe_basica(equipe.get('equipe'), codigo)
            if erros:
                flash('O time não passou na checagem preliminar: ' + ' | '.join(erros[:3]), 'erro')
                return voltar_revisao(torneio_id)
            novo_status = 'aprovado'
            motivo = ''
        elif acao == 'corrigir':
            if len(motivo) < 8 or len(motivo) > 500:
                flash('Informe um motivo de correção de 8 a 500 caracteres.', 'erro')
                return voltar_revisao(torneio_id)
            novo_status = 'correcao_solicitada'
        else:
            flash('Ação de revisão inválida.', 'erro')
            return voltar_revisao(torneio_id)
        try:
            resultado = (supabase.table('arena_torneio_equipes')
                         .update({'status': novo_status, 'motivo_revisao': motivo or None,
                                  'revisado_por': session.get('usuario_email'),
                                  'revisado_em': datetime.now(timezone.utc).isoformat(),
                                  'atualizado_em': datetime.now(timezone.utc).isoformat()})
                         .eq('id', equipe_id).eq('torneio_id', torneio_id)
                         .eq('status', equipe['status']).execute().data or [])
            if not resultado:
                flash('O time mudou durante a revisão. Atualize a página.', 'erro')
                return voltar_revisao(torneio_id)
        except Exception:
            flash('Falha ao registrar a revisão. Verifique a migração da Arena.', 'erro')
            return voltar_revisao(torneio_id)
        if novo_status == 'aprovado':
            mensagem = f'Seu time do slot {equipe["slot"]} foi aprovado na conferência preliminar.'
        else:
            mensagem = f'Seu time do slot {equipe["slot"]} precisa de correção: {motivo}'
        try:
            criar_notificacao(equipe['usuario_email'], 'Revisão do torneio HYPE', mensagem,
                              'torneio', url_for('events26.equipes_torneio', torneio_id=torneio_id))
        except Exception:
            pass
        flash('Revisão registrada no histórico.', 'sucesso')
        return voltar_revisao(torneio_id)

    @bp.route('/admin/torneios/<int:torneio_id>/pagamento', methods=['POST'])
    @login_required
    def admin_pagamento_torneio(torneio_id):
        if not admin_ok():
            flash('Acesso restrito à administração.', 'erro')
            return redirect(url_for('painel'))
        torneio = one('torneios', id=torneio_id)
        if not revisao_aberta(torneio):
            flash('Não é possível alterar pagamentos de inscrições encerradas.', 'erro')
            return voltar_revisao(torneio_id)
        email = (request.form.get('usuario_email') or '').strip().lower()
        status = (request.form.get('acao') or '').strip()
        if status not in ('pendente', 'confirmado', 'dispensado') or not email:
            flash('Pagamento ou jogador inválido.', 'erro')
            return voltar_revisao(torneio_id)
        if not safe_table('arena_torneio_equipes', 'id', torneio_id=torneio_id,
                          usuario_email=email):
            flash('Este jogador não enviou times a este torneio.', 'erro')
            return voltar_revisao(torneio_id)
        if safe_table('inscricoes_torneio', 'id', torneio_id=torneio_id,
                      usuario_email=email):
            flash('A inscrição já foi confirmada; o pagamento está bloqueado.', 'erro')
            return voltar_revisao(torneio_id)
        try:
            supabase.table('arena_torneio_inscricoes_controle').upsert({
                'torneio_id': torneio_id, 'usuario_email': email,
                'pagamento_status': status,
                'pagamento_por': session.get('usuario_email') if status != 'pendente' else None,
                'pagamento_em': datetime.now(timezone.utc).isoformat()
                                if status != 'pendente' else None,
                'atualizado_em': datetime.now(timezone.utc).isoformat(),
            }, on_conflict='torneio_id,usuario_email').execute()
        except Exception:
            flash('Não foi possível salvar o pagamento. Verifique a migração da Arena.', 'erro')
            return voltar_revisao(torneio_id)
        flash('Situação do pagamento atualizada com registro de auditoria.', 'sucesso')
        return voltar_revisao(torneio_id)

    @bp.route('/admin/torneios/<int:torneio_id>/confirmar-inscricao', methods=['POST'])
    @login_required
    def admin_confirmar_inscricao_torneio(torneio_id):
        if not admin_ok():
            flash('Acesso restrito à administração.', 'erro')
            return redirect(url_for('painel'))
        email = (request.form.get('usuario_email') or '').strip().lower()
        if not email:
            flash('Selecione o jogador.', 'erro')
            return voltar_revisao(torneio_id)
        try:
            resultado = supabase.rpc('hype_arena_confirmar_inscricao', {
                'p_torneio_id': torneio_id,
                'p_usuario_email': email,
                'p_admin_email': session.get('usuario_email'),
            }).execute().data
        except Exception:
            flash('Não foi possível confirmar: verifique times, pagamento, vagas e se as inscrições estão abertas.', 'erro')
            return voltar_revisao(torneio_id)
        if resultado == 'inscricao_confirmada':
            torneio = one('torneios', id=torneio_id) or {}
            try:
                criar_notificacao(email, 'Inscrição confirmada na Arena HYPE',
                                  f'Sua inscrição no torneio {torneio.get("titulo", "")} foi confirmada pela administração.',
                                  'torneio', url_for('events26.torneio_detalhe', torneio_id=torneio_id))
            except Exception:
                pass
            flash('Inscrição oficial confirmada! O jogador já conta como participante.', 'sucesso')
        elif resultado == 'ja_inscrito':
            flash('Este jogador já está inscrito.', 'info')
        else:
            flash('A inscrição não pôde ser confirmada. Atualize e confira os requisitos.', 'erro')
        return voltar_revisao(torneio_id)

    @bp.route('/admin/eventos/<int:item_id>/v26', methods=['POST'])
    @login_required
    def admin_evento_v26(item_id):
        if not admin_ok():
            return redirect(url_for('painel'))
        status = (request.form.get('status_evento') or 'agendado').strip()
        if status not in ('agendado', 'em_andamento', 'finalizado', 'cancelado'):
            status = 'agendado'
        payload = {
            'status_evento': status,
            'replay_url': (request.form.get('replay_url') or '').strip() or None,
            'destaque': request.form.get('destaque') == 'on',
        }
        if status == 'finalizado':
            payload['encerrado_em'] = datetime.now(timezone.utc).isoformat()
        try:
            supabase.table('eventos').update(payload).eq('id', item_id).execute()
            registrar_log('atualizar_evento_v26', 'eventos', 'evento', item_id, payload)
            flash('Evento atualizado.', 'sucesso')
        except Exception as e:
            flash(f'Erro ao atualizar evento: {e}', 'erro')
        return redirect(url_for('admin_conteudo'))

    @bp.route('/admin/torneios/<int:item_id>/v26', methods=['POST'])
    @login_required
    def admin_torneio_v26(item_id):
        if not admin_ok():
            return redirect(url_for('painel'))
        torneio = one('torneios', id=item_id)
        if not torneio:
            flash('Torneio não encontrado.', 'erro')
            return redirect(url_for('admin_conteudo'))
        status_atual = torneio.get('status_torneio') or 'inscricoes'
        status = (request.form.get('status_torneio') or status_atual).strip()
        if status not in ('inscricoes', 'em_andamento', 'finalizado', 'cancelado'):
            flash('Situação inválida.', 'erro')
            return redirect(url_for('admin_conteudo'))
        tem_chave = bool(safe_table('partidas_torneio', 'id', torneio_id=item_id))
        if status_atual == 'finalizado' and status != 'finalizado':
            flash('O torneio já terminou; reabrir exigiria revisão dos resultados e do ranking.', 'erro')
            return redirect(url_for('admin_conteudo'))
        if status == 'finalizado' and status_atual != 'finalizado':
            flash('O campeão só pode ser definido após a final validada.', 'erro')
            return redirect(url_for('admin_conteudo'))
        if status == 'em_andamento' and not tem_chave:
            flash('Use "Encerrar e sortear chaves" para iniciar o torneio.', 'erro')
            return redirect(url_for('admin_conteudo'))
        if status == 'inscricoes' and tem_chave:
            flash('Não é possível reabrir inscrições após gerar confrontos.', 'erro')
            return redirect(url_for('admin_conteudo'))
        payload = {
            'status_torneio': status,
            'replay_url': (request.form.get('replay_url') or '').strip() or None,
            'destaque': request.form.get('destaque') == 'on',
            'inscricoes_abertas': status == 'inscricoes' and not tem_chave and
                                   request.form.get('inscricoes_abertas') == 'on',
        }
        try:
            supabase.table('torneios').update(payload).eq('id', item_id).execute()
            registrar_log('atualizar_torneio_v26', 'torneios', 'torneio', item_id, payload)
            flash('Situação do torneio atualizada.', 'sucesso')
        except Exception as e:
            flash(f'Erro ao atualizar torneio: {e}', 'erro')
        return redirect(url_for('admin_conteudo'))

    @bp.route('/admin/live/replays/criar', methods=['POST'])
    @login_required
    def criar_replay():
        if not admin_ok():
            return redirect(url_for('painel'))
        titulo = (request.form.get('titulo') or '').strip()
        youtube_url = (request.form.get('youtube_url') or '').strip()
        if not titulo or not youtube_embed_url(youtube_url):
            flash('Informe um título e uma URL válida do YouTube.', 'erro')
            return redirect(url_for('admin_conteudo'))
        tipo = (request.form.get('origem_tipo') or 'outro').strip()
        if tipo not in ('evento', 'torneio', 'outro'):
            tipo = 'outro'
        origem_id = request.form.get('origem_id', type=int)
        try:
            supabase.table('hype_live_replays').insert({
                'titulo': titulo,
                'descricao': (request.form.get('descricao') or '').strip() or None,
                'youtube_url': youtube_url,
                'origem_tipo': tipo,
                'origem_id': origem_id,
                'publicado': request.form.get('publicado', 'on') == 'on',
                'destaque': request.form.get('destaque') == 'on',
                'criado_por': session.get('usuario_email'),
            }).execute()
            registrar_log('criar_replay', 'hype_live', 'replay', None, {'titulo': titulo, 'origem_tipo': tipo, 'origem_id': origem_id})
            flash('Replay adicionado à HYPE Live.', 'sucesso')
        except Exception as e:
            flash(f'Erro ao adicionar replay: {e}', 'erro')
        return redirect(url_for('admin_conteudo'))

    @bp.route('/admin/live/replays/<int:replay_id>/excluir', methods=['POST'])
    @login_required
    def excluir_replay(replay_id):
        if not admin_ok():
            return redirect(url_for('painel'))
        try:
            supabase.table('hype_live_replays').delete().eq('id', replay_id).execute()
            registrar_log('excluir_replay', 'hype_live', 'replay', replay_id)
            flash('Replay removido.', 'sucesso')
        except Exception as e:
            flash(f'Erro ao remover replay: {e}', 'erro')
        return redirect(url_for('admin_conteudo'))


    # HYPE Arena: o torneio e os jogadores vêm da base existente;
    # as confirmações ficam em tabela privada, acessada só pelo servidor.
    def battle_store():
        if battle_db is not None:
            return battle_db
        from modules.hype_battle_service import get_battle_client
        return get_battle_client()

    def battle_state(partida_id):
        db = battle_store()
        if db is None:
            return {}, False
        try:
            rows = db.table('hype_batalha_participantes').select('*').eq(
                'partida_id', partida_id).execute().data or []
            return {row['usuario_email']: row for row in rows}, True
        except Exception:
            return {}, False

    @bp.route('/torneios/<int:torneio_id>/batalha/<int:partida_id>')
    def sala_batalha(torneio_id, partida_id):
        from flask import abort
        from modules.battle_room_rules import players, both_ready
        torneio = one('torneios', id=torneio_id)
        partida = one('partidas_torneio', id=partida_id)
        if not torneio or not partida or int(partida.get('torneio_id') or 0) != torneio_id:
            abort(404)
        if not torneio.get('publicado', True) and not admin_ok():
            abort(404)

        participantes = players(partida)
        estados, sala_disponivel = battle_state(partida_id)
        perfis = {}
        for email in participantes:
            dados = safe_table('usuarios_clan', 'email,nick_jogo,avatar_url', email=email)
            perfis[email] = dados[0] if dados else {}
        email_atual = session.get('usuario_email')
        meu_estado = estados.get(email_atual, {})
        ambos_prontos = both_ready(partida, estados)
        enviados = bool(participantes) and all(
            estados.get(email, {}).get('vencedor_reportado_email') for email in participantes
        )
        divergencia = bool(enviados and
                          estados[participantes[0]]['vencedor_reportado_email'] !=
                          estados[participantes[1]]['vencedor_reportado_email'])
        torneio_ativo = torneio.get('status_torneio') == 'em_andamento'
        return render_template(
            'sala_batalha.html', torneio=torneio, partida=partida,
            participantes=participantes, perfis=perfis, estados=estados,
            ambos_prontos=ambos_prontos, email_atual=email_atual,
            meu_estado=meu_estado, divergencia=divergencia, admin=admin_ok(),
            sala_disponivel=sala_disponivel, torneio_ativo=torneio_ativo,
            pode_interagir=bool(sala_disponivel and torneio_ativo and
                               email_atual in participantes and
                               partida.get('status') != 'finalizada'),
        )

    def partida_autorizada(partida_id):
        from modules.battle_room_rules import players
        partida = one('partidas_torneio', id=partida_id)
        if not partida:
            return None
        torneio = one('torneios', id=partida.get('torneio_id'))
        if not torneio or torneio.get('status_torneio') != 'em_andamento':
            return None
        if partida.get('status') == 'finalizada':
            return None
        if session.get('usuario_email') not in players(partida):
            return None
        return partida

    @bp.route('/torneios/batalha/<int:partida_id>/pronto', methods=['POST'])
    @login_required
    def sala_batalha_pronto(partida_id):
        partida = partida_autorizada(partida_id)
        if not partida:
            flash('Esta partida não aceita confirmação de presença.', 'erro')
            return redirect(url_for('torneios'))
        db = battle_store()
        url_sala = url_for('events26.sala_batalha',
                           torneio_id=partida['torneio_id'], partida_id=partida_id)
        if db is None:
            flash('Sala de Batalha ainda não ativada. Peça suporte à administração.', 'erro')
            return redirect(url_sala)
        try:
            result = db.rpc('hype_batalha_confirmar_pronto', {
                'p_partida_id': partida_id,
                'p_usuario_email': session['usuario_email'],
            }).execute().data
            if result is True:
                flash('Presença confirmada! Aguarde o adversário.', 'sucesso')
            else:
                flash('Não foi possível confirmar presença nesta partida.', 'erro')
        except Exception:
            flash('A confirmação ainda não está disponível no servidor.', 'erro')
        return redirect(url_sala)

    @bp.route('/torneios/batalha/<int:partida_id>/resultado', methods=['POST'])
    @login_required
    def sala_batalha_resultado(partida_id):
        from modules.battle_room_rules import players
        partida = partida_autorizada(partida_id)
        if not partida:
            flash('Você não pode registrar resultado nesta partida.', 'erro')
            return redirect(url_for('torneios'))
        participantes = players(partida)
        slot = (request.form.get('vencedor_slot') or '').strip()
        url_sala = url_for('events26.sala_batalha',
                           torneio_id=partida['torneio_id'], partida_id=partida_id)
        if slot not in ('1', '2'):
            flash('Escolha um dos dois competidores da partida.', 'erro')
            return redirect(url_sala)
        vencedor = participantes[int(slot) - 1]
        db = battle_store()
        if db is None:
            flash('Sala de Batalha ainda não ativada. Peça suporte à administração.', 'erro')
            return redirect(url_sala)
        try:
            response = db.rpc('hype_batalha_confirmar_resultado', {
                'p_partida_id': partida_id,
                'p_usuario_email': session['usuario_email'],
                'p_vencedor_email': vencedor,
            }).execute().data
            result = response[0] if isinstance(response, list) and response else response
            status = result.get('status') if isinstance(result, dict) else None
            if status == 'finalizada':
                try:
                    registrar_log('resultado_dupla_confirmacao', 'torneios', 'partida',
                                  partida_id, {'torneio_id': partida['torneio_id'],
                                               'vencedor_email': result.get('vencedor_email')})
                    criar_notificacao(result.get('vencedor_email'), 'Vitória confirmada!',
                                      'Os dois competidores confirmaram o resultado da HYPE Arena.',
                                      'torneio', url_sala)
                except Exception:
                    # A notificação não desfaz uma finalização já confirmada pelo banco.
                    pass
                flash('Os dois jogadores confirmaram! Resultado oficial registrado.', 'sucesso')
            elif status == 'divergencia':
                flash('Resultados divergentes. A organização deve revisar a partida.', 'erro')
            elif status == 'aguardando_oponente':
                flash('Sua confirmação foi registrada. Aguardando o adversário.', 'sucesso')
            elif status == 'aguardando_pronto':
                flash('Os dois jogadores devem confirmar presença primeiro.', 'erro')
            else:
                flash('Esta partida não aceita alterações no momento.', 'erro')
        except Exception:
            flash('Não foi possível confirmar o resultado. Solicite revisão administrativa.', 'erro')
        return redirect(url_sala)

    return bp
