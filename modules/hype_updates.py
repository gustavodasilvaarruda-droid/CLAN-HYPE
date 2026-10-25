"""Read-only update distribution for HYPE Minecraft Client.

No uploads, admin actions, Supabase access, or signing keys live here. Releases
must be signed OFFLINE and explicitly staged before a manifest is published.
"""
import os
import re
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, make_response, send_file

hype_updates_bp = Blueprint('hype_updates', __name__)
_RELEASE_NAME = re.compile(r'hypeclient-r[1-9][0-9]{0,8}\.jar\Z', re.ASCII)


def _root():
    directory = os.environ.get('HYPE_UPDATES_DIR', '').strip()
    return Path(directory).resolve() if directory else (Path(current_app.root_path) / 'hype-updates').resolve()


def _safe_regular_file(base, filename):
    # Reject symlinks escaping the dedicated publishing directory.
    directory = base.resolve()
    candidate = (directory / filename).resolve()
    if not candidate.is_relative_to(directory) or not candidate.is_file():
        abort(404)
    return candidate


def _deliver(path, mimetype, cache):
    response = make_response(send_file(path, mimetype=mimetype, conditional=True))
    response.headers['Cache-Control'] = cache
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@hype_updates_bp.get('/hype-updates/manifest.properties')
def updates_manifest():
    """Clients verify the detached Ed25519 signature before trusting metadata."""
    path = _safe_regular_file(_root(), 'manifest.properties')
    return _deliver(path, 'text/plain; charset=utf-8', 'no-store, max-age=0')


@hype_updates_bp.get('/hype-updates/releases/<filename>')
def updates_release(filename):
    if not _RELEASE_NAME.fullmatch(filename):
        abort(404)
    path = _safe_regular_file(_root() / 'releases', filename)
    return _deliver(path, 'application/java-archive', 'public, max-age=31536000, immutable')


@hype_updates_bp.get('/hype-updates/health')
def updates_health():
    root = _root()
    manifest = root / 'manifest.properties'
    # This endpoint is deliberately not a signature/integrity attestation.
    try:
        published = manifest.is_file() and manifest.resolve().is_relative_to(root)
    except OSError:
        published = False
    response = jsonify(service='hype-updates', manifest_present=published)
    response.headers['Cache-Control'] = 'no-store'
    return response
