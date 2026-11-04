-- HYPE Arena: encerramento transacional e pontuação idempotente.
-- Este gatilho NÃO reprocessa torneios antigos, não movimenta moedas
-- e nunca marca campeão de confronto BYE/sem adversário.
-- Para reverter ou revisar uma decisão administrativa, use procedimento próprio.

CREATE OR REPLACE FUNCTION public.hype_batalha_encerrar_torneio_automaticamente()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_torneio RECORD;
    v_rodada_max INTEGER;
    v_total_rodada INTEGER;
    v_pendentes_anteriores INTEGER;
    v_inscritos INTEGER;
    v_vencedores_anteriores INTEGER;
    v_vencedor1 TEXT;
    v_vencedor2 TEXT;
    v_vice_email TEXT;
    v_vice_nick TEXT;
BEGIN
    -- Executar somente na PRIMEIRA transição pendente -> finalizada.
    IF TG_OP <> 'UPDATE'
       OR NEW.status IS DISTINCT FROM 'finalizada'
       OR OLD.status = 'finalizada'
       OR NEW.vencedor_email IS NULL
       OR NEW.jogador1_email IS NULL
       OR NEW.jogador2_email IS NULL
       OR NEW.jogador1_email = NEW.jogador2_email
       OR NEW.vencedor_email NOT IN (NEW.jogador1_email, NEW.jogador2_email) THEN
        RETURN NEW;
    END IF;

    -- Serializar com o gatilho que cria próximas rodadas e com outros resultados.
    SELECT * INTO v_torneio
      FROM public.torneios t
     WHERE t.id = NEW.torneio_id
     FOR UPDATE;

    IF NOT FOUND OR v_torneio.status_torneio IS DISTINCT FROM 'em_andamento' THEN
        RETURN NEW;
    END IF;

    SELECT max(p.rodada) INTO v_rodada_max
      FROM public.partidas_torneio p
     WHERE p.torneio_id = NEW.torneio_id;

    SELECT count(*)::INTEGER INTO v_total_rodada
      FROM public.partidas_torneio p
     WHERE p.torneio_id = NEW.torneio_id
       AND p.rodada = NEW.rodada;

    -- Final = UMA partida na ÚLTIMA rodada, sem confrontos anteriores pendentes.
    IF NEW.rodada IS DISTINCT FROM v_rodada_max OR v_total_rodada <> 1 THEN
        RETURN NEW;
    END IF;

    SELECT count(*)::INTEGER INTO v_pendentes_anteriores
      FROM public.partidas_torneio p
     WHERE p.torneio_id = NEW.torneio_id
       AND p.rodada < NEW.rodada
       AND (p.status <> 'finalizada' OR p.vencedor_email IS NULL
            OR p.vencedor_email NOT IN (p.jogador1_email, p.jogador2_email));
    IF v_pendentes_anteriores > 0 THEN
        RETURN NEW;
    END IF;

    -- Ambos os competidores precisam estar efetivamente inscritos no torneio.
    IF NOT EXISTS (SELECT 1 FROM public.inscricoes_torneio i
                    WHERE i.torneio_id = NEW.torneio_id
                      AND i.usuario_email = NEW.jogador1_email)
       OR NOT EXISTS (SELECT 1 FROM public.inscricoes_torneio i
                       WHERE i.torneio_id = NEW.torneio_id
                         AND i.usuario_email = NEW.jogador2_email) THEN
        RETURN NEW;
    END IF;

    IF NEW.rodada = 1 THEN
        -- Não encerrar torneio com mais de dois inscritos após apenas um duelo.
        SELECT count(*)::INTEGER INTO v_inscritos
          FROM public.inscricoes_torneio i
         WHERE i.torneio_id = NEW.torneio_id;
        IF v_inscritos <> 2 THEN
            RETURN NEW;
        END IF;
    ELSE
        -- Confirmar a origem real dos dois finalistas da rodada anterior.
        SELECT count(*)::INTEGER,
               max(p.vencedor_email) FILTER (WHERE p.ordem = 1),
               max(p.vencedor_email) FILTER (WHERE p.ordem = 2)
          INTO v_vencedores_anteriores, v_vencedor1, v_vencedor2
          FROM public.partidas_torneio p
         WHERE p.torneio_id = NEW.torneio_id
           AND p.rodada = NEW.rodada - 1
           AND p.status = 'finalizada'
           AND p.vencedor_email IS NOT NULL;
        IF v_vencedores_anteriores <> 2
           OR v_vencedor1 IS DISTINCT FROM NEW.jogador1_email
           OR v_vencedor2 IS DISTINCT FROM NEW.jogador2_email THEN
            RETURN NEW;
        END IF;
    END IF;

    IF NEW.vencedor_email = NEW.jogador1_email THEN
        v_vice_email := NEW.jogador2_email;
        v_vice_nick := NEW.jogador2_nick;
    ELSE
        v_vice_email := NEW.jogador1_email;
        v_vice_nick := NEW.jogador1_nick;
    END IF;

    UPDATE public.torneios
       SET status_torneio = 'finalizado',
           inscricoes_abertas = FALSE,
           campeao_email = NEW.vencedor_email,
           campeao_nick = NEW.vencedor_nick,
           vice_campeao_email = v_vice_email,
           vice_campeao_nick = v_vice_nick,
           finalizado_em = now(),
           ranking_processado = CASE
               WHEN v_torneio.ranking_ativo
                    AND v_torneio.temporada_id IS NOT NULL
                    AND NOT v_torneio.ranking_processado
               THEN TRUE
               ELSE v_torneio.ranking_processado
           END
     WHERE id = NEW.torneio_id AND status_torneio = 'em_andamento';

    -- Ranking de temporada é pontuado uma única vez, na mesma transação.
    -- Se qualquer insert falhar, o resultado da partida também faz rollback.
    IF v_torneio.ranking_ativo
       AND v_torneio.temporada_id IS NOT NULL
       AND NOT v_torneio.ranking_processado THEN
        INSERT INTO public.ranking_temporada
            (temporada_id, usuario_email, pontos, vitorias, podios, updated_at)
        VALUES
            (v_torneio.temporada_id, NEW.vencedor_email,
             v_torneio.pontos_campeao, 1, 1, now()),
            (v_torneio.temporada_id, v_vice_email,
             v_torneio.pontos_vice, 0, 1, now())
        ON CONFLICT (temporada_id, usuario_email) DO UPDATE
           SET pontos = public.ranking_temporada.pontos + EXCLUDED.pontos,
               vitorias = public.ranking_temporada.vitorias + EXCLUDED.vitorias,
               podios = public.ranking_temporada.podios + EXCLUDED.podios,
               updated_at = now();
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.hype_batalha_encerrar_torneio_automaticamente()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_hype_batalha_encerrar_torneio_auto
    ON public.partidas_torneio;

CREATE TRIGGER trg_hype_batalha_encerrar_torneio_auto
AFTER UPDATE OF status, vencedor_email ON public.partidas_torneio
FOR EACH ROW
WHEN (NEW.status = 'finalizada' AND OLD.status IS DISTINCT FROM 'finalizada')
EXECUTE FUNCTION public.hype_batalha_encerrar_torneio_automaticamente();
