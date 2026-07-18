from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_layered_validation import (
    EXPECTED_NOT_TESTABLE_ROUTES,
    EXPECTED_SUPPORTED_ROUTES,
    add_recomputed_pct_chg,
    bound_as_of,
    challenger_can_replace,
    classify_module,
    compress_candidates,
    load_config,
    limit_to_tradable_route,
    prepare_output_root,
    select_latest_available_financials,
    update_project_states,
)


CONFIG_PATH = Path(
    "docs/superpowers/specs/2026-07-18-v3-layered-validation-config.yaml"
)


def test_frozen_config_preserves_three_thirty_session_blocks_and_targets():
    config = load_config(CONFIG_PATH)

    assert [(block.id, block.start.isoformat(), block.end.isoformat()) for block in config.blocks] == [
        ("A", "2025-10-30", "2025-12-10"),
        ("B", "2026-01-26", "2026-03-16"),
        ("C", "2026-04-20", "2026-06-03"),
    ]
    assert config.horizons == (10, 20, 30)
    assert config.target_return == pytest.approx(0.20)
    assert config.candidate_cap == 10
    assert config.focus_cap == 5


def test_frozen_config_declares_only_supported_and_not_testable_routes():
    config = load_config(CONFIG_PATH)

    assert config.supported_routes == EXPECTED_SUPPORTED_ROUTES
    assert config.not_testable_routes == EXPECTED_NOT_TESTABLE_ROUTES


def test_prepare_output_root_rejects_non_usb_path(tmp_path: Path):
    config = load_config(CONFIG_PATH)

    with pytest.raises(ValueError, match="U盘专用目录"):
        prepare_output_root(config, output_override=tmp_path / "experiment")


def test_prepare_output_root_creates_only_experiment_children(tmp_path: Path):
    config = load_config(CONFIG_PATH)
    volume = tmp_path / "ZHUTONG"
    unrelated = volume / "其他文件.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")
    experiment = volume / "股票分析助手-V3回测" / config.experiment_id

    prepared = prepare_output_root(
        config,
        output_override=experiment,
        allowed_volume_root=volume,
    )

    assert prepared == experiment
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert {path.name for path in experiment.iterdir()} == {
        "manifests",
        "tables",
        "reports",
    }


def test_bound_as_of_removes_future_rows_and_rejects_future_availability():
    facts = pd.DataFrame(
        {
            "trade_date": ["2026-01-05", "2026-01-06"],
            "available_at": ["2026-01-05T16:00:00+08:00", "2026-01-06T16:00:00+08:00"],
            "close": [10.0, 20.0],
        }
    )

    bounded = bound_as_of(facts, formation_date="2026-01-05", fact_date_column="trade_date")

    assert bounded["close"].tolist() == [10.0]
    assert pd.to_datetime(bounded["available_at"], utc=True).max() <= pd.Timestamp(
        "2026-01-05T23:59:59+08:00"
    ).tz_convert("UTC")


def test_financial_selection_uses_available_at_then_latest_period():
    facts = pd.DataFrame(
        {
            "ts_code": ["A", "A", "A", "B"],
            "report_period": ["2025-06-30", "2025-09-30", "2025-06-30", "2025-06-30"],
            "available_at": [
                "2025-08-30T18:00:00+08:00",
                "2025-10-31T18:00:00+08:00",
                "2025-09-01T18:00:00+08:00",
                "2025-08-31T18:00:00+08:00",
            ],
            "revision_no": [1, 1, 2, 1],
            "tr_yoy": [10.0, 99.0, 12.0, 20.0],
        }
    )

    selected = select_latest_available_financials(facts, formation_date="2025-10-01")

    assert selected.set_index("ts_code")["tr_yoy"].to_dict() == {"A": 12.0, "B": 20.0}
    assert (pd.to_datetime(selected["available_at"], utc=True) <= pd.Timestamp("2025-10-01 23:59:59", tz="Asia/Shanghai").tz_convert("UTC")).all()


def test_recomputed_pct_change_uses_adjacent_close_for_every_partition():
    prices = pd.DataFrame(
        {
            "trade_date": ["2026-01-05", "2026-01-06", "2026-01-07"],
            "ts_code": ["A", "A", "A"],
            "close": [10.0, 11.0, 9.9],
            "pct_chg": [999.0, 999.0, 999.0],
        }
    )

    result = add_recomputed_pct_chg(prices)

    assert pd.isna(result.iloc[0]["recomputed_pct_chg"])
    assert result.iloc[1]["recomputed_pct_chg"] == pytest.approx(10.0)
    assert result.iloc[2]["recomputed_pct_chg"] == pytest.approx(-10.0)
    assert result["pct_chg"].tolist() == [999.0, 999.0, 999.0]


def test_compression_keeps_hotspot_and_price_only_names_in_research_pool():
    evidence = pd.DataFrame(
        [
            _evidence_row("A", routes="hotspot|price", company_evidence=False),
            _evidence_row("B", routes="earnings", company_evidence=True),
        ]
    )

    decisions = compress_candidates(evidence, candidate_cap=10, focus_cap=5)

    assert decisions.set_index("ts_code")["layer"].to_dict() == {
        "A": "research_only",
        "B": "focus",
    }
    assert decisions.set_index("ts_code").loc["A", "decision_reason"] == "missing_company_opportunity_evidence"


def test_compression_uses_pareto_dominance_without_composite_score():
    evidence = pd.DataFrame(
        [
            _evidence_row("A", freshness=3, consistency=3, hotspot=2, price_safety=2, liquidity=3),
            _evidence_row("B", freshness=2, consistency=3, hotspot=2, price_safety=2, liquidity=3),
            _evidence_row("C", freshness=3, consistency=2, hotspot=3, price_safety=3, liquidity=2),
        ]
    )

    decisions = compress_candidates(evidence, candidate_cap=10, focus_cap=5)
    indexed = decisions.set_index("ts_code")

    assert indexed.loc["B", "layer"] == "dominated"
    assert indexed.loc["B", "dominated_by"] == "A"
    assert indexed.loc["A", "layer"] == "focus"
    assert indexed.loc["C", "layer"] == "focus"
    assert "score" not in decisions.columns


def test_compression_abstains_when_capacity_boundary_is_indistinguishable():
    evidence = pd.DataFrame(
        [_evidence_row(code, freshness=3, consistency=3, hotspot=3, price_safety=3, liquidity=3) for code in ("A", "B", "C")]
    )

    decisions = compress_candidates(evidence, candidate_cap=2, focus_cap=1)

    assert set(decisions["layer"]) == {"abstain_capacity_tie"}
    assert not decisions["ts_code"].isin(["A", "B"]).all()


def _evidence_row(
    code: str,
    *,
    routes: str = "earnings|hotspot",
    company_evidence: bool = True,
    freshness: int = 3,
    consistency: int = 3,
    hotspot: int = 2,
    price_safety: int = 2,
    liquidity: int = 3,
) -> dict[str, object]:
    return {
        "formation_date": "2026-01-05",
        "ts_code": code,
        "routes": routes,
        "company_evidence": company_evidence,
        "hard_invalid": False,
        "evidence_freshness": freshness,
        "earnings_cash_consistency": consistency,
        "hotspot_support": hotspot,
        "price_consumption_safety": price_safety,
        "liquidity": liquidity,
    }


def test_project_state_moves_from_new_to_tracking_without_future_results():
    day_one = pd.DataFrame([_evidence_row("A")]).assign(layer="focus")

    first = update_project_states(pd.DataFrame(), day_one, formation_date="2026-01-05")
    second = update_project_states(first, day_one, formation_date="2026-01-12")

    assert first.iloc[0]["project_status"] == "new"
    assert second.iloc[0]["project_status"] == "tracking"
    assert second.iloc[0]["checkpoint"] == "day_5"
    assert second.iloc[0]["project_id"] == first.iloc[0]["project_id"]
    assert "future_return" not in second.columns


def test_project_exits_after_thirty_sessions_or_current_invalidation():
    current = pd.DataFrame([_evidence_row("A")]).assign(layer="focus")
    first = update_project_states(pd.DataFrame(), current, formation_date="2026-01-05")
    first["age_sessions"] = 30

    expired = update_project_states(first, current, formation_date="2026-02-17")

    assert expired.iloc[0]["project_status"] == "exit"
    assert expired.iloc[0]["exit_reason"] == "requires_new_project_after_day_30"


def test_challenger_replaces_only_on_pareto_dominance_or_invalidation():
    incumbent = pd.Series(_evidence_row("OLD", freshness=2, consistency=2, hotspot=2, price_safety=2, liquidity=2))
    stronger = pd.Series(_evidence_row("NEW", freshness=3, consistency=2, hotspot=2, price_safety=2, liquidity=2))
    tradeoff = pd.Series(_evidence_row("MIX", freshness=3, consistency=1, hotspot=3, price_safety=2, liquidity=2))

    assert challenger_can_replace(stronger, incumbent) is True
    assert challenger_can_replace(tradeoff, incumbent) is False
    assert challenger_can_replace(tradeoff, incumbent, incumbent_invalid=True) is True


def test_module_classification_requires_combined_and_two_of_three_blocks():
    supported = classify_module(
        block_effects=[0.10, 0.03, -0.01],
        combined_effect=0.05,
        observations=90,
        concentration_ok=True,
        path_ok=True,
    )
    rejected = classify_module(
        block_effects=[-0.04, -0.01, 0.02],
        combined_effect=-0.02,
        observations=90,
        concentration_ok=True,
        path_ok=True,
    )

    assert supported == "accuracy_supported"
    assert rejected == "inaccuracy_supported"


def test_module_classification_distinguishes_insufficient_and_not_testable():
    assert classify_module(
        block_effects=[0.2],
        combined_effect=0.2,
        observations=4,
        concentration_ok=True,
        path_ok=True,
    ) == "insufficient_evidence"
    assert classify_module(
        block_effects=[],
        combined_effect=None,
        observations=0,
        concentration_ok=False,
        path_ok=False,
        testable=False,
    ) == "not_testable"


def test_route_limit_filters_non_tradable_names_before_applying_cap():
    ranked = ["SUSPENDED", "A", "B", "C"]

    selected = limit_to_tradable_route(
        ranked,
        tradable_codes={"A", "B", "C"},
        limit=2,
    )

    assert selected == ["A", "B"]
