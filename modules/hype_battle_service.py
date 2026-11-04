"""Conexão exclusiva do servidor para o estado da Sala de Batalha HYPE.

RLS não expõe esta tabela ao navegador; nunca devolver a service_role key.
"""
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_battle_client():
    url = os.environ.get("SUPABASE_URL", "").strip()
    service_role = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not service_role:
        return None
    try:
        from supabase import create_client
        return create_client(url, service_role)
    except Exception:
        return None
