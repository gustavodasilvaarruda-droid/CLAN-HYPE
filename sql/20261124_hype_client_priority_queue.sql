-- Central de Publicacoes HYPE: processar o Client antes dos mods dependentes.
-- Seguro para aplicar com jobs em fila; nao processa arquivos nem os publica.
-- Mantem o processamento atomico (FOR UPDATE SKIP LOCKED).
CREATE OR REPLACE FUNCTION public.hype_claim_mod_protection_job()
RETURNS TABLE(job_id uuid, job_draft_id text, job_sha256 text)
LANGUAGE sql
SECURITY INVOKER
SET search_path TO 'public'
AS $function$
  WITH selected AS (
    SELECT j.id
    FROM public.hype_mod_protection_jobs AS j
    WHERE j.status = 'queued'
    ORDER BY
      CASE WHEN j.module_id = 'hypeclient' THEN 0 ELSE 1 END,
      j.requested_at,
      j.id
    LIMIT 1 FOR UPDATE SKIP LOCKED
  ), claimed AS (
    UPDATE public.hype_mod_protection_jobs AS j
    SET status = 'running', started_at = now(), failure_reason = null
    FROM selected AS s WHERE j.id = s.id
    RETURNING j.id, j.draft_id, j.original_sha256
  )
  SELECT id, draft_id, original_sha256 FROM claimed;
$function$;

-- Supabase RPC deve continuar acessivel apenas ao worker privilegiado.
REVOKE ALL ON FUNCTION public.hype_claim_mod_protection_job() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.hype_claim_mod_protection_job() TO service_role;
