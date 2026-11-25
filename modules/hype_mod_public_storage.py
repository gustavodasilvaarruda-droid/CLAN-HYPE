"""Persistent read-only source for APPROVED public HYPE distribution builds.

The public web routes use a separate, private Supabase bucket and stream only
signed releases. Original/source-equivalent JARs remain in hype-mod-originals.
This module never uploads, signs, approves, or publishes any artifacts.
"""
from modules.hype_mod_catalog import InvalidCatalogue, verify_signed_catalogue
from modules.hype_signed_release import InvalidRelease, validate_binary

BUCKET = "hype-mod-distribution"
CATALOG_OBJECT = "stable/1.21.1/catalog.json"
PREFIX = "stable/1.21.1/mods"
MAX_BINARY = 64 * 1024 * 1024


def _private_distribution_bucket(db):
    storage = db.storage
    bucket = storage.get_bucket(BUCKET)
    public = bucket.get("public") if isinstance(bucket, dict) else getattr(bucket, "public", None)
    if public is not False:
        raise RuntimeError("Distribution bucket must be private")
    return storage.from_(BUCKET)


def read_catalogue(db):
    """Only the exact immutable channel path is read; signature is mandatory."""
    raw = _private_distribution_bucket(db).download(CATALOG_OBJECT)
    if not isinstance(raw, bytes):
        raise InvalidCatalogue("Invalid public distribution catalogue bytes")
    verify_signed_catalogue(raw)
    return raw


def read_binary(db, mod_id, sha, size):
    """Only exact catalogue-listed, hash-named JARs may be delivered."""
    if type(size) is not int or not 1000 <= size <= MAX_BINARY:
        raise InvalidRelease("Invalid distribution size")
    # Caller has already checked mod_id and sha against the signed catalogue.
    raw = _private_distribution_bucket(db).download(f"{PREFIX}/{mod_id}/{sha}.jar")
    if not isinstance(raw, bytes) or len(raw) != size:
        raise InvalidRelease("Public JAR size mismatch")
    validate_binary(raw, expected_sha=sha)
    return raw
