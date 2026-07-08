from __future__ import annotations

from datetime import date


class CachePolicy:
    def can_use_for_historical_window(
        self,
        record_trade_date: date,
        target_trade_date: date,
    ) -> bool:
        return record_trade_date < target_trade_date

    def can_use_for_current_decision(
        self,
        record_trade_date: date,
        target_trade_date: date,
    ) -> bool:
        return False
