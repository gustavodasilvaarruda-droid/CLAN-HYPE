-- PILOTO: executar apenas apos revisao, primeiro em homologacao.
-- A fila nao distribui nenhum JAR e nao armazena chaves de assinatura.
-- draft_id e texto porque instalacoes existentes podem usar BIGINT ou UUID.
create table if not exists public.hype_mod_protection_jobs (
  id uuid primary key default gen_random_uuid(),
  draft_id text not null unique,
  original_sha256 text not null check (original_sha256 ~ '^[0-9a-f]{64}$'),
  module_id text not null check (module_id in
    ('hypeclient','hype_pokedex','hype_breed_calculator','hype_battlefield','hype_battle_ai')),
  status text not null default 'queued'
    check (status in ('queued','running','completed','failed')),
  requested_by text not null,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  candidate_sha256 text check (candidate_sha256 is null or candidate_sha256 ~ '^[0-9a-f]{64}$'),
  failure_reason text
);
create index if not exists hype_mod_protection_jobs_fifo_idx
  on public.hype_mod_protection_jobs (requested_at)
  where status = 'queued';
alter table public.hype_mod_protection_jobs enable row level security;
revoke all on public.hype_mod_protection_jobs from public, anon, authenticated;
grant select, insert, update on public.hype_mod_protection_jobs to service_role;

-- Atomico: dois workers nao retiram o mesmo trabalho.
create or replace function public.hype_claim_mod_protection_job()
returns table(job_id uuid, job_draft_id text, job_sha256 text)
language sql security invoker set search_path = public as $$
  with selected as (
    select j.id from public.hype_mod_protection_jobs j
    where j.status = 'queued'
    order by j.requested_at, j.id
    limit 1 for update skip locked
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


-- Finaliza o candidato SOMENTE se o registro ainda estiver elegivel,
-- sem candidato protegido e com o mesmo SHA do momento do agendamento.
-- O lock da linha do draft evita sobrescrever uploads manuais concorrentes.
create or replace function public.hype_finish_mod_protection_draft(
  p_draft_id text,
  p_sha256 text,
  p_job_id uuid,
  p_candidate jsonb
) returns boolean
language plpgsql security invoker set search_path = public as $$
declare
  altered integer;
begin
  if p_candidate is null
    or p_candidate->'protected'->>'sha256' !~ '^[0-9a-f]{64}$'
    or p_candidate->'automatic_review'->>'status' is distinct from 'passed'
    or p_candidate->'automatic_review'->>'candidate_sha256'
       is distinct from p_candidate->'protected'->>'sha256'
    or p_candidate->'protected'->>'sha256' = p_sha256
  then
    return false;
  end if;

  update public.hype_mod_release_drafts d
  set status = 'em_teste',
      meta = (coalesce(d.meta, '{}'::jsonb) - 'manual_review' - 'automatic_review')
             || p_candidate
  where d.id::text = p_draft_id
    and d.sha256 = p_sha256
    and d.status in ('aguardando_protecao', 'em_teste')
    and not (coalesce(d.meta, '{}'::jsonb) ? 'protected')
    and exists (
      select 1 from public.hype_mod_protection_jobs j
      where j.id = p_job_id
        and j.draft_id = p_draft_id
        and j.original_sha256 = p_sha256
        and j.module_id = d.module_id
        and j.status = 'running'
    );
  get diagnostics altered = row_count;
  return altered = 1;
end;
$$;
revoke all on function public.hype_finish_mod_protection_draft(text,text,uuid,jsonb)
  from public, anon, authenticated;
grant execute on function public.hype_finish_mod_protection_draft(text,text,uuid,jsonb)
  to service_role;
