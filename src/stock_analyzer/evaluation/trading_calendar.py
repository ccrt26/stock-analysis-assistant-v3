from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol


class TradingCalendar(Protocol):
    def is_trading_day(self, day: date) -> bool: ...

    def add_trading_days(self, start: date, trading_days: int) -> date: ...


@dataclass(frozen=True)
class WeekdayTradingCalendar:
    holidays: set[date] = field(default_factory=set)
    extra_trading_days: set[date] = field(default_factory=set)

    def is_trading_day(self, day: date) -> bool:
        if day in self.extra_trading_days:
            return True
        if day in self.holidays:
            return False
        return day.weekday() < 5

    def add_trading_days(self, start: date, trading_days: int) -> date:
        if trading_days < 0:
            raise ValueError("trading_days must be non-negative")
        current = start
        remaining = trading_days
        while remaining:
            current += timedelta(days=1)
            if self.is_trading_day(current):
                remaining -= 1
        return current
