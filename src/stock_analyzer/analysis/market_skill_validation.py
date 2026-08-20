"""Formation-date validation helpers for the market interpretation Skill.

All stock outcomes are aggregated to one row per formation date before any
inference.  The helpers are research instruments; they do not create a market
score, a production regime, or a trading rule.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from math import sqrt

import numpy as np
import pandas as pd

from stock_analyzer.analysis.market_context_features import SCOPE_ANCHOR_INDEX_CODES


MARKET_VALIDATION_VERSION = "market-skill-formation-date-v1"
THRESHOLD_FIELDS = (
    "breadth_5d",
    "breadth_20d",
    "turnover_ratio_20d",
    "equal_weight_return_5d",
)
QUANTILES = {"q40": 0.40, "q60": 0.60}


def build_market_formation_panel(
    stock_sample: pd.DataFrame,
    index_daily: pd.DataFrame,
    market_daily_returns: pd.DataFrame,
    *,
    future_volatility_window: int = 20,
) -> pd.DataFrame:
    """Aggregate stock rows and attach index and future market-path facts."""

    required_stock = {
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
    }
    missing = sorted(required_stock - set(stock_sample.columns))
    if missing:
        raise ValueError(f"stock sample lacks required fields: {', '.join(missing)}")
    sample = stock_sample.copy()
    sample["analysis_date"] = pd.to_datetime(
        sample["analysis_date"], errors="raise"
    ).dt.date
    sample["action_date"] = pd.to_datetime(
        sample["action_date"], errors="raise"
    ).dt.date
    if sample.duplicated(["analysis_date", "ts_code"]).any():
        raise ValueError("stock sample has duplicate formation-date security rows")

    indexes = _prepare_index_daily(index_daily)
    market_returns = _prepare_market_daily_returns(market_daily_returns)
    rows: list[dict[str, object]] = []
    for formation_date, group in sample.groupby("analysis_date", sort=True):
        action_dates = group["action_date"].dropna().unique()
        if len(action_dates) != 1:
            raise ValueError("each formation date must have exactly one action date")
        action_date = _as_date(action_dates[0])
        return_1d = _numeric(group["return_1d"])
        return_5d = _numeric(group["return_5d"])
        return_20d = _numeric(group["return_20d"])
        hit = _numeric(group["hit_20pct_d20"])
        future_return = _numeric(group["return_close_d20"])
        relative = _numeric(group["relative_market_20d"])
        current_amount = np.power(10.0, _numeric(group["liquidity_log10_amount"]))
        amount_ratio = _numeric(group["amount_ratio_last_20d"])
        trailing_average_amount = current_amount / amount_ratio
        valid_turnover = (
            np.isfinite(current_amount)
            & (current_amount > 0.0)
            & np.isfinite(trailing_average_amount)
            & (trailing_average_amount > 0.0)
        )
        turnover_coverage_ratio = float(valid_turnover.mean())
        turnover_ratio = (
            float(
                current_amount[valid_turnover].sum()
                / trailing_average_amount[valid_turnover].sum()
            )
            if turnover_coverage_ratio >= 0.95
            else np.nan
        )
        valid_trend = relative.notna() & future_return.notna()
        trend_spread = _tail_spread(
            relative[valid_trend], future_return[valid_trend]
        )
        rows.append(
            {
                "analysis_date": formation_date,
                "action_date": action_date,
                "stock_count": int(group["ts_code"].nunique()),
                "equal_weight_return_5d": _mean_or_nan(return_5d),
                "median_return_5d": _median_or_nan(return_5d),
                "breadth_5d": _positive_share(return_5d),
                "equal_weight_return_20d": _mean_or_nan(return_20d),
                "median_return_20d": _median_or_nan(return_20d),
                "breadth_20d": _positive_share(return_20d),
                "return_dispersion_1d": _std_or_nan(return_1d, ddof=0),
                "turnover_coverage_ratio": turnover_coverage_ratio,
                "turnover_ratio_20d": turnover_ratio,
                "scope_anchor_return_5d": _scope_anchor_return(
                    indexes, formation_date, horizon=5
                ),
                "opportunity_hit_rate_20d": _mean_or_nan(hit),
                "equal_weight_return_close_20d": _mean_or_nan(future_return),
                "future_market_volatility_20d": _future_market_volatility(
                    market_returns,
                    action_date,
                    window=future_volatility_window,
                ),
                "trend_spread_return_20d": trend_spread,
            }
        )
    return pd.DataFrame(rows).sort_values("analysis_date").reset_index(drop=True)


def fit_market_thresholds(
    formation_panel: pd.DataFrame,
    *,
    development_end: date,
) -> dict[str, dict[str, float]]:
    """Fit Q40/Q60 boundaries on development formation dates only."""

    _require_columns(formation_panel, {"analysis_date", *THRESHOLD_FIELDS})
    dates = pd.to_datetime(formation_panel["analysis_date"], errors="raise").dt.date
    development = formation_panel.loc[dates <= _as_date(development_end)]
    if development.empty:
        raise ValueError("development formation period is empty")
    thresholds: dict[str, dict[str, float]] = {}
    for field in THRESHOLD_FIELDS:
        values = _numeric(development[field]).dropna()
        if values.empty:
            raise ValueError(f"development field has no finite values: {field}")
        thresholds[field] = {
            name: float(values.quantile(level)) for name, level in QUANTILES.items()
        }
    absolute = _numeric(development["equal_weight_return_5d"]).abs().dropna()
    thresholds["abs_equal_weight_return_5d"] = {
        name: float(absolute.quantile(level)) for name, level in QUANTILES.items()
    }
    return thresholds


def assign_market_hypotheses(
    formation_panel: pd.DataFrame,
    thresholds: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, pd.Series]]:
    """Assign frozen feature-side groups without reading any future outcome."""

    required_thresholds = {*THRESHOLD_FIELDS, "abs_equal_weight_return_5d"}
    missing_thresholds = sorted(required_thresholds - set(thresholds))
    if missing_thresholds:
        raise ValueError(
            f"market thresholds lack: {', '.join(missing_thresholds)}"
        )
    feature_fields = {
        "scope_anchor_return_5d",
        "equal_weight_return_5d",
        "median_return_5d",
        "breadth_5d",
        "breadth_20d",
        "turnover_ratio_20d",
        "equal_weight_return_20d",
        "return_dispersion_1d",
    }
    _require_columns(formation_panel, feature_fields)
    numeric = {
        field: _numeric(formation_panel[field]) for field in feature_fields
    }

    def q(field: str, name: str) -> float:
        return float(thresholds[field][name])

    anchor = numeric["scope_anchor_return_5d"]
    return_5d = numeric["equal_weight_return_5d"]
    median_5d = numeric["median_return_5d"]
    breadth_5d = numeric["breadth_5d"]
    breadth_20d = numeric["breadth_20d"]
    turnover = numeric["turnover_ratio_20d"]
    return_20d = numeric["equal_weight_return_20d"]
    dispersion = numeric["return_dispersion_1d"]

    h1_complete = pd.concat(
        [anchor, return_5d, median_5d, breadth_5d], axis=1
    ).notna().all(axis=1)
    h1_case = (
        h1_complete
        & (anchor > 0.0)
        & (return_5d > 0.0)
        & (median_5d > 0.0)
        & (breadth_5d >= q("breadth_5d", "q60"))
    )
    h1_control = (
        h1_complete
        & (anchor > 0.0)
        & (
            (median_5d <= 0.0)
            | (breadth_5d <= q("breadth_5d", "q40"))
        )
    )

    h2_complete = pd.concat([turnover, return_5d, breadth_5d], axis=1).notna().all(
        axis=1
    )
    high_turnover = turnover >= q("turnover_ratio_20d", "q60")
    h2_case = (
        h2_complete
        & high_turnover
        & (return_5d >= q("equal_weight_return_5d", "q60"))
        & (breadth_5d >= q("breadth_5d", "q60"))
    )
    h2_control = (
        h2_complete
        & high_turnover
        & (return_5d.abs() <= q("abs_equal_weight_return_5d", "q40"))
        & (breadth_5d <= q("breadth_5d", "q40"))
    )

    h3_available = dispersion.notna()
    h4_complete = pd.concat([return_20d, return_5d, breadth_20d], axis=1).notna().all(
        axis=1
    )
    continuous_rise = (
        h4_complete
        & (return_20d > 0.0)
        & (return_5d > 0.0)
        & (breadth_20d >= q("breadth_20d", "q60"))
    )
    return {
        "market_h1_breadth_index_alignment": {
            "case": h1_case,
            "control": h1_control,
        },
        "market_h2_turnover_price_progress": {
            "case": h2_case,
            "control": h2_control,
        },
        "market_h3_dispersion_future_volatility": {"available": h3_available},
        "market_h4_state_changes_trend_reliability": {
            "continuous_rise": continuous_rise,
            "other": h4_complete & ~continuous_rise,
        },
    }


def evaluate_market_hypotheses(
    formation_panel: pd.DataFrame,
    thresholds: Mapping[str, Mapping[str, float]],
    *,
    validation_start: date = date(2025, 1, 2),
    bootstrap_repetitions: int = 1000,
    permutation_repetitions: int = 1000,
    random_seed: int = 20260819,
) -> dict[str, object]:
    """Evaluate the four frozen hypotheses on validation formation dates."""

    outcome_fields = {
        "analysis_date",
        "opportunity_hit_rate_20d",
        "future_market_volatility_20d",
        "trend_spread_return_20d",
    }
    _require_columns(formation_panel, outcome_fields)
    panel = formation_panel.copy()
    panel["analysis_date"] = pd.to_datetime(
        panel["analysis_date"], errors="raise"
    ).dt.date
    panel = panel[panel["analysis_date"] >= _as_date(validation_start)]
    panel = panel.sort_values("analysis_date").reset_index(drop=True)
    if panel.empty:
        raise ValueError("validation formation period is empty")
    assignments = assign_market_hypotheses(panel, thresholds)
    rng = np.random.default_rng(random_seed)
    specifications = {
        "market_h1_breadth_index_alignment": {
            "kind": "difference",
            "first": "case",
            "second": "control",
            "outcome": "opportunity_hit_rate_20d",
            "minimum_effect": 0.02,
            "tail": "positive",
            "stability_direction": "positive",
        },
        "market_h2_turnover_price_progress": {
            "kind": "difference",
            "first": "case",
            "second": "control",
            "outcome": "opportunity_hit_rate_20d",
            "minimum_effect": 0.02,
            "tail": "positive",
            "stability_direction": "positive",
        },
        "market_h3_dispersion_future_volatility": {
            "kind": "correlation",
            "feature": "return_dispersion_1d",
            "outcome": "future_market_volatility_20d",
            "minimum_effect": 0.15,
            "tail": "positive",
            "stability_direction": "positive",
        },
        "market_h4_state_changes_trend_reliability": {
            "kind": "difference",
            "first": "continuous_rise",
            "second": "other",
            "outcome": "trend_spread_return_20d",
            "minimum_effect": 0.02,
            "tail": "two_sided",
            "stability_direction": "same_sign",
        },
    }
    evaluations: dict[str, dict[str, object]] = {}
    raw_p_values: dict[str, float] = {}
    for hypothesis_id, specification in specifications.items():
        evaluation = _evaluate_one(
            panel,
            assignments[hypothesis_id],
            specification,
            hypothesis_id=hypothesis_id,
            thresholds=thresholds,
            bootstrap_repetitions=bootstrap_repetitions,
            permutation_repetitions=permutation_repetitions,
            rng=rng,
        )
        evaluations[hypothesis_id] = evaluation
        raw_p_values[hypothesis_id] = float(evaluation["raw_p_value"])
    adjusted = _holm_adjust(raw_p_values)
    for hypothesis_id, evaluation in evaluations.items():
        evaluation["holm_adjusted_p_value"] = adjusted[hypothesis_id]
        effect = float(evaluation["effect"])
        lower, upper = evaluation["confidence_interval_95"]
        minimum = float(specifications[hypothesis_id]["minimum_effect"])
        tail = str(specifications[hypothesis_id]["tail"])
        if tail == "positive":
            effect_pass = effect >= minimum and lower > 0.0
            stability_pass = all(
                value is not None and value > 0.0
                for value in evaluation["calendar_period_effects"].values()
            )
        else:
            effect_pass = abs(effect) >= minimum and (lower > 0.0 or upper < 0.0)
            stability_pass = all(
                value is not None and np.sign(value) == np.sign(effect)
                for value in evaluation["calendar_period_effects"].values()
            )
        admission = bool(
            evaluation["coverage_passed"]
            and effect_pass
            and adjusted[hypothesis_id] < 0.05
            and stability_pass
        )
        evaluation["admission_passed"] = admission
        evaluation["maturity"] = (
            "level_2_direct" if admission else "validation_capability"
        )
    return {
        "validation_version": MARKET_VALIDATION_VERSION,
        "unit_of_analysis": "formation_date",
        "formation_date_count": int(len(panel)),
        "first_formation_date": min(panel["analysis_date"]).isoformat(),
        "last_formation_date": max(panel["analysis_date"]).isoformat(),
        "hypotheses": evaluations,
    }


def _evaluate_one(
    panel: pd.DataFrame,
    masks: Mapping[str, pd.Series],
    specification: Mapping[str, object],
    *,
    hypothesis_id: str,
    thresholds: Mapping[str, Mapping[str, float]],
    bootstrap_repetitions: int,
    permutation_repetitions: int,
    rng: np.random.Generator,
) -> dict[str, object]:
    kind = str(specification["kind"])
    outcome = str(specification["outcome"])
    if kind == "difference":
        first_name = str(specification["first"])
        second_name = str(specification["second"])
        first = masks[first_name] & _numeric(panel[outcome]).notna()
        second = masks[second_name] & _numeric(panel[outcome]).notna()
        effect = _difference(panel[outcome], first, second)
        group_counts = {first_name: int(first.sum()), second_name: int(second.sum())}
        coverage = _difference_coverage(panel, first, second)

        def statistic(sampled: pd.DataFrame) -> float:
            sampled_masks = assign_market_hypotheses(sampled, thresholds)
            current = sampled_masks[hypothesis_id]
            return _difference(
                sampled[outcome], current[first_name], current[second_name]
            )

    else:
        feature = str(specification["feature"])
        available = masks["available"] & _numeric(panel[outcome]).notna()
        available &= _numeric(panel[feature]).notna()
        effect = _spearman(panel.loc[available, feature], panel.loc[available, outcome])
        group_counts = {"available": int(available.sum())}
        coverage = _correlation_coverage(panel, available)

        def statistic(sampled: pd.DataFrame) -> float:
            valid = _numeric(sampled[feature]).notna() & _numeric(
                sampled[outcome]
            ).notna()
            return _spearman(
                sampled.loc[valid, feature], sampled.loc[valid, outcome]
            )

    bootstrap_values: list[float] = []
    for _ in range(bootstrap_repetitions):
        sampled = panel.iloc[_moving_block_indices(len(panel), rng, block_size=4)]
        value = statistic(sampled.reset_index(drop=True))
        if np.isfinite(value):
            bootstrap_values.append(float(value))
    if bootstrap_values:
        lower, upper = np.quantile(bootstrap_values, [0.025, 0.975])
    else:
        lower, upper = np.nan, np.nan
    null_values: list[float] = []
    for _ in range(permutation_repetitions):
        randomized = panel.copy()
        randomized[outcome] = _independent_block_values(
            panel[outcome], rng, block_size=4
        )
        value = statistic(randomized)
        if np.isfinite(value):
            null_values.append(float(value))
    tail = str(specification["tail"])
    raw_p = _randomization_p_value(effect, null_values, tail=tail)
    period_effects: dict[str, float | None] = {}
    years = pd.Series(panel["analysis_date"]).map(lambda value: value.year)
    for year in (2025, 2026):
        subset = panel.loc[years == year].reset_index(drop=True)
        if subset.empty:
            period_effects[str(year)] = None
            continue
        value = statistic(subset)
        period_effects[str(year)] = float(value) if np.isfinite(value) else None
    return {
        "effect": float(effect) if np.isfinite(effect) else np.nan,
        "confidence_interval_95": [float(lower), float(upper)],
        "raw_p_value": raw_p,
        "group_date_counts": group_counts,
        "calendar_period_effects": period_effects,
        "coverage_passed": coverage,
    }


def _prepare_index_daily(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, {"trade_date", "index_code", "close"})
    prepared = frame.copy()
    prepared["trade_date"] = pd.to_datetime(
        prepared["trade_date"], errors="raise"
    ).dt.date
    prepared["close"] = _numeric(prepared["close"])
    if prepared.duplicated(["trade_date", "index_code"]).any():
        raise ValueError("index daily has duplicate business facts")
    return prepared.sort_values(["index_code", "trade_date"])


def _prepare_market_daily_returns(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, {"trade_date", "equal_weight_return_1d"})
    prepared = frame.copy()
    prepared["trade_date"] = pd.to_datetime(
        prepared["trade_date"], errors="raise"
    ).dt.date
    prepared["equal_weight_return_1d"] = _numeric(
        prepared["equal_weight_return_1d"]
    )
    if prepared["trade_date"].duplicated().any():
        raise ValueError("market daily returns have duplicate dates")
    return prepared.sort_values("trade_date").reset_index(drop=True)


def _scope_anchor_return(
    indexes: pd.DataFrame, formation_date: date, *, horizon: int
) -> float:
    calendar_dates = sorted(
        indexes.loc[
            indexes["index_code"].astype(str).isin(SCOPE_ANCHOR_INDEX_CODES)
            & (indexes["trade_date"] <= formation_date),
            "trade_date",
        ].unique()
    )
    calendar_dates = calendar_dates[-horizon - 1 :]
    if (
        len(calendar_dates) != horizon + 1
        or calendar_dates[-1] != formation_date
    ):
        return np.nan
    returns: list[float] = []
    for code in SCOPE_ANCHOR_INDEX_CODES:
        code_rows = indexes[
            (indexes["index_code"].astype(str) == code)
            & (indexes["trade_date"] <= formation_date)
        ].set_index("trade_date")["close"]
        values = code_rows.reindex(calendar_dates)
        if not _all_finite_positive(values):
            return np.nan
        returns.append(float(values.iloc[-1] / values.iloc[0] - 1.0))
    return float(np.mean(returns))


def _future_market_volatility(
    market_returns: pd.DataFrame, action_date: date, *, window: int
) -> float:
    future = market_returns[market_returns["trade_date"] >= action_date].head(window)
    if future.empty or future.iloc[0]["trade_date"] != action_date:
        return np.nan
    values = _numeric(future["equal_weight_return_1d"])
    if len(values) != window or not np.isfinite(values).all():
        return np.nan
    return float(values.std(ddof=1) * sqrt(252.0))


def _tail_spread(signal: pd.Series, outcome: pd.Series) -> float:
    if len(signal) < 5 or len(outcome) != len(signal):
        return np.nan
    low, high = signal.quantile([0.20, 0.80])
    first = outcome[signal >= high]
    second = outcome[signal <= low]
    if first.empty or second.empty:
        return np.nan
    return float(first.mean() - second.mean())


def _difference(values: pd.Series, first: pd.Series, second: pd.Series) -> float:
    numeric = _numeric(values)
    if not first.any() or not second.any():
        return np.nan
    return float(numeric[first].mean() - numeric[second].mean())


def _spearman(first: pd.Series, second: pd.Series) -> float:
    left = _numeric(first)
    right = _numeric(second)
    valid = left.notna() & right.notna()
    if valid.sum() < 3:
        return np.nan
    return float(left[valid].rank().corr(right[valid].rank()))


def _difference_coverage(
    panel: pd.DataFrame, first: pd.Series, second: pd.Series
) -> bool:
    if int(first.sum()) < 30 or int(second.sum()) < 30:
        return False
    years = pd.Series(panel["analysis_date"]).map(lambda value: value.year)
    return all(
        int((first & (years == year)).sum()) >= 12
        and int((second & (years == year)).sum()) >= 12
        for year in (2025, 2026)
    )


def _correlation_coverage(panel: pd.DataFrame, available: pd.Series) -> bool:
    if int(available.sum()) < 30:
        return False
    years = pd.Series(panel["analysis_date"]).map(lambda value: value.year)
    return all(int((available & (years == year)).sum()) >= 12 for year in (2025, 2026))


def _moving_block_indices(
    length: int, rng: np.random.Generator, *, block_size: int
) -> np.ndarray:
    if length <= 0:
        return np.array([], dtype=int)
    indices: list[int] = []
    maximum_start = max(0, length - block_size)
    while len(indices) < length:
        start = int(rng.integers(0, maximum_start + 1))
        indices.extend(range(start, min(start + block_size, length)))
    return np.asarray(indices[:length], dtype=int)


def _independent_block_values(
    values: pd.Series, rng: np.random.Generator, *, block_size: int
) -> np.ndarray:
    indices = _moving_block_indices(len(values), rng, block_size=block_size)
    return values.iloc[indices].to_numpy()


def _randomization_p_value(
    observed: float, null_values: Sequence[float], *, tail: str
) -> float:
    if not np.isfinite(observed) or not null_values:
        return 1.0
    null = np.asarray(null_values, dtype=float)
    if tail == "positive":
        exceed = int((null >= observed).sum())
    else:
        exceed = int((np.abs(null) >= abs(observed)).sum())
    return float((exceed + 1) / (len(null) + 1))


def _holm_adjust(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(values, key=values.get)
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, key in enumerate(ordered):
        candidate = min(1.0, (total - rank) * float(values[key]))
        running = max(running, candidate)
        adjusted[key] = running
    return adjusted


def _numeric(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _all_finite_positive(values: pd.Series) -> bool:
    numeric = _numeric(values)
    return bool(len(numeric) > 0 and (np.isfinite(numeric) & (numeric > 0.0)).all())


def _mean_or_nan(values: pd.Series) -> float:
    numeric = _numeric(values).dropna()
    return float(numeric.mean()) if not numeric.empty else np.nan


def _median_or_nan(values: pd.Series) -> float:
    numeric = _numeric(values).dropna()
    return float(numeric.median()) if not numeric.empty else np.nan


def _positive_share(values: pd.Series) -> float:
    numeric = _numeric(values).dropna()
    return float((numeric > 0.0).mean()) if not numeric.empty else np.nan


def _std_or_nan(values: pd.Series, *, ddof: int) -> float:
    numeric = _numeric(values).dropna()
    return float(numeric.std(ddof=ddof)) if len(numeric) > ddof else np.nan


def _require_columns(frame: pd.DataFrame, required: set[str]) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"frame lacks required fields: {', '.join(missing)}")


def _as_date(value: object) -> date:
    return pd.Timestamp(value).date()


__all__ = [
    "MARKET_VALIDATION_VERSION",
    "assign_market_hypotheses",
    "build_market_formation_panel",
    "evaluate_market_hypotheses",
    "fit_market_thresholds",
]
