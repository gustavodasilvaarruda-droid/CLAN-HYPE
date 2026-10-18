-- HYPE MODS 2.0 - MIGRAÇÃO INCREMENTAL E SEGURA (2026-10-18)
-- Execute UMA VEZ no SQL Editor do Supabase, após backup/snapshot.
-- Não recria nem apaga dados existentes; não altera o sistema Breed.
-- Os três módulos iniciais ficam em MANUTENÇÃO por segurança.
-- Requer backend Flask usando uma chave Supabase PRIVADA (service role/secret);
-- nunca inclua a chave de serviço no mod .jar ou no front-end.
--
-- Segurança: as tabelas serão acessíveis APENAS ao backend com chave
-- service_role/secret. Anon e authenticated não devem ler nem editar diretamente.
-- IMPORTANTE: confirme antes que SUPABASE_KEY do Render é uma chave de serviço.
-- A migração não modifica policies de outros sistemas nem tabelas de Breed.

BEGIN;

CREATE TABLE IF NOT EXISTS public.hype_modulos (
    codigo text PRIMARY KEY,
    nome text NOT NULL,
    descricao text DEFAULT '',
    icone text DEFAULT 'blocks',
    categoria text DEFAULT 'ferramentas',
    versao text DEFAULT '',
    estado text NOT NULL DEFAULT 'manutencao',
    visivel boolean NOT NULL DEFAULT true,
    ordem integer NOT NULL DEFAULT 100
);

ALTER TABLE public.hype_modulos
  ADD COLUMN IF NOT EXISTS nome text,
  ADD COLUMN IF NOT EXISTS descricao text DEFAULT '',
  ADD COLUMN IF NOT EXISTS icone text DEFAULT 'blocks',
  ADD COLUMN IF NOT EXISTS categoria text DEFAULT 'ferramentas',
  ADD COLUMN IF NOT EXISTS versao text DEFAULT '',
  ADD COLUMN IF NOT EXISTS estado text DEFAULT 'manutencao',
  ADD COLUMN IF NOT EXISTS visivel boolean DEFAULT true,
  ADD COLUMN IF NOT EXISTS ordem integer DEFAULT 100;

CREATE TABLE IF NOT EXISTS public.hype_modulos_grupos (
    modulo_codigo text NOT NULL,
    cargo_id text NOT NULL,
    PRIMARY KEY (modulo_codigo, cargo_id)
);

ALTER TABLE public.hype_modulos_grupos
  ADD COLUMN IF NOT EXISTS modulo_codigo text,
  ADD COLUMN IF NOT EXISTS cargo_id text;

CREATE TABLE IF NOT EXISTS public.hype_modulos_acessos (
    modulo_codigo text NOT NULL,
    usuario_email text NOT NULL,
    decisao text NOT NULL,
    inicio_em timestamptz NOT NULL DEFAULT now(),
    fim_em timestamptz,
    PRIMARY KEY (modulo_codigo, usuario_email)
);

ALTER TABLE public.hype_modulos_acessos
  ADD COLUMN IF NOT EXISTS modulo_codigo text,
  ADD COLUMN IF NOT EXISTS usuario_email text,
  ADD COLUMN IF NOT EXISTS decisao text,
  ADD COLUMN IF NOT EXISTS inicio_em timestamptz DEFAULT now(),
  ADD COLUMN IF NOT EXISTS fim_em timestamptz;

-- Evita substituição ambígua de permissões.
-- Se existirem duplicações antigas, a transação será revertida sem apagar linhas.
CREATE UNIQUE INDEX IF NOT EXISTS hype_modulos_grupos_modulo_cargo_uidx
    ON public.hype_modulos_grupos (modulo_codigo, cargo_id);
CREATE UNIQUE INDEX IF NOT EXISTS hype_modulos_acessos_modulo_usuario_uidx
    ON public.hype_modulos_acessos (modulo_codigo, usuario_email);
CREATE INDEX IF NOT EXISTS hype_modulos_acessos_fim_idx
    ON public.hype_modulos_acessos (fim_em);

-- O mod Minecraft usa a API Flask com token, NUNCA o Supabase diretamente.
-- RLS + revogação de privilégios protegem permissões e e-mails.
ALTER TABLE public.hype_modulos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hype_modulos_grupos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hype_modulos_acessos ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.hype_modulos FROM anon, authenticated;
REVOKE ALL ON TABLE public.hype_modulos_grupos FROM anon, authenticated;
REVOKE ALL ON TABLE public.hype_modulos_acessos FROM anon, authenticated;

INSERT INTO public.hype_modulos
    (codigo, nome, descricao, icone, categoria, versao, estado, visivel, ordem)
VALUES
    ('hype_battle_ai', 'HYPE Battle AI', 'Assistente competitivo para batalhas Cobblemon.', 'brain-circuit', 'batalhas', '2.0', 'manutencao', true, 10),
    ('hype_breed_tools', 'HYPE Breed Tools', 'Ferramentas de apoio à criação de Pokémon.', 'egg', 'breed', '2.0', 'manutencao', true, 20),
    ('hype_trainer_ai', 'HYPE Trainer AI', 'Treinadores NPC e laboratório de batalhas.', 'swords', 'treinadores', '2.0', 'manutencao', true, 30)
ON CONFLICT (codigo) DO NOTHING;

COMMIT;

-- VALIDAÇÃO OPCIONAL (somente leitura):
-- SELECT codigo, nome, estado FROM public.hype_modulos ORDER BY ordem;
-- SELECT modulo_codigo, cargo_id FROM public.hype_modulos_grupos;
-- SELECT modulo_codigo, usuario_email, decisao, inicio_em, fim_em
-- FROM public.hype_modulos_acessos;
