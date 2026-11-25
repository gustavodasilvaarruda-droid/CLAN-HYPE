"""Worker isolado da Central HYPE: transforma apenas JARs privados enfileirados.

Este modulo NAO inclui um ofuscador. Exige um comando local instalado, confiavel
e configurado pelo administrador no ambiente ISOLADO, nunca no servidor web.
Nao executa o JAR de entrada nem assina, aprova ou publica um release.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from modules.hype_mod_build_checks import check_candidate_compatibility
from modules.hype_mod_protection_queue import JOBS
from modules.hype_mod_staging import (
    BUCKET, MAX_UPLOAD, TABLE, InvalidJar,
    assert_private_bucket, audit_candidate_pair, inspect_original, parse_draft_id, valid_module_id,
)
from modules.hype_signed_release import validate_binary


class ProtectionError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _protector_argv():
    """Aceita SOMENTE argv JSON (sem shell), com caminhos absolutos internos."""
    raw = os.environ.get("HYPE_MOD_PROTECTOR_ARGV_JSON", "")
    try:
        argv = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ProtectionError("Configure HYPE_MOD_PROTECTOR_ARGV_JSON no worker.") from exc
    if (not isinstance(argv, list) or not 2 <= len(argv) <= 32
            or any(not isinstance(v, str) or not 0 < len(v) <= 1024 for v in argv)):
        raise ProtectionError("Comando do ofuscador invalido.")
    if not os.path.isabs(argv[0]):
        raise ProtectionError("Executavel do ofuscador precisa ter caminho absoluto.")
    joined = " ".join(argv)
    if "{input}" not in joined or "{output}" not in joined:
        raise ProtectionError("Ofuscador precisa receber {input} e {output}.")
    if not Path(argv[0]).is_file():
        raise ProtectionError("Executavel do ofuscador nao foi instalado.")
    return argv


def _run_protector(original, command):
    with tempfile.TemporaryDirectory(prefix="hype-protect-") as folder:
        root = Path(folder)
        root.chmod(0o700)
        source = root / "original.jar"
        target = root / "protegido.jar"
        source.write_bytes(original)
        source.chmod(0o600)
        argv = [arg.replace("{input}", str(source)).replace("{output}", str(target))
                for arg in command]
        # Segredos do Supabase NAO sao herdados pelo processo de ofuscacao.
        clean_env = {"PATH": os.environ.get("PATH", ""), "HOME": str(root), "LANG": "C.UTF-8"}
        try:
            subprocess.run(
                argv, cwd=str(root), env=clean_env, timeout=180,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=True, shell=False,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            raise ProtectionError("Ofuscador falhou ou excedeu o tempo limite.") from exc
        if not target.is_file() or target.is_symlink():
            raise ProtectionError("O ofuscador nao produziu um JAR regular.")
        if not 0 < target.stat().st_size <= MAX_UPLOAD:
            raise ProtectionError("O JAR protegido excede o limite do site.")
        return target.read_bytes()


def _load_draft(db, job):
    draft_id = parse_draft_id(job["job_draft_id"])
    rows = (db.table(TABLE).select("id,module_id,version,status,sha256,storage_path,meta")
            .eq("id", draft_id).limit(1).execute().data or [])
    if not rows:
        raise ProtectionError("Original nao encontrado.")
    d = rows[0]
    if (d.get("status") not in ("aguardando_protecao", "em_teste")
            or not valid_module_id(d.get("module_id"))
            or d.get("sha256") != job["job_sha256"]
            or (d.get("meta") or {}).get("protected")):
        raise ProtectionError("Original mudou desde o pedido de protecao.")
    path = d.get("storage_path")
    sha = d["sha256"]
    if not isinstance(path, str) or not re.fullmatch(
            rf"{re.escape(d['module_id'])}/[0-9a-f]{{32}}/{sha}\.jar", path):
        raise ProtectionError("Caminho do JAR original invalido.")
    return d


def process_job(db, job, command):
    """Protege, valida e guarda o candidato SOMENTE em armazenamento privado."""
    assert_private_bucket(db.storage)
    draft = _load_draft(db, job)
    draft_id = parse_draft_id(job["job_draft_id"])
    storage = db.storage.from_(BUCKET)
    original = storage.download(draft["storage_path"])
    validate_binary(original, expected_sha=draft["sha256"])
    inspect_original(original)  # checagem ZIP / Fabric, sem execucao
    candidate = _run_protector(original, command)
    check_candidate_compatibility(original, candidate)
    report = inspect_original(candidate)
    if report["module_id"] != draft["module_id"] or report["version"] != draft["version"]:
        raise ProtectionError("Metadados Fabric alterados durante a protecao.")
    sha = hashlib.sha256(candidate).hexdigest()
    if sha == draft["sha256"]:
        raise ProtectionError("O ofuscador nao alterou o arquivo original.")

    path = f'{draft["module_id"]}/{draft_id}/protected/{uuid4().hex}/{sha}.jar'
    meta = dict(draft.get("meta") or {})
    meta["protected"] = {
        "storage_path": path, "sha256": sha, "size_bytes": len(candidate),
        "static_audit": "passed", "obfuscation_verified": False,
        "received_at": _now(), "protection_job_id": job["job_id"],
    }
    # Testes estaticos NAO provam que a ofuscacao esta correta no Minecraft.
    meta["automatic_review"] = audit_candidate_pair(
        original, candidate, {**draft, "meta": meta}
    )
    meta.pop("manual_review", None)
    storage.upload(path=path, file=candidate,
                   file_options={"content-type": "application/java-archive", "upsert": "false"})
    try:
        # Atualizacao atomica no banco: nao sobrescreve um candidato enviado
        # manualmente nem reverte uma aprovacao em corrida com o worker.
        committed = db.rpc("hype_finish_mod_protection_draft", {
            "p_draft_id": str(draft_id), "p_sha256": draft["sha256"],
            "p_job_id": job["job_id"],
            "p_candidate": {
                "protected": meta["protected"],
                "automatic_review": meta["automatic_review"],
            },
        }).execute().data
        if committed is not True:
            raise ProtectionError("Original mudou enquanto o candidato era armazenado.")
    except Exception:
        storage.remove([path])
        raise
    return sha


def work_once(db, command):
    """Retira um job atomicamente. Falhas nao sao publicadas nem repetidas em loop."""
    claimed = db.rpc("hype_claim_mod_protection_job", {}).execute().data or []
    if not claimed:
        return False
    job = claimed[0]
    job_id = job["job_id"]
    try:
        sha = process_job(db, job, command)
        (db.table(JOBS).update({
            "status": "completed", "candidate_sha256": sha, "finished_at": _now()
        }).eq("id", job_id).eq("status", "running").execute())
    except Exception as exc:
        # Evita mensagens de terceiros/stack traces nos registros administrativos.
        reason = str(exc)[:200] if isinstance(exc, (ProtectionError, InvalidJar)) else "Falha na protecao ou validacao."
        (db.table(JOBS).update({
            "status": "failed", "failure_reason": reason, "finished_at": _now()
        }).eq("id", job_id).eq("status", "running").execute())
    return True


def main():
    if os.environ.get("HYPE_MOD_PROTECTION_WORKER_ENABLED", "") != "1":
        raise SystemExit("Worker desativado por padrao.")
    command = _protector_argv()  # nao retira jobs sem ofuscador configurado
    url = os.environ.get("HYPE_WORKER_SUPABASE_URL", "").strip()
    key = os.environ.get("HYPE_WORKER_SUPABASE_SERVICE_KEY", "").strip()
    if not url.startswith("https://") or not key:
        raise SystemExit("Configure credenciais restritas no ambiente isolado.")
    from supabase import create_client

    db = create_client(url, key)
    work_once(db, command)


if __name__ == "__main__":
    main()
