-- HYPE dynamic owner-uploaded module identifiers (NOT public publishing).
-- Apply only together with the reviewed Flask staging/protection update.
-- The restricted entitlement channel keeps its separate allowlist.
BEGIN;

ALTER TABLE public.hype_mod_release_drafts
  DROP CONSTRAINT IF EXISTS hype_mod_release_drafts_module_id_check;
ALTER TABLE public.hype_mod_release_drafts
  ADD CONSTRAINT hype_mod_release_drafts_module_id_check
  CHECK (module_id ~ '^[a-z][a-z0-9_]{1,63}$' AND module_id <> 'hypebootstrap');

ALTER TABLE public.hype_mod_protection_jobs
  DROP CONSTRAINT IF EXISTS hype_mod_protection_jobs_module_id_check;
ALTER TABLE public.hype_mod_protection_jobs
  ADD CONSTRAINT hype_mod_protection_jobs_module_id_check
  CHECK (module_id ~ '^[a-z][a-z0-9_]{1,63}$' AND module_id <> 'hypebootstrap');

COMMIT;
