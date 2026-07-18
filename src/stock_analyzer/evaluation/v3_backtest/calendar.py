"""Frozen operating calendar for the continuous V3 backtest experiment.

The dates in this module are preregistered inputs.  The builder only validates
them against an open-session calendar; it never derives dates from outcomes or
market signals.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


_BLOCK_RANGES = (
    ("A", date(2025, 10, 30), date(2025, 12, 10), 30),
    ("B", date(2025, 12, 11), date(2026, 1, 23), 30),
    ("C", date(2026, 1, 26), date(2026, 3, 16), 30),
    ("D", date(2026, 3, 17), date(2026, 4, 28), 30),
    ("E", date(2026, 4, 29), date(2026, 6, 4), 24),
)
_MAINTENANCE_RANGE = (date(2026, 6, 5), date(2026, 7, 17), 30)
_MATURITY_END = _MAINTENANCE_RANGE[1]


@dataclass(frozen=True)
class BacktestCalendar:
    """Immutable operational and mature samples with their maturity boundary."""

    operational: tuple[date, ...]
    mature: tuple[date, ...]
    maintenance_tail: tuple[date, ...]
    blocks: tuple[tuple[date, ...], ...]
    maturity_end: date

    @property
    def primary(self) -> tuple[date, ...]:
        """Compatibility alias for the mature formation sample."""

        return self.mature


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
    mature = tuple(origin for block in blocks for origin in block)
    maintenance_tail = _validated_slice(
        sessions,
        start=_MAINTENANCE_RANGE[0],
        end=_MAINTENANCE_RANGE[1],
        expected_count=_MAINTENANCE_RANGE[2],
        label="maintenance tail",
    )
    if mature + maintenance_tail != tuple(
        session
        for session in sessions
        if mature[0] <= session <= _MATURITY_END
    ):
        raise ValueError("operational calendar must be mature sessions plus maintenance tail")

    return BacktestCalendar(
        operational=mature + maintenance_tail,
        mature=mature,
        maintenance_tail=maintenance_tail,
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
