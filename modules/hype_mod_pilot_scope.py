"""Fail-closed scope for HYPE's private Fabric JAR distribution.

Scope OFF is the default even when legacy feature flags are enabled.
An individual pilot is bound to the authenticated email from the server-side
signed session, NOT any query parameter, client header, or mod configuration.

This is not an entitlement grant: per-module permission is checked separately.
"""
import hmac
import os
import re

_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}\Z")


def pilot_scope_status(environ=None):
    env = os.environ if environ is None else environ
    scope = env.get("HYPE_PRIVATE_MOD_ROLLOUT_SCOPE", "off").strip().lower()
    if scope == "single":
        target = env.get("HYPE_PRIVATE_MOD_TESTER_EMAIL", "").strip().lower()
        return "single_ready" if len(target) <= 254 and _EMAIL.fullmatch(target) else "single_missing_tester"
    if scope == "clan":
        return ("clan_ready" if env.get("HYPE_PRIVATE_MOD_CLAN_RELEASE_CONFIRMED", "") == "yes"
                else "clan_unconfirmed")
    return "off"


def can_account_download_private_mods(authenticated_email, environ=None):
    """On every release-list AND binary fetch, require the CURRENT rollout gate."""
    status = pilot_scope_status(environ)
    if not isinstance(authenticated_email, str):
        return False
    email = authenticated_email.strip().lower()
    if not email or len(email) > 254 or not _EMAIL.fullmatch(email):
        return False
    if status == "single_ready":
        env = os.environ if environ is None else environ
        expected = env["HYPE_PRIVATE_MOD_TESTER_EMAIL"].strip().lower()
        return hmac.compare_digest(email, expected)
    if status == "clan_ready":
        return True
    return False
