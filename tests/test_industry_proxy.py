from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis.industry_proxy import (
    FORMULA_VERSION,
    PROXY_METHOD,
    IndustryProxyInputError,
    compute_industry_daily_proxy,
)
from stock_analyzer.data.research_contracts import (
    ResearchDatasetId,
    research_contract,
)


TRADE_DATE = date(2026, 9, 2)
WEIGHT_DATE = date(2026, 9, 1)


def _at(hour: int) -> datetime:
    return datetime(2026, 9, 2, hour, tzinfo=timezone.utc)


def _catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "801010.SI",
                "industry_name": "农林牧渔",
                "is_published": "1",
                "valid_from": date(2021, 12, 13),
                "valid_to": None,
                "available_at": _at(1),
            },
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": "801016.SI",
                "industry_name": "种植业",
                "is_published": "1",
                "valid_from": date(2021, 12, 13),
                "valid_to": None,
                "available_at": _at(1),
            },
        ]
    )


def _members(codes: tuple[str, ...] = ("A.SZ", "B.SZ")) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "801010.SI",
                "ts_code": code,
                "valid_from": date(2021, 12, 13),
                "valid_to": None,
                "available_at": _at(2),
            }
            for code in codes
        ]
    )


def _security_master(codes: tuple[str, ...] = ("A.SZ", "B.SZ")) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": code,
                "valid_from": date(2021, 12, 13),
                "valid_to": None,
                "list_date": date(2020, 1, 1),
                "delist_date": None,
                "available_at": _at(2),
            }
            for code in codes
        ]
    )


def _equity() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"trade_date": WEIGHT_DATE, "ts_code": "A.SZ", "close": 10.0, "pct_chg": 0.0, "available_at": _at(3)},
            {"trade_date": WEIGHT_DATE, "ts_code": "B.SZ", "close": 20.0, "pct_chg": 0.0, "available_at": _at(3)},
            {"trade_date": TRADE_DATE, "ts_code": "A.SZ", "close": 11.0, "pct_chg": 10.0, "available_at": _at(7)},
            {"trade_date": TRADE_DATE, "ts_code": "B.SZ", "close": 19.0, "pct_chg": -5.0, "available_at": _at(7)},
        ]
    )


def _daily_basic() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"trade_date": WEIGHT_DATE, "ts_code": "A.SZ", "free_share": 100.0, "available_at": _at(4)},
            {"trade_date": WEIGHT_DATE, "ts_code": "B.SZ", "free_share": 200.0, "available_at": _at(5)},
        ]
    )


def _compute(**overrides: object) -> pd.DataFrame:
    members = overrides.pop("industry_members", _members())
    values = {
        "trade_date": TRADE_DATE,
        "weight_date": WEIGHT_DATE,
        "industry_catalog": _catalog(),
        "industry_members": members,
        "security_master": _security_master(
            tuple(members["ts_code"].astype(str))
        ),
        "equity_daily": _equity(),
        "daily_basic": _daily_basic(),
        "input_manifest_hash": "manifest-1",
    }
    values.update(overrides)
    return compute_industry_daily_proxy(**values)


def test_proxy_uses_prior_free_float_market_cap_and_stores_decimal_return() -> None:
    row = _compute().iloc[0]

    assert row["industry_code"] == "801010.SI"
    assert row["effective_member_count"] == 2
    assert row["observed_member_count"] == 2
    assert row["member_coverage_ratio"] == pytest.approx(1.0)
    assert row["proxy_return"] == pytest.approx(-0.02)
    assert row["weight_date"] == WEIGHT_DATE
    assert row["proxy_method"] == PROXY_METHOD
    assert row["formula_version"] == FORMULA_VERSION
    assert row["input_manifest_hash"] == "manifest-1"
    assert row["available_at"] == _at(7)
    assert not {
        "open", "high", "low", "close", "pre_close", "official_index_return_1d"
    } & set(row.index)


def test_proxy_only_uses_effective_published_sw2021_l1_members() -> None:
    members = _members(("A.SZ", "B.SZ"))
    members.loc[members["ts_code"] == "A.SZ", "valid_to"] = date(2026, 9, 1)

    row = _compute(industry_members=members).iloc[0]

    assert row["effective_member_count"] == 1
    assert row["observed_member_count"] == 1
    assert row["proxy_return"] == pytest.approx(-0.05)


def test_proxy_below_eighty_percent_coverage_is_explicitly_unavailable() -> None:
    codes = ("A.SZ", "B.SZ", "C.SZ", "D.SZ", "E.SZ")
    row = _compute(industry_members=_members(codes)).iloc[0]

    assert row["effective_member_count"] == 5
    assert row["observed_member_count"] == 2
    assert row["member_coverage_ratio"] == pytest.approx(0.4)
    assert np.isnan(row["proxy_return"])
    assert row["coverage_status"] == "limited"
    assert "80%" in row["limitation_notes"]


def test_proxy_excludes_stale_members_that_delisted_before_trade_date() -> None:
    members = _members(("A.SZ", "B.SZ", "OLD.SZ"))
    security_master = _security_master(("A.SZ", "B.SZ", "OLD.SZ"))
    security_master.loc[
        security_master["ts_code"] == "OLD.SZ", "delist_date"
    ] = date(2025, 7, 1)

    row = _compute(
        industry_members=members,
        security_master=security_master,
    ).iloc[0]

    assert row["effective_member_count"] == 2
    assert row["observed_member_count"] == 2
    assert row["member_coverage_ratio"] == pytest.approx(1.0)
    assert row["coverage_status"] == "complete"
    assert row["proxy_return"] == pytest.approx(-0.02)


def test_proxy_keeps_active_members_without_market_observations_in_denominator() -> None:
    members = _members(("A.SZ", "B.SZ", "C.SZ", "D.SZ", "E.SZ"))

    row = _compute(industry_members=members).iloc[0]

    assert row["effective_member_count"] == 5
    assert row["observed_member_count"] == 2
    assert row["member_coverage_ratio"] == pytest.approx(0.4)
    assert row["coverage_status"] == "limited"


def test_excluded_members_still_constrain_proxy_availability() -> None:
    members = _members(("A.SZ", "B.SZ", "OLD.SZ"))
    members.loc[members["ts_code"] == "OLD.SZ", "available_at"] = _at(10)
    security = _security_master(("A.SZ", "B.SZ", "OLD.SZ"))
    security.loc[security["ts_code"] == "OLD.SZ", "delist_date"] = "20250701"
    security.loc[security["ts_code"] == "OLD.SZ", "available_at"] = _at(9)

    row = _compute(industry_members=members, security_master=security).iloc[0]

    assert row["effective_member_count"] == 2
    assert row["available_at"] == _at(10)


def test_proxy_rejects_duplicate_business_facts_and_missing_weight_session() -> None:
    duplicate = pd.concat([_daily_basic(), _daily_basic().iloc[[0]]], ignore_index=True)
    with pytest.raises(IndustryProxyInputError, match="duplicate"):
        _compute(daily_basic=duplicate)

    current_only = _equity().query("trade_date == @TRADE_DATE").reset_index(drop=True)
    with pytest.raises(IndustryProxyInputError, match="weight date"):
        _compute(equity_daily=current_only)


def test_industry_proxy_contract_is_local_derived_and_old_series_is_legacy() -> None:
    proxy = research_contract(ResearchDatasetId.INDUSTRY_DAILY_PROXY)
    legacy = research_contract(ResearchDatasetId.INDUSTRY_DAILY)

    assert proxy.business_key == ("trade_date", "industry_code")
    assert proxy.partition_field == "trade_date"
    assert proxy.source_policy.approved_sources == ("local_derived",)
    assert proxy.history_window == "250_sessions"
    assert not proxy.required_for_close_screen
    assert not legacy.required_for_close_screen
    assert {
        "proxy_return",
        "effective_member_count",
        "observed_member_count",
        "member_coverage_ratio",
        "weight_date",
        "proxy_method",
        "formula_version",
        "input_manifest_hash",
        "available_at",
    } <= set(proxy.required_columns)
