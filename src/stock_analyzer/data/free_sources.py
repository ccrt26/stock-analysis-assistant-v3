from __future__ import annotations

from datetime import date
from typing import Protocol

from stock_analyzer.data.models import DailyBar, SourceGrade


class BackupDailyClient(Protocol):
    def fetch_rows(self, trade_date: date) -> list[dict]: ...


class LiveBackupDailySource:
    def __init__(self, name: str, client: BackupDailyClient) -> None:
        self.name = name
        self.client = client

    def fetch_daily(self, trade_date: date) -> list[DailyBar]:
        rows = self.client.fetch_rows(trade_date)
        return [
            DailyBar(
                trade_date=trade_date,
                ts_code=str(row["ts_code"]),
                close=float(row["close"]),
                vol=_optional_float(row, "vol"),
                amount=_optional_float(row, "amount"),
                source_name=self.name,
                source_grade=SourceGrade.LIVE_BACKUP,
            )
            for row in rows
        ]


LiveBackupSource = LiveBackupDailySource


def _optional_float(row: dict, key: str) -> float | None:
    value = row.get(key)
    return None if value is None else float(value)
