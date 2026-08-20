from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).parents[1] / "tools" / "run_price_indicator_validation.py"
_SPEC = importlib.util.spec_from_file_location("price_indicator_validation_runner", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_apply_universe_filters = _MODULE._apply_universe_filters


def test_universe_filter_normalizes_duckdb_timestamps_to_formation_dates() -> None:
    sample = pd.DataFrame(
        {
            "analysis_date": [date(2022, 7, 26)],
            "action_date": [date(2022, 7, 27)],
            "ts_code": ["000001.SZ"],
            "available_price_sessions": [100],
        }
    )
    equity = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2022-07-26", "2022-07-27"]),
            "ts_code": ["000001.SZ", "000001.SZ"],
            "pre_close": [10.0, 10.1],
            "up_limit": [11.0, 11.11],
            "down_limit": [9.0, 9.09],
        }
    )
    securities = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "list_date": [date(1991, 4, 3)],
            "delist_date": [pd.NaT],
        }
    )

    observed = _apply_universe_filters(sample, equity, securities)

    assert len(observed) == 1
    assert observed.iloc[0]["analysis_date"] == date(2022, 7, 26)
