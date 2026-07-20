# V3 Operable Target Objective Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not dispatch subagents; the user explicitly requested non-essential subagents not be used.

**Goal:** Implement the frozen `v3-operable-target-full-session-01` contract as a deterministic, reproducible evaluator and reproduce its semantic validation without changing any selector.

**Architecture:** A pure objective module owns the frozen contract identity, canonical hash, path-state classification and continuous metrics. A separate read-only validation runner reconstructs market-session-aligned paths from local warehouse facts and writes only immutable validation artifacts to the dedicated USB experiment directory. No formation-date selection code imports future outcomes.

**Tech Stack:** Python 3.12, pandas, NumPy, Pydantic 2, PyArrow, pytest, YAML.

## Global Constraints

- Authoritative contract: `docs/superpowers/specs/2026-07-20-v3-operable-target-observation-objective-contract.md`.
- Contract version is exactly `v3-operable-target-full-session-01`.
- Action day is session 1; the final horizon is exactly 30 market sessions; the gross target return is exactly 20%.
- Primary success requires at least one known tradable session whose adjusted low is at least `action_price * 1.20`.
- A quoted target session with zero amount, a one-price limit-down, or unresolved adjustment/limit identity cannot become a success witness.
- Missing minute data never blocks the primary daily-bar result.
- The evaluator may classify future outcomes but must never form, qualify, rank or select stocks.
- Existing V01/V02 formations, entries, snapshots and reports remain immutable.
- Runtime artifacts may only be written below `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-20-v3-operable-target-validation`.
- Do not write Supabase, publish, activate launchd jobs, send orders, or add holdings, selling, position-sizing or lifecycle behavior.

---

### Task 1: Freeze the executable objective identity

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_operable_target.py`
- Create: `tests/test_v3_operable_target.py`

**Interfaces:**
- Produces: `ObservationObjectiveContract`, `OBJECTIVE_CONTRACT`, `objective_contract_manifest() -> dict[str, Any]`, and `objective_contract_hash() -> str`.
- Consumes: no warehouse or runtime state.

- [ ] **Step 1: Write the failing contract identity tests**

```python
def test_contract_identity_is_frozen_and_canonical():
    assert OBJECTIVE_CONTRACT.version == "v3-operable-target-full-session-01"
    assert OBJECTIVE_CONTRACT.horizon_sessions == 30
    assert OBJECTIVE_CONTRACT.target_return == pytest.approx(0.20)
    assert OBJECTIVE_CONTRACT.entry_day_counts_as_session_one is True
    assert OBJECTIVE_CONTRACT.primary_success_field == "full_session_target_day"
    assert len(objective_contract_hash()) == 64
    assert objective_contract_hash() == objective_contract_hash()


def test_contract_rejects_unapproved_parameters():
    with pytest.raises(ValidationError):
        ObservationObjectiveContract(
            version="changed",
            horizon_sessions=20,
            target_return=0.15,
            entry_day_counts_as_session_one=True,
            primary_success_field="close_confirmed",
        )
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `pytest tests/test_v3_operable_target.py -q`

Expected: collection fails because `stock_analyzer.evaluation.v3_operable_target` does not exist.

- [ ] **Step 3: Implement the frozen model and canonical hash**

```python
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ObservationObjectiveContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["v3-operable-target-full-session-01"]
    horizon_sessions: Literal[30]
    target_return: Literal[0.2]
    entry_day_counts_as_session_one: Literal[True]
    primary_success_field: Literal["full_session_target_day"]


OBJECTIVE_CONTRACT = ObservationObjectiveContract(
    version="v3-operable-target-full-session-01",
    horizon_sessions=30,
    target_return=0.2,
    entry_day_counts_as_session_one=True,
    primary_success_field="full_session_target_day",
)


def objective_contract_manifest() -> dict[str, Any]:
    return OBJECTIVE_CONTRACT.model_dump(mode="json")


def objective_contract_hash() -> str:
    encoded = json.dumps(
        objective_contract_manifest(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

- [ ] **Step 4: Run the contract tests**

Run: `pytest tests/test_v3_operable_target.py -q`

Expected: the two contract tests pass.

- [ ] **Step 5: Commit the objective identity**

```bash
git add src/stock_analyzer/evaluation/v3_operable_target.py tests/test_v3_operable_target.py
git commit -m "feat: freeze V3 operable target contract"
```

### Task 2: Implement the pure full-session path evaluator

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_operable_target.py`
- Modify: `tests/test_v3_operable_target.py`

**Interfaces:**
- Consumes: one market-session-aligned frame with `trade_date`, raw OHLC, `amount`, `adj_factor`, `down_limit`, and partition-availability flags; one entry mapping with `entry_date`, `action_price`, and `executable_entry`.
- Produces: `evaluate_operable_target_path(prices: pd.DataFrame, entry: Mapping[str, Any], *, observed_horizon: int) -> dict[str, Any]`.

- [ ] **Step 1: Add failing tests for the outcome hierarchy**

```python
def test_intraday_touch_is_not_operable_success():
    path = _path(highs=[12.1], lows=[11.8], closes=[11.9], amounts=[100.0])
    result = evaluate_operable_target_path(path, _entry(), observed_horizon=30)
    assert result["path_state"] == "intraday_touch_only"
    assert result["operable_target_path"] is False


def test_close_confirmation_is_not_full_session_success():
    path = _path(highs=[12.3], lows=[11.9], closes=[12.1], amounts=[100.0])
    result = evaluate_operable_target_path(path, _entry(), observed_horizon=30)
    assert result["path_state"] == "close_confirmed_not_operable"
    assert result["operable_target_path"] is False


def test_nonconsecutive_staircase_with_one_full_target_day_succeeds():
    path = _path(
        highs=[10.8, 11.7, 11.2, 12.6],
        lows=[9.9, 10.8, 10.7, 12.01],
        closes=[10.6, 11.5, 11.0, 12.4],
        amounts=[100.0, 100.0, 100.0, 100.0],
    )
    result = evaluate_operable_target_path(path, _entry(), observed_horizon=30)
    assert result["path_state"] == "operable_target_path"
    assert result["operable_target_path"] is True
    assert result["full_session_target_day_count"] == 1


def test_day_30_counts_but_day_31_does_not():
    day_30 = _thirty_day_path(full_target_index=29)
    assert evaluate_operable_target_path(day_30, _entry(), observed_horizon=30)[
        "operable_target_path"
    ] is True
    day_31 = _thirty_day_path(full_target_index=None)
    assert evaluate_operable_target_path(day_31, _entry(), observed_horizon=30)[
        "operable_target_path"
    ] is False
```

- [ ] **Step 2: Add failing tests for tradability and unknown states**

```python
def test_zero_amount_and_one_price_limit_down_are_not_success_witnesses():
    zero_amount = _path(highs=[12.2], lows=[12.1], closes=[12.2], amounts=[0.0])
    zero_result = evaluate_operable_target_path(zero_amount, _entry(), observed_horizon=30)
    assert zero_result["operable_target_path"] is False

    limit_down = _path(
        opens=[12.1], highs=[12.1], lows=[12.1], closes=[12.1],
        amounts=[100.0], down_limits=[12.1],
    )
    limit_result = evaluate_operable_target_path(limit_down, _entry(), observed_horizon=30)
    assert limit_result["operable_target_path"] is False


def test_missing_decisive_factor_or_limit_is_unresolved_without_other_witness():
    missing_factor = _path(
        highs=[12.2], lows=[12.1], closes=[12.2], amounts=[100.0], adj_factors=[None]
    )
    result = evaluate_operable_target_path(missing_factor, _entry(), observed_horizon=30)
    assert result["path_state"] == "operability_unresolved"
    assert result["operable_target_path"] is None


def test_immature_window_never_emits_final_success_or_failure():
    result = evaluate_operable_target_path(
        _path(highs=[13.0], lows=[12.5], closes=[12.8], amounts=[100.0]),
        _entry(),
        observed_horizon=5,
    )
    assert result["objective_mature"] is False
    assert result["operable_target_path"] is None
    assert result["provisional_full_session_target_day_count"] == 1
```

- [ ] **Step 3: Run the focused tests and verify failures**

Run: `pytest tests/test_v3_operable_target.py -q`

Expected: failures identify the missing evaluator and helper behavior.

- [ ] **Step 4: Implement normalization, witness logic and state precedence**

```python
def evaluate_operable_target_path(
    prices: pd.DataFrame,
    entry: Mapping[str, Any],
    *,
    observed_horizon: int,
) -> dict[str, Any]:
    window = _normalize_market_session_path(prices).iloc[:observed_horizon].copy()
    action_price = float(entry["action_price"])
    target_price = action_price * (1.0 + OBJECTIVE_CONTRACT.target_return)
    objective_mature = observed_horizon >= OBJECTIVE_CONTRACT.horizon_sessions
    window = window.iloc[: OBJECTIVE_CONTRACT.horizon_sessions]
    window["adj_open"] = window["open"] * window["adj_factor"]
    window["adj_high"] = window["high"] * window["adj_factor"]
    window["adj_low"] = window["low"] * window["adj_factor"]
    window["adj_close"] = window["close"] * window["adj_factor"]
    quoted = window[["open", "high", "low", "close"]].notna().all(axis=1)
    one_price_limit_down = (
        quoted
        & window["down_limit"].notna()
        & _series_close(window["open"], window["down_limit"])
        & _series_close(window["high"], window["down_limit"])
        & _series_close(window["low"], window["down_limit"])
        & _series_close(window["close"], window["down_limit"])
    )
    full_target_candidate = window["adj_low"].ge(target_price)
    known_witness = (
        full_target_candidate
        & quoted
        & window["amount"].gt(0)
        & ~one_price_limit_down
        & window["adj_factor"].notna()
        & window["stock_limit_partition_available"]
    )
    unresolved_candidate = (
        window["equity_partition_available"].eq(False)
        | window["adj_factor_partition_available"].eq(False)
        | (
            full_target_candidate.fillna(False)
            & window["stock_limit_partition_available"].eq(False)
        )
    )
    witness_count = int(known_witness.sum())
    provisional_count = witness_count
    if not objective_mature:
        final_success = None
        state = "immature"
    elif witness_count:
        final_success = True
        state = "operable_target_path"
    elif bool(unresolved_candidate.any()):
        final_success = None
        state = "operability_unresolved"
    elif bool(window["adj_close"].ge(target_price).any()):
        final_success = False
        state = "close_confirmed_not_operable"
    elif bool(window["adj_high"].ge(target_price).any()):
        final_success = False
        state = "intraday_touch_only"
    else:
        final_success = False
        state = "not_reached"
    return {
        "objective_version": OBJECTIVE_CONTRACT.version,
        "objective_contract_hash": objective_contract_hash(),
        "objective_mature": objective_mature,
        "path_state": state,
        "operable_target_path": final_success,
        "provisional_full_session_target_day_count": provisional_count,
        "full_session_target_day_count": witness_count if objective_mature else None,
        **_path_metrics(window, action_price, target_price, known_witness),
    }
```

Add these helpers in the same module; the returned field names are the frozen section 7 names and missing facts remain `None`:

```python
_PATH_COLUMNS = {
    "trade_date", "open", "high", "low", "close", "amount", "adj_factor",
    "down_limit", "equity_partition_available",
    "adj_factor_partition_available", "stock_limit_partition_available",
}


def _normalize_market_session_path(prices: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(_PATH_COLUMNS - set(prices.columns))
    if missing:
        raise ValueError(f"market session path lacks fields: {', '.join(missing)}")
    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame["trade_date"].duplicated().any():
        raise ValueError("market session path contains duplicate dates")
    frame = frame.sort_values("trade_date").reset_index(drop=True)
    for field in ("open", "high", "low", "close", "amount", "adj_factor", "down_limit"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    for field in (
        "equity_partition_available",
        "adj_factor_partition_available",
        "stock_limit_partition_available",
    ):
        frame[field] = frame[field].fillna(False).astype(bool)
    return frame


def _series_close(left: pd.Series, right: pd.Series) -> pd.Series:
    return pd.Series(
        np.isclose(
            pd.to_numeric(left, errors="coerce"),
            pd.to_numeric(right, errors="coerce"),
            rtol=1e-6,
            atol=1e-8,
            equal_nan=False,
        ),
        index=left.index,
    )


def _first_date(window: pd.DataFrame, mask: pd.Series) -> str | None:
    positions = np.flatnonzero(mask.fillna(False).to_numpy())
    if not len(positions):
        return None
    return window.iloc[int(positions[0])]["trade_date"].date().isoformat()


def _path_metrics(
    window: pd.DataFrame,
    action_price: float,
    target_price: float,
    full_session_mask: pd.Series,
) -> dict[str, Any]:
    touch = window["adj_high"].ge(target_price)
    close_target = window["adj_close"].ge(target_price)
    next_open_opportunities = sum(
        bool(
            close_target.iloc[index]
            and window["adj_open"].iloc[index + 1] >= target_price
            and window["amount"].iloc[index + 1] > 0
        )
        for index in range(max(0, len(window) - 1))
        if pd.notna(window["adj_open"].iloc[index + 1])
        and pd.notna(window["amount"].iloc[index + 1])
    )
    close_returns = window["adj_close"].dropna().astype(float) / action_price - 1.0
    high_returns = window["adj_high"].dropna().astype(float) / action_price - 1.0
    low_returns = window["adj_low"].dropna().astype(float) / action_price - 1.0
    close_path = pd.Series([0.0, *close_returns.tolist()], dtype=float)
    running_peak = (1.0 + close_path).cummax()
    drawdowns = (1.0 + close_path) / running_peak - 1.0
    first_witness_positions = np.flatnonzero(full_session_mask.to_numpy())
    first_witness = int(first_witness_positions[0]) if len(first_witness_positions) else None
    pre_target = low_returns.iloc[:first_witness] if first_witness is not None else low_returns
    peak_return = float(high_returns.max()) if not high_returns.empty else None
    post_target_giveback = None
    if first_witness is not None and not high_returns.empty and not close_returns.empty:
        post_high = float(window.iloc[first_witness:]["adj_high"].max() / action_price - 1.0)
        post_close = float(window.iloc[first_witness:]["adj_close"].dropna().iloc[-1] / action_price - 1.0)
        post_target_giveback = post_close - post_high
    return {
        "first_touch_date": _first_date(window, touch),
        "first_close_target_date": _first_date(window, close_target),
        "first_full_session_target_date": _first_date(window, full_session_mask),
        "close_target_day_count": int(close_target.sum()),
        "observable_next_open_opportunity_count": int(next_open_opportunities),
        "peak_return_30": peak_return,
        "terminal_return_30": (
            float(close_returns.iloc[-1]) if not close_returns.empty else None
        ),
        "max_drawdown_30": (
            float(drawdowns.min()) if not drawdowns.empty else None
        ),
        "pre_target_max_adverse_return": (
            float(min(0.0, pre_target.min())) if not pre_target.empty else None
        ),
        "post_target_max_giveback": post_target_giveback,
        "target_region_close_occupation_days": int(close_target.sum()),
    }
```

- [ ] **Step 5: Run the evaluator tests**

Run: `pytest tests/test_v3_operable_target.py -q`

Expected: all objective identity, outcome, tradability, boundary and maturity tests pass.

- [ ] **Step 6: Commit the pure evaluator**

```bash
git add src/stock_analyzer/evaluation/v3_operable_target.py tests/test_v3_operable_target.py
git commit -m "feat: evaluate full-session target paths"
```

### Task 3: Verify the contract implementation without touching old runtime artifacts

**Files:**
- Modify only if verification exposes a contract mismatch: files from Tasks 1–3.
- Runtime output: none; the already documented 198-path diagnostic is not rerun by this implementation plan.

**Interfaces:**
- Consumes: completed Tasks 1–3.
- Produces: passing focused and regression tests; the pure module is ready to be consumed by the later selection-observation implementation.

- [ ] **Step 1: Run the complete focused test suite**

Run: `pytest tests/test_v3_operable_target.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run the affected regression suite**

Run: `pytest tests/test_v3_target_retention_diagnostic.py tests/test_v3_next_day_entry_validation.py tests/test_v3_forward_service.py -q`

Expected: all pre-existing V3 observation tests pass; no V01/V02 schema or artifact changes occur.

- [ ] **Step 3: Audit forbidden writes and repository state**

Run: `git status --short`

Expected: only the planned source, tests, config and documentation changes are present; no `supabase/`, `ops/launchd/`, `local_warehouse/`, `local_archive/`, `reports/`, `logs/` or `dist/` paths appear.

- [ ] **Step 4: Commit any verification-only corrections**

```bash
git add src/stock_analyzer/evaluation/v3_operable_target.py tests/test_v3_operable_target.py
git commit -m "test: verify V3 operable target semantics"
```
