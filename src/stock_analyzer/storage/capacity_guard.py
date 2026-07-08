from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


MAX_SELECTED_WINDOW_CODES = 40
MAX_SELECTED_WINDOW_ROWS = 5000


class SupabaseCapacityLimitExceeded(RuntimeError):
    pass


class SupabaseWriteScopeError(ValueError):
    pass


@dataclass(frozen=True)
class CapacityStatus:
    size_mb: float
    warn: bool
    stop_large_writes: bool


class SupabaseCapacityGuard:
    def __init__(self, client, *, warn_mb: float, stop_mb: float) -> None:
        self.client = client
        self.warn_mb = warn_mb
        self.stop_mb = stop_mb

    def check(self) -> CapacityStatus:
        result = self.client.rpc("database_size_mb").execute()
        size_mb = float(result.data)
        return CapacityStatus(
            size_mb=size_mb,
            warn=size_mb >= self.warn_mb,
            stop_large_writes=size_mb >= self.stop_mb,
        )

    def ensure_large_writes_allowed(self) -> CapacityStatus:
        status = self.check()
        if status.stop_large_writes:
            raise SupabaseCapacityLimitExceeded(
                f"Supabase database size is {status.size_mb:.1f} MB; large writes stop at {self.stop_mb:.1f} MB"
            )
        return status


def ensure_selected_market_window_scope(rows: Sequence[object]) -> None:
    ts_codes = {getattr(row, "ts_code") for row in rows}
    if len(ts_codes) > MAX_SELECTED_WINDOW_CODES or len(rows) > MAX_SELECTED_WINDOW_ROWS:
        raise SupabaseWriteScopeError(
            "Supabase selected market window write rejected: "
            f"{len(ts_codes)} codes and {len(rows)} rows exceeds "
            f"{MAX_SELECTED_WINDOW_CODES} codes or {MAX_SELECTED_WINDOW_ROWS} rows"
        )
