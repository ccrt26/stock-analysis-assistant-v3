"""Frozen formation calendar for the complete V3 backtest experiment.

The dates in this module are preregistered inputs.  The builder only validates
them against an open-session calendar; it never derives dates from outcomes or
market signals.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


_EXTENSION_RANGE = (date(2025, 8, 15), date(2025, 10, 29), 48)
_BLOCK_RANGES = (
    ("A", date(2025, 10, 30), date(2026, 1, 7), 48),
    ("B", date(2026, 1, 8), date(2026, 3, 24), 48),
    ("C", date(2026, 3, 25), date(2026, 6, 3), 47),
)
_MATURITY_END = date(2026, 7, 16)
_MAX_HORIZON = 30


@dataclass(frozen=True)
class BacktestCalendar:
    """Immutable, non-overlapping formation samples and maturity boundary."""

    primary: tuple[date, ...]
    extension: tuple[date, ...]
    blocks: tuple[tuple[date, ...], ...]
    maturity_end: date


def build_frozen_calendar(
    open_sessions: Sequence[date],
    *,
    data_end: date,
) -> BacktestCalendar:
    """Validate and return the preregistered calendar.

    ``data_end`` is the common actual cutoff of ``trade_calendar`` and
    ``equity_daily``.  It must cover the frozen maturity boundary.  No price or
    return field is accepted by this interface.
    """

    sessions = tuple(sorted(set(open_sessions)))
    if not sessions:
        raise ValueError("open-session calendar is empty")
    if data_end < _MATURITY_END:
        raise ValueError(
            f"data end {data_end.isoformat()} is before maturity end "
            f"{_MATURITY_END.isoformat()}"
        )

    extension = _validated_slice(
        sessions,
        start=_EXTENSION_RANGE[0],
        end=_EXTENSION_RANGE[1],
        expected_count=_EXTENSION_RANGE[2],
        label="extension",
    )
    blocks = tuple(
        _validated_slice(
            sessions,
            start=start,
            end=end,
            expected_count=expected_count,
            label=f"block {label}",
        )
        for label, start, end, expected_count in _BLOCK_RANGES
    )
    primary = tuple(origin for block in blocks for origin in block)

    future_sessions = tuple(
        session for session in sessions if primary[-1] < session <= _MATURITY_END
    )
    if len(future_sessions) != _MAX_HORIZON:
        raise ValueError(
            "frozen maturity window must contain exactly 30 future open sessions; "
            f"found {len(future_sessions)}"
        )
    if future_sessions[-1] != _MATURITY_END:
        raise ValueError("maturity end is not an open session")

    return BacktestCalendar(
        primary=primary,
        extension=extension,
        blocks=blocks,
        maturity_end=_MATURITY_END,
    )


def _validated_slice(
    sessions: tuple[date, ...],
    *,
    start: date,
    end: date,
    expected_count: int,
    label: str,
) -> tuple[date, ...]:
    selected = tuple(session for session in sessions if start <= session <= end)
    if (
        len(selected) != expected_count
        or not selected
        or selected[0] != start
        or selected[-1] != end
    ):
        raise ValueError(
            f"frozen {label} must contain {expected_count} open sessions from "
            f"{start.isoformat()} through {end.isoformat()}; found {len(selected)}"
        )
    return selected
