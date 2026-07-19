from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.evaluation.v3_compression_revalidation import (
    compress_decision_list,
)
from stock_analyzer.evaluation.v3_forward.ledger import sha256_file
from stock_analyzer.evaluation.v3_forward.rules import (
    CANDIDATE_CAP,
    FOCUS_CAP,
    ROUTE_RECALL_CAP,
    SUPPORTED_ROUTES,
    add_action_confirmations,
    reject_future_fields,
)
from stock_analyzer.evaluation.v3_layered_validation import (
    _as_of_sector_inputs,
    _build_route_evidence,
    _latest_company_facts,
)
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DERIVED_FORMULAS = {
    "market_context": "market-context-v2",
    "sector_hotspot": "sector-hotspot-v3",
    "stock_trading_context": "stock-trading-context-v2",
}
_ALLOWED_DERIVED_QUALITY = {"complete", "complete_with_declared_gaps"}
_FORMATION_DATASETS = (
    ResearchDatasetId.FINANCIAL_INDICATOR,
    ResearchDatasetId.CASH_FLOW,
    ResearchDatasetId.INDUSTRY_CATALOG,
    ResearchDatasetId.INDUSTRY_MEMBER,
    ResearchDatasetId.THEME_CATALOG,
    ResearchDatasetId.THEME_MEMBER,
    ResearchDatasetId.SECURITY_MASTER,
    ResearchDatasetId.COMPANY_PROFILE,
    ResearchDatasetId.ANNOUNCEMENT,
)


@dataclass(frozen=True)
class FormationInputs:
    formation_date: date
    cutoff: datetime
    market: pd.DataFrame
    stocks: pd.DataFrame
    hotspots: pd.DataFrame
    memberships: pd.DataFrame
    company_facts: pd.DataFrame
    names: Mapping[str, str]
    health_report: Mapping[str, Any]
    input_manifest: Mapping[str, Any]
    sector_catalogs: pd.DataFrame
    company_profiles: pd.DataFrame
    announcements: pd.DataFrame


@dataclass(frozen=True)
class _FormationRuleConfig:
    route_recall_cap: int = ROUTE_RECALL_CAP
    candidate_cap: int = CANDIDATE_CAP
    focus_cap: int = FOCUS_CAP
    supported_routes: tuple[str, ...] = SUPPORTED_ROUTES


class _ReadOnlyResearchWarehouse(ResearchWarehouse):
    """ResearchWarehouse read APIs without catalog or index mutations."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.facts_root = self.root / "facts"
        self.staging_root = self.root / ".staging"
        self.duckdb_path = self.root / "research.duckdb"
        if not self.duckdb_path.is_file():
            raise FileNotFoundError(self.duckdb_path)


def formation_cutoff(formation_date: date) -> datetime:
    return datetime.combine(formation_date, time(23, 59, 59), tzinfo=_SHANGHAI)


def validate_health_report(
    payload: Mapping[str, Any], formation_date: date
) -> None:
    if str(payload.get("data_date")) != formation_date.isoformat():
        raise ValueError("health report date does not match formation date")
    if payload.get("complete_core_date") is not True:
        raise ValueError("core data is incomplete for formation date")


def _manifest_json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
    elif isinstance(value, Mapping):
        parsed = dict(value)
    else:
        raise ValueError("derived input manifest is not a mapping")
    return parsed


def validate_derived_manifest(
    row: Mapping[str, Any],
    formation_date: date,
    warehouse_root: Path,
) -> dict[str, Any]:
    feature_set = str(row["feature_set"])
    expected_formula = _DERIVED_FORMULAS.get(feature_set)
    if expected_formula is None or str(row["formula_version"]) != expected_formula:
        raise ValueError(f"unexpected derived formula for {feature_set}")
    if str(row["quality_status"]) not in _ALLOWED_DERIVED_QUALITY:
        raise ValueError(f"derived quality is unavailable for {feature_set}")
    manifest = _manifest_json(row["input_manifest_json"])
    fact_snapshot = manifest.get("fact_snapshot")
    if not isinstance(fact_snapshot, Mapping) or "as_of" not in fact_snapshot:
        raise ValueError(f"derived fact snapshot is missing for {feature_set}")
    as_of = pd.Timestamp(fact_snapshot["as_of"])
    if as_of.tzinfo is None:
        raise ValueError("derived as_of must include timezone")
    cutoff = pd.Timestamp(formation_cutoff(formation_date))
    if as_of.tz_convert(_SHANGHAI) > cutoff:
        raise ValueError(f"derived input exceeds cutoff for {feature_set}")
    path = Path(warehouse_root) / str(row["relative_path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    if sha256_file(path) != str(row["file_sha256"]):
        raise ValueError(f"derived file hash mismatch for {feature_set}")
    return manifest


def validate_visible_facts(
    frame: pd.DataFrame,
    formation_date: date,
    label: str,
) -> None:
    if frame.empty:
        return
    if "available_at" not in frame:
        raise ValueError(f"{label} facts lack available_at")
    available = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
    cutoff = pd.Timestamp(formation_cutoff(formation_date)).tz_convert("UTC")
    if available.isna().any() or (available > cutoff).any():
        raise ValueError(f"future evidence exceeds formation cutoff: {label}")


def _fact_snapshot(
    warehouse: _ReadOnlyResearchWarehouse,
    cutoff: datetime,
) -> tuple[dict[ResearchDatasetId, pd.DataFrame], dict[str, Any]]:
    partitions: dict[ResearchDatasetId, tuple[str, ...]] = {}
    for dataset in _FORMATION_DATASETS:
        manifest = warehouse.partition_manifest(dataset)
        partitions[dataset] = tuple(manifest["partition_value"].astype(str).tolist())
    snapshot = ResearchQuery(warehouse).materialize_snapshot(partitions, as_of=cutoff)
    return (
        {dataset: snapshot.frame(dataset) for dataset in _FORMATION_DATASETS},
        snapshot.input_manifest,
    )


def _names(frames: Mapping[ResearchDatasetId, pd.DataFrame]) -> dict[str, str]:
    names: dict[str, str] = {}
    for dataset in (ResearchDatasetId.SECURITY_MASTER, ResearchDatasetId.COMPANY_PROFILE):
        frame = frames[dataset]
        if frame.empty or "ts_code" not in frame:
            continue
        name_column = next(
            (column for column in ("name", "security_name", "company_name", "fullname") if column in frame),
            None,
        )
        if name_column is None:
            continue
        for item in frame[["ts_code", name_column]].dropna().itertuples(index=False):
            names[str(item[0])] = str(item[1])
    return names


def load_formation_inputs(
    warehouse_root: Path,
    archive_root: Path,
    formation_date: date,
) -> FormationInputs:
    warehouse_root = Path(warehouse_root)
    health_path = Path(archive_root) / "data_health" / f"{formation_date.isoformat()}.json"
    health = json.loads(health_path.read_text(encoding="utf-8"))
    validate_health_report(health, formation_date)
    with connect_research_warehouse(
        warehouse_root / "research.duckdb", read_only=True
    ) as connection:
        derived = connection.execute(
            """
            select * from research_derived_partitions
            where analysis_date = ?
            order by feature_set
            """,
            [formation_date],
        ).fetchdf()
    rows = {str(row["feature_set"]): row for row in derived.to_dict(orient="records")}
    missing = sorted(set(_DERIVED_FORMULAS) - set(rows))
    if missing:
        raise ValueError(f"missing governed observations: {', '.join(missing)}")
    derived_frames: dict[str, pd.DataFrame] = {}
    derived_manifests: dict[str, Any] = {}
    for feature_set in _DERIVED_FORMULAS:
        row = rows[feature_set]
        derived_manifests[feature_set] = {
            "formula_version": str(row["formula_version"]),
            "quality_status": str(row["quality_status"]),
            "row_count": int(row["row_count"]),
            "content_hash": str(row["content_hash"]),
            "file_sha256": str(row["file_sha256"]),
            "input_manifest_hash": str(row["input_manifest_hash"]),
            "input_manifest": validate_derived_manifest(
                row, formation_date, warehouse_root
            ),
        }
        frame = pd.read_parquet(warehouse_root / str(row["relative_path"]))
        if len(frame) != int(row["row_count"]):
            raise ValueError(f"derived row count mismatch for {feature_set}")
        derived_frames[feature_set] = frame
    cutoff = formation_cutoff(formation_date)
    readonly = _ReadOnlyResearchWarehouse(warehouse_root)
    fact_frames, fact_manifest = _fact_snapshot(readonly, cutoff)
    for dataset, frame in fact_frames.items():
        validate_visible_facts(frame, formation_date, dataset.value)
    data = {
        "financials": fact_frames[ResearchDatasetId.FINANCIAL_INDICATOR],
        "cash_flow": fact_frames[ResearchDatasetId.CASH_FLOW],
        "industry_catalog": fact_frames[ResearchDatasetId.INDUSTRY_CATALOG],
        "industry_member": fact_frames[ResearchDatasetId.INDUSTRY_MEMBER],
        "theme_catalog": fact_frames[ResearchDatasetId.THEME_CATALOG],
        "theme_member": fact_frames[ResearchDatasetId.THEME_MEMBER],
    }
    formation_stamp = pd.Timestamp(formation_date)
    sector_catalogs, memberships = _as_of_sector_inputs(data, formation_stamp)
    company_facts = _latest_company_facts(data, formation_stamp)
    input_manifest = {
        "health_report": {
            "path": str(health_path),
            "sha256": sha256_file(health_path),
            "generated_at": health.get("generated_at"),
        },
        "derived": derived_manifests,
        "facts": fact_manifest,
    }
    return FormationInputs(
        formation_date=formation_date,
        cutoff=cutoff,
        market=derived_frames["market_context"],
        stocks=derived_frames["stock_trading_context"],
        hotspots=derived_frames["sector_hotspot"],
        memberships=memberships,
        company_facts=company_facts,
        names=_names(fact_frames),
        health_report=health,
        input_manifest=input_manifest,
        sector_catalogs=sector_catalogs,
        company_profiles=fact_frames[ResearchDatasetId.COMPANY_PROFILE],
        announcements=fact_frames[ResearchDatasetId.ANNOUNCEMENT],
    )


def _risk_notes(row: pd.Series) -> str:
    notes: list[str] = []
    location = pd.to_numeric(pd.Series([row.get("price_location_60d")]), errors="coerce").iloc[0]
    amount_ratio = pd.to_numeric(
        pd.Series([row.get("current_amount_ratio_20d")]), errors="coerce"
    ).iloc[0]
    cash = pd.to_numeric(pd.Series([row.get("n_cashflow_act")]), errors="coerce").iloc[0]
    ocf_yoy = pd.to_numeric(pd.Series([row.get("ocf_yoy")]), errors="coerce").iloc[0]
    if pd.notna(location) and float(location) >= 0.9:
        notes.append("价格位置较高，趋势延续与兑现风险并存")
    if pd.notna(amount_ratio) and float(amount_ratio) >= 1.5:
        notes.append("成交明显放大，不能仅凭放量区分突破或兑现")
    if pd.notna(cash) and float(cash) < 0:
        notes.append("经营活动现金流为负，仅作风险披露")
    if pd.notna(ocf_yoy) and float(ocf_yoy) < 0:
        notes.append("经营现金流同比恶化，仅作风险披露")
    return "；".join(notes) if notes else "未发现可统一否决的形成日风险，仍存在市场与个股不确定性"


def compress_attention_evidence(evidence: pd.DataFrame) -> pd.DataFrame:
    reject_future_fields(evidence)
    if evidence.empty:
        return evidence.copy()
    decisions = compress_decision_list(
        evidence, candidate_cap=CANDIDATE_CAP, focus_cap=FOCUS_CAP
    )
    selected = decisions[decisions["user_layer"].eq("关注")].copy()
    if len(selected) > CANDIDATE_CAP:
        raise ValueError("attention list exceeds frozen candidate cap")
    if selected.duplicated(["formation_date", "ts_code"]).any():
        raise ValueError("attention list contains duplicate stock-date rows")
    selected = add_action_confirmations(selected)
    selected["entry_state"] = "waiting"
    selected["risk_notes"] = selected.apply(_risk_notes, axis=1)
    return selected.reset_index(drop=True)


def form_attention_list(inputs: FormationInputs) -> pd.DataFrame:
    _, evidence, _ = _build_route_evidence(
        config=_FormationRuleConfig(),
        formation_date=pd.Timestamp(inputs.formation_date),
        market=inputs.market,
        stocks=inputs.stocks,
        hotspots=inputs.hotspots,
        memberships=inputs.memberships,
        company_facts=inputs.company_facts,
    )
    selected = compress_attention_evidence(evidence)
    if selected.empty:
        return selected
    selected["stock_name"] = selected["ts_code"].astype(str).map(inputs.names).fillna(
        selected["ts_code"].astype(str)
    )
    selected["formation_item_id"] = (
        "v3-forward-baseline-01|"
        + inputs.formation_date.isoformat()
        + "|"
        + selected["ts_code"].astype(str)
    )
    return selected


__all__ = [
    "FormationInputs",
    "compress_attention_evidence",
    "form_attention_list",
    "formation_cutoff",
    "load_formation_inputs",
    "validate_derived_manifest",
    "validate_health_report",
    "validate_visible_facts",
]
