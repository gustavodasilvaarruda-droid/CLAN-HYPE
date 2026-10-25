"""Read-only update distribution for HYPE Minecraft Client.

No uploads, admin actions, Supabase access, or signing keys live here. Releases
must be signed OFFLINE and explicitly staged before a manifest is published.
"""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, make_response, redirect, send_file

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


def _external_release_url(filename, variable='HYPE_UPDATES_RELEASE_BASE_URL'):
    """Optional persistent GitHub Release/object-store URL; never accepts user URLs."""
    base = os.environ.get(variable, '').strip()
    if not base:
        return None
    parsed = urlsplit(base)
    # Avoid accidentally exposing a release through HTTP or unsafe redirect URLs.
    if (
        parsed.scheme != 'https'
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(c.isspace() for c in base)
        or '\\' in base
    ):
        abort(503)
    return f"{base.rstrip('/')}/{filename}"


@hype_updates_bp.get('/hype-updates/releases/<filename>')
def updates_release(filename):
    if not _RELEASE_NAME.fullmatch(filename):
        abort(404)

    # Prefer a local release for compatibility with existing deployments.
    directory = (_root() / 'releases').resolve()
    candidate = (directory / filename).resolve()
    if candidate.is_relative_to(directory) and candidate.is_file():
        return _deliver(candidate, 'application/java-archive', 'public, max-age=31536000, immutable')

    # Render's ephemeral disk must not be the sole place where releases live.
    url = _external_release_url(filename)
    if not url:
        abort(404)
    response = redirect(url, code=302)
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


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


# Separate opt-in distribution channel for MoreCobblemonTweaks HYPE (Auto Ovo).
# It does not change the HYPE Client R7.17 paths, authentication, or manifests.
_AUTO_OVO_RELEASE_NAME = re.compile(r'hype-auto-ovo-h[1-9][0-9]{0,5}\.jar\Z', re.ASCII)


def _auto_ovo_root():
    return _root() / 'auto-ovo'


@hype_updates_bp.get('/hype-updates/auto-ovo/health')
def auto_ovo_updates_health():
    root = _auto_ovo_root().resolve()
    manifest = root / 'manifest.properties'
    try:
        published = manifest.is_file() and manifest.resolve().is_relative_to(root)
    except OSError:
        published = False
    response = jsonify(service='hype-auto-ovo-updates', manifest_present=published)
    response.headers['Cache-Control'] = 'no-store'
    return response


@hype_updates_bp.get('/hype-updates/auto-ovo/manifest.properties')
def auto_ovo_updates_manifest():
    # A future Auto Ovo client MUST validate the pinned Ed25519 signature,
    # release SHA-256 and module ID. No unsigned updates are ever approved.
    path = _safe_regular_file(_auto_ovo_root(), 'manifest.properties')
    return _deliver(path, 'text/plain; charset=utf-8', 'no-store, max-age=0')


@hype_updates_bp.get('/hype-updates/auto-ovo/releases/<filename>')
def auto_ovo_updates_release(filename):
    if not _AUTO_OVO_RELEASE_NAME.fullmatch(filename):
        abort(404)

    root = _auto_ovo_root()
    directory = (root / 'releases').resolve()
    candidate = (directory / filename).resolve()
    if candidate.is_relative_to(directory) and candidate.is_file():
        return _deliver(candidate, 'application/java-archive', 'public, max-age=31536000, immutable')

    # Independent opt-in base URL; the R7.17 release variable cannot be reused.
    url = _external_release_url(filename, 'HYPE_AUTO_OVO_RELEASE_BASE_URL')
    if not url:
        abort(404)
    response = redirect(url, code=302)
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
