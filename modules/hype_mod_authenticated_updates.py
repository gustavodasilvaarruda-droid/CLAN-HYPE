"""Server-side, fail-closed entitlement checks for restricted HYPE JAR updates.

The caller MUST authenticate the Minecraft user first. Role, clan membership,
and user email come from the server, never from request query/body fields.
This module does not expose JARs, issue download links, or change permissions.
"""
from modules.hype_mod_update_access import MOD_TO_SITE_MODULE, may_receive_mod_update


class ModEntitlementUnavailable(RuntimeError):
    """The current permissions could not be reliably checked."""


def may_account_receive_update(db, mod_id, email, cargo, member):
    """Re-read current server permissions for ONE authenticated user's mod."""
    if not isinstance(email, str) or not email.strip():
        return False
    code = MOD_TO_SITE_MODULE.get(mod_id)
    if code is None:
        return False  # HYPE Client and unknown mods are not private grants.
    try:
        modules = (db.table("hype_modulos")
                   .select("codigo,estado,visivel")
                   .eq("codigo", code).limit(2).execute().data or [])
        assignments = (db.table("hype_modulos_grupos")
                       .select("modulo_codigo,cargo_id")
                       .eq("modulo_codigo", code).limit(500).execute().data or [])
        overrides = (db.table("hype_modulos_acessos")
                     .select("modulo_codigo,decisao,inicio_em,fim_em")
                     .eq("modulo_codigo", code)
                     .eq("usuario_email", email).limit(2).execute().data or [])
        if len(modules) != 1 or len(overrides) > 1:
            return False
        return may_receive_mod_update(
            mod_id, modules, assignments, overrides, cargo, bool(member)
        )
    except Exception as exc:
        raise ModEntitlementUnavailable("Falha ao verificar permissões atuais") from exc


def authorized_mod_ids(db, email, cargo, member):
    """Only identifiers allowed by the latest server-side rules; no versions."""
    return [
        mod_id for mod_id in MOD_TO_SITE_MODULE
        if may_account_receive_update(db, mod_id, email, cargo, member)
    ]
