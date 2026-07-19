from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_forward.inputs import (
    compress_attention_evidence,
    formation_cutoff,
    validate_derived_manifest,
    validate_health_report,
    validate_visible_facts,
)


FORMATION_DATE = date(2026, 7, 17)


def _evidence(code: str, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "formation_date": pd.Timestamp(FORMATION_DATE),
        "ts_code": code,
        "routes": "price",
        "company_evidence": False,
        "hard_invalid": False,
        "report_period": None,
        "tr_yoy": None,
        "netprofit_yoy": None,
        "dt_netprofit_yoy": None,
        "n_cashflow_act": None,
        "evidence_freshness": 1,
        "earnings_cash_consistency": 1,
        "hotspot_support": 1,
        "price_consumption_safety": 2,
        "liquidity": 2,
        "return_5d": 0.02,
        "return_20d": 0.05,
        "relative_return_20d": 0.03,
        "current_amount_ratio_20d": 1.2,
        "price_location_60d": 0.8,
        "average_amount_20d": 30000.0,
        "ocf_yoy": None,
        "pe_ttm": 15.0,
        "pb": 2.0,
    }
    row.update(overrides)
    return row


def test_formation_cutoff_is_end_of_local_formation_day():
    cutoff = formation_cutoff(FORMATION_DATE)

    assert cutoff.isoformat() == "2026-07-17T23:59:59+08:00"


def test_incomplete_health_report_is_rejected():
    with pytest.raises(ValueError, match="core data is incomplete"):
        validate_health_report(
            {"data_date": "2026-07-17", "complete_core_date": False},
            FORMATION_DATE,
        )


def test_derived_manifest_after_cutoff_is_rejected(tmp_path: Path):
    source = tmp_path / "data.parquet"
    pd.DataFrame({"x": [1]}).to_parquet(source, index=False)
    manifest = {
        "feature_set": "market_context",
        "formula_version": "market-context-v2",
        "quality_status": "complete",
        "input_manifest_json": {
            "fact_snapshot": {"as_of": "2026-07-18T00:00:00+08:00"}
        },
        "relative_path": source.name,
        "file_sha256": "not-used-before-cutoff-check",
    }

    with pytest.raises(ValueError, match="derived input exceeds cutoff"):
        validate_derived_manifest(manifest, FORMATION_DATE, tmp_path)


def test_fact_available_after_formation_is_rejected():
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "available_at": ["2026-07-18T00:00:00+08:00"],
        }
    )

    with pytest.raises(ValueError, match="future evidence"):
        validate_visible_facts(frame, FORMATION_DATE, "company")


def test_attention_is_unranked_capped_and_confirmation_matches_baseline():
    rows = [_evidence(f"C{i:02d}", liquidity=3 if i == 0 else 2) for i in range(12)]
    result = compress_attention_evidence(pd.DataFrame(rows))

    assert 0 < len(result) <= 10
    assert not result.duplicated(["formation_date", "ts_code"]).any()
    assert set(result["user_layer"]) == {"关注"}
    assert result["action_confirmed"].all()
    assert "score" not in result.columns


def test_attention_can_be_empty_and_future_paths_are_rejected():
    hard_invalid = pd.DataFrame([_evidence("BAD", hard_invalid=True)])
    empty = compress_attention_evidence(hard_invalid)

    assert empty.empty

    future = pd.DataFrame([_evidence("BAD", action_price=10.0)])
    with pytest.raises(ValueError, match="future field"):
        compress_attention_evidence(future)
