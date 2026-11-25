-- HYPE 5.0: claim only jobs whose original draft still exists and matches.
-- Apply in homologation first; this DOES NOT delete/modify queued historical jobs,
-- publish mods, change storage, or enable a worker.
-- The migration may be applied on a UUID live schema; text draft_id is legacy-compatible.
create or replace function public.hype_claim_mod_protection_job()
returns table(job_id uuid, job_draft_id text, job_sha256 text)
language sql security invoker set search_path = public as $$
  with selected as (
    select j.id from public.hype_mod_protection_jobs j
    join public.hype_mod_release_drafts d
      on d.id::text = j.draft_id
     and d.module_id = j.module_id
     and d.sha256 = j.original_sha256
     and d.status in ('aguardando_protecao', 'em_teste')
     and not (coalesce(d.meta, '{}'::jsonb) ? 'protected')
    where j.status = 'queued'
    order by j.requested_at, j.id
    limit 1 for update of j skip locked
  ), claimed as (
    update public.hype_mod_protection_jobs j
    set status = 'running', started_at = now(), failure_reason = null
    from selected s where j.id = s.id
    returning j.id, j.draft_id, j.original_sha256
  )
  select id, draft_id, original_sha256 from claimed;
$$;
revoke all on function public.hype_claim_mod_protection_job() from public, anon, authenticated;
grant execute on function public.hype_claim_mod_protection_job() to service_role;
