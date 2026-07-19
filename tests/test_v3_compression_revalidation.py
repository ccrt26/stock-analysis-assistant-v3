from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_compression_revalidation import (
    build_comparison_metrics,
    build_recompressed_outcomes,
    compress_decision_list,
    derive_company_driver_state,
    evaluate_acceptance,
    generate_report,
    load_config,
    prepare_output_root,
    validate_decision_contracts,
)


CONFIG_PATH = Path(
    "docs/superpowers/specs/2026-07-19-v3-compression-revalidation-config.yaml"
)


def _row(
    code: str,
    *,
    routes: str = "earnings|hotspot",
    company_evidence: bool = False,
    hard_invalid: bool = False,
    tr: float = np.nan,
    net: float = np.nan,
    core: float = np.nan,
    cash: float = np.nan,
    report_period: str | None = "2025-09-30",
    freshness: int = 2,
    consistency: int = 2,
    hotspot: int = 2,
    price_safety: int = 2,
    liquidity: int = 2,
) -> dict[str, object]:
    return {
        "formation_date": "2026-01-05",
        "ts_code": code,
        "routes": routes,
        "company_evidence": company_evidence,
        "hard_invalid": hard_invalid,
        "report_period": report_period,
        "tr_yoy": tr,
        "netprofit_yoy": net,
        "dt_netprofit_yoy": core,
        "n_cashflow_act": cash,
        "evidence_freshness": freshness,
        "earnings_cash_consistency": consistency,
        "hotspot_support": hotspot,
        "price_consumption_safety": price_safety,
        "liquidity": liquidity,
    }


def test_company_driver_state_distinguishes_complete_partial_absent_and_invalid():
    assert derive_company_driver_state(pd.Series(_row("FULL", company_evidence=True))) == "confirmed"
    assert derive_company_driver_state(pd.Series(_row("PART", tr=10.0))) == "partial"
    assert derive_company_driver_state(
        pd.Series(_row("PRICE", routes="price", report_period=None))
    ) == "absent"
    assert derive_company_driver_state(
        pd.Series(_row("BAD", company_evidence=True, hard_invalid=True))
    ) == "excluded"


def test_user_output_is_one_attention_list_for_all_eligible_evidence_states():
    evidence = pd.DataFrame(
        [
            _row(
                "FULL",
                company_evidence=True,
                tr=10,
                net=10,
                core=10,
                cash=100,
            ),
            _row("PART", company_evidence=False, tr=10, net=-2, core=-3, cash=-1),
            _row(
                "PRICE",
                routes="price",
                company_evidence=False,
                tr=np.nan,
                net=np.nan,
                core=np.nan,
                cash=np.nan,
                report_period=None,
            ),
            _row("BAD", company_evidence=True, hard_invalid=True),
        ]
    )

    result = compress_decision_list(evidence, candidate_cap=10, focus_cap=5)
    indexed = result.set_index("ts_code")
    selected = result[result["user_layer"].eq("关注")]

    assert indexed.loc["FULL", "user_layer"] == "关注"
    assert indexed.loc["PART", "user_layer"] == "关注"
    assert indexed.loc["PRICE", "user_layer"] == "关注"
    assert indexed.loc["BAD", "user_layer"] == "不展示"
    assert set(selected["user_layer"]) == {"关注"}
    assert "score" not in result.columns


def test_caps_are_upper_bounds_and_hard_invalidations_never_fill_the_list():
    rows = [
        _row(
            f"F{i}",
            company_evidence=True,
            tr=10,
            net=10,
            core=10,
            cash=100,
            hotspot=3 if i % 2 else 2,
        )
        for i in range(8)
    ]
    rows += [
        _row(
            f"P{i}",
            routes="price",
            company_evidence=False,
            report_period=None,
            price_safety=3 if i % 2 else 2,
        )
        for i in range(8)
    ]
    rows.append(_row("BAD", company_evidence=True, hard_invalid=True))

    result = compress_decision_list(pd.DataFrame(rows), candidate_cap=10, focus_cap=5)
    selected = result[result["user_layer"].eq("关注")]

    assert 0 < len(selected) <= 10
    assert selected["hard_invalid"].eq(False).all()
    assert result.set_index("ts_code").loc["BAD", "user_layer"] == "不展示"


def test_invalid_cap_relationship_is_rejected():
    evidence = pd.DataFrame([_row("A", company_evidence=True)])

    for candidate_cap, focus_cap in ((0, 0), (5, 6), (10, -1)):
        try:
            compress_decision_list(
                evidence,
                candidate_cap=candidate_cap,
                focus_cap=focus_cap,
            )
        except ValueError as exc:
            assert "capacity" in str(exc)
        else:
            raise AssertionError("invalid capacities must fail")


def test_attention_list_does_not_fill_with_a_dominated_confirmed_candidate():
    evidence = pd.DataFrame(
        [
            _row(
                "STRONG",
                company_evidence=True,
                freshness=3,
                consistency=3,
                hotspot=3,
                price_safety=3,
                liquidity=3,
            ),
            _row(
                "DOMINATED",
                company_evidence=True,
                freshness=2,
                consistency=2,
                hotspot=2,
                price_safety=2,
                liquidity=2,
            ),
        ]
    )

    result = compress_decision_list(evidence, candidate_cap=10, focus_cap=5)
    indexed = result.set_index("ts_code")

    assert indexed.loc["STRONG", "user_layer"] == "关注"
    assert indexed.loc["DOMINATED", "user_layer"] == "不展示"


def test_overconsumed_elasticity_is_not_displayed_to_fill_capacity():
    evidence = pd.DataFrame(
        [
            _row(
                "SAFE",
                routes="price",
                company_evidence=False,
                report_period=None,
                price_safety=2,
            ),
            _row(
                "OVERCONSUMED",
                routes="price",
                company_evidence=False,
                report_period=None,
                price_safety=1,
            ),
        ]
    )

    result = compress_decision_list(evidence, candidate_cap=10, focus_cap=5)
    indexed = result.set_index("ts_code")

    assert indexed.loc["SAFE", "user_layer"] == "关注"
    assert indexed.loc["OVERCONSUMED", "user_layer"] == "不展示"
    assert indexed.loc["OVERCONSUMED", "decision_reason"] == "insufficient_current_action_value"


def test_config_freezes_sources_caps_and_user_layers():
    config = load_config(CONFIG_PATH)

    assert config.candidate_cap == 10
    assert config.focus_cap == 5
    assert config.horizons == (20, 30)
    assert config.user_layers == ("关注",)
    assert config.source_layered_root.name == "2026-07-18-v3-layered-validation"
    assert config.source_action_root.name == "2026-07-19-v3-next-day-entry-validation"


def test_output_root_rejects_non_usb_location(tmp_path: Path):
    config = load_config(CONFIG_PATH)

    with pytest.raises(ValueError, match="U盘专用目录"):
        prepare_output_root(config, output_override=tmp_path / "wrong")


def test_acceptance_requires_improvement_over_old_and_smaller_research_loss():
    rows = []
    for block in ("A", "B", "C", "ALL"):
        for horizon in (20, 30):
            for metric, new, old, research in (
                ("touch_yield_all_plans", 0.30, 0.27, 0.34),
                ("close_yield_all_plans", 0.27, 0.25, 0.28),
                ("retain_3_yield_all_plans", 0.14, 0.13, 0.15),
                ("median_window_min_return", -0.12, -0.13, -0.11),
            ):
                adjusted_new = (
                    new + 0.06
                    if block == "A"
                    and metric
                    in ("touch_yield_all_plans", "close_yield_all_plans")
                    else new
                )
                rows.append(
                    {
                        "block": block,
                        "horizon": horizon,
                        "metric": metric,
                        "new": adjusted_new,
                        "old": old,
                        "research": research,
                    }
                )
    checks = evaluate_acceptance(pd.DataFrame(rows))

    assert checks["new_not_below_old_touch_and_close"] is True
    assert checks["research_compression_loss_shrunk"] is True
    assert checks["retention_not_worse_both_horizons"] is True
    assert checks["path_risk_not_worse_both_horizons"] is True
    assert checks["all_acceptance_passed"] is True


def test_acceptance_fails_when_all_three_blocks_still_lose_to_research():
    rows = []
    for block in ("A", "B", "C", "ALL"):
        for horizon in (20, 30):
            for metric in (
                "touch_yield_all_plans",
                "close_yield_all_plans",
                "retain_3_yield_all_plans",
                "median_window_min_return",
            ):
                rows.append(
                    {
                        "block": block,
                        "horizon": horizon,
                        "metric": metric,
                        "new": 0.20 if "return" not in metric else -0.15,
                        "old": 0.18 if "return" not in metric else -0.16,
                        "research": 0.30 if "return" not in metric else -0.10,
                    }
                )

    checks = evaluate_acceptance(pd.DataFrame(rows))

    assert checks["not_all_blocks_lose_to_research"] is False
    assert checks["all_acceptance_passed"] is False


def test_report_keeps_user_section_to_one_attention_list_and_controls_in_appendix(tmp_path: Path):
    summary = pd.DataFrame(
        [
            {
                "block": "ALL",
                "policy": "v3_recompressed",
                "layer": layer,
                "horizon": horizon,
                "planned_actions": 90,
                "touch_successes": 30,
                "touch_yield_all_plans": 1 / 3,
                "close_successes": 25,
                "close_yield_all_plans": 25 / 90,
                "retain_3_successes": 12,
                "retain_3_yield_all_plans": 12 / 90,
                "median_window_min_return": -0.12,
            }
            for layer in ("all", "关注")
            for horizon in (20, 30)
        ]
    )
    comparisons = pd.DataFrame()
    checks = {
        "new_not_below_old_touch_and_close": True,
        "research_compression_loss_shrunk": True,
        "all_acceptance_passed": True,
    }
    path = tmp_path / "report.md"

    generate_report(summary, comparisons, checks, path)
    text = path.read_text(encoding="utf-8")
    user_section = text.split("## 技术附录", maxsplit=1)[0]

    assert "关注名单" in user_section
    assert "重点" not in user_section
    assert "观察" not in user_section
    assert "research_union" not in user_section
    assert "matched" not in user_section


def test_decision_contracts_enforce_two_layers_caps_and_hard_boundaries():
    decisions = pd.DataFrame(
        [
            {
                "formation_date": "2026-01-05",
                "ts_code": f"A{i}",
                "user_layer": "关注",
                "hard_invalid": False,
            }
            for i in range(10)
        ]
        + [
            {
                "formation_date": "2026-01-05",
                "ts_code": "HIDDEN",
                "user_layer": "不展示",
                "hard_invalid": True,
            }
        ]
    )

    checks = validate_decision_contracts(
        decisions,
        candidate_cap=10,
        focus_cap=5,
        user_layers=("关注",),
    )

    assert checks["daily_candidate_cap"] is True
    assert checks["single_user_layer"] is True
    assert checks["selected_layers_only"] is True
    assert checks["no_hard_invalid_selected"] is True
