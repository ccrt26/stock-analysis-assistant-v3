alter table public.focus_daily_update
    drop constraint if exists focus_daily_update_trade_date_ts_code_key;
alter table public.focus_daily_update
    add constraint focus_daily_update_pkey primary key (trade_date, ts_code);

alter table public.action_recommendation_summary
    drop constraint if exists action_recommendation_summary_trade_date_ts_code_key;
alter table public.action_recommendation_summary
    add constraint action_recommendation_summary_pkey
    primary key (trade_date, ts_code);

alter table public.manual_holding_summary
    drop constraint if exists manual_holding_summary_trade_date_ts_code_key;
alter table public.manual_holding_summary
    add constraint manual_holding_summary_pkey primary key (trade_date, ts_code);

create index if not exists daily_basic_indicator_ts_code_idx
    on public.daily_basic_indicator (ts_code);
create index if not exists daily_feature_snapshot_ts_code_idx
    on public.daily_feature_snapshot (ts_code);
create index if not exists evaluation_result_evaluation_task_id_idx
    on public.evaluation_result (evaluation_task_id);
create index if not exists evidence_package_index_ts_code_idx
    on public.evidence_package_index (ts_code);
create index if not exists focus_watchlist_state_ts_code_idx
    on public.focus_watchlist_state (ts_code);
create index if not exists formal_run_activation_marker_pending_id_idx
    on public.formal_run_activation_marker (pending_id);
create index if not exists formal_run_pending_batch_run_id_idx
    on public.formal_run_pending_batch (run_id);
create index if not exists knowledge_rule_match_rule_id_idx
    on public.knowledge_rule_match (rule_id);
create index if not exists market_price_daily_ts_code_idx
    on public.market_price_daily (ts_code);
create index if not exists recommendation_daily_ts_code_idx
    on public.recommendation_daily (ts_code);
create index if not exists stock_status_daily_ts_code_idx
    on public.stock_status_daily (ts_code);
