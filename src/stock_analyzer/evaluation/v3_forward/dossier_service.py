from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from stock_analyzer.evaluation.v3_forward.dossiers import (
    DOSSIER_SCHEMA_VERSION,
    build_research_dossiers,
    render_research_dossiers,
)
from stock_analyzer.evaluation.v3_forward.inputs import load_formation_inputs
from stock_analyzer.evaluation.v3_forward.ledger import (
    BundleWriteResult,
    ForwardLedger,
    sha256_file,
)
from stock_analyzer.evaluation.v3_forward.service import _stable_hash


_PROHIBITED_DIRECTIVES = ("目标价", "仓位建议", "止损", "止盈", "自动买入", "自动交易")


@dataclass(frozen=True)
class DossierRunResult:
    bundle: BundleWriteResult
    dossier_count: int
    schema_version: str = DOSSIER_SCHEMA_VERSION


def _existing_generated_at(path: Path) -> str | None:
    payload_path = path / "dossiers.json"
    if not payload_path.is_file():
        return None
    value = json.loads(payload_path.read_text(encoding="utf-8")).get("generated_at")
    return str(value) if value is not None else None


def _decision_card_identity(
    path: Path, formation_hash: str, input_manifest_hash: str
) -> tuple[dict[str, Any], pd.DataFrame]:
    payload = json.loads((path / "cards.json").read_text(encoding="utf-8"))
    if str(payload.get("schema_version")) != "v3-forward-decision-cards-01":
        raise ValueError("research dossier requires decision-card schema 01")
    if str(payload.get("source_formation_content_hash")) != formation_hash:
        raise ValueError("decision-card source formation differs")
    if str(payload.get("input_manifest_hash")) != input_manifest_hash:
        raise ValueError("decision-card input identity differs")
    return payload, pd.read_parquet(path / "cards.parquet")


def build_research_dossier(
    *,
    warehouse_root: Path,
    archive_root: Path,
    output_root: Path,
    formation_date: date,
    now: datetime | None = None,
    enforce_real_root: bool = True,
) -> DossierRunResult:
    ledger = ForwardLedger(output_root, enforce_real_root=enforce_real_root)
    formations = [
        bundle
        for bundle in ledger.load_formations()
        if str(bundle.payload.get("formation_date")) == formation_date.isoformat()
    ]
    if len(formations) != 1:
        raise ValueError("research dossier requires exactly one formation bundle")
    formation = formations[0]
    rule_version = str(formation.payload["rule_version"])
    input_manifest_hash = str(formation.payload.get("input_manifest_hash", ""))
    cards_path = (
        Path(output_root)
        / "decision-cards"
        / f"formation_date={formation_date.isoformat()}"
        / f"rule_version={rule_version}"
    )
    cards_bundle = ledger.load_bundle_result(cards_path)
    card_payload, existing_cards = _decision_card_identity(
        cards_path,
        str(formation.manifest["bundle_content_hash"]),
        input_manifest_hash,
    )
    inputs = load_formation_inputs(
        Path(warehouse_root), Path(archive_root), formation_date
    )
    actual_input_hash = _stable_hash(dict(inputs.input_manifest))
    if actual_input_hash != input_manifest_hash:
        raise ValueError("research dossier input identity differs from formation")
    dossiers = build_research_dossiers(
        formation.payload, formation.candidates, inputs
    )
    if set(dossiers["ts_code"].astype(str)) != set(
        existing_cards.get("ts_code", pd.Series(dtype=str)).astype(str)
    ):
        raise ValueError("research dossier scope differs from decision cards")
    report, stock_reports = render_research_dossiers(formation.payload, dossiers)
    prohibited = [term for term in _PROHIBITED_DIRECTIVES if term in report]
    if prohibited:
        raise ValueError(
            "research dossier contains prohibited directives: " + ", ".join(prohibited)
        )
    final = (
        Path(output_root)
        / "research-dossiers"
        / f"formation_date={formation_date.isoformat()}"
        / f"rule_version={rule_version}"
        / f"schema_version={DOSSIER_SCHEMA_VERSION}"
    )
    generated_at = _existing_generated_at(final) or (
        now or datetime.now(timezone.utc)
    ).isoformat()
    payload: dict[str, Any] = {
        "schema_version": DOSSIER_SCHEMA_VERSION,
        "formation_date": formation_date.isoformat(),
        "rule_version": rule_version,
        "data_cutoff_at": formation.payload.get("data_cutoff_at"),
        "generated_at": generated_at,
        "source_formation_content_hash": formation.manifest["bundle_content_hash"],
        "source_decision_card_content_hash": cards_bundle.bundle_content_hash,
        "source_decision_card_generated_at": card_payload.get("generated_at"),
        "input_manifest_hash": actual_input_hash,
        "dossier_count": len(dossiers),
        "scope_statement": "strict-as-of explanatory projection for action-confirmed stocks only",
        "advice_statement": "research dossier is not a trade instruction or return promise",
    }
    bundle = ledger.write_research_dossier_bundle(
        formation_date,
        rule_version,
        DOSSIER_SCHEMA_VERSION,
        payload,
        dossiers,
        report,
        stock_reports,
    )
    ledger.write_report_projection(
        Path(f"formation_date={formation_date.isoformat()}")
        / f"research-dossier-{rule_version}.md",
        report,
    )
    audit = {
        "schema_version": "v3-forward-research-dossier-audit-01",
        "status": "passed",
        "formation_date": formation_date.isoformat(),
        "rule_version": rule_version,
        "dossier_schema_version": DOSSIER_SCHEMA_VERSION,
        "dossier_count": len(dossiers),
        "source_formation_content_hash": formation.manifest["bundle_content_hash"],
        "source_decision_card_content_hash": cards_bundle.bundle_content_hash,
        "input_manifest_hash": actual_input_hash,
        "data_cutoff_at": formation.payload.get("data_cutoff_at"),
        "dossiers_file_sha256": sha256_file(bundle.path / "dossiers.parquet"),
        "report_file_sha256": sha256_file(bundle.path / "report.md"),
        "per_stock_report_sha256": {
            code: sha256_file(bundle.path / "stocks" / f"{code}.md")
            for code in sorted(stock_reports)
        },
        "action_confirmed_scope_passed": True,
        "strict_cutoff_passed": True,
        "prohibited_directives": prohibited,
        "prohibited_directives_passed": not prohibited,
        "original_formation_unchanged": True,
        "original_decision_cards_unchanged": True,
    }
    ledger.write_text_projection(
        "manifests",
        Path(f"formation_date={formation_date.isoformat()}")
        / f"research-dossier-{rule_version}-audit.json",
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return DossierRunResult(bundle=bundle, dossier_count=len(dossiers))


__all__ = ["DossierRunResult", "build_research_dossier"]
