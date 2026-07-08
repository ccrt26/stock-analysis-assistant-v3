create table if not exists public.market_price_daily (
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  open numeric,
  high numeric,
  low numeric,
  close numeric not null,
  pre_close numeric,
  pct_chg numeric,
  vol numeric,
  amount numeric,
  source_name text not null,
  source_grade text not null,
  fetched_at timestamptz not null default now(),
  primary key (trade_date, ts_code)
);

create table if not exists public.daily_basic_indicator (
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  turnover_rate numeric,
  total_mv numeric,
  circ_mv numeric,
  pe_ttm numeric,
  pb numeric,
  source_name text not null,
  source_grade text not null,
  fetched_at timestamptz not null default now(),
  primary key (trade_date, ts_code)
);

alter table public.data_source_run add column if not exists stage text not null default 'unknown';
alter table public.data_source_run add column if not exists attempt integer not null default 1;
alter table public.data_source_run add column if not exists source_grade text not null default 'primary';
alter table public.data_source_run add column if not exists data_status text not null default 'insufficient_live_data';
alter table public.data_source_run add column if not exists record_count integer not null default 0;
alter table public.data_source_run add column if not exists field_coverage jsonb not null default '{}'::jsonb;
alter table public.data_source_run add column if not exists payload jsonb not null default '{}'::jsonb;

alter table public.market_price_daily enable row level security;
alter table public.daily_basic_indicator enable row level security;

create policy market_price_daily_service_role_all on public.market_price_daily
  for all
  to service_role
  using (true)
  with check (true);

create policy daily_basic_indicator_service_role_all on public.daily_basic_indicator
  for all
  to service_role
  using (true)
  with check (true);

create or replace function public.database_size_mb()
returns numeric
language sql
security definer
set search_path = public
as $$
  select pg_database_size(current_database()) / 1024.0 / 1024.0;
$$;

revoke execute on function public.database_size_mb() from public, anon, authenticated;
grant execute on function public.database_size_mb() to service_role;
