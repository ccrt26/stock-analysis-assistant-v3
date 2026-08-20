"""Run the frozen formation-date validation for the market interpretation Skill.

The script writes reproducible research artifacts under the Git-ignored local
archive.  It refuses to run if the preregistered hypothesis file has changed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from stock_analyzer.analysis.market_context_features import SCOPE_ANCHOR_INDEX_CODES
from stock_analyzer.analysis.market_skill_validation import (
    MARKET_VALIDATION_VERSION,
    build_market_formation_panel,
    evaluate_market_hypotheses,
    fit_market_thresholds,
)
from stock_analyzer.config import AppConfig


RUN_ID = "2026-08-19-market-skill-validation-v2"
FIRST_FORMATION_DATE = date(2022, 7, 26)
DEVELOPMENT_END = date(2024, 12, 31)
VALIDATION_START = date(2025, 1, 2)
LAST_FORMATION_DATE = date(2026, 7, 21)
DATA_THROUGH = date(2026, 8, 18)
MARKET_DAILY_START = date(2022, 7, 25)
BOOTSTRAP_REPETITIONS = 1000
PERMUTATION_REPETITIONS = 1000
RANDOM_SEED = 20260819

SAMPLE_COLUMNS = [
    "analysis_date",
    "action_date",
    "ts_code",
    "return_1d",
    "return_5d",
    "return_20d",
    "relative_market_20d",
    "liquidity_log10_amount",
    "amount_ratio_last_20d",
    "hit_20pct_d20",
    "return_close_d20",
]


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    hypothesis_path = (
        repository_root
        / "src"
        / "stock_analyzer"
        / "knowledge"
        / "market_skill_hypotheses.yaml"
    )
    checksum_path = hypothesis_path.with_suffix(".sha256")
    hypothesis_sha256 = _verify_hypothesis_freeze(
        hypothesis_path, checksum_path
    )
    config = AppConfig.load()
    warehouse_root = config.local_warehouse_dir
    source_archive = (
        config.local_archive_dir
        / "price_indicator_validation"
        / "2026-08-19-price-indicator-validation-v1"
        / "frozen-sample.parquet"
    )
    output_root = config.local_archive_dir / "market_skill_validation" / RUN_ID
    if output_root.exists():
        raise FileExistsError(
            f"frozen output already exists; choose a new RUN_ID: {output_root}"
        )
    if not source_archive.exists():
        raise FileNotFoundError(f"frozen stock sample is absent: {source_archive}")

    print("reading frozen stock sample", flush=True)
    sample = pd.read_parquet(source_archive, columns=SAMPLE_COLUMNS)
    _verify_sample_boundaries(sample)
    print(
        f"stock_rows={len(sample)} formation_dates={sample['analysis_date'].nunique()} "
        f"stocks={sample['ts_code'].nunique()}",
        flush=True,
    )
    facts_root = warehouse_root / "facts"
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=4")
        indexes = _index_daily(connection, facts_root)
        print("building default-scope equal-weight daily market returns", flush=True)
        market_daily = _daily_market_returns(
            connection,
            facts_root,
            sample["ts_code"].astype(str).drop_duplicates().sort_values(),
        )
    finally:
        connection.close()
    print(
        f"market_daily_dates={len(market_daily)} "
        f"median_return_count={market_daily['observed_return_count'].median():.0f}",
        flush=True,
    )

    panel = build_market_formation_panel(sample, indexes, market_daily)
    thresholds = fit_market_thresholds(panel, development_end=DEVELOPMENT_END)
    results = evaluate_market_hypotheses(
        panel,
        thresholds,
        validation_start=VALIDATION_START,
        bootstrap_repetitions=BOOTSTRAP_REPETITIONS,
        permutation_repetitions=PERMUTATION_REPETITIONS,
        random_seed=RANDOM_SEED,
    )
    manifest = _input_manifest(
        warehouse_root,
        source_archive=source_archive,
        hypothesis_sha256=hypothesis_sha256,
    )
    results.update(
        {
            "run_id": RUN_ID,
            "design_status": (
                "retrospective frozen design on previously exposed history"
            ),
            "hypothesis_sha256": hypothesis_sha256,
            "input_manifest_sha256": manifest["manifest_sha256"],
            "sample": {
                "stock_row_count": int(len(sample)),
                "stock_count": int(sample["ts_code"].nunique()),
                "formation_date_count": int(panel["analysis_date"].nunique()),
                "first_formation_date": min(panel["analysis_date"]).isoformat(),
                "last_formation_date": max(panel["analysis_date"]).isoformat(),
                "development_end": DEVELOPMENT_END.isoformat(),
                "validation_start": VALIDATION_START.isoformat(),
                "market_daily_first_date": min(
                    market_daily["trade_date"]
                ).isoformat(),
                "market_daily_last_date": max(
                    market_daily["trade_date"]
                ).isoformat(),
                "known_historical_special_treatment_filter": (
                    "inherited from frozen price sample; complete historical names "
                    "remain unavailable"
                ),
            },
        }
    )
    output_root.mkdir(parents=True)
    panel.to_parquet(output_root / "formation-date-panel.parquet", index=False)
    market_daily.to_parquet(output_root / "market-daily-returns.parquet", index=False)
    (output_root / "development-thresholds.json").write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    (output_root / "input-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    (output_root / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2, default=_json_default))


def _verify_hypothesis_freeze(
    hypothesis_path: Path, checksum_path: Path
) -> str:
    if not hypothesis_path.exists() or not checksum_path.exists():
        raise FileNotFoundError("frozen hypothesis file or checksum is absent")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    observed = hashlib.sha256(hypothesis_path.read_bytes()).hexdigest()
    if observed != expected:
        raise ValueError(
            f"frozen hypothesis checksum mismatch: expected {expected}, got {observed}"
        )
    return observed


def _verify_sample_boundaries(sample: pd.DataFrame) -> None:
    dates = pd.to_datetime(sample["analysis_date"], errors="raise").dt.date
    if dates.min() != FIRST_FORMATION_DATE or dates.max() != LAST_FORMATION_DATE:
        raise ValueError("frozen sample formation-date boundaries changed")
    action_dates = pd.to_datetime(sample["action_date"], errors="raise").dt.date
    pairs = pd.DataFrame({"formation": dates, "action": action_dates}).drop_duplicates()
    if pairs["formation"].duplicated().any():
        raise ValueError("a formation date has multiple action dates")


def _index_daily(
    connection: duckdb.DuckDBPyConnection, facts_root: Path
) -> pd.DataFrame:
    index_glob = str(facts_root / "index_daily" / "**" / "*.parquet")
    return connection.execute(
        """
        SELECT trade_date, index_code, close
        FROM read_parquet(?)
        WHERE index_code IN (SELECT * FROM unnest(?))
          AND trade_date BETWEEN DATE '2022-06-01' AND ?
        ORDER BY trade_date, index_code
        """,
        [index_glob, list(SCOPE_ANCHOR_INDEX_CODES), DATA_THROUGH],
    ).fetchdf()


def _daily_market_returns(
    connection: duckdb.DuckDBPyConnection,
    facts_root: Path,
    codes: pd.Series,
) -> pd.DataFrame:
    connection.register("market_validation_codes", pd.DataFrame({"ts_code": codes}))
    equity_glob = str(facts_root / "equity_daily" / "**" / "*.parquet")
    adjustment_glob = str(facts_root / "adj_factor" / "**" / "*.parquet")
    calendar_glob = str(facts_root / "trade_calendar" / "**" / "*.parquet")
    try:
        return connection.execute(
            """
            WITH calendar AS (
                SELECT
                    cal_date AS trade_date,
                    lag(cal_date) OVER (ORDER BY cal_date) AS prior_trade_date
                FROM read_parquet(?)
                WHERE exchange = 'SSE'
                  AND is_open
                  AND cal_date BETWEEN ? AND ?
            ), prices AS (
                SELECT
                    e.trade_date,
                    e.ts_code,
                    e.close * a.adj_factor AS adjusted_close
                FROM read_parquet(?) e
                JOIN market_validation_codes c USING (ts_code)
                JOIN read_parquet(?) a USING (trade_date, ts_code)
                WHERE e.trade_date BETWEEN ? AND ?
                  AND isfinite(e.close)
                  AND e.close > 0
                  AND isfinite(a.adj_factor)
                  AND a.adj_factor > 0
            ), lagged AS (
                SELECT
                    trade_date,
                    ts_code,
                    adjusted_close,
                    lag(adjusted_close) OVER (
                        PARTITION BY ts_code ORDER BY trade_date
                    ) AS prior_adjusted_close,
                    lag(trade_date) OVER (
                        PARTITION BY ts_code ORDER BY trade_date
                    ) AS observed_prior_trade_date
                FROM prices
            ), returns AS (
                SELECT
                    p.trade_date,
                    p.adjusted_close / p.prior_adjusted_close - 1.0 AS return_1d
                FROM lagged p
                JOIN calendar c USING (trade_date)
                WHERE p.observed_prior_trade_date = c.prior_trade_date
                  AND isfinite(p.prior_adjusted_close)
                  AND p.prior_adjusted_close > 0
            )
            SELECT
                trade_date,
                avg(return_1d) AS equal_weight_return_1d,
                count(*) AS observed_return_count
            FROM returns
            WHERE isfinite(return_1d)
            GROUP BY trade_date
            ORDER BY trade_date
            """,
            [
                calendar_glob,
                MARKET_DAILY_START,
                DATA_THROUGH,
                equity_glob,
                adjustment_glob,
                MARKET_DAILY_START,
                DATA_THROUGH,
            ],
        ).fetchdf()
    finally:
        connection.unregister("market_validation_codes")


def _input_manifest(
    warehouse_root: Path,
    *,
    source_archive: Path,
    hypothesis_sha256: str,
) -> dict[str, Any]:
    connection = duckdb.connect(
        str(warehouse_root / "research.duckdb"), read_only=True
    )
    try:
        partitions = connection.execute(
            """
            SELECT
                dataset_id,
                partition_value,
                row_count,
                content_hash,
                file_sha256,
                quality_status
            FROM research_fact_partitions
            WHERE dataset_id IN ('equity_daily', 'adj_factor', 'index_daily', 'trade_calendar')
            ORDER BY dataset_id, partition_value
            """
        ).fetchdf().to_dict("records")
    finally:
        connection.close()
    source_sha256 = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    canonical = json.dumps(partitions, ensure_ascii=False, sort_keys=True, default=str)
    overall = hashlib.sha256(
        (
            hypothesis_sha256
            + source_sha256
            + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        ).encode("utf-8")
    ).hexdigest()
    return {
        "hypothesis_sha256": hypothesis_sha256,
        "frozen_stock_sample": str(source_archive),
        "frozen_stock_sample_sha256": source_sha256,
        "warehouse_partition_count": len(partitions),
        "warehouse_partitions": partitions,
        "manifest_sha256": overall,
    }


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


if __name__ == "__main__":
    main()
