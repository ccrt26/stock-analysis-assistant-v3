from __future__ import annotations

from datetime import date
from statistics import pstdev

from stock_analyzer.data.formal_policy import FORMAL_EQUITY_FEATURE_SESSION_COUNT
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


MIN_CURRENT_BAR_COVERAGE = 0.95


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
    stock_status_by_code: dict[str, dict[str, bool]] | None = None,
) -> MarketDataBundle:
    stock_status_by_code = stock_status_by_code or {}
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
    requested_codes = {stock.ts_code for stock in stock_basic}
    missing_current_codes = sorted(requested_codes - current_codes)
    if requested_codes and missing_current_codes and can_generate_decisions:
        current_bar_coverage = len(requested_codes & current_codes) / len(
            requested_codes
        )
        if current_bar_coverage < MIN_CURRENT_BAR_COVERAGE:
            missing = ", ".join(missing_current_codes[:20])
            if len(missing_current_codes) > 20:
                missing = f"{missing}, ..."
            raise InsufficientFeatureCoverage(
                "current trade date live bar coverage "
                f"{current_bar_coverage:.2%} is below minimum "
                f"{MIN_CURRENT_BAR_COVERAGE:.2%}; missing "
                f"{len(missing_current_codes)} of {len(requested_codes)}: {missing}"
            )

    if not current_codes and can_generate_decisions:
        raise InsufficientFeatureCoverage(
            "current trade date live bars are required for decisions"
        )

    stocks: list[StockSnapshot] = []
    feature_profiles: dict[str, FeatureSnapshot] = {}
    raw_relative_returns: dict[str, float] = {}
    stock_names: dict[str, str] = {}
    for stock in stock_basic:
        stock_names[stock.ts_code] = stock.name
        current_basic = basics_by_code.get(stock.ts_code)
        current_bars = sorted(
            (
                bar
                for bar in bars_by_code.get(stock.ts_code, [])
                if bar.trade_date <= trade_date
            ),
            key=lambda item: item.trade_date,
        )
        if not current_bars or current_bars[-1].trade_date != trade_date:
            continue
        if len(current_bars) < FORMAL_EQUITY_FEATURE_SESSION_COUNT:
            continue

        status = stock_status_by_code.get(stock.ts_code, {})
        stocks.append(
            StockSnapshot(
                trade_date=trade_date,
                ts_code=stock.ts_code,
                name=stock.name,
                listing_days=_listing_days(stock.list_date, trade_date),
                turnover_rate=current_basic.turnover_rate if current_basic else None,
                amount=current_bars[-1].amount,
                is_st=status.get("is_st", False),
                is_suspended=status.get("is_suspended", False),
                has_delisting_risk=status.get("has_delisting_risk", False),
            )
        )
        raw_relative_returns[stock.ts_code] = _trend(current_bars, 20)
        feature_profiles[stock.ts_code] = FeatureSnapshot(
            trade_date=trade_date,
            ts_code=stock.ts_code,
            trend_20d=_trend(current_bars, 20),
            trend_60d=_trend(current_bars, 60),
            relative_strength=raw_relative_returns[stock.ts_code],
            volatility_20d=_volatility(current_bars[-20:]),
            liquidity_score=_liquidity_score(current_bars[-1].amount),
            quality_score=0.7 if current_basic else 0.5,
            market_regime="unknown",
            data_quality="ok" if current_basic else "missing_daily_basic",
        )

    relative_strengths = _cross_sectional_percentiles(raw_relative_returns)
    feature_profiles = {
        code: feature.model_copy(
            update={"relative_strength": relative_strengths[code]}
        )
        for code, feature in feature_profiles.items()
    }

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


def _cross_sectional_percentiles(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    if len(values) == 1:
        return {next(iter(values)): 0.5}
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    output: dict[str, float] = {}
    index = 0
    denominator = len(ordered) - 1
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        percentile = ((index + end - 1) / 2) / denominator
        for code, _ in ordered[index:end]:
            output[code] = round(percentile, 6)
        index = end
    return output
