-- HYPE Client release catalog. Apply in staging first, then production.
-- The live hype_mod_release_drafts.id is UUID (not bigint).
-- This private catalog is also required for safe deletion checks in the admin panel.
-- Private objects are served only by the Flask application after approval.
create table if not exists public.hype_mod_published_releases (
  release bigint primary key check (release between 1 and 999999999),
  draft_id uuid not null unique references public.hype_mod_release_drafts(id) on delete restrict,
  module_id text not null default 'hypeclient' check (module_id = 'hypeclient'),
  version text not null,
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  size_bytes bigint not null check (size_bytes between 1000 and 10485760),
  storage_path text not null unique,
  manifest text not null check (octet_length(manifest) <= 16384),
  status text not null default 'published' check (status in ('published', 'disabled')),
  published_by text not null,
  published_at timestamptz not null default now()
);
create index if not exists hype_mod_published_status_idx
  on public.hype_mod_published_releases (status, release desc);
alter table public.hype_mod_published_releases enable row level security;
revoke all on public.hype_mod_published_releases from anon, authenticated;
grant select, insert, update on public.hype_mod_published_releases to service_role;
-- No public bucket and no RLS read policies for original JAR files.
