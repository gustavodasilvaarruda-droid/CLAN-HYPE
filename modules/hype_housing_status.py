"""Situação da moradia dos integrantes HYPE, sem alterar contratos ou cobranças.

Uma moradia regular exige casa ocupada/ativa e contrato ativo para o mesmo
jogador e casa. Registros desencontrados são marcados para revisão, não
contabilizados como casa válida.
"""


def _email(value):
    return str(value or '').strip().casefold()


def preencher_situacao_moradia(usuarios, casas, contratos):
    """Anota usuários in-place e devolve indicadores administrativos.

    A lista de usuários deve ter a chave hype_ativo, derivada da filiação ao
    clã, e não do cargo. None em casas/contratos sinaliza falha de consulta.
    """
    ativos = [u for u in usuarios if u.get('hype_ativo')]
    resumo = {
        'ok': casas is not None and contratos is not None,
        'total': len(ativos), 'com_casa': 0, 'sem_casa': 0,
        'verificar': 0, 'disponiveis': 0, 'faltam_unidades': 0,
    }
    if not resumo['ok']:
        for usuario in usuarios:
            usuario['moradia_status'] = 'indisponivel' if usuario.get('hype_ativo') else 'fora_cla'
            usuario['moradia_nome'] = None
        return resumo

    casas_por_email = {}
    casas_por_id = {}
    for casa in casas:
        if casa.get('ativa') is False:
            continue
        casa_id = str(casa.get('id'))
        casas_por_id[casa_id] = casa
        email = _email(casa.get('ocupante_email'))
        if casa.get('status') == 'disponivel' and not email:
            resumo['disponiveis'] += 1
        if email:
            casas_por_email.setdefault(email, []).append(casa)

    contratos_por_email = {}
    for contrato in contratos:
        if contrato.get('status') == 'ativo' and _email(contrato.get('usuario_email')):
            contratos_por_email.setdefault(_email(contrato['usuario_email']), []).append(contrato)

    for usuario in usuarios:
        usuario['moradia_nome'] = None
        if not usuario.get('hype_ativo'):
            usuario['moradia_status'] = 'fora_cla'
            continue
        email = _email(usuario.get('email'))
        vinculadas = casas_por_email.get(email, [])
        ativos_usuario = contratos_por_email.get(email, [])
        regular = (
            len(vinculadas) == 1 and len(ativos_usuario) == 1
            and vinculadas[0].get('status') == 'ocupada'
            and str(vinculadas[0].get('id')) == str(ativos_usuario[0].get('casa_id'))
        )
        if regular:
            usuario['moradia_status'] = 'com_casa'
            casa = vinculadas[0]
            usuario['moradia_nome'] = (
                (casa.get('codigo') or casa.get('nome') or 'Casa atribuída')
            )
        elif vinculadas or ativos_usuario:
            usuario['moradia_status'] = 'verificar'
            nomes = [c.get('codigo') or c.get('nome') or 'Casa sem identificação' for c in vinculadas]
            if not nomes:
                nomes = [casas_por_id.get(str(c.get('casa_id')), {}).get('codigo') or
                         'Contrato ativo sem casa ocupada' for c in ativos_usuario]
            usuario['moradia_nome'] = ', '.join(nomes)
        else:
            usuario['moradia_status'] = 'sem_casa'
        resumo[usuario['moradia_status']] += 1

    resumo['faltam_unidades'] = max(0, resumo['sem_casa'] - resumo['disponiveis'])
    return resumo
