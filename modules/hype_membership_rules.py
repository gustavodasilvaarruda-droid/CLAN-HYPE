"""Regras de filiação do CLAN HYPE independentes do Flask.

'Membro' é a conta do servidor. 'Membro HYPE' é o vínculo ativo,
não um cargo de função. Funções especiais exigem filiação aprovada.
"""

BASIC_ROLE = 'membro'
LEGACY_ROLE_IDS = frozenset({'visitante', 'membro_hype', 'pedri'})


def role_requires_active_clan(role):
    """Somente o cargo básico pode ser atribuído fora do clã."""
    return str(role or '').strip() != BASIC_ROLE


def selectable_roles(roles):
    """Oculta cargos redundantes sem remover permissões legadas dos mods."""
    return [role for role in roles
            if role.get('id') not in LEGACY_ROLE_IDS]


def membership_status(active):
    return 'Membro HYPE' if active else 'Membro do servidor'
