create table if not exists public.strategy_v2_snapshot (
  evidence_id text primary key,
  trade_date date not null,
  ts_code text not null,
  name text not null,
  payload jsonb not null,
  action_payload jsonb not null,
  data_insufficient boolean not null default false,
  source_versions jsonb not null default '{}'::jsonb,
  sha256 text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.focus_entry_thesis (
  evidence_id text primary key,
  trade_date date not null,
  ts_code text not null,
  source text not null,
  thesis_payload jsonb not null,
  action_payload jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.focus_daily_update (
  trade_date date not null,
  ts_code text not null,
  update_payload jsonb not null,
  action_payload jsonb not null,
  created_at timestamptz not null default now(),
  constraint focus_daily_update_trade_date_ts_code_key unique (trade_date, ts_code)
);

create table if not exists public.action_recommendation_summary (
  trade_date date not null,
  ts_code text not null,
  decision text not null,
  position_min_pct numeric not null,
  position_max_pct numeric not null,
  invalidation_conditions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  constraint action_recommendation_summary_trade_date_ts_code_key unique (trade_date, ts_code)
);

create table if not exists public.manual_holding_summary (
  trade_date date not null,
  ts_code text not null,
  held boolean not null,
  position_band text not null,
  last_action_state text not null,
  created_at timestamptz not null default now(),
  constraint manual_holding_summary_trade_date_ts_code_key unique (trade_date, ts_code)
);

create table if not exists public.operational_daily_status (
  trade_date date primary key,
  is_trading_day boolean not null,
  recommendation_state text not null,
  focus_state text not null,
  recommendation_count integer not null,
  focus_count integer not null,
  blocking_missing_fields jsonb not null default '[]'::jsonb,
  message text not null,
  created_at timestamptz not null default now()
);

alter table public.strategy_v2_snapshot enable row level security;
alter table public.focus_entry_thesis enable row level security;
alter table public.focus_daily_update enable row level security;
alter table public.action_recommendation_summary enable row level security;
alter table public.manual_holding_summary enable row level security;
alter table public.operational_daily_status enable row level security;

create policy strategy_v2_snapshot_service_role_all on public.strategy_v2_snapshot
  for all
  to service_role
  using (true)
  with check (true);

create policy focus_entry_thesis_service_role_all on public.focus_entry_thesis
  for all
  to service_role
  using (true)
  with check (true);

create policy focus_daily_update_service_role_all on public.focus_daily_update
  for all
  to service_role
  using (true)
  with check (true);

create policy action_recommendation_summary_service_role_all on public.action_recommendation_summary
  for all
  to service_role
  using (true)
  with check (true);

create policy manual_holding_summary_service_role_all on public.manual_holding_summary
  for all
  to service_role
  using (true)
  with check (true);

create policy operational_daily_status_service_role_all on public.operational_daily_status
  for all
  to service_role
  using (true)
  with check (true);
