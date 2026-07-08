from __future__ import annotations

from stock_analyzer.domain.models import EvidencePackage, EvaluationTask
from stock_analyzer.evaluation.trading_calendar import (
    TradingCalendar,
    WeekdayTradingCalendar,
)


def create_evaluation_tasks(
    package: EvidencePackage,
    trading_calendar: TradingCalendar | None = None,
) -> list[EvaluationTask]:
    calendar = trading_calendar or WeekdayTradingCalendar()
    schedule = [
        (5, "result"),
        (20, "result"),
        (40, "result"),
        (20, "method"),
        (40, "method"),
        (40, "knowledge"),
    ]
    return [
        EvaluationTask(
            trade_date=package.trade_date,
            ts_code=package.ts_code,
            evidence_id=package.evidence_id,
            checkpoint_days=days,
            due_date=calendar.add_trading_days(package.trade_date, days),
            evaluation_layer=layer,
        )
        for days, layer in schedule
    ]
