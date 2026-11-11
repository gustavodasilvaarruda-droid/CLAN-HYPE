-- Arena HYPE: moderação privada, pagamento e inscrição oficial manual.
-- Esta migração NÃO aprova times nem inscreve ninguém automaticamente.
ALTER TABLE public.arena_torneio_equipes
  ADD COLUMN IF NOT EXISTS revisado_por text,
  ADD COLUMN IF NOT EXISTS revisado_em timestamptz,
  ADD COLUMN IF NOT EXISTS motivo_revisao text;

CREATE TABLE IF NOT EXISTS public.arena_torneio_inscricoes_controle (
  torneio_id bigint NOT NULL REFERENCES public.torneios(id) ON DELETE CASCADE,
  usuario_email text NOT NULL REFERENCES public.usuarios_clan(email) ON UPDATE CASCADE ON DELETE CASCADE,
  pagamento_status text NOT NULL DEFAULT 'pendente'
    CHECK (pagamento_status IN ('pendente', 'confirmado', 'dispensado')),
  pagamento_por text,
  pagamento_em timestamptz,
  inscricao_confirmada_por text,
  inscricao_confirmada_em timestamptz,
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(torneio_id, usuario_email)
);

CREATE TABLE IF NOT EXISTS public.arena_torneio_inscricoes_controle_historico (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  torneio_id bigint NOT NULL,
  usuario_email text NOT NULL,
  operacao text NOT NULL,
  registro jsonb NOT NULL,
  criado_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_arena_revisao_historico
  ON public.arena_torneio_inscricoes_controle_historico(torneio_id, usuario_email, criado_em);

ALTER TABLE public.arena_torneio_inscricoes_controle ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.arena_torneio_inscricoes_controle_historico ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.arena_torneio_inscricoes_controle FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.arena_torneio_inscricoes_controle_historico FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.arena_torneio_inscricoes_controle TO service_role;
GRANT ALL ON public.arena_torneio_inscricoes_controle_historico TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.arena_torneio_inscricoes_controle_historico_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.registrar_historico_controle_arena()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
BEGIN
  INSERT INTO public.arena_torneio_inscricoes_controle_historico
    (torneio_id, usuario_email, operacao, registro)
  VALUES (NEW.torneio_id, NEW.usuario_email, TG_OP, to_jsonb(NEW));
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_historico_controle_arena ON public.arena_torneio_inscricoes_controle;
CREATE TRIGGER trg_historico_controle_arena
  AFTER INSERT OR UPDATE ON public.arena_torneio_inscricoes_controle
  FOR EACH ROW EXECUTE FUNCTION public.registrar_historico_controle_arena();

REVOKE EXECUTE ON FUNCTION public.registrar_historico_controle_arena() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_historico_controle_arena() TO service_role;

-- Inscrição e controle são gravados juntos numa transação; a linha do torneio
-- é bloqueada para evitar aceitar duas pessoas na última vaga.
CREATE OR REPLACE FUNCTION public.hype_arena_confirmar_inscricao(
  p_torneio_id bigint,
  p_usuario_email text,
  p_admin_email text
) RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE
  v_torneio public.torneios%ROWTYPE;
  v_pagamento text;
  v_nick text;
  v_total integer;
  v_enviados integer;
  v_nao_aprovados integer;
BEGIN
  IF nullif(btrim(p_admin_email), '') IS NULL
     OR nullif(btrim(p_usuario_email), '') IS NULL THEN
    RAISE EXCEPTION 'Administrador e jogador são obrigatórios.';
  END IF;
  SELECT * INTO v_torneio
    FROM public.torneios WHERE id = p_torneio_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Torneio não encontrado.'; END IF;
  IF NOT v_torneio.publicado OR NOT v_torneio.inscricoes_abertas
     OR v_torneio.status_torneio <> 'inscricoes' THEN
    RAISE EXCEPTION 'Inscrições do torneio estão fechadas.';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.inscricoes_torneio
    WHERE torneio_id = p_torneio_id AND usuario_email = p_usuario_email
  ) THEN RETURN 'ja_inscrito'; END IF;

  SELECT pagamento_status INTO v_pagamento
    FROM public.arena_torneio_inscricoes_controle
    WHERE torneio_id = p_torneio_id AND usuario_email = p_usuario_email
    FOR UPDATE;
  IF v_pagamento IS NULL OR v_pagamento NOT IN ('confirmado', 'dispensado') THEN
    RAISE EXCEPTION 'Confirme o pagamento ou dispense a cobrança antes da inscrição.';
  END IF;

  PERFORM 1 FROM public.arena_torneio_equipes
    WHERE torneio_id = p_torneio_id AND usuario_email = p_usuario_email FOR UPDATE;
  SELECT count(*)::integer,
         count(*) FILTER (WHERE status <> 'aprovado')::integer
    INTO v_enviados, v_nao_aprovados
    FROM public.arena_torneio_equipes
    WHERE torneio_id = p_torneio_id AND usuario_email = p_usuario_email;
  IF v_enviados = 0 OR v_enviados > 3 OR v_nao_aprovados <> 0 THEN
    RAISE EXCEPTION 'Todos os times enviados precisam estar aprovados.';
  END IF;
  SELECT nick_jogo INTO v_nick FROM public.usuarios_clan
    WHERE email = p_usuario_email;
  IF v_nick IS NULL OR btrim(v_nick) = '' THEN
    RAISE EXCEPTION 'Jogador não encontrado.';
  END IF;
  SELECT count(*)::integer INTO v_total
    FROM public.inscricoes_torneio WHERE torneio_id = p_torneio_id;
  IF v_torneio.limite_participantes IS NOT NULL
    AND v_total >= v_torneio.limite_participantes THEN
    RAISE EXCEPTION 'As vagas deste torneio estão esgotadas.';
  END IF;

  INSERT INTO public.inscricoes_torneio (torneio_id, usuario_email, nick_jogo)
  VALUES (p_torneio_id, p_usuario_email, v_nick)
  ON CONFLICT ON CONSTRAINT inscricao_torneio_unica DO NOTHING;
  IF NOT FOUND THEN RETURN 'ja_inscrito'; END IF;
  UPDATE public.arena_torneio_inscricoes_controle
    SET inscricao_confirmada_por = p_admin_email,
        inscricao_confirmada_em = now(),
        atualizado_em = now()
    WHERE torneio_id = p_torneio_id AND usuario_email = p_usuario_email;
  RETURN 'inscricao_confirmada';
END;
$$;
REVOKE EXECUTE ON FUNCTION public.hype_arena_confirmar_inscricao(bigint, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.hype_arena_confirmar_inscricao(bigint, text, text)
  TO service_role;
