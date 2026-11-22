"""Read-only update distribution for HYPE Minecraft Client.

No uploads, admin actions, Supabase access, or signing keys live here. Releases
must be signed OFFLINE and explicitly staged before a manifest is published.
"""
import os
import re
import io
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, make_response, redirect, send_file
from modules.hype_signed_release import InvalidRelease, validate_binary, SHA
from modules.hype_mod_catalog import (InvalidCatalogue, verify_signed_catalogue,
                                     MODULE_IDS, CATALOGUE_BASE_URL)

hype_updates_bp = Blueprint('hype_updates', __name__)
_RELEASE_NAME = re.compile(r'hypeclient-r[1-9][0-9]{0,8}\.jar\Z', re.ASCII)


def _managed_enabled():
    return os.getenv('HYPE_MOD_DISTRIBUTION_ENABLED', '').lower() in ('1', 'true', 'yes')


def _release_db():
    db = current_app.extensions.get('hype_release_db')
    if db is None:
        abort(503)
    return db


def _managed_latest():
    try:
        data = (_release_db().table('hype_mod_published_releases')
                .select('release,manifest').eq('status', 'published')
                .order('release', desc=True).limit(1).execute().data or [])
    except Exception:
        current_app.logger.exception('Failed to load HYPE signed manifest')
        abort(503)
    if not data:
        abort(404)
    return data[0]


def _managed_jar(filename):
    number = int(filename[len('hypeclient-r'):-len('.jar')])
    try:
        db = _release_db()
        releases = (db.table('hype_mod_published_releases')
                    .select('release,size_bytes,sha256,storage_path,status')
                    .eq('release', number).eq('status', 'published').limit(1)
                    .execute().data or [])
        if not releases:
            abort(404)
        item = releases[0]
        path = item['storage_path']
        sha = item['sha256']
        if not (path.startswith('hypeclient/') and path.endswith('/' + sha + '.jar')):
            abort(503)
        # The published JAR remains in private Storage. Never redirect clients
        # to a third-party URL or leak a storage service-role key.
        raw = db.storage.from_('hype-mod-originals').download(path)
        if len(raw) != int(item['size_bytes']):
            abort(503)
        validate_binary(raw, expected_sha=sha)
    except InvalidRelease:
        current_app.logger.error('HYPE release checksum mismatch: %s', filename)
        abort(503)
    except Exception as exc:
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            raise
        current_app.logger.exception('Failed to serve HYPE release: %s', filename)
        abort(503)
    return _deliver(io.BytesIO(raw), 'application/java-archive',
                    'public, max-age=31536000, immutable')


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
    if _managed_enabled():
        release = _managed_latest()
        response = make_response(release['manifest'], 200)
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
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
    if _managed_enabled():
        return _managed_jar(filename)

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
    if _managed_enabled():
        try:
            _managed_latest()
            published = True
        except Exception:
            published = False
        response = jsonify(service='hype-updates', manifest_present=published,
                           managed_distribution=True)
        response.headers['Cache-Control'] = 'no-store'
        return response
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


@hype_updates_bp.get('/hype-updates/mods/catalog.json')
def multi_mod_signed_catalogue():
    """Preview-only signed catalogue for a future HYPE bootstrap (OFF by default).

    This is NOT consumed by the current HYPE Client, and this route does not
    expose or publish any mod JARs. Keep disabled until the matching signed
    binary endpoints and new Java bootstrap have passed end-to-end testing.
    """
    if os.getenv('HYPE_MULTI_MOD_CATALOG_ENABLED', '').lower() not in ('1', 'true', 'yes'):
        abort(404)
    path = _safe_regular_file(_root() / 'mods', 'catalog.json')
    try:
        raw = path.read_bytes()
        catalogue = verify_signed_catalogue(raw)
    except (InvalidCatalogue, OSError):
        current_app.logger.exception('Invalid HYPE multi-mod signed catalogue')
        abort(503)
    # The pilot catalogue is public. Never disclose restricted releases on it.
    # A per-user signed/authorized catalogue is still required for multi-mod.
    if any(item['id'] != 'hypeclient' for item in catalogue['mods']):
        abort(403)
    response = make_response(raw, 200)
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response



@hype_updates_bp.get('/hype-updates/mods/<mod_id>/<sha256>.jar')
def multi_mod_signed_binary(mod_id, sha256):
    """Pilot binary delivery: OFF unless both independent switches are enabled.

    Only serve an immutable hash-named JAR that is named in the currently signed
    and verified catalogue. No original uploads or candidate staging paths are
    readable through this route. Never enable for restricted modules until the
    authorization/entitlements policy is implemented.
    """
    if (os.getenv('HYPE_MULTI_MOD_CATALOG_ENABLED', '').lower() not in ('1', 'true', 'yes')
            or os.getenv('HYPE_MULTI_MOD_DOWNLOADS_ENABLED', '').lower() not in ('1', 'true', 'yes')):
        abort(404)
    if mod_id not in MODULE_IDS or not SHA.fullmatch(sha256):
        abort(404)
    # Signed does not mean authorized. This legacy pilot URL has NO login;
    # private mods must be served only by the future per-user download API.
    if mod_id != 'hypeclient':
        abort(403)
    try:
        catalogue = verify_signed_catalogue(
            _safe_regular_file(_root() / 'mods', 'catalog.json').read_bytes()
        )
    except (InvalidCatalogue, OSError):
        current_app.logger.exception('Invalid catalogue for HYPE pilot download')
        abort(503)
    expected = next((item for item in catalogue['mods']
                     if item['id'] == mod_id and item['sha256'] == sha256), None)
    if (expected is None or
            expected['url'] != f'{CATALOGUE_BASE_URL}{mod_id}/{sha256}.jar'):
        abort(404)
    path = _safe_regular_file(_root() / 'mods' / mod_id, f'{sha256}.jar')
    try:
        if path.stat().st_size != expected['size']:
            abort(503)
        raw = path.read_bytes()
        if len(raw) != expected['size']:
            abort(503)
        validate_binary(raw, expected_sha=sha256)
    except InvalidRelease:
        current_app.logger.error('Failed integrity check for %s/%s', mod_id, sha256)
        abort(503)
    except OSError:
        current_app.logger.exception('Unable to read HYPE pilot binary')
        abort(503)
    return _deliver(io.BytesIO(raw), 'application/java-archive',
                    'public, max-age=31536000, immutable')


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
