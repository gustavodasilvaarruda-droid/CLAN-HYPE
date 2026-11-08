-- CLAN HYPE | 2026-11-08 | Migracao de cargos e filiacao
-- Executar em conjunto com a atualizacao do app.py, com backup confirmado.
-- Não altera contratos, pedidos, torneios ou o vínculo existente com o clã.
BEGIN;
-- Snapshot privado anterior a qualquer mudança, para auditoria e recuperação.
CREATE SCHEMA IF NOT EXISTS hype_migration_backup;
CREATE TABLE IF NOT EXISTS hype_migration_backup.usuarios_cargos_20261108 AS
  SELECT email, cargo FROM public.usuarios_clan;
CREATE TABLE IF NOT EXISTS hype_migration_backup.membros_hype_20261108 AS
  SELECT usuario_email, ativo, entrou_em, saiu_em, observacao, updated_at
  FROM public.membros_hype;
ALTER TABLE public.usuarios_clan ALTER COLUMN cargo SET DEFAULT 'membro';
ALTER TABLE public.membros_hype ALTER COLUMN ativo SET DEFAULT FALSE;
-- Deixa de forçar 'visitante' para novos cadastros.
DROP TRIGGER IF EXISTS trg_zz_hype_forcar_visitante_cadastro ON public.usuarios_clan;
-- Alterar cargo nunca aprova ou remove automaticamente um integrante HYPE.
DROP TRIGGER IF EXISTS trg_hype_sincronizar_membro_cargo ON public.usuarios_clan;
-- Conversão das contas básicas: sem alterar a filiação HYPE.
UPDATE public.usuarios_clan SET cargo = 'membro' WHERE cargo = 'visitante';
-- Verificar filiação ativa antes e depois, conforme checklist no PR.
COMMIT;
-- Depois da migração:
-- SELECT cargo, count(*) FROM public.usuarios_clan GROUP BY cargo ORDER BY cargo;
-- SELECT count(*) FROM public.membros_hype WHERE ativo;
-- SELECT tgname FROM pg_trigger
--  WHERE tgrelid='public.usuarios_clan'::regclass AND NOT tgisinternal;
-- Os cargos virtuais/legados 'membro_hype', 'visitante' e 'pedri'
-- permanecem no banco para não perder autorizações de mods ou referências.
