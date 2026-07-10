from datetime import date

from stock_analyzer.data.models import SourceStatus
from stock_analyzer.data.source_registry import (
    DataFamilySourcePlan,
    record_recovery_attempt,
    strategy_v2_source_registry,
)
from stock_analyzer.domain.models import DataRequirementLevel


def test_required_data_families_have_primary_backup_and_local_cache():
    registry = strategy_v2_source_registry()
    required_families = [
        "stock_identity",
        "daily_ohlcv",
        "daily_basic_valuation",
        "company_profile",
        "industry_board",
        "market_board_context",
        "official_hard_risk",
        "manual_holdings",
    ]

    for family in required_families:
        plan = registry[family]
        assert isinstance(plan, DataFamilySourcePlan)
        assert plan.level == DataRequirementLevel.REQUIRED
        assert plan.primary_path
        assert plan.local_cache_path
        if family != "manual_holdings":
            assert plan.backup_path


def test_source_registry_names_exact_collection_paths():
    registry = strategy_v2_source_registry()

    assert registry["daily_ohlcv"].primary_path == "TushareMarketDataSource.fetch_daily"
    assert registry["daily_ohlcv"].backup_path == "akshare.stock_zh_a_hist"
    assert (
        registry["daily_basic_valuation"].primary_path
        == "TushareMarketDataSource.fetch_daily_basic"
    )
    assert (
        registry["fundamentals_summary"].primary_path
        == "tushare.income|balancesheet|cashflow|fina_indicator|forecast|express"
    )
    assert (
        registry["events_catalysts"].backup_path
        == "eastmoney.announcements|sse.disclosure_cache|szse.disclosure_cache"
    )


def test_recovery_attempt_serializes_without_secrets():
    attempt = record_recovery_attempt(
        family="daily_ohlcv",
        source_name="tushare.daily",
        status=SourceStatus.FAILED,
        message="request failed without exposing token",
        trade_date=date(2026, 7, 10),
    )

    payload = attempt.model_dump(mode="json")

    assert payload["family"] == "daily_ohlcv"
    assert payload["source_name"] == "tushare.daily"
    assert payload["status"] == "failed"
    assert "token" not in payload["message"].lower()
