# Task 7 Report: Focus Watchlist V2, Entry Thesis, and Daily Tracking

## Status

DONE

## Files Changed

- `src/stock_analyzer/analysis/focus.py`
- `src/stock_analyzer/domain/models.py`
- `tests/test_focus_strategy_v2.py`
- `tests/test_focus_state_machine.py`
- `tests/test_strategy_v2_contracts.py`
- `.superpowers/sdd/task-7-report.md`

## Commit Hash

- `3d6b42f10e0013598e6d214e11baffe51db86b17`
- Commit message: `feat: add strategy v2 focus tracking`

## RED

- Command: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py -v`
- Result: expected collection failure before implementation because `update_focus_watchlist_v2` did not exist.
- Key error: `ImportError: cannot import name 'update_focus_watchlist_v2' from 'stock_analyzer.analysis.focus'`.

## GREEN

- Command: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py tests/test_focus_state_machine.py -v`
- Result: `10 passed`.

- Command: `.venv/bin/python -m pytest tests/test_strategy_v2_contracts.py -v`
- Result: `18 passed`.

- Command: `git diff --check`
- Result: exit 0, no whitespace errors.

## Implementation Notes

- Added `FocusUpdateResult`, `update_focus_watchlist_v2`, `build_focus_entry_thesis`, and `build_focus_daily_update`.
- Preserved the legacy `update_focus_watchlist()` behavior.
- System candidates are grouped by `ts_code` and require at least 3 supportive snapshots in the latest 5 observations.
- Supportive snapshots require complete data, expected upside of at least 10%, risk/reward of at least 1.5, and no hard-risk/no-participation decision.
- New system entries are capped at 5 and ranked by `internal_score`, then `risk_reward`, then evidence quality.
- Manual entries are outside the system cap and produce honest theses. When no Strategy V2 evidence exists, `validation_result` is `证据不足` and `risk_notes` includes `证据不足`.
- Added `FocusEntryThesis.validation_result` and `FocusEntryThesis.risk_notes` with compatible defaults.

## Self-Review

- Confirmed manual entries with missing evidence do not inherit positive system language or praise.
- Confirmed existing focus rows continue and receive daily updates with current invalidation conditions when a snapshot exists.
- Confirmed duplicate daily updates are avoided when an existing focus is also supplied as a manual entry.
- Confirmed empty manual entry codes are ignored defensively.
- No `.env.local`, secrets, tokens, production writes, or external services were read or used.

## Concerns

- None blocking.

## Review Fix: Focus Gates and Missing Snapshot Updates

### Status

DONE

### Files Changed

- `src/stock_analyzer/analysis/focus.py`
- `tests/test_focus_strategy_v2.py`
- `tests/test_focus_state_machine.py`
- `.superpowers/sdd/task-7-report.md`

### RED

- Command: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py tests/test_focus_state_machine.py -v`
- Result before implementation: `6 failed, 9 passed`.
- Covered failures: full 5-observation entry window, existing system focus cap accounting, low-liquidity/WAIT_FOR_CONFIRMATION rejection, no-support rejection, ranking order, and data-insufficient daily updates for existing focus rows without current snapshots.

### GREEN

- Command: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py tests/test_focus_state_machine.py -v`
- Result after implementation: `15 passed`.

### Implementation Notes

- System focus cap now counts existing non-manual active focus rows before admitting new system candidates; manual entries remain outside the cap.
- System entry now requires a complete latest 5-observation window, at least 3 supportive observations, an acceptable action decision, actual support evidence, liquidity support, and no blocking hard-risk/liquidity counter evidence.
- Ranking now uses `internal_score`, thesis quality, then liquidity quality.
- Existing focus rows without a current Strategy V2 snapshot now receive an explicit data-insufficient daily update with `CONFIRM_REMOVAL`, required confirmations, invalidation conditions, no positive support, and no praising thesis language.

### Concerns

- None blocking.

## Review Fix: Require Current Snapshot for Daily Update

### Status

DONE

### Files Changed

- `src/stock_analyzer/analysis/focus.py`
- `tests/test_focus_strategy_v2.py`
- `.superpowers/sdd/task-7-report.md`

### RED

- Command: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py::test_existing_focus_with_stale_history_without_today_snapshot_gets_data_insufficient_update -v`
- Result before implementation: `1 failed`.
- Covered failure: stale history through `2026-07-09` was incorrectly emitted as a positive daily update during the requested `2026-07-10` focus update.

### GREEN

- Command: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py::test_existing_focus_with_stale_history_without_today_snapshot_gets_data_insufficient_update -v`
- Result after implementation: `1 passed`.

- Command: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py tests/test_focus_state_machine.py -v`
- Result after implementation: `16 passed`.

### Implementation Notes

- Existing focus daily updates now resolve the usable Strategy V2 snapshot by matching `snapshot.trade_date` to the requested update `trade_date`.
- Stale history can still support five-observation qualification context, but a candidate's latest qualifying snapshot must be from the requested `trade_date` before a system focus daily update is emitted.
- When no current snapshot exists for an existing focus, the update path emits the explicit data-insufficient `CONFIRM_REMOVAL` update for the requested `trade_date`.

### Concerns

- None blocking.
