from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from stock_analyzer.evaluation.v3_forward.inputs import (
    form_attention_list,
    load_formation_inputs,
)
from stock_analyzer.evaluation.v3_forward.ledger import (
    BundleWriteResult,
    ForwardLedger,
    sha256_file,
)
from stock_analyzer.evaluation.v3_forward.reports import (
    render_entry_report,
    render_formation_report,
)
from stock_analyzer.evaluation.v3_forward.rules import (
    RULE_VERSION,
    TARGET_RETURN,
    classify_entry,
    rule_manifest,
    rule_manifest_hash,
)


@dataclass(frozen=True)
class FormationRunResult:
    bundle: BundleWriteResult
    attention_count: int
    action_count: int


@dataclass(frozen=True)
class UpdateRunResult:
    entry_bundles: tuple[BundleWriteResult, ...]
    snapshot_bundles: tuple[BundleWriteResult, ...]
    waiting_formations: tuple[date, ...]


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"cannot encode {type(value)!r}")


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def form_observation(
    *,
    warehouse_root: Path,
    archive_root: Path,
    output_root: Path,
    formation_date: date,
    now: datetime | None = None,
    enforce_real_root: bool = True,
) -> FormationRunResult:
    ledger = ForwardLedger(output_root, enforce_real_root=enforce_real_root)
    existing = next(
        (
            bundle
            for bundle in ledger.load_formations()
            if str(bundle.payload.get("formation_date")) == formation_date.isoformat()
        ),
        None,
    )
    inputs = load_formation_inputs(Path(warehouse_root), Path(archive_root), formation_date)
    candidates = form_attention_list(inputs)
    generated = (
        str(existing.payload["generated_at"])
        if existing is not None and "generated_at" in existing.payload
        else (now or datetime.now(timezone.utc)).isoformat()
    )
    input_manifest = dict(inputs.input_manifest)
    payload = {
        "schema_version": "v3-forward-formation-01",
        "formation_batch_id": f"{RULE_VERSION}|{formation_date.isoformat()}",
        "rule_version": RULE_VERSION,
        "rule_manifest_hash": rule_manifest_hash(),
        "rule_manifest": rule_manifest(),
        "formation_date": formation_date.isoformat(),
        "data_cutoff_at": inputs.cutoff.isoformat(),
        "generated_at": generated,
        "input_manifest_hash": _stable_hash(input_manifest),
        "input_manifest": input_manifest,
        "attention_count": len(candidates),
        "action_count": int(
            candidates.get("action_confirmed", pd.Series(dtype=bool))
            .fillna(False)
            .astype(bool)
            .sum()
        ),
        "entry_state": "waiting",
        "future_visibility_statement": "formation uses no facts after the formation cutoff",
        "advice_statement": "forward observation only; not trading advice",
    }
    report = render_formation_report(payload, candidates)
    bundle = ledger.write_formation_bundle(payload, candidates, report)
    return FormationRunResult(bundle, len(candidates), int(payload["action_count"]))


def _market_sessions(warehouse_root: Path, through: date) -> list[date]:
    sessions: list[date] = []
    root = Path(warehouse_root) / "facts" / "equity_daily"
    for path in root.glob("trade_date=*"):
        try:
            value = date.fromisoformat(path.name.split("=", 1)[1])
        except (IndexError, ValueError):
            continue
        if value <= through:
            sessions.append(value)
    return sorted(set(sessions))


def _read_partition(warehouse_root: Path, table: str, trading_date: date) -> pd.DataFrame:
    path = (
        Path(warehouse_root)
        / "facts"
        / table
        / f"trade_date={trading_date.isoformat()}"
        / "data.parquet"
    )
    return pd.read_parquet(path) if path.is_file() else pd.DataFrame()


def _source_signatures(warehouse_root: Path, trading_date: date) -> str:
    signatures: dict[str, str] = {}
    for table in ("equity_daily", "adj_factor", "stock_limit"):
        path = (
            Path(warehouse_root)
            / "facts"
            / table
            / f"trade_date={trading_date.isoformat()}"
            / "data.parquet"
        )
        if path.is_file():
            signatures[table] = sha256_file(path)
    return json.dumps(signatures, ensure_ascii=False, sort_keys=True)


def _entry_rows(
    warehouse_root: Path,
    formation_date: date,
    entry_date: date,
    candidates: pd.DataFrame,
    observed_at: datetime,
) -> pd.DataFrame:
    confirmed = candidates[
        candidates["action_confirmed"].fillna(False).astype(bool)
    ].copy()
    columns = [
        "formation_date",
        "entry_date",
        "ts_code",
        "entry_status",
        "executable_entry",
        "raw_entry_open",
        "entry_adj_factor",
        "formation_close",
        "action_price",
        "target_price",
        "formation_to_entry_gap",
        "observed_at",
        "input_file_sha256",
    ]
    if confirmed.empty:
        return pd.DataFrame(columns=columns)
    entry_prices = _read_partition(warehouse_root, "equity_daily", entry_date)
    entry_factors = _read_partition(warehouse_root, "adj_factor", entry_date)
    limits = _read_partition(warehouse_root, "stock_limit", entry_date)
    formation_prices = _read_partition(warehouse_root, "equity_daily", formation_date)
    formation_factors = _read_partition(warehouse_root, "adj_factor", formation_date)
    base = confirmed[["ts_code"]].drop_duplicates().copy()
    quote_columns = [column for column in ("ts_code", "open", "high", "low", "close") if column in entry_prices]
    quotes = entry_prices[quote_columns].copy() if quote_columns else pd.DataFrame({"ts_code": []})
    frame = base.merge(quotes, on="ts_code", how="left")
    if not entry_factors.empty:
        frame = frame.merge(
            entry_factors[["ts_code", "adj_factor"]], on="ts_code", how="left"
        )
    else:
        frame["adj_factor"] = np.nan
    if not limits.empty:
        frame = frame.merge(limits[["ts_code", "up_limit"]], on="ts_code", how="left")
    else:
        frame["up_limit"] = np.nan
    formation = formation_prices[["ts_code", "close"]].rename(
        columns={"close": "formation_raw_close"}
    ) if not formation_prices.empty else pd.DataFrame({"ts_code": [], "formation_raw_close": []})
    if not formation_factors.empty:
        formation = formation.merge(
            formation_factors[["ts_code", "adj_factor"]].rename(
                columns={"adj_factor": "formation_adj_factor"}
            ),
            on="ts_code",
            how="left",
        )
    frame = frame.merge(formation, on="ts_code", how="left")
    rows: list[dict[str, Any]] = []
    signatures = _source_signatures(warehouse_root, entry_date)
    for row in frame.to_dict(orient="records"):
        classification = classify_entry(row)
        factor = pd.to_numeric(pd.Series([row.get("adj_factor")]), errors="coerce").iloc[0]
        raw_open = classification["raw_entry_open"]
        action_price = (
            float(raw_open) * float(factor)
            if raw_open is not None and pd.notna(factor)
            else None
        )
        formation_close = None
        if pd.notna(row.get("formation_raw_close")) and pd.notna(row.get("formation_adj_factor")):
            formation_close = float(row["formation_raw_close"]) * float(row["formation_adj_factor"])
        rows.append(
            {
                "formation_date": formation_date,
                "entry_date": entry_date,
                "ts_code": str(row["ts_code"]),
                **classification,
                "entry_adj_factor": float(factor) if pd.notna(factor) else None,
                "formation_close": formation_close,
                "action_price": action_price,
                "target_price": action_price * (1.0 + TARGET_RETURN) if action_price else None,
                "formation_to_entry_gap": (
                    action_price / formation_close - 1.0
                    if action_price and formation_close
                    else None
                ),
                "observed_at": observed_at,
                "input_file_sha256": signatures,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def update_observations(
    *,
    warehouse_root: Path,
    output_root: Path,
    as_of_date: date,
    now: datetime | None = None,
    enforce_real_root: bool = True,
) -> UpdateRunResult:
    ledger = ForwardLedger(output_root, enforce_real_root=enforce_real_root)
    sessions = _market_sessions(warehouse_root, as_of_date)
    observed_at = now or datetime.now(timezone.utc)
    entry_results: list[BundleWriteResult] = []
    waiting: list[date] = []
    for formation in ledger.load_formations():
        formation_date = date.fromisoformat(str(formation.payload["formation_date"]))
        future_sessions = [value for value in sessions if value > formation_date]
        if not future_sessions:
            waiting.append(formation_date)
            continue
        entry_date = future_sessions[0]
        entries = _entry_rows(
            Path(warehouse_root),
            formation_date,
            entry_date,
            formation.candidates,
            observed_at,
        )
        report = render_entry_report(
            formation_date.isoformat(), entry_date.isoformat(), entries
        )
        entry_results.append(
            ledger.write_entry_bundle(
                formation_date, entry_date, entries, report
            )
        )
    return UpdateRunResult(tuple(entry_results), (), tuple(waiting))


__all__ = [
    "FormationRunResult",
    "UpdateRunResult",
    "form_observation",
    "update_observations",
]
