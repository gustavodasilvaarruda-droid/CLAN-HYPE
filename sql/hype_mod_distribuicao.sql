-- HYPE - Artefatos finais para distribuição AUTENTICADA (não são originais).
-- Executar no SQL Editor do Supabase, com o papel apropriado.
create table if not exists public.hype_mod_distribuicao (
  id uuid primary key default gen_random_uuid(),
  module_id text not null check (module_id ~ '^[a-z0-9_]{3,70}$'),
  version text not null check (char_length(version) between 1 and 120),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 10485760),
  storage_path text not null unique,
  status text not null default 'rascunho' check (status in ('rascunho','publicado','suspenso')),
  uploaded_by text not null,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  unique(module_id, sha256)
);
create index if not exists hype_mod_distribuicao_ativas
  on public.hype_mod_distribuicao (module_id, published_at desc)
  where status='publicado';
alter table public.hype_mod_distribuicao enable row level security;
revoke all on table public.hype_mod_distribuicao from anon, authenticated;

-- Bucket privado: a aplicação Flask lê/entrega os bytes somente após autorização.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('hype-mod-distribuicao', 'hype-mod-distribuicao', false,
        10485760, array['application/java-archive'])
on conflict (id) do nothing;
-- Se o bucket já existia, conferir manualmente que public=false.
-- Acesso de escrita e leitura é via chave de serviço mantida SOMENTE no Render.
-- NÃO criar política de acesso público em storage.objects.
