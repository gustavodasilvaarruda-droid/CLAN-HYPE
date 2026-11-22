-- Registro PRIVADO de releases dos quatro mods restritos (piloto).
-- Aplicar primeiro em homologacao; nao executado automaticamente.
-- Nao altera a tabela/manifesto publico do HYPE Client.
create table if not exists public.hype_mod_restricted_releases (
    id uuid primary key default gen_random_uuid(),
    module_id text not null check (module_id in (
        'hype_pokedex', 'hype_breed_calculator', 'hype_battlefield', 'hype_battle_ai'
    )),
    release bigint not null check (release between 1 and 999999999),
    draft_id uuid not null unique references public.hype_mod_release_drafts(id) on delete restrict,
    version text not null check (length(version) between 1 and 120),
    sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
    size_bytes bigint not null check (size_bytes between 1000 and 10485760),
    storage_path text not null unique,
    -- Manifesto Ed25519 assinado FORA do servidor; chave privada nunca no site.
    manifest text not null check (octet_length(manifest) between 50 and 16384),
    status text not null default 'disabled' check (status in ('published','disabled')),
    published_by text not null,
    published_at timestamptz not null default now(),
    unique (module_id, release),
    unique (module_id, sha256)
);
create index if not exists hype_mod_restricted_latest_idx
    on public.hype_mod_restricted_releases(module_id, status, release desc);
alter table public.hype_mod_restricted_releases enable row level security;
revoke all on public.hype_mod_restricted_releases from public, anon, authenticated;
grant select, insert, update on public.hype_mod_restricted_releases to service_role;
-- SEM policies de leitura publica. Storage original/protegido permanece privado.
-- Esta migracao nao insere releases e NAO ativa download algum.
