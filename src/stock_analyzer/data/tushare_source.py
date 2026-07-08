from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

import pandas as pd

from stock_analyzer.data.models import DailyBar, DailyBasicRow, SourceGrade, StockBasicRow


class MissingTushareField(RuntimeError):
    pass


class TushareUnavailable(RuntimeError):
    pass


class TushareMarketDataSource:
    def __init__(self, token: str, pro: Optional[object] = None) -> None:
        self.source_name = "tushare"
        self.token = token
        self.pro = pro or _create_tushare_pro(token)

    def fetch_stock_basic(self) -> list[StockBasicRow]:
        df = self.pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,name,exchange,list_date",
        )
        _require_columns(df, ["ts_code", "name", "exchange", "list_date"], "stock_basic")
        return [
            StockBasicRow(
                ts_code=str(row.ts_code),
                name=str(row.name),
                exchange=str(row.exchange),
                list_date=_parse_yyyymmdd(row.list_date),
            )
            for row in df.itertuples(index=False)
        ]

    def fetch_trade_calendar(self, start_date: date, end_date: date) -> dict[date, bool]:
        df = self.pro.trade_cal(
            exchange="SSE",
            start_date=_format_yyyymmdd(start_date),
            end_date=_format_yyyymmdd(end_date),
            fields="cal_date,is_open",
        )
        _require_columns(df, ["cal_date", "is_open"], "trade_cal")
        return {
            _parse_yyyymmdd(row.cal_date): int(row.is_open) == 1
            for row in df.itertuples(index=False)
        }

    def fetch_daily(self, trade_date: date) -> list[DailyBar]:
        df = self.pro.daily(trade_date=_format_yyyymmdd(trade_date))
        required = ["ts_code", "trade_date", "close", "amount"]
        _require_columns(df, required, "daily")
        return [
            DailyBar(
                trade_date=_parse_yyyymmdd(row.trade_date),
                ts_code=str(row.ts_code),
                open=_optional_float(row, "open"),
                high=_optional_float(row, "high"),
                low=_optional_float(row, "low"),
                close=float(row.close),
                pre_close=_optional_float(row, "pre_close"),
                pct_chg=_optional_float(row, "pct_chg"),
                vol=_optional_float(row, "vol"),
                amount=_optional_float(row, "amount"),
                source_name=self.source_name,
                source_grade=SourceGrade.PRIMARY,
            )
            for row in df.itertuples(index=False)
        ]

    def fetch_daily_basic(self, trade_date: date) -> list[DailyBasicRow]:
        df = self.pro.daily_basic(trade_date=_format_yyyymmdd(trade_date))
        _require_columns(df, ["ts_code", "trade_date", "turnover_rate"], "daily_basic")
        return [
            DailyBasicRow(
                trade_date=_parse_yyyymmdd(row.trade_date),
                ts_code=str(row.ts_code),
                turnover_rate=_optional_float(row, "turnover_rate"),
                total_mv=_optional_float(row, "total_mv"),
                circ_mv=_optional_float(row, "circ_mv"),
                pe_ttm=_optional_float(row, "pe_ttm"),
                pb=_optional_float(row, "pb"),
                source_name=self.source_name,
                source_grade=SourceGrade.PRIMARY,
            )
            for row in df.itertuples(index=False)
        ]


def _create_tushare_pro(token: str):
    try:
        import tushare as ts
    except ImportError as exc:
        raise TushareUnavailable("tushare package is not installed; install tushare before live source access") from exc
    ts.set_token(token)
    return ts.pro_api()


def _require_columns(df: pd.DataFrame, names: Iterable[str], stage: str) -> None:
    missing = [name for name in names if name not in df.columns]
    if missing:
        raise MissingTushareField(f"Tushare {stage} response missing fields: {', '.join(missing)}")


def _parse_yyyymmdd(value) -> date:
    text = str(value)
    return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))


def _format_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _optional_float(row, name: str) -> Optional[float]:
    if not hasattr(row, name):
        return None
    value = getattr(row, name)
    if pd.isna(value):
        return None
    return float(value)
