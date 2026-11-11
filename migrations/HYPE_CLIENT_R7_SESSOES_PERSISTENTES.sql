-- HYPE Client R7: sessoes persistentes e revogaveis.
-- Execute SOMENTE este arquivo no SQL Editor de seu Supabase existente.
-- Migracao aditiva: preserva contas, sessoes do site e pedidos.
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.hype_client_sessoes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_email TEXT NOT NULL
        REFERENCES public.usuarios_clan(email) ON UPDATE CASCADE ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_uso_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_em TIMESTAMPTZ NOT NULL,
    revogado_em TIMESTAMPTZ,
    CONSTRAINT hype_client_sessoes_hash_check
        CHECK (length(token_hash) = 64 AND token_hash ~ '^[0-9a-f]+$')
);
CREATE INDEX IF NOT EXISTS idx_hype_client_sessoes_usuario
    ON public.hype_client_sessoes(usuario_email, revogado_em);
CREATE INDEX IF NOT EXISTS idx_hype_client_sessoes_validade
    ON public.hype_client_sessoes(expira_em)
    WHERE revogado_em IS NULL;

ALTER TABLE public.hype_client_sessoes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "hype_client_sessoes_bloqueio_publico"
    ON public.hype_client_sessoes;
CREATE POLICY "hype_client_sessoes_bloqueio_publico"
    ON public.hype_client_sessoes
    AS RESTRICTIVE FOR ALL TO anon, authenticated
    USING (FALSE) WITH CHECK (FALSE);

-- Reforca que so o backend de servico deve acessar estas credenciais.
REVOKE ALL ON public.hype_client_sessoes FROM anon, authenticated;

COMMIT;
NOTIFY pgrst, 'reload schema';
