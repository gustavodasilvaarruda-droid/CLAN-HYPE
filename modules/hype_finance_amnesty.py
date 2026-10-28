"""Isencao auditada de comissoes antigas. Nao modifica o caixa do Cla."""
from datetime import date
from flask import Blueprint, flash, redirect, request, session, url_for


def validar_isencao(data_corte, motivo, confirmou):
    try:
        corte = date.fromisoformat((data_corte or '').strip())
    except (ValueError, TypeError):
        raise ValueError('Informe uma data de inicio valida.') from None
    if corte > date.today():
        raise ValueError('A data de inicio nao pode estar no futuro.')
    motivo = (motivo or '').strip()
    if len(motivo) < 10:
        raise ValueError('Descreva o motivo da isencao (minimo de 10 caracteres).')
    if not confirmou:
        raise ValueError('Confirme que deseja isentar apenas as comissoes pendentes antigas.')
    return corte, motivo[:500]


def create_finance_amnesty_blueprint(supabase, login_required, is_admin, registrar_log):
    bp = Blueprint('finance_amnesty', __name__)

    @bp.route('/admin/financeiro/comissoes/isentar-antigas', methods=['POST'])
    @login_required
    def isentar_antigas():
        if not is_admin():
            flash('Apenas a administracao pode isentar comissoes.', 'erro')
            return redirect(url_for('painel'))
        try:
            corte, motivo = validar_isencao(
                request.form.get('data_inicio_cobranca'),
                request.form.get('motivo'),
                request.form.get('confirmar_isencao') == 'sim',
            )
            resposta = supabase.rpc('hype_isentar_comissoes_anteriores', {
                'p_data_corte': corte.isoformat(),
                'p_operador_email': session.get('usuario_email'),
                'p_motivo': motivo,
            }).execute()
            dados = resposta.data or []
            dados = dados[0] if isinstance(dados, list) and dados else (dados if isinstance(dados, dict) else {})
            quantidade = int(dados.get('quantidade') or 0)
            total = int(dados.get('total_valor') or 0)
            registrar_log('isentar_comissoes_antigas', 'financeiro_breed', 'lote', None, {
                'quantidade': quantidade, 'valor': total, 'data_corte': corte.isoformat(),
                'motivo': motivo,
            })
            flash(f'{quantidade} comissao(oes) antiga(s) isenta(s). Nenhum valor foi lancado no caixa.', 'sucesso')
        except ValueError as erro:
            flash(str(erro), 'erro')
        except Exception:
            # Nao expor mensagens de banco/senhas a usuarios.
            flash('Nao foi possivel aplicar a isencao. Confira se a migracao do banco foi instalada.', 'erro')
        return redirect(url_for('final.financeiro'))

    return bp
