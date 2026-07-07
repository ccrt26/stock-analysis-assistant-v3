from pathlib import Path


def test_initial_schema_contains_required_tables_and_rls():
    sql = Path(
        "/Users/ccrt/股票分析助手/.worktrees/codex/v3-mvp/supabase/migrations/202607070001_init_core.sql"
    ).read_text()
    for table in [
        "market_calendar",
        "stock_master",
        "stock_status_daily",
        "daily_feature_snapshot",
        "recommendation_daily",
        "focus_watchlist_state",
        "evidence_package_index",
        "knowledge_rule",
        "knowledge_rule_match",
        "evaluation_task",
        "evaluation_result",
        "data_source_run",
    ]:
        assert f"create table if not exists public.{table}" in sql.lower()
        assert f"alter table public.{table} enable row level security" in sql.lower()
