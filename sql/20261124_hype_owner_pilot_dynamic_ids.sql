-- Owner-only Fabric mod homologation can store newly created IDs.
-- Public/protected releases remain restricted by their separate validators.
-- Never allow the Bootstrap to replace itself through the owner pilot.
ALTER TABLE public.hype_mod_release_drafts
    DROP CONSTRAINT IF EXISTS hype_mod_release_drafts_module_id_check;
ALTER TABLE public.hype_mod_release_drafts
    ADD CONSTRAINT hype_mod_release_drafts_module_id_check
    CHECK (module_id ~ '^[a-z][a-z0-9_-]{1,63}$' AND module_id <> 'hypebootstrap');
