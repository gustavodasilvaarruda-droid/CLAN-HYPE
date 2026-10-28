-- HYPE Wallet V1: moeda virtual do Minecraft; aplicar SOMENTE após revisão em homologação.
-- Toda operação de escrita passa pelo servidor Flask com credencial service_role protegida.
create table if not exists public.hype_wallet_accounts (
  owner_id text primary key check (length(trim(owner_id)) > 0),
  balance bigint not null default 0 check (balance >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.hype_wallet_deposit_requests (
  id uuid primary key default gen_random_uuid(),
  owner_id text not null references public.hype_wallet_accounts(owner_id),
  amount bigint not null check (amount > 0),
  status text not null default 'pending' check (status in ('pending','confirmed','rejected')),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by text,
  note text
);
create index if not exists hype_wallet_deposit_requests_owner_idx on public.hype_wallet_deposit_requests(owner_id, created_at desc);
create table if not exists public.hype_wallet_entries (
  id uuid primary key default gen_random_uuid(),
  operation_key text not null unique check (length(trim(operation_key)) > 0),
  owner_id text not null references public.hype_wallet_accounts(owner_id),
  delta bigint not null check (delta <> 0),
  kind text not null check (kind in ('deposit','purchase','refund','adjustment')),
  reference text not null,
  actor_id text not null,
  created_at timestamptz not null default now()
);
create index if not exists hype_wallet_entries_owner_idx on public.hype_wallet_entries(owner_id, created_at desc);
alter table public.hype_wallet_accounts enable row level security;
alter table public.hype_wallet_deposit_requests enable row level security;
alter table public.hype_wallet_entries enable row level security;
-- Sem policies públicas: usuários não podem editar diretamente saldo ou confirmações.
revoke all on public.hype_wallet_accounts, public.hype_wallet_deposit_requests, public.hype_wallet_entries from public, anon, authenticated;
revoke all on public.hype_wallet_accounts, public.hype_wallet_deposit_requests, public.hype_wallet_entries from public;
-- RPC administrativa: bloquear acesso direto a papéis externos.
create or replace function public.hype_wallet_post(
  p_operation_key text, p_owner_id text, p_delta bigint, p_kind text,
  p_reference text, p_actor_id text
) returns bigint language plpgsql security definer set search_path = public, pg_temp as $$
declare v_balance bigint;
declare v_old public.hype_wallet_entries%rowtype;
begin
  if nullif(trim(p_operation_key),'') is null or nullif(trim(p_owner_id),'') is null
     or nullif(trim(p_reference),'') is null or nullif(trim(p_actor_id),'') is null
     or p_delta is null or p_delta = 0
     or p_kind not in ('deposit','purchase','refund','adjustment') then
    raise exception 'invalid wallet operation';
  end if;
  -- Advisory lock serializa inclusive requisições de saldo ainda inexistente.
  perform pg_advisory_xact_lock(hashtextextended(p_owner_id, 0));
  select * into v_old from public.hype_wallet_entries where operation_key = p_operation_key;
  if found then
    if v_old.owner_id <> p_owner_id or v_old.delta <> p_delta or v_old.kind <> p_kind
       or v_old.reference <> p_reference then
      raise exception 'idempotency key reused for different operation';
    end if;
    select balance into v_balance from public.hype_wallet_accounts where owner_id=p_owner_id;
    return v_balance;
  end if;
  insert into public.hype_wallet_accounts(owner_id) values(p_owner_id) on conflict do nothing;
  select balance into v_balance from public.hype_wallet_accounts where owner_id=p_owner_id for update;
  if p_delta < 0 and v_balance < -p_delta then raise exception 'insufficient balance'; end if;
  update public.hype_wallet_accounts
     set balance=balance+p_delta, updated_at=now()
   where owner_id=p_owner_id returning balance into v_balance;
  insert into public.hype_wallet_entries(operation_key,owner_id,delta,kind,reference,actor_id)
    values(p_operation_key,p_owner_id,p_delta,p_kind,p_reference,p_actor_id);
  return v_balance;
end $$;
revoke all on function public.hype_wallet_post(text,text,bigint,text,text,text) from public, anon, authenticated;
grant execute on function public.hype_wallet_post(text,text,bigint,text,text,text) to service_role;
-- Confirmar depósito com trava em linha e operação idempotente.
create or replace function public.hype_wallet_confirm_deposit(
  p_request_id uuid, p_actor_id text
) returns bigint language plpgsql security definer set search_path=public,pg_temp as $$
declare r public.hype_wallet_deposit_requests%rowtype; v_balance bigint;
begin
  if nullif(trim(p_actor_id),'') is null then raise exception 'actor required'; end if;
  select * into r from public.hype_wallet_deposit_requests where id=p_request_id for update;
  if not found then raise exception 'deposit request missing'; end if;
  if r.status='rejected' then raise exception 'deposit rejected'; end if;
  if r.status='confirmed' then
    select balance into v_balance from public.hype_wallet_accounts where owner_id=r.owner_id;
    return v_balance;
  end if;
  v_balance := public.hype_wallet_post('deposit:'||r.id::text,r.owner_id,r.amount,'deposit',r.id::text,p_actor_id);
  update public.hype_wallet_deposit_requests set status='confirmed', reviewed_at=now(), reviewed_by=p_actor_id where id=r.id;
  return v_balance;
end $$;
revoke all on function public.hype_wallet_confirm_deposit(uuid,text) from public, anon, authenticated;
grant execute on function public.hype_wallet_confirm_deposit(uuid,text) to service_role;
-- IMPORTANTE: a API Flask ainda deverá validar cargo de líder/admin,
-- usuário autenticado, CSRF e a confirmação do pagamento no jogo.
