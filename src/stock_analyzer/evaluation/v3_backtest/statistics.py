"""Separate, auditable statistics for the frozen V3 backtest experiment."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


STATIONARY_BLOCK_LENGTHS = (5, 10, 20)
STATIONARY_BOOTSTRAP_SEEDS = (20260717, 20260718, 20260719)

_CONTROL_COHORTS = {
    "all_market",
    "matched_market",
    "hotspot_baseline",
    "earnings_baseline",
    "price_baseline",
}


def compare_layers(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Summarize focus, backup layers, and frozen transparent cohorts separately.

    Focus rows are evaluated from their action baseline.  Backup and control
    rows are evaluated from their discovery baseline.  A discovery success
    therefore cannot be reused to make a later focus promotion look successful.
    """

    required = {
        "cohort",
        "layer",
        "baseline_type",
        "horizon",
        "complete_horizon",
        "target_touched",
        "first_target_session",
        "terminal_return",
        "max_adverse_return",
        "target_before_drawdown_5",
        "target_before_drawdown_10",
    }
    _require_columns(outcomes, required, "outcomes")
    prepared = outcomes.copy()
    prepared["group"] = prepared.apply(_comparison_group, axis=1)
    expected_baseline = prepared["group"].map(
        lambda value: "action" if value == "focus" else "discovery"
    )
    prepared = prepared[prepared["baseline_type"].astype(str) == expected_baseline]

    rows: list[dict[str, object]] = []
    for (group_name, horizon), group in prepared.groupby(
        ["group", "horizon"], sort=True, dropna=False
    ):
        complete = group[group["complete_horizon"].astype(bool)]
        hits = complete[complete["target_touched"].astype(bool)]
        rows.append(
            {
                "group": group_name,
                "horizon": horizon,
                "projects": len(group),
                "complete": len(complete),
                "hits": len(hits),
                "touch_rate": _safe_ratio(len(hits), len(complete)),
                "mean_first_target_session": _mean(hits["first_target_session"]),
                "median_first_target_session": _median(
                    hits["first_target_session"]
                ),
                "mean_terminal_return": _mean(complete["terminal_return"]),
                "median_terminal_return": _median(complete["terminal_return"]),
                "mean_max_adverse_return": _mean(
                    complete["max_adverse_return"]
                ),
                "median_max_adverse_return": _median(
                    complete["max_adverse_return"]
                ),
                "target_before_drawdown_5_rate": _boolean_rate(
                    complete["target_before_drawdown_5"]
                ),
                "target_before_drawdown_10_rate": _boolean_rate(
                    complete["target_before_drawdown_10"]
                ),
            }
        )
    return pd.DataFrame(rows)


def compare_replacements(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Compare every challenger with the security it replaced on the same basis."""

    required = {
        "replacement_id",
        "replacement_role",
        "baseline_type",
        "baseline_date",
        "horizon",
        "complete_horizon",
        "target_touched",
        "first_target_session",
        "terminal_return",
        "max_adverse_return",
    }
    _require_columns(outcomes, required, "replacement outcomes")
    prepared = outcomes.copy()
    if not (prepared["baseline_type"].astype(str) == "replacement").all():
        raise ValueError("replacement comparisons require the replacement baseline")
    prepared["baseline_date"] = pd.to_datetime(
        prepared["baseline_date"], errors="raise"
    ).dt.normalize()

    rows: list[dict[str, object]] = []
    for (replacement_id, horizon), group in prepared.groupby(
        ["replacement_id", "horizon"], sort=True, dropna=False
    ):
        roles = group["replacement_role"].astype(str)
        if len(group) != 2 or set(roles) != {"challenger", "replaced"}:
            raise ValueError(
                "each replacement must include exactly one challenger and replaced row"
            )
        if group["baseline_date"].nunique() != 1:
            raise ValueError("replacement pair must share one baseline date")
        if not group["complete_horizon"].astype(bool).all():
            raise ValueError("replacement pair must use the same complete horizon")
        challenger = group[roles == "challenger"].iloc[0]
        replaced = group[roles == "replaced"].iloc[0]
        challenger_hit = bool(challenger["target_touched"])
        replaced_hit = bool(replaced["target_touched"])
        lead_advantage = _lead_advantage(challenger, replaced)
        success = (challenger_hit and not replaced_hit) or (
            challenger_hit
            and replaced_hit
            and lead_advantage is not None
            and lead_advantage > 0
        )
        rows.append(
            {
                "replacement_id": replacement_id,
                "baseline_date": challenger["baseline_date"],
                "horizon": horizon,
                "challenger_target_touched": challenger_hit,
                "replaced_target_touched": replaced_hit,
                "touch_delta": int(challenger_hit) - int(replaced_hit),
                "lead_session_advantage": lead_advantage,
                "terminal_return_delta": float(challenger["terminal_return"])
                - float(replaced["terminal_return"]),
                "drawdown_return_delta": float(challenger["max_adverse_return"])
                - float(replaced["max_adverse_return"]),
                "replacement_success": success,
            }
        )
    return pd.DataFrame(rows)


def summarize_occupancy(statuses: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Report project delays, daily churn/retention, and common exposure."""

    required = {
        "trade_date",
        "project_id",
        "policy",
        "active",
        "layer",
        "transition",
        "invalidated",
        "target_touched",
        "industry",
        "theme",
    }
    _require_columns(statuses, required, "daily statuses")
    prepared = statuses.copy()
    prepared["trade_date"] = pd.to_datetime(
        prepared["trade_date"], errors="raise"
    ).dt.normalize()
    if prepared.duplicated(["trade_date", "policy", "project_id"]).any():
        raise ValueError("daily statuses contain duplicate project-date rows")
    prepared = prepared.sort_values(["policy", "project_id", "trade_date"])

    project_rows: list[dict[str, object]] = []
    for (policy, project_id), group in prepared.groupby(
        ["policy", "project_id"], sort=True, dropna=False
    ):
        group = group.sort_values("trade_date")
        invalidation_date = _first_true_date(group, "invalidated")
        target_date = _first_true_date(group, "target_touched")
        exit_dates = group.loc[
            group["transition"].astype(str).isin({"exited", "replaced"}),
            "trade_date",
        ]
        if exit_dates.empty and group["active"].astype(bool).any():
            first_active_date = group.loc[
                group["active"].astype(bool), "trade_date"
            ].iloc[0]
            later_inactive = group.loc[
                (group["trade_date"] > first_active_date)
                & ~group["active"].astype(bool),
                "trade_date",
            ]
            exit_date = later_inactive.iloc[0] if len(later_inactive) else pd.NaT
        else:
            exit_date = exit_dates.iloc[0] if len(exit_dates) else pd.NaT
        active = group["active"].astype(bool)
        invalid_days = (
            int((active & (group["trade_date"] > invalidation_date)).sum())
            if pd.notna(invalidation_date)
            else 0
        )
        target_days = (
            int((active & (group["trade_date"] > target_date)).sum())
            if pd.notna(target_date)
            else 0
        )
        premature = bool(
            pd.notna(exit_date)
            and pd.notna(target_date)
            and target_date >= exit_date
        )
        project_rows.append(
            {
                "policy": policy,
                "project_id": project_id,
                "active_days": int(active.sum()),
                "invalidation_date": invalidation_date,
                "invalidated_occupancy_days": invalid_days,
                "target_date": target_date,
                "target_occupancy_days": target_days,
                "exit_date": exit_date,
                "premature_exit": premature,
            }
        )

    daily_rows: list[dict[str, object]] = []
    exposure_rows: list[dict[str, object]] = []
    for policy, policy_group in prepared.groupby("policy", sort=True, dropna=False):
        previous_active: set[str] | None = None
        for trade_date, day in policy_group.groupby("trade_date", sort=True):
            active_day = day[day["active"].astype(bool)]
            active_ids = set(active_day["project_id"].astype(str))
            transitions = day["transition"].astype(str)
            daily_rows.append(
                {
                    "policy": policy,
                    "trade_date": trade_date,
                    "active": len(active_ids),
                    "new": int((transitions == "new").sum()),
                    "upgraded": int((transitions == "upgraded").sum()),
                    "downgraded": int((transitions == "downgraded").sum()),
                    "replaced": int((transitions == "replaced").sum()),
                    "exited": int((transitions == "exited").sum()),
                    "retention_rate": (
                        None
                        if previous_active is None or not previous_active
                        else len(previous_active & active_ids) / len(previous_active)
                    ),
                    "complete_reset": bool(
                        previous_active and not (previous_active & active_ids)
                    ),
                }
            )
            industry_counts = _value_counts(active_day["industry"])
            theme_counts = _value_counts(active_day["theme"])
            count = len(active_ids)
            exposure_rows.append(
                {
                    "policy": policy,
                    "trade_date": trade_date,
                    "active": count,
                    "industry_counts": industry_counts,
                    "theme_counts": theme_counts,
                    "max_industry_share": (
                        max(industry_counts.values()) / count
                        if count and industry_counts
                        else None
                    ),
                    "max_theme_share": (
                        max(theme_counts.values()) / count
                        if count and theme_counts
                        else None
                    ),
                }
            )
            previous_active = active_ids

    return {
        "projects": pd.DataFrame(project_rows),
        "daily": pd.DataFrame(daily_rows),
        "exposure": pd.DataFrame(exposure_rows),
    }


def stationary_block_interval(
    values: pd.DataFrame,
    *,
    value_column: str,
    date_column: str = "formation_date",
    sample_column: str = "sample",
    block_column: str = "time_block",
    block_lengths: Sequence[int] = STATIONARY_BLOCK_LENGTHS,
    seeds: Sequence[int] = STATIONARY_BOOTSTRAP_SEEDS,
    repetitions: int = 2_000,
    confidence: float = 0.95,
) -> pd.DataFrame:
    """Report all preregistered stationary-bootstrap sensitivities and blocks."""

    if tuple(block_lengths) != STATIONARY_BLOCK_LENGTHS:
        raise ValueError("stationary sensitivity must report 5, 10, and 20 sessions")
    if tuple(seeds) != STATIONARY_BOOTSTRAP_SEEDS:
        raise ValueError("stationary bootstrap seeds are preregistered and fixed")
    if repetitions <= 0:
        raise ValueError("repetitions must be positive")
    if not 0 < confidence < 1:
        raise ValueError("confidence must lie strictly between zero and one")
    _require_columns(
        values,
        {date_column, sample_column, block_column, value_column},
        "block values",
    )
    prepared = values.copy()
    prepared[date_column] = pd.to_datetime(
        prepared[date_column], errors="raise"
    ).dt.normalize()
    prepared[value_column] = pd.to_numeric(
        prepared[value_column], errors="raise"
    )
    primary = prepared[prepared[sample_column].astype(str) == "primary"]
    if primary.empty:
        raise ValueError("primary sample is empty")
    if set(primary[block_column].astype(str)) != {"A", "B", "C"}:
        raise ValueError("primary sample must report blocks A, B, and C separately")
    date_values = (
        primary.groupby(date_column, sort=True)[value_column].mean().to_numpy(float)
    )
    estimate = float(np.mean(date_values))
    alpha = (1.0 - confidence) / 2.0

    rows: list[dict[str, object]] = []
    for mean_length in STATIONARY_BLOCK_LENGTHS:
        bootstrap_values: list[float] = []
        for seed in STATIONARY_BOOTSTRAP_SEEDS:
            rng = np.random.default_rng(seed)
            for _ in range(repetitions):
                indices = _stationary_indices(
                    len(date_values), mean_length=mean_length, rng=rng
                )
                bootstrap_values.append(float(np.mean(date_values[indices])))
        rows.append(
            {
                "scope": "primary_interval",
                "time_block": None,
                "mean_block_length": mean_length,
                "seeds": STATIONARY_BOOTSTRAP_SEEDS,
                "repetitions": repetitions,
                "n_dates": len(date_values),
                "estimate": estimate,
                "lower": float(np.quantile(bootstrap_values, alpha)),
                "upper": float(np.quantile(bootstrap_values, 1.0 - alpha)),
            }
        )
    for time_block, group in primary.groupby(block_column, sort=True, dropna=False):
        rows.append(
            {
                "scope": "primary_time_block",
                "time_block": time_block,
                "mean_block_length": None,
                "seeds": STATIONARY_BOOTSTRAP_SEEDS,
                "repetitions": repetitions,
                "n_dates": group[date_column].nunique(),
                "estimate": float(
                    group.groupby(date_column)[value_column].mean().mean()
                ),
                "lower": None,
                "upper": None,
            }
        )
    extension = prepared[prepared[sample_column].astype(str) == "extension"]
    if not extension.empty:
        extension_dates = extension.groupby(date_column, sort=True)[value_column].mean()
        rows.append(
            {
                "scope": "extension_sample",
                "time_block": "extension",
                "mean_block_length": None,
                "seeds": STATIONARY_BOOTSTRAP_SEEDS,
                "repetitions": repetitions,
                "n_dates": len(extension_dates),
                "estimate": float(extension_dates.mean()),
                "lower": None,
                "upper": None,
            }
        )
    return pd.DataFrame(rows)


def audit_representative_misses(candidates: pd.DataFrame) -> pd.DataFrame:
    """Classify tradable representative target misses from frozen audit facts."""

    required = {
        "formation_date",
        "ts_code",
        "representative",
        "target_touched",
        "basically_tradable",
        "selected",
        "route_scanned",
        "evidence_complete",
        "comparison_passed",
    }
    _require_columns(candidates, required, "miss candidates")
    prepared = candidates.copy()
    prepared["formation_date"] = pd.to_datetime(
        prepared["formation_date"], errors="raise"
    ).dt.normalize()
    mask = (
        prepared["representative"].astype(bool)
        & prepared["target_touched"].astype(bool)
        & prepared["basically_tradable"].astype(bool)
        & ~prepared["selected"].astype(bool)
    )
    misses = prepared[mask].copy()
    misses["miss_reason"] = misses.apply(_miss_reason, axis=1)
    return misses.sort_values(["formation_date", "ts_code"]).reset_index(drop=True)


def _comparison_group(row: pd.Series) -> str:
    cohort = str(row["cohort"])
    return cohort if cohort in _CONTROL_COHORTS else str(row["layer"])


def _lead_advantage(
    challenger: pd.Series,
    replaced: pd.Series,
) -> float | None:
    challenger_hit = bool(challenger["target_touched"])
    replaced_hit = bool(replaced["target_touched"])
    if challenger_hit and replaced_hit:
        return float(replaced["first_target_session"]) - float(
            challenger["first_target_session"]
        )
    if challenger_hit and not replaced_hit:
        return float("inf")
    if replaced_hit and not challenger_hit:
        return float("-inf")
    return None


def _first_true_date(group: pd.DataFrame, column: str) -> pd.Timestamp | pd.NaT:
    dates = group.loc[group[column].astype(bool), "trade_date"]
    return dates.iloc[0] if len(dates) else pd.NaT


def _value_counts(values: pd.Series) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in values.dropna().astype(str).value_counts().items()
    }


def _stationary_indices(
    size: int,
    *,
    mean_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    indices = np.empty(size, dtype=int)
    indices[0] = int(rng.integers(size))
    restart_probability = 1.0 / mean_length
    for position in range(1, size):
        if rng.random() < restart_probability:
            indices[position] = int(rng.integers(size))
        else:
            indices[position] = (indices[position - 1] + 1) % size
    return indices


def _miss_reason(row: pd.Series) -> str:
    if not bool(row["route_scanned"]):
        return "route_miss"
    if not bool(row["evidence_complete"]):
        return "evidence_missing"
    if not bool(row["comparison_passed"]):
        return "comparison_failure"
    return "capacity_limit"


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} lack required fields: {', '.join(missing)}")


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if len(numeric) else None


def _median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if len(numeric) else None


def _boolean_rate(values: pd.Series) -> float | None:
    present = values.dropna()
    return float(present.astype(bool).mean()) if len(present) else None


__all__ = [
    "STATIONARY_BLOCK_LENGTHS",
    "STATIONARY_BOOTSTRAP_SEEDS",
    "audit_representative_misses",
    "compare_layers",
    "compare_replacements",
    "stationary_block_interval",
    "summarize_occupancy",
]
