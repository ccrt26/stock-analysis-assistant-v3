create extension if not exists pgcrypto;

create table if not exists public.market_calendar (
  trade_date date primary key,
  is_trading_day boolean not null,
  market text not null default 'CN_A'
);

create table if not exists public.stock_master (
  ts_code text primary key,
  name text not null,
  exchange text not null,
  list_date date
);

create table if not exists public.stock_status_daily (
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  is_st boolean not null default false,
  is_suspended boolean not null default false,
  has_delisting_risk boolean not null default false,
  listing_days integer not null,
  turnover_rate numeric,
  amount numeric,
  official_risk_events jsonb not null default '[]'::jsonb,
  primary key (trade_date, ts_code)
);

create table if not exists public.daily_feature_snapshot (
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  features jsonb not null,
  rule_hits jsonb not null default '[]'::jsonb,
  data_quality text not null,
  primary key (trade_date, ts_code)
);

create table if not exists public.recommendation_daily (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  action text not null,
  score numeric not null,
  reasons jsonb not null,
  risks jsonb not null,
  evidence_id text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.focus_watchlist_state (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  state text not null,
  entry_date date,
  entry_reason text,
  invalidation_conditions jsonb not null default '[]'::jsonb,
  exit_reason text,
  created_at timestamptz not null default now()
);

create table if not exists public.evidence_package_index (
  evidence_id text primary key,
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  storage_path text not null,
  sha256 text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.knowledge_rule (
  rule_id text primary key,
  source_grade text not null,
  rule_type text not null,
  source_reference text not null,
  payload jsonb not null,
  enabled boolean not null default true
);

create table if not exists public.knowledge_rule_match (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  ts_code text not null,
  rule_id text not null references public.knowledge_rule(rule_id),
  match_reason text not null
);

create table if not exists public.evaluation_task (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  ts_code text not null,
  evidence_id text not null,
  checkpoint_days integer not null,
  evaluation_layer text not null,
  due_date date not null,
  status text not null default 'pending'
);

create table if not exists public.evaluation_result (
  id uuid primary key default gen_random_uuid(),
  evaluation_task_id uuid not null references public.evaluation_task(id),
  result_payload jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.data_source_run (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  source_name text not null,
  status text not null,
  message text not null,
  created_at timestamptz not null default now()
);

alter table public.market_calendar enable row level security;
alter table public.stock_master enable row level security;
alter table public.stock_status_daily enable row level security;
alter table public.daily_feature_snapshot enable row level security;
alter table public.recommendation_daily enable row level security;
alter table public.focus_watchlist_state enable row level security;
alter table public.evidence_package_index enable row level security;
alter table public.knowledge_rule enable row level security;
alter table public.knowledge_rule_match enable row level security;
alter table public.evaluation_task enable row level security;
alter table public.evaluation_result enable row level security;
alter table public.data_source_run enable row level security;

alter table public.recommendation_daily
  add constraint recommendation_daily_action_check
  check (
    action in (
      '进入观察',
      '继续观察',
      '高风险观察',
      '降级观察',
      '剔除观察',
      '数据不足，不形成结论'
    )
  );

alter table public.focus_watchlist_state
  add constraint focus_watchlist_state_state_check
  check (
    state in (
      '进入观察',
      '继续观察',
      '高风险观察',
      '降级观察',
      '剔除观察',
      '数据不足，不形成结论'
    )
  );

create policy recommendation_daily_service_role_all on public.recommendation_daily
  for all
  to service_role
  using (true)
  with check (true);

create policy focus_watchlist_state_service_role_all on public.focus_watchlist_state
  for all
  to service_role
  using (true)
  with check (true);

create policy market_calendar_service_role_all on public.market_calendar
  for all
  to service_role
  using (true)
  with check (true);

create policy stock_master_service_role_all on public.stock_master
  for all
  to service_role
  using (true)
  with check (true);

create policy stock_status_daily_service_role_all on public.stock_status_daily
  for all
  to service_role
  using (true)
  with check (true);

create policy daily_feature_snapshot_service_role_all on public.daily_feature_snapshot
  for all
  to service_role
  using (true)
  with check (true);

create policy evidence_package_index_service_role_all on public.evidence_package_index
  for all
  to service_role
  using (true)
  with check (true);

create policy knowledge_rule_service_role_all on public.knowledge_rule
  for all
  to service_role
  using (true)
  with check (true);

create policy knowledge_rule_match_service_role_all on public.knowledge_rule_match
  for all
  to service_role
  using (true)
  with check (true);

create policy evaluation_task_service_role_all on public.evaluation_task
  for all
  to service_role
  using (true)
  with check (true);

create policy evaluation_result_service_role_all on public.evaluation_result
  for all
  to service_role
  using (true)
  with check (true);

create policy data_source_run_service_role_all on public.data_source_run
  for all
  to service_role
  using (true)
  with check (true);
