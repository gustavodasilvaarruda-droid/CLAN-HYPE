-- HYPE Arena: cria a próxima rodada automaticamente ao finalizar um confronto.
-- O campeão, ranking, prêmios e pagamentos continuam sob controle administrativo.
-- A função dispara APENAS em updates futuros de partidas (não reprocessa torneios antigos).
-- Requer índice único já existente: partida_torneio_posicao_unica (torneio_id, rodada, ordem).
CREATE OR REPLACE FUNCTION public.hype_batalha_avancar_rodada_automaticamente()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_status_torneio TEXT;
    v_total INTEGER;
    v_concluidas INTEGER;
    v_vencedores_distintos INTEGER;
BEGIN
    -- Nenhuma ação em partidas já encerradas, alterações de metadados ou BYEs.
    IF TG_OP <> 'UPDATE'
       OR NEW.status IS DISTINCT FROM 'finalizada'
       OR OLD.status = 'finalizada'
       OR NEW.vencedor_email IS NULL
       OR NEW.jogador2_email IS NULL
       OR NEW.vencedor_email NOT IN (NEW.jogador1_email, NEW.jogador2_email) THEN
        RETURN NEW;
    END IF;

    -- Serializa encerramentos concorrentes de partidas do mesmo torneio.
    SELECT t.status_torneio INTO v_status_torneio
      FROM public.torneios t
     WHERE t.id = NEW.torneio_id
     FOR UPDATE;
    IF v_status_torneio IS DISTINCT FROM 'em_andamento' THEN
        RETURN NEW;
    END IF;

    -- Nunca recria uma rodada seguinte (nem sobrescreve chave definida pelo admin).
    IF EXISTS (
        SELECT 1 FROM public.partidas_torneio p
         WHERE p.torneio_id = NEW.torneio_id AND p.rodada > NEW.rodada
    ) THEN
        RETURN NEW;
    END IF;

    SELECT count(*)::INTEGER,
           count(*) FILTER (
               WHERE p.status = 'finalizada'
                 AND p.vencedor_email IS NOT NULL
                 AND p.vencedor_email IN (p.jogador1_email, p.jogador2_email)
           )::INTEGER,
           count(DISTINCT p.vencedor_email)::INTEGER
      INTO v_total, v_concluidas, v_vencedores_distintos
      FROM public.partidas_torneio p
     WHERE p.torneio_id = NEW.torneio_id
       AND p.rodada = NEW.rodada;

    -- A final possui um só vencedor: não disparar premiações ou ranking.
    -- Um duelo pendente, vencedor inválido ou dados inconsistentes bloqueiam avanço.
    IF v_total < 2 OR v_total % 2 <> 0
       OR v_concluidas <> v_total
       OR v_vencedores_distintos <> v_total THEN
        RETURN NEW;
    END IF;

    WITH ordenados AS (
        SELECT row_number() OVER (ORDER BY p.ordem, p.id) AS pos,
               p.vencedor_email, p.vencedor_nick
          FROM public.partidas_torneio p
         WHERE p.torneio_id = NEW.torneio_id
           AND p.rodada = NEW.rodada
    )
    INSERT INTO public.partidas_torneio (
        torneio_id, rodada, ordem,
        jogador1_email, jogador1_nick, jogador2_email, jogador2_nick, status
    )
    SELECT NEW.torneio_id,
           NEW.rodada + 1,
           ((a.pos + 1) / 2)::INTEGER,
           a.vencedor_email, a.vencedor_nick,
           b.vencedor_email, b.vencedor_nick,
           'pendente'
      FROM ordenados a
      JOIN ordenados b ON b.pos = a.pos + 1
     WHERE a.pos % 2 = 1
    ON CONFLICT (torneio_id, rodada, ordem) DO NOTHING;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.hype_batalha_avancar_rodada_automaticamente()
  FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_hype_batalha_avanco_automatico
  ON public.partidas_torneio;

CREATE TRIGGER trg_hype_batalha_avanco_automatico
AFTER UPDATE OF status, vencedor_email ON public.partidas_torneio
FOR EACH ROW
WHEN (NEW.status = 'finalizada' AND OLD.status IS DISTINCT FROM 'finalizada')
EXECUTE FUNCTION public.hype_batalha_avancar_rodada_automaticamente();
