"""Policy for future authenticated HYPE mod downloads (not an endpoint).

The legacy HYPE Client bootstrap is handled separately. This module MUST only
be called after authenticating the player on the server; its boolean result is
not a substitute for that authentication or for Fabric runtime access checks.
"""
from modules.hype_mod_access import visible_modules_for_user

# Signed JAR identifiers are different from the existing site module codes.
# Never infer a module's privileges from the JAR filename supplied by a client.
MOD_TO_SITE_MODULE = {
    "hype_pokedex": "pokedex",
    "hype_breed_calculator": "breed_calculator",
    "hype_battlefield": "campo_batalha",
    "hype_battle_ai": "battle_ai",
}


def may_receive_mod_update(mod_id, modules, assignments, overrides, cargo, member, now=None):
    """Fail closed for missing, hidden, stopped, or unauthorized modules.

    Caller must verify a current authenticated player, fetch live permissions
    from the server, and never accept permission rows supplied by the player.
    The mandatory bootstrap itself is intentionally outside this policy.
    """
    site_code = MOD_TO_SITE_MODULE.get(mod_id)
    if not site_code:
        return False
    matched = [m for m in modules if m.get("codigo") == site_code]
    if len(matched) != 1:
        return False
    decision = visible_modules_for_user(
        matched, assignments, overrides, cargo, member, now=now
    )
    return len(decision) == 1 and decision[0]["permitido"] is True
