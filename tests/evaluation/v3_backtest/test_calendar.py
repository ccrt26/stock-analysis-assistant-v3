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


def test_frozen_calendar_has_143_primary_and_48_extension_origins(open_sessions):
    calendar = build_frozen_calendar(open_sessions, data_end=date(2026, 7, 16))

    assert calendar.primary[0] == date(2025, 10, 30)
    assert calendar.primary[-1] == date(2026, 6, 3)
    assert len(calendar.primary) == 143
    assert tuple(map(len, calendar.blocks)) == (48, 48, 47)
    assert len(calendar.extension) == 48
    assert calendar.maturity_end == date(2026, 7, 16)


def test_frozen_calendar_keeps_extension_and_primary_disjoint(open_sessions):
    calendar = build_frozen_calendar(open_sessions, data_end=date(2026, 7, 16))

    assert calendar.extension[0] == date(2025, 8, 15)
    assert calendar.extension[-1] == date(2025, 10, 29)
    assert not set(calendar.extension).intersection(calendar.primary)
    assert tuple(origin for block in calendar.blocks for origin in block) == calendar.primary


def test_frozen_calendar_fails_closed_before_all_outcomes_mature(open_sessions):
    with pytest.raises(ValueError, match="maturity end"):
        build_frozen_calendar(open_sessions, data_end=date(2026, 7, 15))


def test_frozen_calendar_fails_when_a_frozen_origin_is_not_open(open_sessions):
    incomplete = tuple(
        session for session in open_sessions if session != date(2026, 1, 8)
    )

    with pytest.raises(ValueError, match="block B"):
        build_frozen_calendar(incomplete, data_end=date(2026, 7, 16))


def test_frozen_calendar_requires_thirty_future_sessions(open_sessions):
    incomplete = tuple(
        session for session in open_sessions if session != date(2026, 6, 10)
    )

    with pytest.raises(ValueError, match="30 future open sessions"):
        build_frozen_calendar(incomplete, data_end=date(2026, 7, 16))
