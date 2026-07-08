from __future__ import annotations

from datetime import date
from statistics import pstdev

from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    DataStatus,
    MarketDataBundle,
    SourceGrade,
    SourceRunRecord,
    StockBasicRow,
)
from stock_analyzer.domain.models import FeatureSnapshot, StockSnapshot


class InsufficientFeatureCoverage(RuntimeError):
    pass


def build_market_bundle(
    *,
    trade_date: date,
    stock_basic: list[StockBasicRow],
    daily_bars: list[DailyBar],
    daily_basic: list[DailyBasicRow],
    data_status: DataStatus,
    source_grade: SourceGrade,
    source_versions: dict[str, str],
    source_runs: list[SourceRunRecord],
) -> MarketDataBundle:
    bars_by_code: dict[str, list[DailyBar]] = {}
    for bar in daily_bars:
        bars_by_code.setdefault(bar.ts_code, []).append(bar)

    basics_by_code = {
        item.ts_code: item for item in daily_basic if item.trade_date == trade_date
    }
    current_codes = {bar.ts_code for bar in daily_bars if bar.trade_date == trade_date}
    can_generate_decisions = data_status in {
        DataStatus.COMPLETE_PRIMARY,
        DataStatus.COMPLETE_LIVE_BACKUP,
    }
    if not current_codes and can_generate_decisions:
        raise InsufficientFeatureCoverage("current trade date live bars are required for decisions")

    stocks: list[StockSnapshot] = []
    feature_profiles: dict[str, FeatureSnapshot] = {}
    stock_names: dict[str, str] = {}
    for stock in stock_basic:
        stock_names[stock.ts_code] = stock.name
        current_basic = basics_by_code.get(stock.ts_code)
        current_bars = sorted(
            bars_by_code.get(stock.ts_code, []), key=lambda item: item.trade_date
        )
        if stock.ts_code not in current_codes or len(current_bars) < 61:
            continue

        stocks.append(
            StockSnapshot(
                trade_date=trade_date,
                ts_code=stock.ts_code,
                name=stock.name,
                listing_days=_listing_days(stock.list_date, trade_date),
                turnover_rate=current_basic.turnover_rate if current_basic else None,
                amount=current_bars[-1].amount,
            )
        )
        feature_profiles[stock.ts_code] = FeatureSnapshot(
            trade_date=trade_date,
            ts_code=stock.ts_code,
            trend_20d=_trend(current_bars, 20),
            trend_60d=_trend(current_bars, 60),
            relative_strength=_trend(current_bars, 20),
            volatility_20d=_volatility(current_bars[-20:]),
            liquidity_score=_liquidity_score(current_bars[-1].amount),
            quality_score=0.7 if current_basic else 0.5,
            market_regime="unknown",
            data_quality="ok" if current_basic else "missing_daily_basic",
        )

    return MarketDataBundle(
        trade_date=trade_date,
        data_status=data_status,
        source_grade=source_grade,
        source_versions=source_versions,
        stock_basic=stock_basic,
        daily_bars=daily_bars,
        daily_basic=daily_basic,
        source_runs=source_runs,
        stocks=stocks,
        stock_names=stock_names,
        feature_profiles=feature_profiles,
    )


def _listing_days(list_date: date | None, trade_date: date) -> int:
    if list_date is None:
        return 9999
    return max((trade_date - list_date).days, 0)


def _trend(bars: list[DailyBar], window: int) -> float:
    start = bars[-window - 1].close
    end = bars[-1].close
    return 0.0 if start == 0 else (end - start) / start


def _volatility(bars: list[DailyBar]) -> float:
    closes = [bar.close for bar in bars]
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]
    return pstdev(returns) if len(returns) > 1 else 0.0


def _liquidity_score(amount: float | None) -> float:
    if amount is None:
        return 0.0
    return min(amount / 500000000.0, 1.0)
