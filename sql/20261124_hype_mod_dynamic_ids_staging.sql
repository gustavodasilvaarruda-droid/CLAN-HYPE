-- Central HYPE: rascunhos e fila aceitam novos IDs Fabric seguros.
-- O canal de publicacao permanece restrito ate implementar catalogue assinado dinamico.
-- Alinha o CHECK ao validador Python [a-z][a-z0-9_]{1,63} e proibe o Bootstrap.
BEGIN;
ALTER TABLE public.hype_mod_release_drafts
  DROP CONSTRAINT hype_mod_release_drafts_module_id_check;
ALTER TABLE public.hype_mod_release_drafts
  ADD CONSTRAINT hype_mod_release_drafts_module_id_check
  CHECK (module_id ~ '^[a-z][a-z0-9_]{1,63}$' AND module_id <> 'hypebootstrap');

ALTER TABLE public.hype_mod_protection_jobs
  DROP CONSTRAINT hype_mod_protection_jobs_module_id_check;
ALTER TABLE public.hype_mod_protection_jobs
  ADD CONSTRAINT hype_mod_protection_jobs_module_id_check
  CHECK (module_id ~ '^[a-z][a-z0-9_]{1,63}$' AND module_id <> 'hypebootstrap');
COMMIT;
