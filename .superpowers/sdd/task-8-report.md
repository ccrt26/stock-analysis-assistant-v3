# Task 8 Report: Strategy V2 Daily Pipeline Orchestration

## Status

Implemented.

## Commit

- Implementation commit: `af8aed494cdffea327ad05c1ed3428c7788363e5`
- Commit message: `feat: orchestrate strategy v2 daily pipeline`
- Report note: this report is written after the implementation commit so it can include the real implementation hash. A commit cannot contain its own final immutable hash.

## Files Changed

- `src/stock_analyzer/pipeline.py`
- `src/stock_analyzer/cli.py`
- `src/stock_analyzer/reports/generator.py`
- `tests/test_pipeline_smoke.py`
- `tests/test_cli.py`
- `.superpowers/sdd/task-8-report.md`

## RED

- `.venv/bin/python -m pytest tests/test_pipeline_smoke.py::test_trading_day_pipeline_outputs_data_insufficient_report_when_live_data_missing tests/test_pipeline_smoke.py::test_strategy_v2_pipeline_persists_operational_status_without_full_market_supabase_write -v`
- Result: exit 1, 2 failed as expected.
- Expected failures: `run_daily_pipeline()` did not yet accept `allow_data_insufficient_output` or `strategy_v2`.
- `.venv/bin/python -m pytest tests/test_cli.py::test_run_daily_forwards_strategy_v2_and_data_insufficient_flags -v`
- Result: exit 1, 1 failed as expected.
- Expected failure: Typer exited with code 2 because the new CLI flags did not exist.

## GREEN

- `.venv/bin/python -m pytest tests/test_pipeline_smoke.py tests/test_cli.py -v`
- Result: exit 0, 48 passed in 0.78s.
- `.venv/bin/python -m pytest tests/test_strategy_v2_recommendation.py tests/test_focus_strategy_v2.py -v`
- Result: exit 0, 15 passed in 0.09s.
- Extra renderer check: `.venv/bin/python -m pytest tests/test_report_generation.py -v`
- Result: exit 0, 6 passed in 0.10s.
- `git diff --check`
- Result: exit 0.

## Self-Review

- `DailyRunResult` now carries `OperationalDailyStatus`.
- `run_daily_pipeline` preserves the default legacy path and adds opt-in `strategy_v2`, `allow_data_insufficient_output`, `manual_entries`, and `manual_holdings` parameters.
- Strategy V2 mode calls `generate_strategy_v2_recommendations`, `update_focus_watchlist_v2`, and `build_evidence_package_from_strategy_snapshot`.
- Data-insufficient production input with the opt-in flag writes `report_mode: data_insufficient`, returns recommendation/focus states as `data_insufficient`, records blocking fields, and does not save positive recommendations.
- Complete production input still saves the full bundle to the local warehouse before selected decision windows are written to the repository.
- CLI `run-daily` exposes `--strategy-v2` and `--allow-data-insufficient-output`, both defaulting to false.
- No `.env.local` or secrets/tokens were read, printed, copied, or logged. No real Supabase, Tushare, Cloudflare, broker, or network APIs were called. No production writes were executed.

## Concerns

- The report file is intentionally written after the implementation commit to record the real commit hash.

## Review Fix: Live Provider Data-Insufficient Routing

## Commit

- Fix commit: recorded in the final task response because a commit cannot contain its own final immutable hash.
- Commit message: `fix: render data insufficient on live provider failure`

## RED

- `.venv/bin/python -m pytest tests/test_pipeline_smoke.py::test_trading_day_pipeline_outputs_data_insufficient_report_when_provider_load_raises tests/test_cli.py::test_run_daily_allow_data_insufficient_continues_when_provider_build_fails -v`
- Result: exit 1, 2 failed as expected.
- Expected failures: `run_daily_pipeline()` let `CurrentLiveDataUnavailable` escape from `market_data_provider.load(...)`, and CLI `run-daily` exited before forwarding opt-in data-insufficient behavior to the pipeline when provider construction failed.

## GREEN

- `.venv/bin/python -m pytest tests/test_pipeline_smoke.py::test_trading_day_pipeline_outputs_data_insufficient_report_when_provider_load_raises tests/test_cli.py::test_run_daily_allow_data_insufficient_continues_when_provider_build_fails -v`
- Result: exit 0, 2 passed in 0.58s.
- `.venv/bin/python -m pytest tests/test_pipeline_smoke.py tests/test_cli.py -v`
- Result: exit 0, 50 passed in 0.46s.

## Self-Review

- `run_daily_pipeline` now catches `CurrentLiveDataUnavailable` from `market_data_provider.load(trade_date)` and routes it through the same `allow_data_insufficient_output` helper used by other insufficient-data branches.
- Default behavior still fails when `allow_data_insufficient_output=False`.
- CLI `run-daily` now continues to `run_daily_pipeline` with `market_data_provider=None` when provider construction raises `CurrentLiveDataUnavailable` and `--allow-data-insufficient-output` is present; without the flag it still exits with the existing failure path.
- Tests use fakes and monkeypatches only. No `.env.local` or secrets/tokens were read, printed, copied, or logged. No real provider, network, Supabase, or production writes were called.

## Concerns

- None.
