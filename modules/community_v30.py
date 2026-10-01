from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timezone
from urllib.parse import urlparse


def create_community_blueprint(supabase, login_required, safe_table, is_admin, registrar_log, criar_notificacao):
    bp = Blueprint('community', __name__)

    def email_atual():
        return session.get('usuario_email')

    def _voltar_seguro(padrao):
        destino = request.referrer or padrao
        try:
            ref = urlparse(destino)
            if ref.netloc and ref.netloc != request.host:
                return padrao
        except Exception:
            return padrao
        return destino

    def _usuarios_map():
        return {
            u.get('email'): u
            for u in safe_table('usuarios_clan', 'email,nick_jogo,nome_exibicao,avatar_url,banner_url,bio,cargo,xp,nivel,privacidade_perfil')
            if u.get('email')
        }

    def _membros_hype_set():
        return {
            x.get('usuario_email')
            for x in safe_table('membros_hype', 'usuario_email,ativo')
            if x.get('usuario_email') and x.get('ativo')
        }

    def _funcoes_map():
        out = {}
        for row in safe_table('usuarios_funcoes', 'usuario_email,funcao'):
            if row.get('usuario_email') and row.get('funcao'):
                out.setdefault(row['usuario_email'], []).append(row['funcao'])
        return out

    def _contagens_seguidores():
        seguidores = {}
        seguindo = {}
        for r in safe_table('comunidade_seguidores', 'seguidor_email,seguido_email'):
            a, b = r.get('seguidor_email'), r.get('seguido_email')
            if a and b:
                seguindo[a] = seguindo.get(a, 0) + 1
                seguidores[b] = seguidores.get(b, 0) + 1
        return seguidores, seguindo

    def _comentarios(alvo_tipo, alvo_id, usuarios=None):
        usuarios = usuarios or _usuarios_map()
        rows = [
            dict(x) for x in safe_table('comunidade_comentarios', '*', alvo_tipo=alvo_tipo, alvo_id=alvo_id)
            if str(x.get('status') or 'ativo') == 'ativo'
        ]
        rows.sort(key=lambda x: str(x.get('created_at') or ''))
        for c in rows:
            c['autor'] = usuarios.get(c.get('usuario_email')) or {}
        return rows

    def _time_publico(time_id):
        rows = safe_table('times_pokemon', '*', id=time_id)
        if not rows:
            return None
        t = rows[0]
        if not t.get('publico') or str(t.get('moderacao_status') or 'visivel') == 'oculto':
            return None
        return t

    def _build_publica(build_id):
        rows = safe_table('builds_pokemon', '*', id=build_id)
        if not rows:
            return None
        b = rows[0]
        if not b.get('publicado') or str(b.get('status_publicacao') or 'publicado') != 'publicado':
            return None
        if str(b.get('moderacao_status') or 'visivel') == 'oculto':
            return None
        return b

    def _feed(usuarios, modo='todos'):
        now_email = email_atual()
        seguindo = {
            r.get('seguido_email')
            for r in safe_table('comunidade_seguidores', 'seguido_email', seguidor_email=now_email)
            if r.get('seguido_email')
        } if now_email else set()
        permitidos = set(usuarios.keys())
        if modo == 'seguindo' and now_email:
            permitidos = set(seguindo) | {now_email}

        itens = []
        for t in safe_table('times_pokemon', '*'):
            autor = t.get('usuario_email')
            if not t.get('publico') or str(t.get('moderacao_status') or 'visivel') == 'oculto' or autor not in permitidos:
                continue
            itens.append({
                'tipo': 'time', 'autor_email': autor, 'autor': usuarios.get(autor) or {},
                'titulo': t.get('nome') or 'Time público',
                'descricao': t.get('descricao') or 'Publicou uma composição no Team Builder.',
                'alvo_id': t.get('id'), 'share_token': t.get('share_token'),
                'created_at': t.get('updated_at') or t.get('created_at'),
                'dados': t,
            })
        for b in safe_table('builds_pokemon', '*'):
            autor = b.get('autor_email')
            if not b.get('publicado') or str(b.get('status_publicacao') or 'publicado') != 'publicado' or str(b.get('moderacao_status') or 'visivel') == 'oculto' or autor not in permitidos:
                continue
            itens.append({
                'tipo': 'build', 'autor_email': autor, 'autor': usuarios.get(autor) or {},
                'titulo': f"{b.get('pokemon') or 'Pokémon'} — {b.get('titulo') or 'Build'}",
                'descricao': b.get('estrategia') or b.get('papel') or 'Publicou uma Build HYPE.',
                'alvo_id': b.get('id'), 'created_at': b.get('created_at'), 'dados': b,
            })
        for c in safe_table('comunidade_comentarios', '*'):
            autor = c.get('usuario_email')
            if str(c.get('status') or 'ativo') != 'ativo' or autor not in permitidos:
                continue
            itens.append({
                'tipo': 'comentario', 'autor_email': autor, 'autor': usuarios.get(autor) or {},
                'titulo': 'Comentou na comunidade', 'descricao': c.get('conteudo') or '',
                'alvo_tipo': c.get('alvo_tipo'), 'alvo_id': c.get('alvo_id'),
                'created_at': c.get('created_at'), 'dados': c,
            })
        for f in safe_table('comunidade_seguidores', '*'):
            autor = f.get('seguidor_email')
            alvo = f.get('seguido_email')
            if autor not in permitidos:
                continue
            u_alvo = usuarios.get(alvo) or {}
            itens.append({
                'tipo': 'follow', 'autor_email': autor, 'autor': usuarios.get(autor) or {},
                'titulo': 'Começou a seguir um membro',
                'descricao': u_alvo.get('nome_exibicao') or u_alvo.get('nick_jogo') or 'Membro HYPE',
                'alvo_email': alvo, 'created_at': f.get('created_at'), 'dados': f,
            })

        # Aproveita atividades de perfil somente quando o dono permite expor atividade.
        for a in safe_table('atividades_perfil', '*'):
            autor = a.get('usuario_email')
            if autor not in permitidos:
                continue
            priv = (usuarios.get(autor) or {}).get('privacidade_perfil') or {}
            if not bool(priv.get('mostrar_atividade', True)):
                continue
            itens.append({
                'tipo': 'atividade', 'autor_email': autor, 'autor': usuarios.get(autor) or {},
                'titulo': a.get('titulo') or str(a.get('tipo') or 'Atividade').replace('_', ' ').title(),
                'descricao': a.get('descricao') or '', 'created_at': a.get('created_at'), 'dados': a,
            })

        itens.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        return itens[:60]

    def _destaques_resolvidos(usuarios):
        rows = [dict(x) for x in safe_table('comunidade_destaques', '*') if x.get('ativo')]
        rows.sort(key=lambda x: (int(x.get('ordem') or 0), str(x.get('created_at') or '')), reverse=True)
        out = []
        for d in rows[:12]:
            tipo, chave = d.get('alvo_tipo'), str(d.get('alvo_chave') or '')
            alvo = None
            if tipo == 'perfil':
                alvo = usuarios.get(chave)
            elif tipo == 'time' and chave.isdigit():
                alvo = _time_publico(int(chave))
            elif tipo == 'build' and chave.isdigit():
                alvo = _build_publica(int(chave))
            elif tipo == 'evento' and chave.isdigit():
                r = safe_table('eventos', '*', id=int(chave)); alvo = r[0] if r else None
            elif tipo == 'torneio' and chave.isdigit():
                r = safe_table('torneios', '*', id=int(chave)); alvo = r[0] if r else None
            if alvo:
                d['alvo'] = alvo
                out.append(d)
        return out

    @bp.route('/comunidade')
    def home():
        usuarios = _usuarios_map()
        membros_hype = _membros_hype_set()
        funcoes = _funcoes_map()
        seguidores_count, seguindo_count = _contagens_seguidores()
        modo = request.args.get('feed', 'todos')
        if modo not in ('todos', 'seguindo'):
            modo = 'todos'
        feed = _feed(usuarios, modo)

        membros = []
        for email, u0 in usuarios.items():
            u = dict(u0)
            u['membro_hype'] = email in membros_hype
            u['funcoes'] = funcoes.get(email, [])
            u['seguidores'] = seguidores_count.get(email, 0)
            u['seguindo'] = seguindo_count.get(email, 0)
            membros.append(u)
        membros.sort(key=lambda u: (-int(u.get('xp') or 0), str(u.get('nick_jogo') or '').casefold()))

        times_publicos = [dict(x) for x in safe_table('times_pokemon', '*') if x.get('publico') and str(x.get('moderacao_status') or 'visivel') != 'oculto']
        builds_publicas = [dict(x) for x in safe_table('builds_pokemon', '*') if x.get('publicado') and str(x.get('status_publicacao') or 'publicado') == 'publicado' and str(x.get('moderacao_status') or 'visivel') != 'oculto']
        fav_times = {}
        for f in safe_table('times_favoritos', 'time_id'):
            tid = f.get('time_id'); fav_times[tid] = fav_times.get(tid, 0) + 1
        fav_builds = {}
        for f in safe_table('builds_favoritos', 'build_id'):
            bid = f.get('build_id'); fav_builds[bid] = fav_builds.get(bid, 0) + 1
        for t in times_publicos:
            t['autor'] = usuarios.get(t.get('usuario_email')) or {}
            t['favoritos_total'] = fav_times.get(t.get('id'), 0)
        for b in builds_publicas:
            b['autor'] = usuarios.get(b.get('autor_email')) or {}
            b['favoritos_total'] = fav_builds.get(b.get('id'), 0)
        times_publicos.sort(key=lambda x: (int(x.get('visualizacoes') or 0) + x.get('favoritos_total', 0) * 4, str(x.get('updated_at') or '')), reverse=True)
        builds_publicas.sort(key=lambda x: (x.get('favoritos_total', 0), str(x.get('created_at') or '')), reverse=True)

        seguindo_ids = set()
        if email_atual():
            seguindo_ids = {x.get('seguido_email') for x in safe_table('comunidade_seguidores', 'seguido_email', seguidor_email=email_atual())}

        stats = {
            'membros': len(usuarios),
            'membros_hype': len(membros_hype),
            'times': len(times_publicos),
            'builds': len(builds_publicas),
            'comentarios': len([x for x in safe_table('comunidade_comentarios', 'id,status') if str(x.get('status') or 'ativo') == 'ativo'])
        }
        return render_template('comunidade.html', feed=feed, modo_feed=modo, membros=membros[:12], times=times_publicos[:8], builds=builds_publicas[:8], destaques=_destaques_resolvidos(usuarios), stats=stats, seguindo_ids=seguindo_ids, pode_admin=is_admin())

    @bp.route('/comunidade/membros')
    def membros():
        usuarios = _usuarios_map()
        hype = _membros_hype_set()
        funcoes = _funcoes_map()
        seguidores_count, seguindo_count = _contagens_seguidores()
        q = (request.args.get('q') or '').strip().casefold()
        cargo = (request.args.get('cargo') or '').strip()
        funcao = (request.args.get('funcao') or '').strip()
        status = (request.args.get('status') or 'todos').strip()
        rows = []
        for email, u0 in usuarios.items():
            u = dict(u0)
            u['membro_hype'] = email in hype
            u['funcoes'] = funcoes.get(email, [])
            u['seguidores'] = seguidores_count.get(email, 0)
            u['seguindo'] = seguindo_count.get(email, 0)
            texto = f"{u.get('nick_jogo') or ''} {u.get('nome_exibicao') or ''}".casefold()
            if q and q not in texto:
                continue
            if cargo and u.get('cargo') != cargo:
                continue
            if funcao and funcao not in u['funcoes']:
                continue
            if status == 'hype' and not u['membro_hype']:
                continue
            if status == 'fora' and u['membro_hype']:
                continue
            rows.append(u)
        rows.sort(key=lambda u: (-int(u.get('xp') or 0), str(u.get('nick_jogo') or '').casefold()))
        seguindo_ids = set()
        if email_atual():
            seguindo_ids = {x.get('seguido_email') for x in safe_table('comunidade_seguidores', 'seguido_email', seguidor_email=email_atual())}
        cargos = sorted({u.get('cargo') for u in usuarios.values() if u.get('cargo')})
        funcoes_lista = sorted({f for fs in funcoes.values() for f in fs})
        return render_template('comunidade_membros.html', membros=rows, q=request.args.get('q',''), cargo=cargo, funcao=funcao, status=status, cargos=cargos, funcoes_lista=funcoes_lista, seguindo_ids=seguindo_ids)

    @bp.route('/comunidade/seguir/<nick>', methods=['POST'])
    @login_required
    def seguir(nick):
        eu = email_atual()
        candidatos = [u for u in safe_table('usuarios_clan', 'email,nick_jogo') if str(u.get('nick_jogo') or '').casefold() == str(nick or '').casefold()]
        if not candidatos:
            flash('Membro não encontrado.', 'erro')
            return redirect(_voltar_seguro(url_for('community.membros')))
        alvo = candidatos[0]
        email_alvo = alvo.get('email')
        if not email_alvo or email_alvo == eu:
            flash('Você não pode seguir a si mesmo.', 'erro')
            return redirect(_voltar_seguro(url_for('community.membros')))
        existente = safe_table('comunidade_seguidores', '*', seguidor_email=eu, seguido_email=email_alvo)
        try:
            if existente:
                supabase.table('comunidade_seguidores').delete().eq('seguidor_email', eu).eq('seguido_email', email_alvo).execute()
                flash('Você deixou de seguir este membro.', 'info')
            else:
                supabase.table('comunidade_seguidores').insert({'seguidor_email': eu, 'seguido_email': email_alvo}).execute()
                criar_notificacao(email_alvo, 'Novo seguidor', f"{session.get('nick_jogo') or 'Um membro'} começou a seguir seu perfil na Comunidade HYPE.", 'info', url_for('perfil_publico', nick=session.get('nick_jogo')))
                flash('Agora você segue este membro.', 'sucesso')
        except Exception as e:
            flash(f'Não foi possível atualizar o seguimento: {e}', 'erro')
        return redirect(_voltar_seguro(url_for('community.membros')))

    @bp.route('/comunidade/build/<int:build_id>')
    def build_detalhe(build_id):
        build = _build_publica(build_id)
        if not build:
            flash('Build indisponível na comunidade.', 'erro')
            return redirect(url_for('community.home'))
        usuarios = _usuarios_map()
        autor = usuarios.get(build.get('autor_email')) or {}
        comentarios = _comentarios('build', build_id, usuarios)
        favoritos = safe_table('builds_favoritos', '*', build_id=build_id)
        favoritado = bool(email_atual() and any(x.get('usuario_email') == email_atual() for x in favoritos))
        return render_template('comunidade_build.html', build=build, autor=autor, comentarios=comentarios, favoritos_total=len(favoritos), favoritado=favoritado)

    @bp.route('/comunidade/comentario', methods=['POST'])
    @login_required
    def comentar():
        tipo = (request.form.get('alvo_tipo') or '').strip()
        try:
            alvo_id = int(request.form.get('alvo_id') or 0)
        except Exception:
            alvo_id = 0
        conteudo = (request.form.get('conteudo') or '').strip()
        if tipo not in ('time', 'build') or not alvo_id or not (1 <= len(conteudo) <= 800):
            flash('Comentário inválido. Use entre 1 e 800 caracteres.', 'erro')
            return redirect(url_for('community.home'))
        alvo = _time_publico(alvo_id) if tipo == 'time' else _build_publica(alvo_id)
        if not alvo:
            flash('Conteúdo indisponível para comentários.', 'erro')
            return redirect(url_for('community.home'))
        # Anti-spam leve: evita flood acidental ou automatizado de comentários.
        try:
            recentes = safe_table('comunidade_comentarios', 'created_at', usuario_email=email_atual())
            datas = []
            for r in recentes:
                raw = str(r.get('created_at') or '')
                if not raw:
                    continue
                try:
                    datas.append(datetime.fromisoformat(raw.replace('Z', '+00:00')))
                except Exception:
                    pass
            if datas:
                ultima = max(datas)
                if ultima.tzinfo is None:
                    ultima = ultima.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - ultima).total_seconds() < 15:
                    flash('Aguarde alguns segundos antes de enviar outro comentário.', 'erro')
                    if tipo == 'time' and alvo.get('share_token'):
                        return redirect(url_for('competitive.time_compartilhado', share_token=alvo.get('share_token')) + '#comentarios')
                    return redirect(url_for('community.build_detalhe', build_id=alvo_id) + '#comentarios')
        except Exception:
            pass
        try:
            supabase.table('comunidade_comentarios').insert({'usuario_email': email_atual(), 'alvo_tipo': tipo, 'alvo_id': alvo_id, 'conteudo': conteudo}).execute()
            autor_email = alvo.get('usuario_email') if tipo == 'time' else alvo.get('autor_email')
            if autor_email and autor_email != email_atual():
                link = url_for('competitive.time_compartilhado', share_token=alvo.get('share_token')) if tipo == 'time' else url_for('community.build_detalhe', build_id=alvo_id)
                criar_notificacao(autor_email, 'Novo comentário', f"{session.get('nick_jogo') or 'Um membro'} comentou em seu {'time' if tipo == 'time' else 'build'}.", 'info', link)
            flash('Comentário publicado.', 'sucesso')
        except Exception as e:
            flash(f'Não foi possível publicar o comentário: {e}', 'erro')
        if tipo == 'time' and alvo.get('share_token'):
            return redirect(url_for('competitive.time_compartilhado', share_token=alvo.get('share_token')) + '#comentarios')
        return redirect(url_for('community.build_detalhe', build_id=alvo_id) + '#comentarios')

    @bp.route('/comunidade/comentario/<int:comentario_id>/excluir', methods=['POST'])
    @login_required
    def excluir_comentario(comentario_id):
        rows = safe_table('comunidade_comentarios', '*', id=comentario_id)
        if not rows:
            return redirect(url_for('community.home'))
        c = rows[0]
        if c.get('usuario_email') != email_atual() and not is_admin():
            flash('Você não pode remover este comentário.', 'erro')
            return redirect(url_for('community.home'))
        supabase.table('comunidade_comentarios').update({'status': 'removido', 'moderado_por': email_atual(), 'moderado_em': datetime.now(timezone.utc).isoformat()}).eq('id', comentario_id).execute()
        flash('Comentário removido.', 'sucesso')
        return redirect(_voltar_seguro(url_for('community.home')))

    @bp.route('/comunidade/admin')
    @login_required
    def admin():
        if not is_admin():
            return redirect(url_for('community.home'))
        usuarios = _usuarios_map()
        comentarios = [dict(x) for x in safe_table('comunidade_comentarios', '*')]
        comentarios.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        for c in comentarios:
            c['autor'] = usuarios.get(c.get('usuario_email')) or {}
        times = [dict(x) for x in safe_table('times_pokemon', '*') if x.get('publico')]
        builds = [dict(x) for x in safe_table('builds_pokemon', '*') if x.get('publicado')]
        for t in times:
            t['autor'] = usuarios.get(t.get('usuario_email')) or {}
        for b in builds:
            b['autor'] = usuarios.get(b.get('autor_email')) or {}
        return render_template('admin_comunidade.html', comentarios=comentarios[:100], times=times[:100], builds=builds[:100], destaques=safe_table('comunidade_destaques', '*'))

    @bp.route('/comunidade/admin/comentario/<int:comentario_id>/<acao>', methods=['POST'])
    @login_required
    def admin_comentario(comentario_id, acao):
        if not is_admin():
            return redirect(url_for('community.home'))
        if acao not in ('ocultar', 'restaurar', 'remover'):
            return redirect(url_for('community.admin'))
        status = {'ocultar': 'oculto', 'restaurar': 'ativo', 'remover': 'removido'}[acao]
        motivo = (request.form.get('motivo') or '').strip()[:300] or None
        supabase.table('comunidade_comentarios').update({'status': status, 'motivo_moderacao': motivo, 'moderado_por': email_atual(), 'moderado_em': datetime.now(timezone.utc).isoformat()}).eq('id', comentario_id).execute()
        registrar_log('moderar_comentario', 'comunidade', 'comentario', comentario_id, {'acao': acao, 'motivo': motivo})
        flash('Moderação do comentário atualizada.', 'sucesso')
        return redirect(url_for('community.admin'))

    @bp.route('/comunidade/admin/conteudo/<tipo>/<int:alvo_id>/<acao>', methods=['POST'])
    @login_required
    def admin_conteudo(tipo, alvo_id, acao):
        if not is_admin():
            return redirect(url_for('community.home'))
        if tipo not in ('time', 'build') or acao not in ('ocultar', 'restaurar'):
            return redirect(url_for('community.admin'))
        tabela = 'times_pokemon' if tipo == 'time' else 'builds_pokemon'
        status = 'oculto' if acao == 'ocultar' else 'visivel'
        motivo = (request.form.get('motivo') or '').strip()[:300] or None
        supabase.table(tabela).update({'moderacao_status': status, 'moderacao_motivo': motivo, 'moderado_por': email_atual(), 'moderado_em': datetime.now(timezone.utc).isoformat()}).eq('id', alvo_id).execute()
        registrar_log('moderar_conteudo', 'comunidade', tipo, alvo_id, {'acao': acao, 'motivo': motivo})
        flash('Visibilidade do conteúdo atualizada.', 'sucesso')
        return redirect(url_for('community.admin'))

    @bp.route('/comunidade/admin/destaque', methods=['POST'])
    @login_required
    def admin_destaque():
        if not is_admin():
            return redirect(url_for('community.home'))
        tipo = (request.form.get('alvo_tipo') or '').strip()
        chave = (request.form.get('alvo_chave') or '').strip()[:120]
        titulo = (request.form.get('titulo') or '').strip()[:140]
        descricao = (request.form.get('descricao') or '').strip()[:400] or None
        try:
            ordem = int(request.form.get('ordem') or 0)
        except Exception:
            ordem = 0
        if tipo not in ('perfil', 'time', 'build', 'evento', 'torneio') or not chave or not titulo:
            flash('Informe tipo, alvo e título do destaque.', 'erro')
            return redirect(url_for('community.admin'))
        existente = safe_table('comunidade_destaques', '*', alvo_tipo=tipo, alvo_chave=chave)
        data = {'alvo_tipo': tipo, 'alvo_chave': chave, 'titulo': titulo, 'descricao': descricao, 'ordem': ordem, 'ativo': True, 'criado_por': email_atual()}
        if existente:
            supabase.table('comunidade_destaques').update(data).eq('id', existente[0].get('id')).execute()
        else:
            supabase.table('comunidade_destaques').insert(data).execute()
        registrar_log('destacar_conteudo', 'comunidade', tipo, chave, {'titulo': titulo})
        flash('Destaque salvo.', 'sucesso')
        return redirect(url_for('community.admin'))

    @bp.route('/comunidade/admin/destaque/<int:destaque_id>/excluir', methods=['POST'])
    @login_required
    def admin_destaque_excluir(destaque_id):
        if not is_admin():
            return redirect(url_for('community.home'))
        supabase.table('comunidade_destaques').delete().eq('id', destaque_id).execute()
        registrar_log('remover_destaque', 'comunidade', 'destaque', destaque_id)
        flash('Destaque removido.', 'sucesso')
        return redirect(url_for('community.admin'))

    return bp
