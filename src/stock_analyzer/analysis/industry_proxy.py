"""Point-in-time Shenwan L1 return proxy derived from governed local facts."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


PROXY_METHOD = "sw_l1_free_float_proxy_v1"
FORMULA_VERSION = "sw-l1-free-float-proxy-v1"
MINIMUM_MEMBER_COVERAGE = 0.80
_OUTPUT_COLUMNS = (
    "trade_date",
    "industry_system",
    "level",
    "industry_code",
    "industry_name",
    "proxy_return",
    "effective_member_count",
    "observed_member_count",
    "member_coverage_ratio",
    "coverage_status",
    "limitation_notes",
    "weight_date",
    "proxy_method",
    "formula_version",
    "input_manifest_hash",
    "available_at",
)


class IndustryProxyInputError(ValueError):
    """Raised when an input cannot support deterministic proxy calculation."""


def compute_industry_daily_proxy(
    *,
    trade_date: date,
    weight_date: date,
    industry_catalog: pd.DataFrame,
    industry_members: pd.DataFrame,
    security_master: pd.DataFrame,
    equity_daily: pd.DataFrame,
    daily_basic: pd.DataFrame,
    input_manifest_hash: str,
    minimum_member_coverage: float = MINIMUM_MEMBER_COVERAGE,
) -> pd.DataFrame:
    """Return one Shenwan L1 proxy observation for ``trade_date``.

    The weight for stock ``i`` is ``free_share(i, weight_date) *
    close(i, weight_date)``.  Tushare ``pct_chg`` is converted from percentage
    points to a decimal return before aggregation.  Rows below the member
    coverage threshold remain auditable but expose no usable ``proxy_return``.
    """

    current_date = _as_date(trade_date, "trade_date")
    prior_date = _as_date(weight_date, "weight_date")
    if prior_date >= current_date:
        raise IndustryProxyInputError("weight date must precede trade date")
    if not 0.0 <= minimum_member_coverage <= 1.0:
        raise IndustryProxyInputError("minimum member coverage must be within [0, 1]")
    manifest_hash = str(input_manifest_hash).strip()
    if not manifest_hash:
        raise IndustryProxyInputError("input manifest hash is required")

    catalog = _effective_catalog(industry_catalog, current_date)
    if catalog.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    members = _effective_members(industry_members, current_date)
    security = _prepare_security_master(security_master, current_date)
    known_security_codes = set(security["ts_code"].astype(str))
    active_security = security.loc[security["is_active_on_trade_date"]].copy()
    active_security_codes = set(active_security["ts_code"].astype(str))
    security_availability = (
        security.groupby("ts_code", sort=False)["available_at"]
        .apply(lambda values: _latest_available_at(values.tolist()))
        .to_dict()
    )
    members["security_available_at"] = members["ts_code"].astype(str).map(
        security_availability
    )
    lifecycle_availability_by_industry = {
        str(code): (
            group["security_available_at"].dropna().tolist()
            + group["available_at"].tolist()
        )
        for code, group in members.groupby("industry_code", sort=False)
    }
    members = members.loc[
        ~members["ts_code"].astype(str).isin(known_security_codes)
        | members["ts_code"].astype(str).isin(active_security_codes)
    ].copy()
    equity = _prepare_market_facts(equity_daily, "equity_daily")
    basic = _prepare_market_facts(daily_basic, "daily_basic")

    prior_equity = equity.loc[equity["trade_date"] == prior_date].copy()
    current_equity = equity.loc[equity["trade_date"] == current_date].copy()
    prior_basic = basic.loc[basic["trade_date"] == prior_date].copy()
    if prior_equity.empty or prior_basic.empty:
        raise IndustryProxyInputError(
            f"weight date {prior_date.isoformat()} facts are missing"
        )
    _reject_duplicates(prior_equity, ("trade_date", "ts_code"), "equity_daily")
    _reject_duplicates(current_equity, ("trade_date", "ts_code"), "equity_daily")
    _reject_duplicates(prior_basic, ("trade_date", "ts_code"), "daily_basic")

    prior_equity = prior_equity[
        ["ts_code", "close", "available_at"]
    ].rename(
        columns={"close": "prior_close", "available_at": "close_available_at"}
    )
    prior_basic = prior_basic[
        ["ts_code", "free_share", "available_at"]
    ].rename(columns={"available_at": "free_share_available_at"})
    current_equity = current_equity[
        ["ts_code", "pct_chg", "available_at"]
    ].rename(columns={"available_at": "return_available_at"})
    observations = prior_equity.merge(prior_basic, on="ts_code", how="outer").merge(
        current_equity, on="ts_code", how="outer"
    )
    observations["prior_close"] = pd.to_numeric(
        observations["prior_close"], errors="coerce"
    )
    observations["free_share"] = pd.to_numeric(
        observations["free_share"], errors="coerce"
    )
    observations["pct_chg"] = pd.to_numeric(
        observations["pct_chg"], errors="coerce"
    )
    observations["weight"] = (
        observations["prior_close"] * observations["free_share"]
    )
    observations["return_decimal"] = observations["pct_chg"] / 100.0
    observations["is_observed"] = (
        np.isfinite(observations["weight"])
        & (observations["weight"] > 0)
        & np.isfinite(observations["return_decimal"])
    )
    observations = observations.set_index("ts_code", drop=False)

    rows: list[dict[str, Any]] = []
    members_by_industry = {
        str(code): group
        for code, group in members.groupby("industry_code", sort=False)
    }
    empty_members = members.iloc[0:0]
    for item in catalog.sort_values("industry_code").to_dict(orient="records"):
        industry_code = str(item["industry_code"])
        group_members = members_by_industry.get(industry_code, empty_members)
        codes = tuple(sorted(set(group_members["ts_code"].astype(str))))
        effective_count = len(codes)
        selected = observations.reindex(codes) if codes else observations.iloc[0:0]
        observed = selected.loc[selected["is_observed"].fillna(False)].copy()
        observed_count = len(observed)
        coverage_ratio = (
            observed_count / effective_count if effective_count else np.nan
        )
        complete = bool(
            effective_count
            and coverage_ratio >= minimum_member_coverage
            and observed_count
        )
        proxy_return = (
            float(
                np.average(
                    observed["return_decimal"].astype(float),
                    weights=observed["weight"].astype(float),
                )
            )
            if complete
            else np.nan
        )
        availability_values: list[object] = [item.get("available_at")]
        availability_values.extend(group_members.get("available_at", pd.Series()).tolist())
        availability_values.extend(
            lifecycle_availability_by_industry.get(industry_code, ())
        )
        if not observed.empty:
            for column in (
                "close_available_at",
                "free_share_available_at",
                "return_available_at",
            ):
                availability_values.extend(observed[column].tolist())
        available_at = _latest_available_at(availability_values)
        limitations = ""
        if not effective_count:
            limitations = "no effective SW2021/L1 members"
        elif not complete:
            limitations = (
                f"member coverage {coverage_ratio:.2%} is below required "
                f"{minimum_member_coverage:.0%}"
            )
        rows.append(
            {
                "trade_date": current_date,
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": industry_code,
                "industry_name": item.get("industry_name"),
                "proxy_return": proxy_return,
                "effective_member_count": effective_count,
                "observed_member_count": observed_count,
                "member_coverage_ratio": coverage_ratio,
                "coverage_status": "complete" if complete else "limited",
                "limitation_notes": limitations,
                "weight_date": prior_date,
                "proxy_method": PROXY_METHOD,
                "formula_version": FORMULA_VERSION,
                "input_manifest_hash": manifest_hash,
                "available_at": available_at,
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)


def _effective_catalog(frame: pd.DataFrame, current_date: date) -> pd.DataFrame:
    required = {
        "industry_system",
        "level",
        "industry_code",
        "industry_name",
        "is_published",
        "valid_from",
        "available_at",
    }
    catalog = _require_columns(frame, required, "industry catalog")
    catalog = _with_validity_dates(catalog)
    published = catalog["is_published"].astype(str).str.strip().str.lower().isin(
        {"1", "true", "y", "yes"}
    )
    active = (
        (catalog["industry_system"].astype(str) == "SW2021")
        & (catalog["level"].astype(str) == "L1")
        & published
        & (catalog["valid_from"] <= current_date)
        & (catalog["valid_to"].isna() | (catalog["valid_to"] >= current_date))
    )
    result = catalog.loc[active].copy()
    _reject_duplicates(result, ("industry_code",), "effective industry catalog")
    return result


def _effective_members(frame: pd.DataFrame, current_date: date) -> pd.DataFrame:
    required = {
        "industry_system",
        "level",
        "industry_code",
        "ts_code",
        "valid_from",
        "available_at",
    }
    members = _require_columns(frame, required, "industry members")
    members = _with_validity_dates(members)
    active = (
        (members["industry_system"].astype(str) == "SW2021")
        & (members["level"].astype(str) == "L1")
        & (members["valid_from"] <= current_date)
        & (members["valid_to"].isna() | (members["valid_to"] >= current_date))
    )
    result = members.loc[active].copy()
    _reject_duplicates(
        result,
        ("industry_code", "ts_code"),
        "effective industry members",
    )
    return result


def _prepare_security_master(
    frame: pd.DataFrame,
    current_date: date,
) -> pd.DataFrame:
    required = {"ts_code", "valid_from", "list_date", "available_at"}
    security = _require_columns(frame, required, "security master")
    if security.empty:
        raise IndustryProxyInputError("security master is empty")
    security = _with_validity_dates(security)
    security["list_date"] = security["list_date"].map(
        lambda value: _optional_date(value, "security master.list_date")
    )
    if security["list_date"].isna().any():
        raise IndustryProxyInputError("security master.list_date is required")
    if "delist_date" not in security:
        security["delist_date"] = None
    security["delist_date"] = security["delist_date"].map(
        lambda value: _optional_date(value, "security master.delist_date")
    )
    _reject_duplicates(
        security,
        ("ts_code", "valid_from"),
        "security master",
    )
    security["is_active_on_trade_date"] = (
        (security["valid_from"] <= current_date)
        & (security["list_date"] <= current_date)
        & (security["valid_to"].isna() | (security["valid_to"] >= current_date))
        & (
            security["delist_date"].isna()
            | (security["delist_date"] >= current_date)
        )
    )
    active = security.loc[security["is_active_on_trade_date"]]
    _reject_duplicates(active, ("ts_code",), "active security master")
    return security


def _prepare_market_facts(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    required = {"trade_date", "ts_code", "available_at"}
    result = _require_columns(frame, required, label)
    result["trade_date"] = result["trade_date"].map(
        lambda value: _as_date(value, f"{label}.trade_date")
    )
    return result


def _with_validity_dates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["valid_from"] = result["valid_from"].map(
        lambda value: _as_date(value, "valid_from")
    )
    if "valid_to" not in result:
        result["valid_to"] = None
    result["valid_to"] = result["valid_to"].map(
        lambda value: None if pd.isna(value) else _as_date(value, "valid_to")
    )
    return result


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    label: str,
) -> pd.DataFrame:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise IndustryProxyInputError(
            f"{label} lacks required columns: {', '.join(missing)}"
        )
    return frame.copy()


def _reject_duplicates(
    frame: pd.DataFrame,
    key: tuple[str, ...],
    label: str,
) -> None:
    if frame.empty:
        return
    duplicated = frame.duplicated(subset=list(key), keep=False)
    if duplicated.any():
        raise IndustryProxyInputError(
            f"duplicate {label} business facts: {int(duplicated.sum())} rows"
        )


def _latest_available_at(values: list[object]) -> pd.Timestamp:
    normalized = pd.to_datetime(pd.Series(values, dtype="object"), utc=True, errors="coerce")
    if normalized.notna().sum() != len(values):
        raise IndustryProxyInputError("all used inputs require available_at")
    return normalized.max()


def _as_date(value: object, label: str) -> date:
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError) as exc:
        raise IndustryProxyInputError(f"invalid {label}: {value!r}") from exc


def _optional_date(value: object, label: str) -> date | None:
    if pd.isna(value) or not str(value).strip():
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        try:
            return pd.to_datetime(text, format="%Y%m%d").date()
        except (TypeError, ValueError) as exc:
            raise IndustryProxyInputError(
                f"invalid {label}: {value!r}"
            ) from exc
    return _as_date(value, label)


__all__ = [
    "FORMULA_VERSION",
    "MINIMUM_MEMBER_COVERAGE",
    "PROXY_METHOD",
    "IndustryProxyInputError",
    "compute_industry_daily_proxy",
]
