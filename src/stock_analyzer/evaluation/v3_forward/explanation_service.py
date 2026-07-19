from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from stock_analyzer.evaluation.v3_forward.explanations import (
    build_decision_cards,
    render_decision_cards,
)
from stock_analyzer.evaluation.v3_forward.inputs import load_formation_inputs
from stock_analyzer.evaluation.v3_forward.ledger import (
    BundleWriteResult,
    ForwardLedger,
    sha256_file,
)
from stock_analyzer.evaluation.v3_forward.service import _stable_hash


@dataclass(frozen=True)
class DecisionCardRunResult:
    bundle: BundleWriteResult
    card_count: int


def _existing_generated_at(path: Path) -> str | None:
    payload = path / "cards.json"
    if not payload.is_file():
        return None
    value = json.loads(payload.read_text(encoding="utf-8")).get("generated_at")
    return str(value) if value is not None else None


def _announcement_times(cards: pd.DataFrame) -> list[pd.Timestamp]:
    times: list[pd.Timestamp] = []
    if cards.empty or "recent_announcements_json" not in cards:
        return times
    for value in cards["recent_announcements_json"]:
        for item in json.loads(str(value)):
            times.append(pd.Timestamp(item["available_at"]))
    return times


def explain_observation(
    *,
    warehouse_root: Path,
    archive_root: Path,
    output_root: Path,
    formation_date: date,
    now: datetime | None = None,
    enforce_real_root: bool = True,
) -> DecisionCardRunResult:
    ledger = ForwardLedger(output_root, enforce_real_root=enforce_real_root)
    matches = [
        bundle
        for bundle in ledger.load_formations()
        if str(bundle.payload.get("formation_date")) == formation_date.isoformat()
    ]
    if len(matches) != 1:
        raise ValueError("decision-card explanation requires exactly one formation bundle")
    formation = matches[0]
    inputs = load_formation_inputs(
        Path(warehouse_root), Path(archive_root), formation_date
    )
    input_manifest_hash = _stable_hash(dict(inputs.input_manifest))
    if input_manifest_hash != str(formation.payload.get("input_manifest_hash")):
        raise ValueError("decision-card input identity differs from formation")
    rule_version = str(formation.payload["rule_version"])
    cards = build_decision_cards(formation.payload, formation.candidates, inputs)
    final = (
        Path(output_root)
        / "decision-cards"
        / f"formation_date={formation_date.isoformat()}"
        / f"rule_version={rule_version}"
    )
    generated_at = _existing_generated_at(final) or (
        now or datetime.now(timezone.utc)
    ).isoformat()
    payload: dict[str, Any] = {
        "schema_version": "v3-forward-decision-cards-01",
        "formation_date": formation_date.isoformat(),
        "rule_version": rule_version,
        "data_cutoff_at": formation.payload.get("data_cutoff_at"),
        "generated_at": generated_at,
        "source_formation_content_hash": formation.manifest["bundle_content_hash"],
        "input_manifest_hash": input_manifest_hash,
        "card_count": len(cards),
        "scope_statement": "strict-as-of explanation projection; original formation is unchanged",
        "advice_statement": "action confirmation is not an automatic buy instruction",
    }
    report_payload = {**formation.payload, "generated_at": generated_at}
    report = render_decision_cards(report_payload, cards)
    bundle = ledger.write_decision_card_bundle(
        formation_date, rule_version, payload, cards, report
    )
    ledger.write_report_projection(
        Path(f"formation_date={formation_date.isoformat()}")
        / f"decision-cards-{rule_version}.md",
        report,
    )
    announcement_times = _announcement_times(cards)
    cutoff = pd.Timestamp(inputs.cutoff).tz_convert("UTC")
    audit = {
        "schema_version": "v3-forward-decision-card-audit-01",
        "status": "passed",
        "formation_date": formation_date.isoformat(),
        "rule_version": rule_version,
        "card_count": len(cards),
        "source_formation_content_hash": formation.manifest["bundle_content_hash"],
        "cards_file_sha256": sha256_file(bundle.path / "cards.parquet"),
        "report_file_sha256": sha256_file(bundle.path / "report.md"),
        "max_announcement_available_at": (
            max(announcement_times).isoformat() if announcement_times else None
        ),
        "cutoff_at_utc": cutoff.isoformat(),
        "announcement_cutoff_passed": bool(
            not announcement_times or max(announcement_times) <= cutoff
        ),
        "original_formation_unchanged": True,
    }
    ledger.write_text_projection(
        "manifests",
        Path(f"formation_date={formation_date.isoformat()}")
        / f"decision-cards-{rule_version}-audit.json",
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return DecisionCardRunResult(bundle=bundle, card_count=len(cards))


__all__ = ["DecisionCardRunResult", "explain_observation"]
