from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs


def create_events_v26_blueprint(supabase, login_required, safe_table, is_admin, registrar_log, criar_notificacao):
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
        rodadas = {}
        for p in partidas:
            rodadas.setdefault(int(p.get('rodada') or 1), []).append(p)
        torneio['total_inscritos'] = len(participantes)
        torneio['usuario_inscrito'] = bool(session.get('usuario_email') and any(x.get('usuario_email') == session.get('usuario_email') for x in participantes))
        temporadas = {x.get('id'): x.get('nome') for x in safe_table('temporadas')}
        formatos = {x.get('codigo'): x.get('nome') for x in safe_table('formatos_competitivos')}
        torneio['temporada_nome'] = temporadas.get(torneio.get('temporada_id'))
        torneio['formato_nome_config'] = formatos.get(torneio.get('formato_codigo'))
        replay_embed = youtube_embed_url(torneio.get('replay_url'))
        return render_template('torneio_detalhe.html', torneio=torneio, participantes=participantes, rodadas=rodadas, replay_embed=replay_embed)

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
        status = (request.form.get('status_torneio') or 'inscricoes').strip()
        if status not in ('inscricoes', 'em_andamento', 'finalizado', 'cancelado'):
            status = 'inscricoes'
        payload = {
            'status_torneio': status,
            'replay_url': (request.form.get('replay_url') or '').strip() or None,
            'destaque': request.form.get('destaque') == 'on',
            'inscricoes_abertas': status == 'inscricoes' and request.form.get('inscricoes_abertas') == 'on',
        }
        try:
            supabase.table('torneios').update(payload).eq('id', item_id).execute()
            registrar_log('atualizar_torneio_v26', 'torneios', 'torneio', item_id, payload)
            flash('Torneio atualizado.', 'sucesso')
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

    return bp
