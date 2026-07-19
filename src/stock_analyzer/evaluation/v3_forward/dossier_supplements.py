from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from stock_analyzer.evaluation.v3_forward.ledger import (
    BundleWriteResult,
    ForwardLedger,
)


SUPPLEMENT_SCHEMA_VERSION = "v3-forward-official-supplement-01"

_REQUIRED_COLUMNS = (
    "ts_code",
    "fact_category",
    "fact_text",
    "source_title",
    "source_url",
    "published_at",
    "observed_at",
)
_STATIC_CATEGORIES = {
    "business_model",
    "company_history",
    "customer_structure",
    "industry_position",
    "operating_model",
    "product_portfolio",
    "revenue_composition",
}
_OFFICIAL_HOST_SUFFIXES = (
    "cninfo.com.cn",
    "szse.cn",
    "sse.com.cn",
    "bse.cn",
)
_OUTPUT_COLUMNS = (
    "formation_date",
    "schema_version",
    *_REQUIRED_COLUMNS,
)


def _is_official_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _OFFICIAL_HOST_SUFFIXES
    )


def normalize_official_supplements(
    facts: pd.DataFrame, *, formation_date: date, cutoff: pd.Timestamp
) -> pd.DataFrame:
    missing = [field for field in _REQUIRED_COLUMNS if field not in facts]
    if missing:
        raise ValueError(f"supplement lacks fields: {', '.join(missing)}")
    normalized = facts.loc[:, _REQUIRED_COLUMNS].copy()
    for field in (
        "ts_code",
        "fact_category",
        "fact_text",
        "source_title",
        "source_url",
    ):
        normalized[field] = normalized[field].astype(str).str.strip()
        if normalized[field].eq("").any():
            raise ValueError(f"supplement has blank {field}")
    invalid_categories = sorted(
        set(normalized["fact_category"]) - _STATIC_CATEGORIES
    )
    if invalid_categories:
        raise ValueError(
            "supplement category is not static: " + ", ".join(invalid_categories)
        )
    if not normalized["source_url"].map(_is_official_url).all():
        raise ValueError("supplement source_url is not an allowed official source")

    cutoff_timestamp = pd.Timestamp(cutoff)
    if cutoff_timestamp.tzinfo is None:
        raise ValueError("supplement cutoff must include timezone")
    published = pd.to_datetime(normalized["published_at"], utc=True, errors="raise")
    observed = pd.to_datetime(normalized["observed_at"], utc=True, errors="raise")
    if published.isna().any() or (published > cutoff_timestamp.tz_convert("UTC")).any():
        raise ValueError("supplement published_at exceeds formation cutoff")
    if observed.isna().any():
        raise ValueError("supplement observed_at is invalid")
    normalized["published_at"] = published.map(lambda value: value.isoformat())
    normalized["observed_at"] = observed.map(lambda value: value.isoformat())
    normalized.insert(0, "schema_version", SUPPLEMENT_SCHEMA_VERSION)
    normalized.insert(0, "formation_date", formation_date.isoformat())
    normalized = normalized.sort_values(
        ["ts_code", "fact_category", "source_url", "fact_text"]
    ).reset_index(drop=True)
    if normalized.duplicated(
        ["ts_code", "fact_category", "source_url", "fact_text"]
    ).any():
        raise ValueError("supplement contains duplicate facts")
    return normalized.loc[:, _OUTPUT_COLUMNS]


def write_official_supplements(
    *,
    output_root: Path,
    formation_date: date,
    cutoff: pd.Timestamp,
    facts: pd.DataFrame,
    enforce_real_root: bool = True,
) -> BundleWriteResult:
    normalized = normalize_official_supplements(
        facts, formation_date=formation_date, cutoff=cutoff
    )
    payload = {
        "schema_version": SUPPLEMENT_SCHEMA_VERSION,
        "formation_date": formation_date.isoformat(),
        "data_cutoff_at": pd.Timestamp(cutoff).isoformat(),
        "fact_count": len(normalized),
        "source_policy": "official static facts published no later than formation cutoff",
        "selection_effect": "none",
    }
    report = (
        f"# V3 官方补充事实：{formation_date.isoformat()}\n\n"
        f"- 事实数量：{len(normalized)}\n"
        "- 来源范围：巨潮资讯、证券交易所等官方来源。\n"
        "- 边界：只补公司静态事实，不改变选股、动作确认或任何价格数据。\n"
    )
    ledger = ForwardLedger(output_root, enforce_real_root=enforce_real_root)
    return ledger.write_official_supplement_bundle(
        formation_date,
        SUPPLEMENT_SCHEMA_VERSION,
        payload,
        normalized,
        report,
    )


def read_official_supplements(
    output_root: Path,
    *,
    formation_date: date,
    enforce_real_root: bool = True,
) -> tuple[pd.DataFrame, str | None]:
    path = (
        Path(output_root)
        / "official-supplements"
        / f"formation_date={formation_date.isoformat()}"
        / f"schema_version={SUPPLEMENT_SCHEMA_VERSION}"
    )
    if not path.is_dir():
        return pd.DataFrame(columns=_OUTPUT_COLUMNS), None
    ledger = ForwardLedger(output_root, enforce_real_root=enforce_real_root)
    bundle = ledger.load_bundle_result(path)
    payload = json.loads((path / "supplements.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != SUPPLEMENT_SCHEMA_VERSION:
        raise ValueError("official supplement schema differs")
    facts = pd.read_parquet(path / "supplements.parquet")
    return facts, bundle.bundle_content_hash


__all__ = [
    "SUPPLEMENT_SCHEMA_VERSION",
    "normalize_official_supplements",
    "read_official_supplements",
    "write_official_supplements",
]
