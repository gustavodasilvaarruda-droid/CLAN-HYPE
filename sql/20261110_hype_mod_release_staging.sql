-- EXECUTAR PRIMEIRO EM HOMOLOGACAO; NAO EXECUTADO AUTOMATICAMENTE.
-- Armazena SOMENTE rascunhos privados de JARs originais.
create table if not exists public.hype_mod_release_drafts (
  id bigint generated always as identity primary key,
  module_id text not null check (module_id ~ '^[a-z][a-z0-9_-]{1,100}$'),
  version text not null check (char_length(version) between 1 and 120),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 10485760),
  original_filename text not null,
  storage_path text not null unique,
  uploaded_by text not null,
  status text not null default 'aguardando_protecao'
    check (status in ('aguardando_protecao','em_teste','rejeitado','pronto_para_aprovacao')),
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists hype_mod_release_drafts_created_idx
  on public.hype_mod_release_drafts (created_at desc);
alter table public.hype_mod_release_drafts enable row level security;
revoke all on public.hype_mod_release_drafts from anon, authenticated;
grant select, insert, update, delete on public.hype_mod_release_drafts to service_role;
grant usage, select on sequence public.hype_mod_release_drafts_id_seq to service_role;
-- Original JARs never belong in a public bucket.
insert into storage.buckets (id, name, public, file_size_limit)
values ('hype-mod-originals', 'hype-mod-originals', false, 10485760)
on conflict (id) do nothing;
do $$
begin
  if exists (select 1 from storage.buckets where id = 'hype-mod-originals' and public is true) then
    raise exception 'Bucket hype-mod-originals precisa ser PRIVADO';
  end if;
end;
$$;
-- Do not create anon/authenticated SELECT policies for storage.objects.
