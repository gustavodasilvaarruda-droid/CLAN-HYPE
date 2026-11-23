"""Isolated owner-only original JAR pilot security checks."""
import base64
import hashlib
import io
import json
import uuid
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_STORED

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from modules import hype_signed_release as signed
from modules import hype_manifest_signer as signer
from modules.hype_mod_pilot_original import (
    pilot_original_enabled, publish_pilot_original,
    find_pilot_original, download_pilot_original,
    InvalidPrivateRelease,
)


EMAIL = "teste@example.com"
MODULE = "hype_pokedex"


def jar_bytes(version):
    out = io.BytesIO()
    with ZipFile(out, "w", ZIP_STORED) as z:
        z.writestr("fabric.mod.json", json.dumps({
            "schemaVersion": 1, "id": MODULE, "version": version,
            "depends": {"minecraft": "1.21.1"},
        }))
        z.writestr("br/hype/Test.class", b"fake class data " * 128)
    return out.getvalue()


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.where = []
        self.data = None
        self.max_rows = None

    def select(self, *a): return self
    def eq(self, col, val):
        self.where.append((col, val))
        return self
    def order(self, *a, **kw): return self
    def limit(self, val):
        self.max_rows = val
        return self
    def update(self, data):
        self.data = data
        return self
    def execute(self):
        rows = [r for r in self.db.rows
                if all(r.get(k) == v for k, v in self.where)]
        if self.max_rows is not None:
            rows = rows[:self.max_rows]
        if self.data is not None:
            for row in rows: row.update(self.data)
        return SimpleNamespace(data=[dict(row) for row in rows])


class Storage:
    def __init__(self, jars):
        self.jars = jars
    def get_bucket(self, name): return {"public": False}
    def from_(self, name): return self
    def download(self, path): return self.jars[path]


class DB:
    def __init__(self, drafts, jars):
        self.rows = drafts
        self.storage = Storage(jars)
    def table(self, name):
        assert name == "hype_mod_release_drafts"
        return Query(self, name)


def fixture_db(version="1.0"):
    raw = jar_bytes(version)
    sha = hashlib.sha256(raw).hexdigest()
    draft_id = str(uuid.uuid4())
    path = f"{MODULE}/{uuid.uuid4().hex}/{sha}.jar"
    draft = {
        "id": draft_id, "module_id": MODULE, "version": version,
        "status": "aguardando_protecao", "sha256": sha,
        "size_bytes": len(raw), "storage_path": path, "meta": {},
    }
    return DB([draft], {path: raw}), raw, draft


@pytest.fixture
def key(monkeypatch):
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo,
    )).decode("ascii")
    monkeypatch.setattr(signed, "PUBLIC_KEY_DER_B64", public)
    monkeypatch.setattr(signer, "PUBLIC_KEY_DER_B64", public)
    monkeypatch.setenv("HYPE_MOD_PILOT_ORIGINAL_ENABLED", "1")
    monkeypatch.setenv("HYPE_PRIVATE_MOD_ROLLOUT_SCOPE", "single")
    monkeypatch.setenv("HYPE_PRIVATE_MOD_TESTER_EMAIL", EMAIL)
    return private


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("HYPE_MOD_PILOT_ORIGINAL_ENABLED", raising=False)
    assert not pilot_original_enabled(EMAIL)


def test_private_original_signed_publish_and_download(key):
    db, raw, draft = fixture_db()
    manifest = signer.sign_private_mod_manifest(raw, key, 1)
    row = publish_pilot_original(
        db, draft_id=draft["id"], manifest_bytes=manifest, published_by=EMAIL,
    )
    assert row["sha256"] == draft["sha256"]
    latest = find_pilot_original(db, MODULE)
    assert latest[1]["manifest"] == manifest.decode("ascii")
    assert download_pilot_original(db, latest[0]).read() == raw
    assert find_pilot_original(db, MODULE, sha256="a" * 64) is None


def test_wrong_account_denied_and_public_account_never_enabled(key):
    db, raw, draft = fixture_db()
    manifest = signer.sign_private_mod_manifest(raw, key, 3)
    assert not pilot_original_enabled("another@example.com")
    with pytest.raises(InvalidPrivateRelease):
        publish_pilot_original(
            db, draft_id=draft["id"], manifest_bytes=manifest,
            published_by="another@example.com",
        )


def test_unsigned_manifest_rejected(key):
    db, raw, draft = fixture_db()
    manifest = signer.sign_private_mod_manifest(raw, key, 2)
    corrupted = manifest.replace(b"signature=", b"signature=AAAA", 1)
    with pytest.raises(InvalidPrivateRelease):
        publish_pilot_original(
            db, draft_id=draft["id"], manifest_bytes=corrupted, published_by=EMAIL,
        )


def test_latest_requires_increasing_release(key):
    db, raw, draft = fixture_db("1.0")
    manifest = signer.sign_private_mod_manifest(raw, key, 4)
    publish_pilot_original(db, draft_id=draft["id"],
                           manifest_bytes=manifest, published_by=EMAIL)
    newer_db, newer_raw, newer_draft = fixture_db("1.1")
    db.rows += newer_db.rows
    db.storage.jars.update(newer_db.storage.jars)
    with pytest.raises(InvalidPrivateRelease):
        publish_pilot_original(
            db, draft_id=newer_draft["id"],
            manifest_bytes=signer.sign_private_mod_manifest(newer_raw, key, 4),
            published_by=EMAIL,
        )
    publish_pilot_original(
        db, draft_id=newer_draft["id"],
        manifest_bytes=signer.sign_private_mod_manifest(newer_raw, key, 5),
        published_by=EMAIL,
    )
    assert find_pilot_original(db, MODULE)[1]["release"] == 5


def test_tampered_original_never_served(key):
    db, raw, draft = fixture_db()
    publish_pilot_original(
        db, draft_id=draft["id"],
        manifest_bytes=signer.sign_private_mod_manifest(raw, key, 1),
        published_by=EMAIL,
    )
    db.storage.jars[draft["storage_path"]] = raw + b"x"
    with pytest.raises((ValueError, InvalidPrivateRelease)):
        download_pilot_original(db, db.rows[0])
