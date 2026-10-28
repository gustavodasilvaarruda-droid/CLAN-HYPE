-- Etapa 2 - usuario informa que pagou no Minecraft, lider confere.
-- Migração incremental segura: não altera saldo nem pedidos atuais.
alter table public.hype_wallet_deposit_requests add column if not exists reported_at timestamptz;
alter table public.hype_wallet_deposit_requests add column if not exists payment_note text;
alter table public.hype_wallet_deposit_requests
  drop constraint if exists hype_wallet_deposit_requests_status_check;
alter table public.hype_wallet_deposit_requests
  add constraint hype_wallet_deposit_requests_status_check
  check (status in ('pending','reported','confirmed','rejected'));

create or replace function public.hype_wallet_report_deposit(
  p_request_id uuid, p_owner_id text, p_note text default null
) returns boolean language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.hype_wallet_deposit_requests%rowtype;
begin
  if p_request_id is null or nullif(trim(p_owner_id),'') is null then
    raise exception 'invalid report request';
  end if;
  select * into r from public.hype_wallet_deposit_requests where id=p_request_id for update;
  if not found or r.owner_id <> p_owner_id then
    raise exception 'request not found for this member';
  end if;
  if r.status='rejected' then raise exception 'deposit rejected'; end if;
  if r.status in ('reported','confirmed') then return true; end if;
  update public.hype_wallet_deposit_requests
     set status='reported', reported_at=now(), payment_note=left(coalesce(p_note,''),180)
   where id=r.id and status='pending';
  return true;
end $$;
revoke all on function public.hype_wallet_report_deposit(uuid,text,text) from public,anon,authenticated;
grant execute on function public.hype_wallet_report_deposit(uuid,text,text) to service_role;

-- Limite de pedidos não conciliados por membro (pendente + informado).
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
      where owner_id=p_owner_id and status in ('pending','reported')) >= 5 then
    raise exception 'too many pending deposits';
  end if;
  insert into public.hype_wallet_deposit_requests(owner_id,amount)
    values(p_owner_id,p_amount) returning id into v_request_id;
  return v_request_id;
end $$;
revoke all on function public.hype_wallet_request_deposit(text,bigint) from public,anon,authenticated;
grant execute on function public.hype_wallet_request_deposit(text,bigint) to service_role;

-- Exige a etapa de confirmação do jogador antes de o líder lançar crédito.
create or replace function public.hype_wallet_confirm_deposit(
  p_request_id uuid, p_actor_id text
) returns bigint language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.hype_wallet_deposit_requests%rowtype; v_balance bigint;
begin
  if nullif(trim(p_actor_id),'') is null then raise exception 'actor required'; end if;
  select * into r from public.hype_wallet_deposit_requests where id=p_request_id for update;
  if not found then raise exception 'deposit request missing'; end if;
  if r.status='rejected' then raise exception 'deposit rejected'; end if;
  if r.status='pending' then raise exception 'payment not reported by member'; end if;
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
