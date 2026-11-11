"""Source-level security and route gating smoke checks (no server credentials)."""
from pathlib import Path
source = (Path(__file__).parents[1] / "modules" / "hype_mod_staging.py").read_text()

def test_routes_are_opt_in():
    assert 'HYPE_MOD_STAGING_ENABLED' in source
    assert 'register_mod_release_routes' in source
    assert 'admin_only()' in source

def test_private_storage_and_no_publishing():
    assert 'assert_private_bucket(db.storage)' in source
    assert '"public"' in source
    assert '/releases/upload' in source
    assert '.upload(' in source
    assert 'service_key' in source
    assert 'send_file' not in source
