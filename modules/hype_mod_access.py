"""Effective access decisions for the HYPE Minecraft Client.

Pure functions: no Flask, no credentials, no database connection and no writes.
This must be re-evaluated by the backend for each protected operation.
"""
from datetime import datetime, timezone


def _datetime(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _active_override(override, now):
    if not override or override.get('decisao') not in ('permitir', 'bloquear'):
        return False
    begin = _datetime(override.get('inicio_em'))
    if begin is None or now < begin:
        return False
    end_raw = override.get('fim_em')
    if end_raw is not None:
        end = _datetime(end_raw)
        if end is None or now >= end:
            return False
    return True


def user_groups(cargo, member):
    """Separate basic members from active members of the HYPE clan.

    A public signup has cargo='visitante' and cannot use HYPE modules.
    The basic 'membro' grant requires a non-visitor role. The exclusive
    'membro_hype' group (and specialty roles) requires active clan status.
    """
    if not cargo or str(cargo) == 'visitante':
        return set()
    groups = {'membro'}
    if member:
        groups.update(('membro_hype', str(cargo)))
    return groups


def evaluate_module(module, user_roles, allowed_roles, override=None, now=None):
    """Fail closed. Global OFF/maintenance always wins, even over manual grants."""
    now = now or datetime.now(timezone.utc)
    state = module.get('estado')
    if state != 'ativo':
        reason = 'manutencao' if state == 'manutencao' else 'desativado_globalmente'
        return {'permitido': False, 'motivo': reason}
    if _active_override(override, now):
        if override['decisao'] == 'bloquear':
            return {'permitido': False, 'motivo': 'bloqueio_individual'}
        return {'permitido': True, 'motivo': 'liberacao_individual'}
    if set(user_roles) & set(allowed_roles):
        return {'permitido': True, 'motivo': 'cargo_permitido'}
    return {'permitido': False, 'motivo': 'sem_permissao'}


def visible_modules_for_user(modules, assignments, overrides, cargo, member, now=None):
    """Public-facing DTO: never disclose access reasons, emails or admin metadata."""
    groups = user_groups(cargo, member)
    by_mod = {}
    for row in assignments:
        if row.get('modulo_codigo') and row.get('cargo_id'):
            by_mod.setdefault(row['modulo_codigo'], set()).add(row['cargo_id'])
    by_override = {r['modulo_codigo']: r for r in overrides if r.get('modulo_codigo')}
    response = []
    for row in modules:
        if row.get('visivel') is False:
            continue
        code = row.get('codigo')
        if not code:
            continue
        # Individual overrides never approve a public visitor implicitly.
        decision = (evaluate_module(row, groups, by_mod.get(code, ()), by_override.get(code), now)
                    if groups else {'permitido': False, 'motivo': 'conta_sem_aprovacao'})
        response.append({
            'codigo': code, 'nome': row.get('nome') or code,
            'descricao': row.get('descricao') or '',
            'icone': row.get('icone') or 'blocks',
            'categoria': row.get('categoria') or 'ferramentas',
            'versao': row.get('versao') or '',
            'estado': row.get('estado') if row.get('estado') in ('ativo', 'manutencao') else 'desativado',
            **decision,
        })
    return response
