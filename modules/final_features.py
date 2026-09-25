from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timezone


def create_final_blueprint(supabase, login_required, safe_table, is_admin, registrar_log):
    bp = Blueprint('final', __name__)

    def current_email(): return session.get('usuario_email')
    def one(table, **filters):
        q=supabase.table(table).select('*')
        for k,v in filters.items(): q=q.eq(k,v)
        rows=q.limit(1).execute().data or []
        return rows[0] if rows else None

    @bp.route('/calendario')
    def calendario():
        eventos=safe_table('eventos'); torneios=safe_table('torneios')
        itens=[]
        for x in eventos: itens.append({**x,'tipo':'Evento'})
        for x in torneios: itens.append({**x,'tipo':'Torneio'})
        itens.sort(key=lambda x: str(x.get('data_evento') or x.get('data_torneio') or x.get('data_hora') or ''))
        return render_template('calendario.html', itens=itens)

    @bp.route('/temporadas')
    def temporadas():
        return render_template('temporadas.html', temporadas=safe_table('temporadas'), ranking=safe_table('ranking_temporada'))

    @bp.route('/ranking/competitivo')
    def ranking_competitivo():
        temporadas=safe_table('temporadas')
        atual=next((x for x in temporadas if x.get('ativa')), None)
        tid=request.args.get('temporada_id', type=int) or (atual or {}).get('id')
        ranking=[]
        if tid:
            ranking=supabase.table('ranking_temporada').select('*').eq('temporada_id',tid).order('pontos',desc=True).execute().data or []
        usuarios = {x.get('email'): x for x in safe_table('usuarios_clan','email,nick_jogo,avatar_url')}
        for r in ranking:
            u = usuarios.get(r.get('usuario_email')) or {}
            r['nick_jogo'] = u.get('nick_jogo') or r.get('usuario_email')
            r['avatar_url'] = u.get('avatar_url')
        return render_template('ranking_competitivo.html', temporadas=temporadas, temporada_id=tid, ranking=ranking)

    @bp.route('/admin/temporadas', methods=['GET','POST'])
    @login_required
    def admin_temporadas():
        if not is_admin(): return redirect(url_for('painel'))
        if request.method=='POST':
            nome=request.form.get('nome','').strip(); inicio=request.form.get('inicio') or None; fim=request.form.get('fim') or None
            if nome:
                supabase.table('temporadas').insert({'nome':nome,'inicio':inicio,'fim':fim,'ativa':request.form.get('ativa')=='on'}).execute()
                registrar_log('criar','temporadas','temporada',None,nome)
            return redirect(url_for('final.admin_temporadas'))
        return render_template('admin_temporadas.html', temporadas=safe_table('temporadas'))

    @bp.route('/admin/temporadas/<int:tid>/ativar', methods=['POST'])
    @login_required
    def ativar_temporada(tid):
        if not is_admin(): return redirect(url_for('painel'))
        supabase.table('temporadas').update({'ativa':False}).neq('id',0).execute()
        supabase.table('temporadas').update({'ativa':True}).eq('id',tid).execute(); registrar_log('ativar','temporadas','temporada',tid)
        return redirect(url_for('final.admin_temporadas'))

    @bp.route('/admin/ranking/pontuar', methods=['POST'])
    @login_required
    def pontuar():
        if not is_admin(): return redirect(url_for('painel'))
        tid=int(request.form['temporada_id']); email=request.form['email'].strip().lower(); pts=int(request.form.get('pontos',0)); vit=int(request.form.get('vitorias',0)); pod=int(request.form.get('podios',0))
        row=one('ranking_temporada',temporada_id=tid,usuario_email=email)
        data={'temporada_id':tid,'usuario_email':email,'pontos':(row or {}).get('pontos',0)+pts,'vitorias':(row or {}).get('vitorias',0)+vit,'podios':(row or {}).get('podios',0)+pod}
        supabase.table('ranking_temporada').upsert(data,on_conflict='temporada_id,usuario_email').execute(); registrar_log('pontuar','ranking','usuario',email,str(data))
        return redirect(url_for('final.ranking_competitivo',temporada_id=tid))

    @bp.route('/builds-pokemon', methods=['GET','POST'])
    @login_required
    def builds_pokemon():
        if request.method=='POST':
            campos=['pokemon','titulo','nature','ability','evs','ivs','moves','item','estrategia','formato','papel','tipo_tera','explicacao_moves','parceiros','fraquezas_coberturas','legalidade']
            data={k:request.form.get(k,'').strip() or None for k in campos}
            admin=bool(is_admin())
            data.update({
                'autor_email':current_email(),
                'publicado':admin,
                'status_publicacao':'publicado' if admin else 'em_revisao',
                'versao':1
            })
            if not data['pokemon'] or not data['titulo']:
                flash('Informe Pokémon e título.','erro')
            else:
                supabase.table('builds_pokemon').insert(data).execute()
                registrar_log('criar','builds_pokemon','build',None,data['titulo'])
                flash('Build publicada.' if admin else 'Build enviada para revisão antes da publicação.','sucesso')
            return redirect(url_for('final.builds_pokemon'))
        rows=supabase.table('builds_pokemon').select('*').eq('publicado',True).order('created_at',desc=True).execute().data or []
        minhas=[]
        try:
            minhas=supabase.table('builds_pokemon').select('*').eq('autor_email',current_email()).neq('status_publicacao','publicado').order('created_at',desc=True).execute().data or []
        except Exception:
            pass
        favoritos=set()
        if current_email():
            favoritos={x.get('build_id') for x in safe_table('builds_favoritos','build_id',usuario_email=current_email())}
        return render_template('builds_pokemon.html', builds=rows, minhas_pendentes=minhas, favoritos=favoritos)

    @bp.route('/admin/eventos/<int:evento_id>/resultado', methods=['POST'])
    @login_required
    def resultado_evento(evento_id):
        if not is_admin(): return redirect(url_for('eventos'))
        data={'evento_id':evento_id,'usuario_email':request.form.get('usuario_email'),'colocacao':int(request.form.get('colocacao',1)),'premio':request.form.get('premio') or None,'observacao':request.form.get('observacao') or None,'imagem_url':request.form.get('imagem_url') or None}
        supabase.table('resultados_evento').upsert(data,on_conflict='evento_id,usuario_email').execute(); registrar_log('resultado','eventos','evento',evento_id,str(data)); flash('Resultado registrado.','sucesso')
        return redirect(url_for('final.resultados_evento',evento_id=evento_id))

    @bp.route('/eventos/<int:evento_id>/resultados')
    def resultados_evento(evento_id):
        evento=one('eventos',id=evento_id); resultados=supabase.table('resultados_evento').select('*').eq('evento_id',evento_id).order('colocacao').execute().data or []
        return render_template('resultados_evento.html',evento=evento,resultados=resultados,pode_admin=is_admin())

    @bp.route('/estatisticas')
    @login_required
    def estatisticas():
        email=current_email(); breeds=safe_table('pedidos_breed'); builds=safe_table('pedidos_build'); inscr_e=safe_table('inscricoes_evento'); inscr_t=safe_table('inscricoes_torneio'); cons=safe_table('conquistas_usuario')
        stats={'breeds_pedidos':sum(x.get('usuario_email')==email for x in breeds),'breeds_feitos':sum(x.get('breeder_responsavel')==email and x.get('status')=='entregue' for x in breeds),'builds_pedidos':sum(x.get('usuario_email')==email for x in builds),'builds_feitos':sum(x.get('builder_email')==email and x.get('status')=='entregue' for x in builds),'eventos':sum(x.get('usuario_email')==email for x in inscr_e),'torneios':sum(x.get('usuario_email')==email for x in inscr_t),'conquistas':sum(x.get('usuario_email')==email for x in cons)}
        return render_template('estatisticas.html',stats=stats)

    @bp.route('/admin/financeiro')
    @login_required
    def financeiro():
        if not is_admin(): return redirect(url_for('painel'))
        pedidos=[x for x in safe_table('pedidos_breed') if x.get('status')=='entregue']
        total=sum(float(x.get('preco_total') or 0) for x in pedidos); por={}
        for x in pedidos:
            b=x.get('breeder_responsavel') or 'Sem breeder'; por[b]=por.get(b,0)+float(x.get('preco_total') or 0)
        return render_template('financeiro.html',total=total,por_breeder=sorted(por.items(),key=lambda z:z[1],reverse=True),pedidos=pedidos)

    @bp.route('/admin/configuracoes', methods=['GET','POST'])
    @login_required
    def configuracoes():
        if not is_admin(): return redirect(url_for('painel'))
        if request.method=='POST':
            for chave in ['discord_url','discord_webhook_url','nome_clan','youtube_live_url','youtube_live_titulo']:
                valor=request.form.get(chave,'').strip(); supabase.table('configuracoes_site').upsert({'chave':chave,'valor':valor},on_conflict='chave').execute()
            supabase.table('configuracoes_site').upsert({
                'chave':'youtube_live_ativo',
                'valor':'true' if request.form.get('youtube_live_ativo')=='on' else 'false'
            },on_conflict='chave').execute()
            registrar_log('alterar','configuracoes'); flash('Configurações salvas.','sucesso'); return redirect(url_for('final.configuracoes'))
        cfg={x.get('chave'):x.get('valor') for x in safe_table('configuracoes_site')}
        return render_template('admin_configuracoes.html',cfg=cfg)

    return bp
