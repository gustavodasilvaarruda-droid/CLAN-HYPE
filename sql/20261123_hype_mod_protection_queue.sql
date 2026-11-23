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
