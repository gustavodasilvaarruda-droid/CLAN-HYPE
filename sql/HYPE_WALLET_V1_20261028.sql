-- HYPE WALLET V1: saldo em moeda do Minecraft. Sem migrar/apagar historico existente.
-- Apenas o backend Flask com SUPABASE_SERVICE_ROLE_KEY executa as RPCs.
-- Usar em banco de homologacao antes de ativar pagamentos no site.
create table if not exists public.hype_wallet_accounts (
  owner_id text primary key references public.usuarios_clan(email) on update cascade on delete restrict,
  balance bigint not null default 0 check (balance >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.hype_wallet_deposit_requests (
  id uuid primary key default gen_random_uuid(),
  owner_id text not null references public.hype_wallet_accounts(owner_id) on update cascade on delete restrict,
  amount bigint not null check (amount between 1 and 1000000000000),
  status text not null default 'pending' check (status in ('pending','confirmed','rejected')),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by text references public.usuarios_clan(email) on update cascade on delete set null,
  note text
);
create index if not exists hype_wallet_deposit_requests_owner_idx
  on public.hype_wallet_deposit_requests(owner_id, created_at desc);
create table if not exists public.hype_wallet_entries (
  id uuid primary key default gen_random_uuid(),
  operation_key text not null unique check (length(trim(operation_key)) > 0),
  owner_id text not null references public.hype_wallet_accounts(owner_id) on update cascade on delete restrict,
  delta bigint not null check (delta between -1000000000000 and 1000000000000 and delta <> 0),
  kind text not null check (kind in ('deposit','purchase','refund','adjustment')),
  reference text not null,
  actor_id text not null,
  created_at timestamptz not null default now()
);
create index if not exists hype_wallet_entries_owner_idx
  on public.hype_wallet_entries(owner_id, created_at desc);

alter table public.hype_wallet_accounts enable row level security;
alter table public.hype_wallet_deposit_requests enable row level security;
alter table public.hype_wallet_entries enable row level security;
revoke all on public.hype_wallet_accounts, public.hype_wallet_deposit_requests,
  public.hype_wallet_entries from public, anon, authenticated;
grant select, insert, update on public.hype_wallet_accounts to service_role;
grant select, insert, update on public.hype_wallet_deposit_requests to service_role;
grant select, insert on public.hype_wallet_entries to service_role;

create or replace function public.hype_wallet_request_deposit(
  p_owner_id text, p_amount bigint
) returns uuid language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_request_id uuid;
begin
  if nullif(trim(p_owner_id),'') is null or p_amount is null
     or p_amount < 1 or p_amount > 1000000000000 then
    raise exception 'invalid deposit request';
  end if;
  -- impedir corrida entre pedidos novos para a mesma carteira
  perform pg_advisory_xact_lock(hashtextextended('request:'||p_owner_id,0));
  insert into public.hype_wallet_accounts(owner_id) values(p_owner_id) on conflict do nothing;
  if (select count(*) from public.hype_wallet_deposit_requests
      where owner_id=p_owner_id and status='pending') >= 5 then
    raise exception 'too many pending deposits';
  end if;
  insert into public.hype_wallet_deposit_requests(owner_id,amount)
    values(p_owner_id,p_amount) returning id into v_request_id;
  return v_request_id;
end $$;
revoke all on function public.hype_wallet_request_deposit(text,bigint) from public,anon,authenticated;
grant execute on function public.hype_wallet_request_deposit(text,bigint) to service_role;

create or replace function public.hype_wallet_post(
  p_operation_key text, p_owner_id text, p_delta bigint, p_kind text,
  p_reference text, p_actor_id text
) returns bigint language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_balance bigint; v_old public.hype_wallet_entries%rowtype;
begin
  if nullif(trim(p_operation_key),'') is null or nullif(trim(p_owner_id),'') is null
     or nullif(trim(p_reference),'') is null or nullif(trim(p_actor_id),'') is null
     or p_delta is null or p_delta=0 or p_delta < -1000000000000 or p_delta > 1000000000000
     or p_kind is null or p_kind not in ('deposit','purchase','refund','adjustment') then
    raise exception 'invalid wallet operation';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('wallet:'||p_owner_id,0));
  select * into v_old from public.hype_wallet_entries where operation_key=p_operation_key;
  if found then
    if v_old.owner_id<>p_owner_id or v_old.delta<>p_delta or v_old.kind<>p_kind
       or v_old.reference<>p_reference then
      raise exception 'idempotency key reused for different operation';
    end if;
    select balance into v_balance from public.hype_wallet_accounts where owner_id=p_owner_id;
    return v_balance;
  end if;
  insert into public.hype_wallet_accounts(owner_id) values(p_owner_id) on conflict do nothing;
  select balance into v_balance from public.hype_wallet_accounts where owner_id=p_owner_id for update;
  if p_delta<0 and v_balance < -p_delta then raise exception 'insufficient balance'; end if;
  update public.hype_wallet_accounts
     set balance=balance+p_delta, updated_at=now()
   where owner_id=p_owner_id returning balance into v_balance;
  insert into public.hype_wallet_entries(operation_key,owner_id,delta,kind,reference,actor_id)
    values(p_operation_key,p_owner_id,p_delta,p_kind,p_reference,p_actor_id);
  return v_balance;
end $$;
revoke all on function public.hype_wallet_post(text,text,bigint,text,text,text) from public,anon,authenticated;
grant execute on function public.hype_wallet_post(text,text,bigint,text,text,text) to service_role;

create or replace function public.hype_wallet_confirm_deposit(
  p_request_id uuid, p_actor_id text
) returns bigint language plpgsql security definer set search_path=pg_catalog,public as $$
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
  v_balance:=public.hype_wallet_post('deposit:'||r.id::text,r.owner_id,r.amount,'deposit',r.id::text,p_actor_id);
  update public.hype_wallet_deposit_requests
    set status='confirmed',reviewed_at=now(),reviewed_by=p_actor_id where id=r.id;
  return v_balance;
end $$;
revoke all on function public.hype_wallet_confirm_deposit(uuid,text) from public,anon,authenticated;
grant execute on function public.hype_wallet_confirm_deposit(uuid,text) to service_role;

create or replace function public.hype_wallet_reject_deposit(
  p_request_id uuid, p_actor_id text, p_note text default null
) returns boolean language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.hype_wallet_deposit_requests%rowtype;
begin
  if nullif(trim(p_actor_id),'') is null then raise exception 'actor required'; end if;
  select * into r from public.hype_wallet_deposit_requests where id=p_request_id for update;
  if not found then raise exception 'deposit request missing'; end if;
  if r.status='confirmed' then raise exception 'already confirmed'; end if;
  if r.status='rejected' then return true; end if;
  update public.hype_wallet_deposit_requests
     set status='rejected', reviewed_at=now(), reviewed_by=p_actor_id,
         note=left(coalesce(p_note,''),500) where id=r.id;
  return true;
end $$;
revoke all on function public.hype_wallet_reject_deposit(uuid,text,text) from public,anon,authenticated;
grant execute on function public.hype_wallet_reject_deposit(uuid,text,text) to service_role;
