"""Visao de prestacao de contas baseada somente nas entradas confirmadas no caixa."""
from collections import defaultdict
from flask import Blueprint, render_template, redirect, session, url_for, flash


def calcular_resumo_caixa(registros):
    entradas = saidas = 0
    categorias = defaultdict(lambda: {'entradas': 0, 'saidas': 0})
    for row in registros:
        try:
            valor = int(row.get('valor') or 0)
        except (TypeError, ValueError):
            continue
        if valor <= 0:
            continue
        tipo = row.get('tipo')
        categoria = str(row.get('categoria') or 'geral')[:80]
        if tipo == 'entrada':
            entradas += valor
            categorias[categoria]['entradas'] += valor
        elif tipo == 'saida':
            saidas += valor
            categorias[categoria]['saidas'] += valor
    return {
        'entradas': entradas, 'saidas': saidas, 'saldo': entradas - saidas,
        'categorias': sorted(
            ({'nome': nome, **valores} for nome, valores in categorias.items()),
            key=lambda item: (-item['entradas']-item['saidas'], item['nome']),
        ),
    }


def create_finance_public_blueprint(supabase, login_required, membro_hype_ativo, is_admin):
    bp = Blueprint('finance_public', __name__)

    @bp.route('/cla/economia')
    @login_required
    def economia_cla():
        email = session.get('usuario_email')
        if not email or not (membro_hype_ativo(email) or is_admin()):
            flash('A prestacao de contas e exclusiva dos membros do Cla HYPE.', 'erro')
            return redirect(url_for('painel'))
        try:
            # Evita o limite padrao de 1.000 linhas de consultas PostgREST.
            registros = []
            pagina = 1000
            for inicio in range(0, 100000, pagina):
                lote = (supabase.table('hype_caixa_clan')
                        .select('id,tipo,categoria,valor,created_at')
                        .order('id')
                        .range(inicio, inicio + pagina - 1)
                        .execute().data or [])
                registros.extend(lote)
                if len(lote) < pagina:
                    break
            else:
                raise RuntimeError('Extrato extenso: usar agregacao no banco.')
        except Exception:
            flash('A economia do cla esta temporariamente indisponivel.', 'erro')
            return redirect(url_for('tesouro_hype'))
        resumo = calcular_resumo_caixa(registros)
        registros.sort(key=lambda item: str(item.get('created_at') or ''), reverse=True)
        return render_template('economia_cla.html', resumo=resumo, registros=registros[:100])

    return bp
