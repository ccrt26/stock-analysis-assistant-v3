from datetime import date
from pathlib import Path

import duckdb
import pytest

from stock_analyzer.evaluation.v3_backtest.calendar import build_frozen_calendar


@pytest.fixture(scope="module")
def open_sessions() -> tuple[date, ...]:
    warehouse_root = Path(__file__).parents[3] / "local_warehouse" / "facts"
    calendar_paths = sorted((warehouse_root / "trade_calendar").rglob("*.parquet"))
    if not calendar_paths:
        pytest.fail("frozen backtest requires the local trade_calendar facts")

    with duckdb.connect() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT cal_date
            FROM read_parquet(?, union_by_name = true)
            WHERE is_open
            ORDER BY cal_date
            """,
            [[str(path) for path in calendar_paths]],
        ).fetchall()
    return tuple(row[0] for row in rows)


def test_calendar_has_174_operational_and_144_mature_sessions(open_sessions):
    calendar = build_frozen_calendar(open_sessions, data_end=date(2026, 7, 17))

    assert calendar.operational[0] == date(2025, 10, 30)
    assert calendar.operational[-1] == date(2026, 7, 17)
    assert calendar.mature[-1] == date(2026, 6, 4)
    assert len(calendar.operational) == 174
    assert len(calendar.mature) == 144
    assert len(calendar.maintenance_tail) == 30
    assert tuple(map(len, calendar.blocks)) == (30, 30, 30, 30, 24)


def test_calendar_preserves_mature_and_operational_contracts(open_sessions):
    calendar = build_frozen_calendar(open_sessions, data_end=date(2026, 7, 17))

    assert calendar.mature[0] == date(2025, 10, 30)
    assert calendar.mature[-1] == date(2026, 6, 4)
    assert calendar.maintenance_tail[0] == date(2026, 6, 5)
    assert calendar.maintenance_tail[-1] == date(2026, 7, 17)
    assert calendar.operational == calendar.mature + calendar.maintenance_tail
    assert tuple(origin for block in calendar.blocks for origin in block) == calendar.mature
    assert calendar.primary == calendar.mature
    assert calendar.maturity_end == date(2026, 7, 17)


def test_frozen_calendar_fails_closed_before_all_outcomes_mature(open_sessions):
    with pytest.raises(ValueError, match="maturity end"):
        build_frozen_calendar(open_sessions, data_end=date(2026, 7, 16))


def test_frozen_calendar_fails_when_a_frozen_origin_is_not_open(open_sessions):
    incomplete = tuple(
        session for session in open_sessions if session != date(2026, 1, 26)
    )

    with pytest.raises(ValueError, match="block C"):
        build_frozen_calendar(incomplete, data_end=date(2026, 7, 17))


def test_frozen_calendar_requires_thirty_future_sessions(open_sessions):
    incomplete = tuple(
        session for session in open_sessions if session != date(2026, 6, 11)
    )

    with pytest.raises(ValueError, match="maintenance tail"):
        build_frozen_calendar(incomplete, data_end=date(2026, 7, 17))
