from __future__ import annotations

from datetime import date
from typing import Protocol

from stock_analyzer.config import AppConfig
from stock_analyzer.data.models import (
    DataStatus,
    MarketDataBundle,
    SourceGrade,
    SourceRunRecord,
    SourceStatus,
)
from stock_analyzer.data.tushare_source import TushareMarketDataSource


class CurrentLiveDataUnavailable(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    def load(self, trade_date: date) -> MarketDataBundle: ...


class TushareProvider:
    def __init__(self, source: TushareMarketDataSource) -> None:
        self.source = source

    def load(self, trade_date: date) -> MarketDataBundle:
        stock_basic = self.source.fetch_stock_basic()
        daily_bars = self.source.fetch_daily(trade_date)
        daily_basic = self.source.fetch_daily_basic(trade_date)
        if not daily_bars:
            raise CurrentLiveDataUnavailable(
                f"Tushare returned no current daily bars for {trade_date.isoformat()}"
            )
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
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"tushare": f"daily:{trade_date.isoformat()}"},
            stock_basic=stock_basic,
            daily_bars=daily_bars,
            daily_basic=daily_basic,
            source_runs=source_runs,
        )


def build_production_market_data_provider(config: AppConfig) -> MarketDataProvider:
    token = config.resolve_tushare_token()
    if not token:
        raise CurrentLiveDataUnavailable(
            "Tushare token is missing and no live backup provider is configured"
        )
    return TushareProvider(TushareMarketDataSource(token=token))
