"""Deterministic validation for predeclared, context-rich price scenarios.

The scenarios are research interpretations, not production scores or trading
rules.  Assignment uses formation-date price/volume fields only; future path
columns are read exclusively by the evaluation helpers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import numpy as np
import pandas as pd


QUANTILES = (0.20, 0.40, 0.60, 0.80)
QUANTILE_NAMES = ("q20", "q40", "q60", "q80")

SCENARIO_THRESHOLD_FIELDS = (
    "return_5d",
    "return_20d",
    "relative_market_5d",
    "relative_market_20d",
    "up_days_5d",
    "mean_close_position_5d",
    "upper_shadow_frequency_5d",
    "fade_frequency_5d",
    "volume_amplification_days_5d",
    "volume_price_efficiency_5d",
    "limit_up_return_contribution_5d",
    "amount_ratio_last_20d",
    "breakout_vs_prior60",
    "ema_distance_20d",
    "macd_histogram_ratio_change_5d",
    "efficiency_ratio_20d",
    "adx_14d",
    "dmi_directional_spread_14d",
    "rsi_14d",
    "stochastic_k_9_3",
    "bollinger_percent_b_20_2",
    "bollinger_bandwidth_change_5d",
    "signed_amount_balance_20d",
    "price_amount_efficiency_20d",
)

ABSOLUTE_THRESHOLD_FIELDS = {
    "abs_return_20d": "return_20d",
    "abs_relative_market_20d": "relative_market_20d",
    "abs_dmi_directional_spread_14d": "dmi_directional_spread_14d",
    "abs_volume_price_efficiency_5d": "volume_price_efficiency_5d",
}

POSITIVE_ONLY_THRESHOLD_FIELDS = {
    "positive_limit_up_return_contribution_5d": "limit_up_return_contribution_5d",
}

SCENARIO_SPECS: dict[str, dict[str, str]] = {
    "trend_continuation": {
        "label_cn": "既有趋势延续",
        "family": "趋势延续",
        "expected": "positive_hit",
        "primary_metric": "hit_rate",
    },
    "initial_activation": {
        "label_cn": "初步激活",
        "family": "趋势延续",
        "expected": "positive_hit",
        "primary_metric": "hit_rate",
    },
    "healthy_pullback": {
        "label_cn": "上升趋势内健康回撤",
        "family": "回撤与反转",
        "expected": "positive_hit",
        "primary_metric": "hit_rate",
    },
    "range_cross_noise": {
        "label_cn": "震荡噪声中的交叉",
        "family": "区间与噪声",
        "expected": "negative_hit",
        "primary_metric": "hit_rate",
    },
    "confirmed_breakout": {
        "label_cn": "有效突破",
        "family": "突破",
        "expected": "positive_hit",
        "primary_metric": "hit_rate",
    },
    "failed_breakout": {
        "label_cn": "失败突破",
        "family": "突破",
        "expected": "negative_d20",
        "primary_metric": "d20",
    },
    "oversold_strong_downtrend": {
        "label_cn": "强下跌中的超卖",
        "family": "回撤与反转",
        "expected": "negative_hit",
        "primary_metric": "hit_rate",
    },
    "reversal_attempt": {
        "label_cn": "真实反转尝试",
        "family": "回撤与反转",
        "expected": "positive_hit",
        "primary_metric": "hit_rate",
    },
    "trend_exhaustion": {
        "label_cn": "趋势衰竭",
        "family": "衰竭与冲击",
        "expected": "negative_d20",
        "primary_metric": "d20",
    },
    "single_day_impulse": {
        "label_cn": "单日脉冲或透支",
        "family": "衰竭与冲击",
        "expected": "negative_d20",
        "primary_metric": "d20",
    },
    "price_volume_divergence": {
        "label_cn": "量价背离",
        "family": "背离",
        "expected": "negative_d20",
        "primary_metric": "d20",
    },
}


def fit_scenario_thresholds(
    frame: pd.DataFrame,
    *,
    development_end: date,
    fields: Sequence[str] = SCENARIO_THRESHOLD_FIELDS,
) -> dict[str, dict[str, float]]:
    """Fit fixed quantile group boundaries on development rows only."""

    if "analysis_date" not in frame.columns:
        raise ValueError("analysis_date is required")
    missing = sorted(set(fields) - set(frame.columns))
    if missing:
        raise ValueError(f"threshold frame lacks: {', '.join(missing)}")
    dates = pd.to_datetime(frame["analysis_date"], errors="raise").dt.date
    development = dates <= development_end
    if not development.any():
        raise ValueError("development period is empty")
    thresholds: dict[str, dict[str, float]] = {}
    for field in fields:
        values = pd.to_numeric(frame.loc[development, field], errors="coerce")
        values = values[np.isfinite(values)]
        if values.empty:
            raise ValueError(f"development field has no finite values: {field}")
        thresholds[field] = {
            name: float(values.quantile(level))
            for name, level in zip(QUANTILE_NAMES, QUANTILES, strict=True)
        }
    for derived, source in POSITIVE_ONLY_THRESHOLD_FIELDS.items():
        if source not in fields:
            continue
        values = pd.to_numeric(frame.loc[development, source], errors="coerce")
        values = values[np.isfinite(values) & (values > 0.0)]
        if values.empty:
            raise ValueError(
                f"development field has no finite positive values: {source}"
            )
        thresholds[derived] = {
            name: float(values.quantile(level))
            for name, level in zip(QUANTILE_NAMES, QUANTILES, strict=True)
        }
    if tuple(fields) == SCENARIO_THRESHOLD_FIELDS:
        for derived, source in ABSOLUTE_THRESHOLD_FIELDS.items():
            values = pd.to_numeric(frame.loc[development, source], errors="coerce").abs()
            values = values[np.isfinite(values)]
            thresholds[derived] = {
                name: float(values.quantile(level))
                for name, level in zip(QUANTILE_NAMES, QUANTILES, strict=True)
            }
    return thresholds


def assign_price_scenarios(
    frame: pd.DataFrame,
    thresholds: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, pd.Series]]:
    """Assign predeclared case/control masks without reading outcome columns."""

    _validate_assignment_inputs(frame, thresholds)
    n = frame.index
    numeric = {
        field: pd.to_numeric(frame[field], errors="coerce")
        for field in SCENARIO_THRESHOLD_FIELDS
    }
    breakout250 = frame["breakout_prior_250d_high"].fillna(False).astype(bool)
    macd_up = frame["macd_bullish_cross_last_5d"].fillna(False).astype(bool)
    macd_down = frame["macd_bearish_cross_last_5d"].fillna(False).astype(bool)
    kd_up = frame["stochastic_bullish_cross_last_5d"].fillna(False).astype(bool)

    def q(field: str, name: str) -> float:
        return float(thresholds[field][name])

    def complete(*fields: str, booleans: Sequence[str] = ()) -> pd.Series:
        available = pd.Series(True, index=n)
        for field in fields:
            available &= numeric[field].notna()
        for field in booleans:
            available &= frame[field].notna()
        return available

    r5 = numeric["return_5d"]
    r20 = numeric["return_20d"]
    rel5 = numeric["relative_market_5d"]
    rel20 = numeric["relative_market_20d"]
    up_days = numeric["up_days_5d"]
    close_pos = numeric["mean_close_position_5d"]
    upper_shadow = numeric["upper_shadow_frequency_5d"]
    fade = numeric["fade_frequency_5d"]
    volume_days = numeric["volume_amplification_days_5d"]
    volume_eff = numeric["volume_price_efficiency_5d"]
    limit_share = numeric["limit_up_return_contribution_5d"]
    amount_ratio = numeric["amount_ratio_last_20d"]
    breakout60 = numeric["breakout_vs_prior60"]
    ema = numeric["ema_distance_20d"]
    macd_change = numeric["macd_histogram_ratio_change_5d"]
    er = numeric["efficiency_ratio_20d"]
    adx = numeric["adx_14d"]
    dmi = numeric["dmi_directional_spread_14d"]
    rsi = numeric["rsi_14d"]
    stoch_k = numeric["stochastic_k_9_3"]
    boll_b = numeric["bollinger_percent_b_20_2"]
    boll_change = numeric["bollinger_bandwidth_change_5d"]
    signed_amount = numeric["signed_amount_balance_20d"]
    long_volume_eff = numeric["price_amount_efficiency_20d"]

    assignments: dict[str, dict[str, pd.Series]] = {}

    fields = (
        "return_20d",
        "relative_market_20d",
        "ema_distance_20d",
        "dmi_directional_spread_14d",
        "efficiency_ratio_20d",
        "up_days_5d",
        "mean_close_position_5d",
        "volume_price_efficiency_5d",
        "signed_amount_balance_20d",
        "price_amount_efficiency_20d",
        "limit_up_return_contribution_5d",
    )
    base = complete(*fields) & (r20 >= q("return_20d", "q60")) & (
        rel20 >= q("relative_market_20d", "q60")
    ) & (ema > 0.0) & (dmi > 0.0)
    assignments["trend_continuation"] = {
        "case": base
        & (er >= q("efficiency_ratio_20d", "q60"))
        & (up_days >= q("up_days_5d", "q60"))
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (volume_eff > 0.0)
        & (signed_amount > 0.0)
        & (long_volume_eff > 0.0)
        & (limit_share < q("positive_limit_up_return_contribution_5d", "q80")),
        "control": base
        & (
            (er <= q("efficiency_ratio_20d", "q40"))
            | (close_pos <= q("mean_close_position_5d", "q40"))
            | (volume_eff <= 0.0)
            | (signed_amount <= 0.0)
            | (long_volume_eff <= 0.0)
        ),
    }

    fields = (
        "return_20d",
        "return_5d",
        "relative_market_5d",
        "amount_ratio_last_20d",
        "macd_histogram_ratio_change_5d",
        "dmi_directional_spread_14d",
        "mean_close_position_5d",
        "volume_price_efficiency_5d",
        "limit_up_return_contribution_5d",
    )
    base = complete(*fields, booleans=("macd_bullish_cross_last_5d",)) & (
        r20 >= q("return_20d", "q40")
    ) & (r20 <= q("return_20d", "q60")) & (
        r5 >= q("return_5d", "q60")
    ) & (rel5 >= q("relative_market_5d", "q60")) & (
        amount_ratio >= q("amount_ratio_last_20d", "q60")
    )
    assignments["initial_activation"] = {
        "case": base
        & macd_up
        & (macd_change > 0.0)
        & (dmi > 0.0)
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (volume_eff > 0.0)
        & (limit_share < q("positive_limit_up_return_contribution_5d", "q80")),
        "control": base
        & (
            ~macd_up
            | (macd_change <= 0.0)
            | (dmi <= 0.0)
            | (close_pos <= q("mean_close_position_5d", "q40"))
            | (volume_eff <= 0.0)
        ),
    }

    fields = (
        "return_20d",
        "relative_market_20d",
        "return_5d",
        "ema_distance_20d",
        "dmi_directional_spread_14d",
        "efficiency_ratio_20d",
        "rsi_14d",
        "amount_ratio_last_20d",
        "mean_close_position_5d",
        "fade_frequency_5d",
        "signed_amount_balance_20d",
        "macd_histogram_ratio_change_5d",
    )
    base = complete(*fields) & (r20 >= q("return_20d", "q60")) & (
        rel20 >= q("relative_market_20d", "q60")
    ) & (r5 < 0.0) & (ema > 0.0) & (
        amount_ratio <= q("amount_ratio_last_20d", "q60")
    )
    assignments["healthy_pullback"] = {
        "case": base
        & (dmi > 0.0)
        & (er >= q("efficiency_ratio_20d", "q40"))
        & (rsi >= q("rsi_14d", "q20"))
        & (rsi <= q("rsi_14d", "q60"))
        & (close_pos >= q("mean_close_position_5d", "q40"))
        & (fade <= q("fade_frequency_5d", "q60"))
        & (signed_amount >= q("signed_amount_balance_20d", "q20")),
        "control": base
        & (
            (dmi <= 0.0)
            | (macd_change <= q("macd_histogram_ratio_change_5d", "q20"))
            | (close_pos <= q("mean_close_position_5d", "q40"))
            | (fade >= q("fade_frequency_5d", "q60"))
            | (signed_amount <= q("signed_amount_balance_20d", "q20"))
        ),
    }

    fields = (
        "return_20d",
        "relative_market_20d",
        "adx_14d",
        "efficiency_ratio_20d",
        "dmi_directional_spread_14d",
        "volume_price_efficiency_5d",
        "amount_ratio_last_20d",
        "mean_close_position_5d",
        "relative_market_5d",
    )
    base = complete(
        *fields,
        booleans=("macd_bullish_cross_last_5d", "stochastic_bullish_cross_last_5d"),
    ) & (macd_up | kd_up)
    assignments["range_cross_noise"] = {
        "case": base
        & (r20.abs() <= q("abs_return_20d", "q40"))
        & (rel20.abs() <= q("abs_relative_market_20d", "q40"))
        & (adx <= q("adx_14d", "q40"))
        & (er <= q("efficiency_ratio_20d", "q40"))
        & (dmi.abs() <= q("abs_dmi_directional_spread_14d", "q40"))
        & (volume_eff.abs() <= q("abs_volume_price_efficiency_5d", "q40"))
        & (amount_ratio <= q("amount_ratio_last_20d", "q60"))
        & (close_pos >= q("mean_close_position_5d", "q40"))
        & (close_pos <= q("mean_close_position_5d", "q60")),
        "control": base
        & (rel5 >= q("relative_market_5d", "q60"))
        & (adx >= q("adx_14d", "q60"))
        & (er >= q("efficiency_ratio_20d", "q60"))
        & (dmi > 0.0)
        & (volume_eff > 0.0)
        & (close_pos >= q("mean_close_position_5d", "q60")),
    }

    fields = (
        "breakout_vs_prior60",
        "relative_market_5d",
        "relative_market_20d",
        "efficiency_ratio_20d",
        "dmi_directional_spread_14d",
        "mean_close_position_5d",
        "volume_price_efficiency_5d",
        "signed_amount_balance_20d",
        "price_amount_efficiency_20d",
        "limit_up_return_contribution_5d",
    )
    base = complete(*fields, booleans=("breakout_prior_250d_high",)) & (
        (breakout60 >= 0.0) | breakout250
    )
    assignments["confirmed_breakout"] = {
        "case": base
        & (rel5 >= q("relative_market_5d", "q60"))
        & (rel20 >= q("relative_market_20d", "q60"))
        & (er >= q("efficiency_ratio_20d", "q60"))
        & (dmi > 0.0)
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (volume_eff > 0.0)
        & (signed_amount > 0.0)
        & (long_volume_eff > 0.0)
        & (limit_share < q("positive_limit_up_return_contribution_5d", "q80")),
        "control": base
        & (
            (rel5 <= q("relative_market_5d", "q40"))
            | (er <= q("efficiency_ratio_20d", "q40"))
            | (dmi <= 0.0)
            | (close_pos <= q("mean_close_position_5d", "q40"))
            | (volume_eff <= 0.0)
            | (signed_amount <= 0.0)
        ),
    }

    fields = (
        "breakout_vs_prior60",
        "bollinger_percent_b_20_2",
        "amount_ratio_last_20d",
        "volume_amplification_days_5d",
        "fade_frequency_5d",
        "upper_shadow_frequency_5d",
        "volume_price_efficiency_5d",
        "macd_histogram_ratio_change_5d",
        "dmi_directional_spread_14d",
        "relative_market_5d",
        "mean_close_position_5d",
    )
    base = complete(*fields) & ((breakout60 >= 0.0) | (boll_b >= 1.0)) & (
        (amount_ratio >= q("amount_ratio_last_20d", "q60"))
        | (volume_days >= q("volume_amplification_days_5d", "q60"))
    )
    assignments["failed_breakout"] = {
        "case": base
        & (fade >= q("fade_frequency_5d", "q60"))
        & (upper_shadow >= q("upper_shadow_frequency_5d", "q60"))
        & (volume_eff <= 0.0)
        & ((macd_change < 0.0) | (dmi < 0.0)),
        "control": base
        & (rel5 >= q("relative_market_5d", "q60"))
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (fade <= q("fade_frequency_5d", "q40"))
        & (volume_eff > 0.0)
        & (macd_change > 0.0)
        & (dmi > 0.0),
    }

    fields = (
        "rsi_14d",
        "return_20d",
        "relative_market_20d",
        "relative_market_5d",
        "ema_distance_20d",
        "adx_14d",
        "dmi_directional_spread_14d",
        "mean_close_position_5d",
        "signed_amount_balance_20d",
        "macd_histogram_ratio_change_5d",
        "volume_price_efficiency_5d",
    )
    base = complete(*fields, booleans=("macd_bullish_cross_last_5d",)) & (
        rsi <= q("rsi_14d", "q20")
    )
    assignments["oversold_strong_downtrend"] = {
        "case": base
        & (r20 <= q("return_20d", "q20"))
        & (rel20 <= q("relative_market_20d", "q20"))
        & (ema < 0.0)
        & (adx >= q("adx_14d", "q60"))
        & (dmi < 0.0)
        & (close_pos <= q("mean_close_position_5d", "q40"))
        & (signed_amount < 0.0),
        "control": base
        & (rel5 >= q("relative_market_5d", "q60"))
        & (macd_up | (macd_change >= q("macd_histogram_ratio_change_5d", "q60")))
        & (dmi > 0.0)
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (volume_eff > 0.0)
        & (signed_amount > 0.0),
    }

    fields = (
        "return_20d",
        "return_5d",
        "relative_market_5d",
        "macd_histogram_ratio_change_5d",
        "dmi_directional_spread_14d",
        "rsi_14d",
        "amount_ratio_last_20d",
        "mean_close_position_5d",
        "volume_price_efficiency_5d",
        "signed_amount_balance_20d",
        "limit_up_return_contribution_5d",
    )
    base = complete(*fields, booleans=("macd_bullish_cross_last_5d",)) & (
        r20 <= q("return_20d", "q40")
    ) & (r5 >= q("return_5d", "q60")) & (
        rel5 >= q("relative_market_5d", "q60")
    )
    assignments["reversal_attempt"] = {
        "case": base
        & (macd_up | (macd_change >= q("macd_histogram_ratio_change_5d", "q60")))
        & (dmi > 0.0)
        & (rsi >= q("rsi_14d", "q20"))
        & (rsi <= q("rsi_14d", "q60"))
        & (amount_ratio >= q("amount_ratio_last_20d", "q60"))
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (volume_eff > 0.0)
        & (signed_amount > 0.0)
        & (limit_share < q("positive_limit_up_return_contribution_5d", "q80")),
        "control": base
        & (
            (dmi <= 0.0)
            | (close_pos <= q("mean_close_position_5d", "q40"))
            | (volume_eff <= 0.0)
            | (signed_amount <= 0.0)
        ),
    }

    fields = (
        "return_20d",
        "relative_market_20d",
        "rsi_14d",
        "ema_distance_20d",
        "macd_histogram_ratio_change_5d",
        "fade_frequency_5d",
        "upper_shadow_frequency_5d",
        "volume_price_efficiency_5d",
        "signed_amount_balance_20d",
        "amount_ratio_last_20d",
        "dmi_directional_spread_14d",
        "mean_close_position_5d",
    )
    base = complete(*fields, booleans=("macd_bearish_cross_last_5d",)) & (
        r20 >= q("return_20d", "q80")
    ) & (rel20 >= q("relative_market_20d", "q60")) & (
        rsi >= q("rsi_14d", "q80")
    ) & (ema > 0.0) & (amount_ratio >= q("amount_ratio_last_20d", "q60"))
    assignments["trend_exhaustion"] = {
        "case": base
        & (macd_down | (macd_change <= q("macd_histogram_ratio_change_5d", "q20")))
        & (
            (fade >= q("fade_frequency_5d", "q60"))
            | (upper_shadow >= q("upper_shadow_frequency_5d", "q60"))
        )
        & ((volume_eff <= 0.0) | (signed_amount <= 0.0)),
        "control": base
        & (macd_change >= q("macd_histogram_ratio_change_5d", "q60"))
        & (dmi > 0.0)
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (fade <= q("fade_frequency_5d", "q40"))
        & (volume_eff > 0.0)
        & (signed_amount > 0.0),
    }

    fields = (
        "return_5d",
        "relative_market_5d",
        "amount_ratio_last_20d",
        "limit_up_return_contribution_5d",
        "up_days_5d",
        "efficiency_ratio_20d",
        "bollinger_bandwidth_change_5d",
        "mean_close_position_5d",
        "volume_price_efficiency_5d",
    )
    base = complete(*fields) & (r5 >= q("return_5d", "q80")) & (
        rel5 >= q("relative_market_5d", "q60")
    ) & (amount_ratio >= q("amount_ratio_last_20d", "q60"))
    assignments["single_day_impulse"] = {
        "case": base
        & (limit_share >= q("positive_limit_up_return_contribution_5d", "q80"))
        & (up_days <= q("up_days_5d", "q40"))
        & (er >= q("efficiency_ratio_20d", "q60"))
        & (boll_change >= q("bollinger_bandwidth_change_5d", "q60")),
        "control": base
        & (limit_share <= q("positive_limit_up_return_contribution_5d", "q40"))
        & (up_days >= q("up_days_5d", "q60"))
        & (er >= q("efficiency_ratio_20d", "q60"))
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (volume_eff > 0.0),
    }

    fields = (
        "return_5d",
        "amount_ratio_last_20d",
        "volume_amplification_days_5d",
        "volume_price_efficiency_5d",
        "price_amount_efficiency_20d",
        "fade_frequency_5d",
        "upper_shadow_frequency_5d",
        "mean_close_position_5d",
        "macd_histogram_ratio_change_5d",
        "dmi_directional_spread_14d",
        "relative_market_5d",
        "signed_amount_balance_20d",
    )
    base = complete(*fields) & (r5 >= q("return_5d", "q60")) & (
        (amount_ratio >= q("amount_ratio_last_20d", "q60"))
        | (volume_days >= q("volume_amplification_days_5d", "q60"))
    )
    assignments["price_volume_divergence"] = {
        "case": base
        & (volume_eff <= q("volume_price_efficiency_5d", "q20"))
        & (long_volume_eff <= 0.0)
        & (
            (fade >= q("fade_frequency_5d", "q60"))
            | (upper_shadow >= q("upper_shadow_frequency_5d", "q60"))
        )
        & (close_pos <= q("mean_close_position_5d", "q40"))
        & ((macd_change <= 0.0) | (dmi <= 0.0)),
        "control": base
        & (rel5 >= q("relative_market_5d", "q60"))
        & (volume_eff >= q("volume_price_efficiency_5d", "q60"))
        & (long_volume_eff > 0.0)
        & (signed_amount > 0.0)
        & (close_pos >= q("mean_close_position_5d", "q60"))
        & (fade <= q("fade_frequency_5d", "q40"))
        & (macd_change > 0.0)
        & (dmi > 0.0),
    }

    for groups in assignments.values():
        groups["case"] = groups["case"].fillna(False).astype(bool)
        groups["control"] = groups["control"].fillna(False).astype(bool)
        groups["control"] &= ~groups["case"]
    return assignments


def compare_scenario_groups(
    frame: pd.DataFrame,
    *,
    case_mask: pd.Series,
    control_mask: pd.Series,
    bootstrap_repetitions: int = 1_000,
    random_seed: int = 20260819,
) -> dict[str, object]:
    """Compare groups with formation dates as the unit of weighting."""

    required = {
        "analysis_date",
        "ts_code",
        "hit_20pct_d20",
        "mfe_20d",
        "mae_20d",
        "return_close_d20",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"scenario evaluation frame lacks: {', '.join(missing)}")
    if bootstrap_repetitions <= 0:
        raise ValueError("bootstrap_repetitions must be positive")
    dates = pd.to_datetime(frame["analysis_date"], errors="raise").dt.date
    working = frame.copy()
    working["analysis_date"] = dates
    case = working.loc[pd.Series(case_mask, index=frame.index).fillna(False)].copy()
    control = working.loc[pd.Series(control_mask, index=frame.index).fillna(False)].copy()
    metrics = {
        "hit_rate": "hit_20pct_d20",
        "mfe": "mfe_20d",
        "mae": "mae_20d",
        "d20": "return_close_d20",
    }
    result: dict[str, object] = {
        "case_row_count": int(len(case)),
        "control_row_count": int(len(control)),
        "case_stock_count": int(case["ts_code"].nunique()),
        "control_stock_count": int(control["ts_code"].nunique()),
        "case_date_count": int(case["analysis_date"].nunique()),
        "control_date_count": int(control["analysis_date"].nunique()),
        "case_first_date": min(case["analysis_date"]).isoformat() if len(case) else None,
        "case_last_date": max(case["analysis_date"]).isoformat() if len(case) else None,
        "control_first_date": (
            min(control["analysis_date"]).isoformat() if len(control) else None
        ),
        "control_last_date": (
            max(control["analysis_date"]).isoformat() if len(control) else None
        ),
    }
    for label, field in metrics.items():
        result[f"case_{label}"] = _group_level_summary(case[field], label)
        result[f"control_{label}"] = _group_level_summary(control[field], label)
    paired = _paired_daily_differences(case, control, metrics)
    result["common_date_count"] = int(len(paired))
    rng = np.random.default_rng(random_seed)
    for label in metrics:
        values = paired[label].to_numpy(dtype=float) if label in paired else np.array([])
        result[f"{label}_delta_date_equal"] = (
            float(np.mean(values)) if len(values) else np.nan
        )
        distribution = _date_block_bootstrap(
            values,
            repetitions=bootstrap_repetitions,
            rng=rng,
        )
        result[f"{label}_ci_low"] = (
            float(np.quantile(distribution, 0.025)) if len(distribution) else np.nan
        )
        result[f"{label}_ci_high"] = (
            float(np.quantile(distribution, 0.975)) if len(distribution) else np.nan
        )
        positive_p, negative_p = _block_sign_flip_p_values(
            values,
            repetitions=bootstrap_repetitions,
            rng=rng,
        )
        result[f"{label}_positive_p"] = positive_p
        result[f"{label}_negative_p"] = negative_p
    year_coverage: dict[str, dict[str, int]] = {}
    year_deltas: dict[str, dict[str, float]] = {}
    for year in (2025, 2026):
        case_year = case[case["analysis_date"].map(lambda value: value.year == year)]
        control_year = control[
            control["analysis_date"].map(lambda value: value.year == year)
        ]
        paired_year = _paired_daily_differences(case_year, control_year, metrics)
        label = str(year)
        year_coverage[label] = {
            "case_rows": int(len(case_year)),
            "control_rows": int(len(control_year)),
            "common_dates": int(len(paired_year)),
        }
        year_deltas[label] = {
            metric: (
                float(paired_year[metric].mean())
                if metric in paired_year and len(paired_year)
                else np.nan
            )
            for metric in metrics
        }
    result["year_coverage"] = year_coverage
    result["year_deltas"] = year_deltas
    return result


def evaluate_price_scenarios(
    frame: pd.DataFrame,
    thresholds: Mapping[str, Mapping[str, float]],
    *,
    bootstrap_repetitions: int = 1_000,
    random_seed: int = 20260819,
) -> dict[str, dict[str, object]]:
    """Evaluate all predeclared scenarios and apply multiplicity correction."""

    assignments = assign_price_scenarios(frame, thresholds)
    results: dict[str, dict[str, object]] = {}
    expected_raw: dict[str, float] = {}
    opposite_raw: dict[str, float] = {}
    for offset, (scenario, spec) in enumerate(SCENARIO_SPECS.items()):
        groups = assignments[scenario]
        comparison = compare_scenario_groups(
            frame,
            case_mask=groups["case"],
            control_mask=groups["control"],
            bootstrap_repetitions=bootstrap_repetitions,
            random_seed=random_seed + offset * 101,
        )
        metric = spec["primary_metric"]
        expected_positive = spec["expected"] == "positive_hit"
        expected_raw[scenario] = float(
            comparison[f"{metric}_{'positive' if expected_positive else 'negative'}_p"]
        )
        opposite_raw[scenario] = float(
            comparison[f"{metric}_{'negative' if expected_positive else 'positive'}_p"]
        )
        results[scenario] = {"spec": dict(spec), **comparison}
    expected_adjusted = holm_adjust(expected_raw)
    opposite_adjusted = holm_adjust(opposite_raw)
    for scenario, spec in SCENARIO_SPECS.items():
        result = results[scenario]
        metric = spec["primary_metric"]
        result["primary_delta"] = result[f"{metric}_delta_date_equal"]
        result["primary_ci_low"] = result[f"{metric}_ci_low"]
        result["primary_ci_high"] = result[f"{metric}_ci_high"]
        result["expected_raw_p"] = expected_raw[scenario]
        result["opposite_raw_p"] = opposite_raw[scenario]
        result["expected_holm_p"] = expected_adjusted[scenario]
        result["opposite_holm_p"] = opposite_adjusted[scenario]
        result["year_primary_deltas"] = {
            year: values[metric]
            for year, values in result["year_deltas"].items()
        }
        result["evidence_profile"] = describe_scenario_evidence(
            result,
            expected=spec["expected"],
        )
    return results


def describe_scenario_evidence(
    metrics: Mapping[str, object],
    *,
    expected: str,
) -> dict[str, object]:
    """Describe direction, uncertainty and coverage without an admission gate."""

    if expected not in {"positive_hit", "negative_hit", "negative_d20"}:
        raise ValueError(f"unsupported expectation: {expected}")
    delta = float(metrics["primary_delta"])
    ci_low = float(metrics["primary_ci_low"])
    ci_high = float(metrics["primary_ci_high"])
    year_values = metrics["year_primary_deltas"]
    if not isinstance(year_values, Mapping):
        raise ValueError("year_primary_deltas must be a mapping")
    expected_sign = 1.0 if expected == "positive_hit" else -1.0

    def direction(value: float) -> str:
        if not np.isfinite(value) or value == 0.0:
            return "flat_or_unavailable"
        return "expected" if np.sign(value) == expected_sign else "opposite"

    if not np.isfinite(ci_low) or not np.isfinite(ci_high):
        interval_relation = "unavailable"
    elif ci_low > 0.0:
        interval_relation = "above_zero"
    elif ci_high < 0.0:
        interval_relation = "below_zero"
    else:
        interval_relation = "crosses_zero"
    return {
        "effect_direction": direction(delta),
        "effect_size": delta,
        "interval_relation": interval_relation,
        "interval_low": ci_low,
        "interval_high": ci_high,
        "expected_holm_p": float(metrics["expected_holm_p"]),
        "opposite_holm_p": float(metrics["opposite_holm_p"]),
        "year_directions": {
            str(year): direction(float(value))
            for year, value in year_values.items()
        },
        "case_rows": int(metrics["case_row_count"]),
        "control_rows": int(metrics["control_row_count"]),
        "common_dates": int(metrics["common_date_count"]),
        "automatic_scene_decision": None,
    }


def holm_adjust(raw: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down family-wise multiplicity adjustment."""

    finite_or_one = {
        key: float(raw[key]) if np.isfinite(float(raw[key])) else 1.0
        for key in raw
    }
    ordered = sorted(finite_or_one, key=finite_or_one.get)
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for position, key in enumerate(ordered):
        running = max(running, min(1.0, (total - position) * finite_or_one[key]))
        adjusted[key] = running
    return adjusted


def _validate_assignment_inputs(
    frame: pd.DataFrame,
    thresholds: Mapping[str, Mapping[str, float]],
) -> None:
    boolean_fields = {
        "breakout_prior_250d_high",
        "macd_bullish_cross_last_5d",
        "macd_bearish_cross_last_5d",
        "stochastic_bullish_cross_last_5d",
    }
    required_fields = set(SCENARIO_THRESHOLD_FIELDS) | boolean_fields
    missing = sorted(required_fields - set(frame.columns))
    if missing:
        raise ValueError(f"scenario frame lacks: {', '.join(missing)}")
    required_thresholds = (
        set(SCENARIO_THRESHOLD_FIELDS)
        | set(ABSOLUTE_THRESHOLD_FIELDS)
        | set(POSITIVE_ONLY_THRESHOLD_FIELDS)
    )
    missing_thresholds = sorted(required_thresholds - set(thresholds))
    if missing_thresholds:
        raise ValueError(f"scenario thresholds lack: {', '.join(missing_thresholds)}")
    for field in required_thresholds:
        if set(thresholds[field]) != set(QUANTILE_NAMES):
            raise ValueError(f"scenario threshold quantiles are incomplete: {field}")


def _group_level_summary(series: pd.Series, label: str) -> float:
    numeric = pd.to_numeric(series, errors="coerce")
    numeric = numeric[np.isfinite(numeric)]
    if numeric.empty:
        return np.nan
    if label == "hit_rate":
        return float(numeric.mean())
    return float(numeric.median())


def _paired_daily_differences(
    case: pd.DataFrame,
    control: pd.DataFrame,
    metrics: Mapping[str, str],
) -> pd.DataFrame:
    if case.empty or control.empty:
        return pd.DataFrame(columns=list(metrics))
    case_daily = case.groupby("analysis_date", sort=True)[list(metrics.values())].mean()
    control_daily = control.groupby("analysis_date", sort=True)[list(metrics.values())].mean()
    common = case_daily.index.intersection(control_daily.index).sort_values()
    if common.empty:
        return pd.DataFrame(columns=list(metrics))
    output = pd.DataFrame(index=common)
    for label, field in metrics.items():
        output[label] = case_daily.loc[common, field] - control_daily.loc[common, field]
    return output


def _date_block_bootstrap(
    values: np.ndarray,
    *,
    repetitions: int,
    rng: np.random.Generator,
    block_size: int = 4,
) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return np.array([], dtype=float)
    blocks = [finite[start : start + block_size] for start in range(0, len(finite), block_size)]
    distribution = np.empty(repetitions, dtype=float)
    for repetition in range(repetitions):
        selected = rng.integers(0, len(blocks), size=len(blocks))
        sample = np.concatenate([blocks[index] for index in selected])[: len(finite)]
        distribution[repetition] = float(np.mean(sample))
    return distribution


def _block_sign_flip_p_values(
    values: np.ndarray,
    *,
    repetitions: int,
    rng: np.random.Generator,
    block_size: int = 4,
) -> tuple[float, float]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return np.nan, np.nan
    blocks = [finite[start : start + block_size] for start in range(0, len(finite), block_size)]
    observed = float(np.mean(finite))
    permuted = np.empty(repetitions, dtype=float)
    for repetition in range(repetitions):
        signs = rng.choice((-1.0, 1.0), size=len(blocks))
        sample = np.concatenate(
            [block * sign for block, sign in zip(blocks, signs, strict=True)]
        )
        permuted[repetition] = float(np.mean(sample))
    positive = float((1 + np.sum(permuted >= observed)) / (repetitions + 1))
    negative = float((1 + np.sum(permuted <= observed)) / (repetitions + 1))
    return positive, negative


__all__ = [
    "ABSOLUTE_THRESHOLD_FIELDS",
    "POSITIVE_ONLY_THRESHOLD_FIELDS",
    "SCENARIO_SPECS",
    "SCENARIO_THRESHOLD_FIELDS",
    "assign_price_scenarios",
    "compare_scenario_groups",
    "describe_scenario_evidence",
    "evaluate_price_scenarios",
    "fit_scenario_thresholds",
    "holm_adjust",
]
