from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path

import pandas as pd


_SCRIPT = Path(__file__).parents[1] / "tools" / "run_price_scenario_validation.py"
_SPEC = importlib.util.spec_from_file_location("price_scenario_validation_runner", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_merge_v2_features = _MODULE._merge_v2_features


def test_merge_replaces_v1_indicator_values_without_changing_outcomes() -> None:
    base = pd.DataFrame(
        {
            "analysis_date": [date(2025, 1, 2)],
            "ts_code": ["000001.SZ"],
            "formula_version": ["price-indicator-preregistered-v1"],
            "ema_distance_20d": [999.0],
            "hit_20pct_d20": [1],
            "return_close_d20": [0.12],
        }
    )
    v2 = pd.DataFrame(
        {
            "analysis_date": [date(2025, 1, 2)],
            "ts_code": ["000001.SZ"],
            "formula_version": ["price-indicator-conditional-states-v2"],
            "ema_distance_20d": [0.02],
            "dmi_directional_spread_14d": [5.0],
        }
    )

    observed = _merge_v2_features(base, v2)

    assert observed.iloc[0]["formula_version"] == "price-indicator-conditional-states-v2"
    assert observed.iloc[0]["ema_distance_20d"] == 0.02
    assert observed.iloc[0]["dmi_directional_spread_14d"] == 5.0
    assert observed.iloc[0]["hit_20pct_d20"] == 1
    assert observed.iloc[0]["return_close_d20"] == 0.12
