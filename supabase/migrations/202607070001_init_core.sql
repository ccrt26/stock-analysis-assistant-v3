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
