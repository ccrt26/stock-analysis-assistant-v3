import re
from pathlib import Path


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "202607070001_init_core.sql"
)


def test_initial_schema_contains_required_tables_and_rls():
    sql = SCHEMA_PATH.read_text()
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


def test_initial_schema_constrains_action_labels_and_service_role_policies():
    sql = SCHEMA_PATH.read_text().lower()
    compact_sql = re.sub(r"\s+", " ", sql)

    for label in [
        "进入观察",
        "继续观察",
        "高风险观察",
        "降级观察",
        "剔除观察",
        "数据不足，不形成结论",
    ]:
        assert label in compact_sql

    assert re.search(r"check\s*\(\s*action\s+in\s*\(", compact_sql)
    assert re.search(r"check\s*\(\s*state\s+in\s*\(", compact_sql)

    policy_roles = set(re.findall(r"create policy .*? to ([a-z_][a-z0-9_]*) ", compact_sql))
    assert policy_roles == {"service_role"}


def test_initial_schema_has_idempotent_daily_unique_constraints():
    sql = SCHEMA_PATH.read_text().lower()
    compact_sql = re.sub(r"\s+", " ", sql)

    assert re.search(
        r"recommendation_daily.*unique\s*\(\s*trade_date\s*,\s*ts_code\s*\)",
        compact_sql,
    )
    assert re.search(
        r"focus_watchlist_state.*unique\s*\(\s*trade_date\s*,\s*ts_code\s*\)",
        compact_sql,
    )
    assert "evidence_id text primary key" in compact_sql
    assert re.search(
        (
            r"evaluation_task.*unique\s*\(\s*trade_date\s*,\s*ts_code\s*,"
            r"\s*evidence_id\s*,\s*checkpoint_days\s*,\s*evaluation_layer\s*\)"
        ),
        compact_sql,
    )
