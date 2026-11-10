-- Arena HYPE 3.0 — registro PRIVADO dos times enviados aos torneios.
-- Aplicar no Supabase antes de ativar a interface. Sem alteração nas
-- inscrições, confrontos, ranking ou times existentes.
CREATE TABLE IF NOT EXISTS public.arena_torneio_equipes (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  torneio_id bigint NOT NULL REFERENCES public.torneios(id) ON DELETE CASCADE,
  usuario_email text NOT NULL,
  slot smallint NOT NULL CHECK (slot BETWEEN 1 AND 3),
  nome text NOT NULL CHECK (char_length(nome) BETWEEN 1 AND 100),
  equipe jsonb NOT NULL,
  formato_codigo text NOT NULL,
  regras_snapshot text NOT NULL,
  status text NOT NULL DEFAULT 'aguardando_verificacao'
    CHECK (status IN ('aguardando_verificacao','correcao_solicitada','aprovado')),
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  enviado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT arena_torneio_equipes_unico UNIQUE(torneio_id, usuario_email, slot)
);

CREATE INDEX IF NOT EXISTS idx_arena_torneio_equipes_torneio
  ON public.arena_torneio_equipes(torneio_id);
CREATE TABLE IF NOT EXISTS public.arena_torneio_equipes_historico (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  torneio_id bigint NOT NULL,
  usuario_email text NOT NULL,
  slot smallint NOT NULL,
  operacao text NOT NULL,
  registro jsonb NOT NULL,
  criado_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_arena_torneio_hist_torneio
  ON public.arena_torneio_equipes_historico(torneio_id, usuario_email);

-- Somente o backend com service_role consulta equipes e histórico.
-- Se o backend estiver configurado apenas com anon key, o fluxo falha
-- fechado: NÃO abra uma policy pública para corrigir isso.
ALTER TABLE public.arena_torneio_equipes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.arena_torneio_equipes_historico ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.arena_torneio_equipes FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.arena_torneio_equipes_historico FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.arena_torneio_equipes TO service_role;
GRANT ALL ON public.arena_torneio_equipes_historico TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.arena_torneio_equipes_id_seq TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.arena_torneio_equipes_historico_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.registrar_historico_equipes_arena()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
SET search_path = public AS $
BEGIN
  INSERT INTO public.arena_torneio_equipes_historico
    (torneio_id, usuario_email, slot, operacao, registro)
  VALUES (NEW.torneio_id, NEW.usuario_email, NEW.slot, TG_OP, to_jsonb(NEW));
  RETURN NEW;
END; $$;
DROP TRIGGER IF EXISTS trg_historico_equipes_arena ON public.arena_torneio_equipes;
CREATE TRIGGER trg_historico_equipes_arena
AFTER INSERT OR UPDATE ON public.arena_torneio_equipes
FOR EACH ROW EXECUTE FUNCTION public.registrar_historico_equipes_arena();
REVOKE EXECUTE ON FUNCTION public.registrar_historico_equipes_arena() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_historico_equipes_arena() TO service_role;
