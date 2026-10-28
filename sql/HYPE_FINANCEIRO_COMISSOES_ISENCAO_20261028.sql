-- HYPE: isencao inicial das comissoes, SEM registrar entrada ficticia no caixa.
-- Aplicar manualmente no Supabase apos revisar os constraints existentes.
-- A migracao e transacional; o RPC so e executavel por service_role.
BEGIN;

ALTER TABLE public.hype_breed_comissoes
  ADD COLUMN IF NOT EXISTS isento_em timestamptz,
  ADD COLUMN IF NOT EXISTS isento_por text,
  ADD COLUMN IF NOT EXISTS isento_motivo text;

-- Se existir a constraint convencional, ampliar o rol de status sem remove-la.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='public.hype_breed_comissoes'::regclass
      AND conname='hype_breed_comissoes_status_check'
  ) THEN
    ALTER TABLE public.hype_breed_comissoes
      DROP CONSTRAINT hype_breed_comissoes_status_check;
    ALTER TABLE public.hype_breed_comissoes
      ADD CONSTRAINT hype_breed_comissoes_status_check
      CHECK (status IN ('pendente','informado','pago','cancelado','isento'));
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.hype_isentar_comissoes_anteriores(
  p_data_corte date, p_operador_email text, p_motivo text
)
RETURNS TABLE(quantidade bigint, total_valor bigint)
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_qtd bigint;
  v_total bigint;
BEGIN
  IF p_data_corte IS NULL OR p_data_corte > CURRENT_DATE + 1
     OR p_data_corte < DATE '2020-01-01' THEN
    RAISE EXCEPTION 'Data de corte invalida';
  END IF;
  IF length(trim(coalesce(p_operador_email,''))) < 3
    OR length(trim(coalesce(p_motivo,''))) < 10 THEN
    RAISE EXCEPTION 'Operador e motivo detalhado obrigatorios';
  END IF;
  WITH alteradas AS (
    UPDATE public.hype_breed_comissoes c
    SET status = 'isento',
        isento_em = now(),
        isento_por = lower(trim(p_operador_email)),
        isento_motivo = left(trim(p_motivo),500),
        updated_at = now()
    WHERE c.status = 'pendente'
      AND COALESCE(c.gerada_em, c.created_at) < p_data_corte::timestamptz
    RETURNING c.valor
  )
  SELECT count(*), coalesce(sum(valor), 0) INTO v_qtd, v_total FROM alteradas;
  RETURN QUERY SELECT v_qtd, v_total;
END $$;

REVOKE ALL ON FUNCTION public.hype_isentar_comissoes_anteriores(date,text,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.hype_isentar_comissoes_anteriores(date,text,text) TO service_role;

COMMIT;
