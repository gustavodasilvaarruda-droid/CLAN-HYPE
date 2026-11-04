-- HYPE Arena: armazenamento e confirmação transacional dos confrontos.
-- APLICAR primeiro em um ambiente de teste e revisar permissões antes da produção.
-- As funções são executáveis apenas pela role de serviço do backend Flask.
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
REVOKE ALL ON public.hype_batalha_participantes FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.hype_batalha_participantes TO service_role;

CREATE OR REPLACE FUNCTION public.hype_batalha_confirmar_pronto(
    p_partida_id BIGINT, p_usuario_email TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $$
DECLARE
    m RECORD;
BEGIN
    SELECT p.*, t.status_torneio AS torneio_status
      INTO m
      FROM public.partidas_torneio p
      JOIN public.torneios t ON t.id = p.torneio_id
     WHERE p.id = p_partida_id
     FOR UPDATE OF p;
    IF NOT FOUND OR m.torneio_status <> 'em_andamento' OR m.status = 'finalizada'
       OR m.jogador1_email IS NULL OR m.jogador2_email IS NULL
       OR m.jogador1_email = m.jogador2_email
       OR p_usuario_email NOT IN (m.jogador1_email, m.jogador2_email) THEN
        RETURN FALSE;
    END IF;
    INSERT INTO public.hype_batalha_participantes
        (partida_id, usuario_email, pronto, atualizado_em)
    VALUES (p_partida_id, p_usuario_email, TRUE, now())
    ON CONFLICT (partida_id, usuario_email) DO UPDATE
        SET pronto = TRUE, atualizado_em = now();
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.hype_batalha_confirmar_resultado(
    p_partida_id BIGINT, p_usuario_email TEXT, p_vencedor_email TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $$
DECLARE
    m RECORD;
    r1 RECORD;
    r2 RECORD;
    v_nick TEXT;
BEGIN
    -- Trava a mesma partida: dois envios concorrentes não geram dois resultados.
    SELECT p.*, t.status_torneio AS torneio_status
      INTO m
      FROM public.partidas_torneio p
      JOIN public.torneios t ON t.id = p.torneio_id
     WHERE p.id = p_partida_id
     FOR UPDATE OF p;
    IF NOT FOUND OR m.torneio_status <> 'em_andamento'
       OR m.status = 'finalizada'
       OR m.jogador1_email IS NULL OR m.jogador2_email IS NULL
       OR m.jogador1_email = m.jogador2_email
       OR p_usuario_email NOT IN (m.jogador1_email, m.jogador2_email)
       OR p_vencedor_email NOT IN (m.jogador1_email, m.jogador2_email) THEN
        RETURN jsonb_build_object('status', 'bloqueado');
    END IF;

    SELECT * INTO r1 FROM public.hype_batalha_participantes
     WHERE partida_id = p_partida_id AND usuario_email = m.jogador1_email;
    SELECT * INTO r2 FROM public.hype_batalha_participantes
     WHERE partida_id = p_partida_id AND usuario_email = m.jogador2_email;
    IF NOT COALESCE(r1.pronto, FALSE) OR NOT COALESCE(r2.pronto, FALSE) THEN
        RETURN jsonb_build_object('status', 'aguardando_pronto');
    END IF;

    UPDATE public.hype_batalha_participantes
       SET vencedor_reportado_email = p_vencedor_email, atualizado_em = now()
     WHERE partida_id = p_partida_id AND usuario_email = p_usuario_email;
    SELECT * INTO r1 FROM public.hype_batalha_participantes
     WHERE partida_id = p_partida_id AND usuario_email = m.jogador1_email;
    SELECT * INTO r2 FROM public.hype_batalha_participantes
     WHERE partida_id = p_partida_id AND usuario_email = m.jogador2_email;

    IF r1.vencedor_reportado_email IS NOT NULL
       AND r1.vencedor_reportado_email = r2.vencedor_reportado_email THEN
        IF r1.vencedor_reportado_email = m.jogador1_email THEN
            v_nick := m.jogador1_nick;
        ELSE
            v_nick := m.jogador2_nick;
        END IF;
        UPDATE public.partidas_torneio SET
            vencedor_email = r1.vencedor_reportado_email,
            vencedor_nick = v_nick, status = 'finalizada', finalizada_em = now()
         WHERE id = p_partida_id;
        RETURN jsonb_build_object('status', 'finalizada',
                                  'vencedor_email', r1.vencedor_reportado_email,
                                  'vencedor_nick', v_nick);
    END IF;
    IF r1.vencedor_reportado_email IS NOT NULL
       AND r2.vencedor_reportado_email IS NOT NULL THEN
        RETURN jsonb_build_object('status', 'divergencia');
    END IF;
    RETURN jsonb_build_object('status', 'aguardando_oponente');
END;
$$;
REVOKE ALL ON FUNCTION public.hype_batalha_confirmar_pronto(BIGINT, TEXT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.hype_batalha_confirmar_resultado(BIGINT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.hype_batalha_confirmar_pronto(BIGINT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.hype_batalha_confirmar_resultado(BIGINT, TEXT, TEXT)
    TO service_role;
