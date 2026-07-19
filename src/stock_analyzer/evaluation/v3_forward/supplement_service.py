from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from stock_analyzer.evaluation.v3_forward.dossier_supplements import (
    SUPPLEMENT_SCHEMA_VERSION,
    write_official_supplements,
)
from stock_analyzer.evaluation.v3_forward.ledger import BundleWriteResult, ForwardLedger


@dataclass(frozen=True)
class SupplementRunResult:
    bundle: BundleWriteResult
    fact_count: int
    schema_version: str = SUPPLEMENT_SCHEMA_VERSION


def add_official_dossier_supplements(
    *,
    output_root: Path,
    formation_date: date,
    facts_json: Path,
    enforce_real_root: bool = True,
) -> SupplementRunResult:
    ledger = ForwardLedger(output_root, enforce_real_root=enforce_real_root)
    formations = [
        item
        for item in ledger.load_formations()
        if str(item.payload.get("formation_date")) == formation_date.isoformat()
    ]
    if len(formations) != 1:
        raise ValueError("official supplements require exactly one formation bundle")
    formation = formations[0]
    raw: Any = json.loads(Path(facts_json).read_text(encoding="utf-8"))
    records = raw.get("facts") if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        raise ValueError("official supplement JSON must be a list or contain facts list")
    facts = pd.DataFrame(records)
    confirmed_codes = set(
        formation.candidates.loc[
            formation.candidates["action_confirmed"].fillna(False).astype(bool),
            "ts_code",
        ].astype(str)
    )
    supplied_codes = set(facts.get("ts_code", pd.Series(dtype=str)).astype(str))
    if not supplied_codes <= confirmed_codes:
        raise ValueError("official supplements must only describe action-confirmed stocks")
    result = write_official_supplements(
        output_root=output_root,
        formation_date=formation_date,
        cutoff=pd.Timestamp(formation.payload["data_cutoff_at"]),
        facts=facts,
        enforce_real_root=enforce_real_root,
    )
    return SupplementRunResult(bundle=result, fact_count=len(facts))


__all__ = ["SupplementRunResult", "add_official_dossier_supplements"]
