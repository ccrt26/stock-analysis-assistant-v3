# Task 5 Report: Action and Position Policy

## Status

DONE

## Files Changed

- `src/stock_analyzer/analysis/action_policy.py`
- `tests/test_action_policy.py`
- `.superpowers/sdd/task-5-report.md`

## Commit Hash

- Implementation commit: `c06a1d6df6782cd6718b2679e40cf060143475f4`
- Commit message: `feat: add quantified action policy`
- Report note: this report is written after the implementation commit so it can
  record the real implementation hash.

## RED

- Command: `.venv/bin/python -m pytest tests/test_action_policy.py -v`
- Result: failed before implementation with
  `ModuleNotFoundError: No module named 'stock_analyzer.analysis.action_policy'`.
- This was the expected missing-module RED from the Task 5 brief.

## GREEN

- Command: `.venv/bin/python -m pytest tests/test_action_policy.py -v`
- Result: 10 passed.
- Command:
  `.venv/bin/python -m pytest tests/test_strategy_v2_contracts.py tests/test_action_policy.py -v`
- Result: 28 passed.

## Implementation Summary

- Added deterministic `ActionPolicyInput` with the brief inputs plus optional
  `hard_risk: bool = False`.
- Added `build_action_recommendation()` returning domain
  `ActionRecommendation` with non-empty reasoning, confirmations,
  invalidation conditions, risk text, and staging plans.
- Implemented hard-risk gates for hard risk, liquidity below `0.25`,
  risk-reward below `1.0`, and 20-day volatility above `0.45`.
- Implemented strong setup thresholds exactly at market support `>= 0.70`,
  thesis quality `>= 0.75`, risk-reward `>= 1.5`, volatility `<= 0.35`,
  and liquidity `>= 0.60`.
- Implemented small exploratory, conditional add, wait-for-confirmation,
  avoid-chasing, and high-position holding adjustment paths.
- Preserved the current `ManualHolding` fields and used exact
  `ActionDecision` enum members from `domain.models`.

## Self-Review

- Scope stayed within the assigned files only.
- No `.env.local`, secrets, tokens, production data, broker APIs, order APIs, or
  production writes were read or used.
- Existing high positions at or above `15.0%` cannot receive a higher target
  and always include `holding_adjustment`.
- Position ranges are non-negative and ordered through the
  `ActionRecommendation` model contract.
- Tests adapt the brief's stale holding sample to the current `ManualHolding`
  shape: `name`, `position_pct`, `cost_price`, `quantity`, `entry_date`,
  `thesis_id`, and `notes`.
- Policy output avoids broker/order language such as broker, order, 券商, 下单,
  订单, and 委托.

## Concerns

- None blocking. The report is intentionally separate from the implementation
  commit because a commit cannot contain its own final immutable hash.
