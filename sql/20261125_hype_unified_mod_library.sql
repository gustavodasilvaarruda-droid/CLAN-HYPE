-- HYPE unified mod library: archive any syntactically valid Fabric mod ID.
-- No releases, storage visibility, signatures, roles or RLS are changed.
-- Existing HYPE modules remain valid; unknown mods may be stored privately,
-- but private/published update endpoints retain their own allowlists.
alter table public.hype_mod_release_drafts
  drop constraint if exists hype_mod_release_drafts_module_id_check;

alter table public.hype_mod_release_drafts
  add constraint hype_mod_release_drafts_module_id_check
  check (module_id ~ '^[a-z][a-z0-9_-]{1,63}$');
