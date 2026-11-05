-- HYPE Client -> Site: idempotency of game-origin Breed orders.
-- Run in Supabase SQL editor BEFORE deploying the matching Flask API.
-- Additive and reversible: existing website orders retain NULL.
ALTER TABLE public.pedidos_breed
    ADD COLUMN IF NOT EXISTS hype_client_request_id uuid;

CREATE UNIQUE INDEX IF NOT EXISTS pedidos_breed_hype_client_request_id_unique
    ON public.pedidos_breed (hype_client_request_id)
    WHERE hype_client_request_id IS NOT NULL;

COMMENT ON COLUMN public.pedidos_breed.hype_client_request_id IS
    'UUID v4 supplied by HYPE Client for safe retries (unique across all users).';
