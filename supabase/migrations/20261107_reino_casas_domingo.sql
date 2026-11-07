-- Reino HYPE: cobrança autônoma de CASAS no domingo, 09h (Brasília).
-- Não altera contratos ou cobranças de LOJAS.
-- A chave única (tipo_unidade, contrato_id, referencia_vencimento)
-- protege contra cobranças duplicadas mesmo com acessos concorrentes ao Flask.
CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog;
CREATE SCHEMA IF NOT EXISTS hype_jobs;
REVOKE ALL ON SCHEMA hype_jobs FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION hype_jobs.cobrar_casas_domingo()
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $function$
DECLARE
    hoje date := (now() AT TIME ZONE 'America/Sao_Paulo')::date;
    contrato record;
    venc date;
    cobranca_id bigint;
    total integer := 0;
    total_aberto bigint;
BEGIN
    -- Evita cobranças fora do domingo mesmo se alguém executar o job manualmente.
    IF EXTRACT(ISODOW FROM hoje) <> 7 THEN
        RETURN 0;
    END IF;
    FOR contrato IN
        SELECT id, casa_id, usuario_email, valor_semanal, proximo_vencimento
          FROM public.contratos_casas
         WHERE status = 'ativo' AND proximo_vencimento <= hoje
         FOR UPDATE
    LOOP
        venc := contrato.proximo_vencimento;
        WHILE venc <= hoje LOOP
            cobranca_id := NULL;
            INSERT INTO public.hype_reino_cobrancas
                (tipo_unidade, contrato_id, casa_id, usuario_email,
                 referencia_vencimento, valor, status, gerada_em)
            VALUES
                ('casa', contrato.id, contrato.casa_id, contrato.usuario_email,
                 venc, GREATEST(0, contrato.valor_semanal), 'pendente', now())
            ON CONFLICT (tipo_unidade, contrato_id, referencia_vencimento) DO NOTHING
            RETURNING id INTO cobranca_id;
            IF cobranca_id IS NOT NULL THEN
                total := total + 1;
                SELECT COALESCE(sum(valor),0) INTO total_aberto
                  FROM public.hype_reino_cobrancas
                 WHERE usuario_email = contrato.usuario_email
                   AND tipo_unidade = 'casa'
                   AND status IN ('pendente','informado');
                INSERT INTO public.notificacoes
                    (usuario_email, titulo, mensagem, tipo, link)
                VALUES
                    (contrato.usuario_email, 'Aluguel da casa vence neste domingo',
                     'Vencimento: ' || to_char(venc, 'DD/MM/YYYY')
                     || '. Valor semanal: ' || contrato.valor_semanal::text
                     || ' moedas. Total em aberto de casas: ' || total_aberto::text
                     || ' moedas. Informe o pagamento no Meu Aluguel; a administração confirmará.',
                     'aviso', '/reino/financeiro');
            END IF;
            venc := venc + 7;
        END LOOP;
        UPDATE public.contratos_casas
           SET proximo_vencimento = venc
         WHERE id = contrato.id;
    END LOOP;
    RETURN total;
END;
$function$;
REVOKE ALL ON FUNCTION hype_jobs.cobrar_casas_domingo() FROM PUBLIC, anon, authenticated;
-- Executa somente como proprietário do agendamento (postgres); nenhum endpoint público.
SELECT cron.schedule(
    'hype-casas-domingo-0900-brasilia',
    '0 12 * * 0',
    'SELECT hype_jobs.cobrar_casas_domingo();'
);
