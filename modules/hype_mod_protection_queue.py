"""Fila privada para proteger JARs HYPE. Nenhum job publica releases.

O processo web apenas agenda; um worker isolado obfusca e valida os bytes.
Ativacao independente: HYPE_MOD_PROTECTION_QUEUE_ENABLED=1.
"""
from __future__ import annotations

import re

from modules.hype_mod_staging import (
    TABLE, IDS, BUCKET, InvalidJar, assert_private_bucket, parse_draft_id,
)

JOBS = "hype_mod_protection_jobs"


def queue_protection(db, draft_id, requested_by):
    """Registra um job para um original JA existente e imutavel."""
    draft_id = parse_draft_id(str(draft_id))
    rows = (db.table(TABLE).select("id,module_id,sha256,status,meta,storage_path")
            .eq("id", draft_id).limit(1).execute().data or [])
    if not rows:
        raise InvalidJar("Arquivo original nao encontrado.")
    draft = rows[0]
    if draft.get("module_id") not in IDS or draft.get("status") not in ("aguardando_protecao", "em_teste"):
        raise InvalidJar("Somente originais pendentes ou em teste podem entrar na fila.")
    if (draft.get("meta") or {}).get("protected"):
        raise InvalidJar("Este arquivo ja possui um candidato protegido.")
    sha = draft.get("sha256")
    path = draft.get("storage_path")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise InvalidJar("SHA-256 do original invalido.")
    if (not isinstance(path, str)
            or not re.fullmatch(rf"{re.escape(draft['module_id'])}/[0-9a-f]{{32}}/{sha}\.jar", path)):
        raise InvalidJar("Caminho privado do original invalido.")
    assert_private_bucket(db.storage)
    jobs = (db.table(JOBS).select("id,status,original_sha256").eq("draft_id", str(draft_id))
            .limit(1).execute().data or [])
    if jobs:
        job = jobs[0]
        if job["status"] != "failed" or job["original_sha256"] != sha:
            raise InvalidJar("Esta versao ja possui um pedido de protecao. Consulte o status na Central.")
        updated = (db.table(JOBS).update({
            "status": "queued", "failure_reason": None,
            "started_at": None, "finished_at": None, "candidate_sha256": None,
            "requested_by": requested_by,
        }).eq("id", job["id"]).eq("status", "failed").execute().data or [])
        if not updated:
            raise InvalidJar("A fila mudou durante a tentativa. Atualize a pagina.")
        return job["id"]
    saved = db.table(JOBS).insert({
        "draft_id": str(draft_id), "original_sha256": sha,
        "module_id": draft["module_id"], "requested_by": requested_by,
        "status": "queued",
    }).execute().data or []
    if not saved:
        raise RuntimeError("Nao foi possivel registrar a protecao.")
    return saved[0]["id"]


def jobs_for_drafts(db):
    rows = (db.table(JOBS)
            .select("draft_id,status,failure_reason,requested_at")
            .order("requested_at", desc=True).limit(200).execute().data or [])
    return {str(row["draft_id"]): row for row in rows}
