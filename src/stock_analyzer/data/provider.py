from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

from stock_analyzer.config import AppConfig
from stock_analyzer.data.feature_builder import (
    InsufficientFeatureCoverage,
    build_market_bundle,
)
from stock_analyzer.data.models import (
    DailyBar,
    DataStatus,
    MarketDataBundle,
    SourceGrade,
    SourceRunRecord,
    SourceStatus,
)
from stock_analyzer.data.tushare_source import TushareMarketDataSource


_DAILY_HISTORY_LOOKBACK_DAYS = 120


class CurrentLiveDataUnavailable(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    def load(self, trade_date: date) -> MarketDataBundle: ...


class TushareProvider:
    def __init__(self, source: TushareMarketDataSource) -> None:
        self.source = source

    def load(self, trade_date: date) -> MarketDataBundle:
        stock_basic = self.source.fetch_stock_basic()
        daily_bars = _fetch_daily_history(self.source, trade_date)
        current_daily_bars = [bar for bar in daily_bars if bar.trade_date == trade_date]
        if not current_daily_bars:
            raise CurrentLiveDataUnavailable(
                "Tushare returned no current trade date daily bars for "
                f"{trade_date.isoformat()}"
            )
        daily_basic = self.source.fetch_daily_basic(trade_date)
        source_runs = [
            SourceRunRecord(
                trade_date=trade_date,
                source_name="tushare",
                stage="daily",
                status=SourceStatus.SUCCESS,
                message="ok",
                source_grade=SourceGrade.PRIMARY,
                data_status=DataStatus.COMPLETE_PRIMARY,
                record_count=len(daily_bars),
            )
        ]
        try:
            bundle = build_market_bundle(
                trade_date=trade_date,
                stock_basic=stock_basic,
                daily_bars=daily_bars,
                daily_basic=daily_basic,
                data_status=DataStatus.COMPLETE_PRIMARY,
                source_grade=SourceGrade.PRIMARY,
                source_versions={"tushare": f"daily:{trade_date.isoformat()}"},
                source_runs=source_runs,
            )
        except InsufficientFeatureCoverage as exc:
            raise CurrentLiveDataUnavailable(str(exc)) from exc
        if not bundle.stocks or not bundle.feature_profiles:
            raise CurrentLiveDataUnavailable(
                "Tushare live data did not produce decision feature inputs for "
                f"{trade_date.isoformat()}"
            )
        return bundle


def _fetch_daily_history(
    source: TushareMarketDataSource,
    trade_date: date,
) -> list[DailyBar]:
    daily_bars = []
    for offset in range(_DAILY_HISTORY_LOOKBACK_DAYS, -1, -1):
        daily_bars.extend(source.fetch_daily(trade_date - timedelta(days=offset)))
    return daily_bars


def build_production_market_data_provider(config: AppConfig) -> MarketDataProvider:
    token = config.resolve_tushare_token()
    if not token:
        raise CurrentLiveDataUnavailable(
            "Tushare token is missing and no live backup provider is configured"
        )
    return TushareProvider(TushareMarketDataSource(token=token))
