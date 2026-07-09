from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Mapping


TradingDayStatus = Literal["trading_day", "non_trading_day", "calendar_unknown"]


@dataclass(frozen=True)
class TradingDayDecision:
    status: TradingDayStatus
    source: str
    message: str


def decide_trading_day(
    trade_date: date,
    repository,
    tushare_calendar_loader=None,
) -> TradingDayDecision:
    try:
        supabase_value = repository.load_market_calendar_day(trade_date)
    except Exception:
        return TradingDayDecision(
            status="calendar_unknown",
            source="unknown",
            message=(
                "Supabase market_calendar lookup failed; trading-day status "
                "requires human review."
            ),
        )

    if supabase_value is not None:
        return _decision_from_calendar_value(trade_date, bool(supabase_value), "supabase")

    if tushare_calendar_loader is None:
        return TradingDayDecision(
            status="calendar_unknown",
            source="unknown",
            message=(
                "No Supabase market_calendar row and no Tushare calendar loader "
                "was provided."
            ),
        )

    try:
        tushare_calendar = _fetch_tushare_calendar(tushare_calendar_loader, trade_date)
        is_trading_day = tushare_calendar.get(trade_date)
    except Exception:
        return TradingDayDecision(
            status="calendar_unknown",
            source="unknown",
            message=(
                "No Supabase market_calendar row and Tushare calendar lookup "
                "failed; trading-day status requires human review."
            ),
        )

    if is_trading_day is None:
        return TradingDayDecision(
            status="calendar_unknown",
            source="unknown",
            message=(
                "No Supabase market_calendar row and Tushare returned no row "
                f"for {trade_date.isoformat()}."
            ),
        )

    try:
        repository.save_market_calendar_day(
            trade_date,
            bool(is_trading_day),
            market="CN_A",
        )
    except Exception:
        return TradingDayDecision(
            status="calendar_unknown",
            source="unknown",
            message=(
                "Tushare returned a calendar row, but Supabase market_calendar "
                "writeback failed; trading-day status requires human review."
            ),
        )

    return _decision_from_calendar_value(trade_date, bool(is_trading_day), "tushare")


def _fetch_tushare_calendar(loader, trade_date: date) -> Mapping[date, bool]:
    if hasattr(loader, "fetch_trade_calendar"):
        return loader.fetch_trade_calendar(trade_date, trade_date)
    if callable(loader):
        return loader(trade_date, trade_date)
    raise TypeError("tushare_calendar_loader must fetch a trade calendar")


def _decision_from_calendar_value(
    trade_date: date,
    is_trading_day: bool,
    source: str,
) -> TradingDayDecision:
    if is_trading_day:
        return TradingDayDecision(
            status="trading_day",
            source=source,
            message=f"{trade_date.isoformat()} is a trading day from {source}.",
        )
    return TradingDayDecision(
        status="non_trading_day",
        source=source,
        message=f"{trade_date.isoformat()} is not a trading day from {source}.",
    )
