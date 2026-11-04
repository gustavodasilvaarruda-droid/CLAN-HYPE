-- HYPE Arena: Sala de Batalha. Executar em ambiente de teste antes de produção.
-- As ações desta tabela passam somente pelo backend Flask. Usar SUPABASE_KEY
-- server-side com permissão de service_role e nunca expor a chave no frontend.
CREATE TABLE IF NOT EXISTS public.hype_batalha_participantes (
    partida_id BIGINT NOT NULL REFERENCES public.partidas_torneio(id) ON DELETE CASCADE,
    usuario_email TEXT NOT NULL,
    pronto BOOLEAN NOT NULL DEFAULT FALSE,
    vencedor_reportado_email TEXT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (partida_id, usuario_email)
);
CREATE INDEX IF NOT EXISTS idx_hype_batalha_participantes_partida
    ON public.hype_batalha_participantes (partida_id);
ALTER TABLE public.hype_batalha_participantes ENABLE ROW LEVEL SECURITY;
-- Sem políticas públicas: não permitir confirmações diretamente pelo navegador.
-- Os acessos são autorizados no backend e usam a role de serviço.
