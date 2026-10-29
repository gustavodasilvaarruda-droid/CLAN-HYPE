-- Carteira HYPE: auditoria de consistência financeira exclusivamente leitura.
-- Não movimenta moedas nem altera tabelas ou registros existentes.
create or replace function public.hype_wallet_integrity_report()
returns table(
  accounts bigint,
  pending bigint,
  reported bigint,
  confirmed bigint,
  ledger_sum bigint,
  balances_sum bigint,
  mismatched_accounts bigint,
  confirmed_without_entry bigint,
  entries_without_confirmation bigint
)
language sql
stable
security definer
set search_path=pg_catalog,public
as $$
  select
    (select count(*) from public.hype_wallet_accounts)::bigint,
    (select count(*) from public.hype_wallet_deposit_requests where status='pending')::bigint,
    (select count(*) from public.hype_wallet_deposit_requests where status='reported')::bigint,
    (select count(*) from public.hype_wallet_deposit_requests where status='confirmed')::bigint,
    (select coalesce(sum(delta),0) from public.hype_wallet_entries)::bigint,
    (select coalesce(sum(balance),0) from public.hype_wallet_accounts)::bigint,
    (select count(*) from public.hype_wallet_accounts a
      where a.balance <> coalesce((select sum(e.delta)
                                      from public.hype_wallet_entries e
                                     where e.owner_id=a.owner_id),0))::bigint,
    (select count(*) from public.hype_wallet_deposit_requests d
      where d.status='confirmed' and not exists
        (select 1 from public.hype_wallet_entries e
          where e.operation_key='deposit:'||d.id::text
            and e.owner_id=d.owner_id and e.delta=d.amount and e.kind='deposit'))::bigint,
    (select count(*) from public.hype_wallet_entries e
      where e.kind='deposit' and not exists
        (select 1 from public.hype_wallet_deposit_requests d
          where e.operation_key='deposit:'||d.id::text
            and d.status='confirmed' and d.owner_id=e.owner_id and d.amount=e.delta))::bigint;
$$;
revoke all on function public.hype_wallet_integrity_report() from public,anon,authenticated;
grant execute on function public.hype_wallet_integrity_report() to service_role;
