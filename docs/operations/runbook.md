# Phase 1 Operations Runbook

This runbook covers the Phase 1 local Mac production flow for stock-analysis-assistant-v3. Phase 1 can run the local daily job, classify failures, clean same-day partial outputs before approved retries, write machine-readable status, and prepare `dist/pages`. It does not publish Cloudflare Pages automatically.

## Approval Gates

- Do not enable launchd without explicit approval.
- Do not run a real production job without explicit approval.
- Do not run production same-day cleanup without explicit approval.
- Do not deploy Cloudflare Pages without explicit approval.
- Do not print, copy, commit, or log the local env file contents or credential values.

## Daily Schedule

The required local schedule is:

| Slot | Attempt | Purpose |
| --- | --- | --- |
| 18:30 | 1 | First production run after market data should be available. |
| 19:00 | 2 | First retry after classification and cleanup-before-retry. |
| 19:30 | 3 | Final retry after classification and cleanup-before-retry. |

The launchd template is `ops/launchd/com.ccrt.stock-analysis-assistant.daily.plist.example`. It is an example only and must remain unloaded until explicitly approved.

## Approved Run Command

After approval, run the daily job from `/Users/ccrt/股票分析助手`:

```bash
PROJECT_ROOT=/Users/ccrt/股票分析助手 PYTHONPATH=src .venv/bin/python -m stock_analyzer ops run-daily-job --trade-date YYYY-MM-DD --scheduled-slot 18:30 --attempt 1 --prepare-deploy
```

For approved retries, keep the same `trade_date`, set `--scheduled-slot 19:00 --attempt 2` or `--scheduled-slot 19:30 --attempt 3`, and keep `--prepare-deploy`.

Mac notification is disabled by default. Enable it only when desired with `--notify-mac` or `STOCK_ANALYZER_NOTIFY_MAC=1`; it should fire only when the final status is `failed_needs_human`.

### Strategy V2 daily run

Use fixture or dry-run for local validation:

```bash
stock-analyzer run-daily --trade-date YYYY-MM-DD --fixture-mode --strategy-v2
```

Production Strategy V2 writes require explicit approval before running without fixture mode. Do not print `.env.local`, service-role keys, Tushare tokens, Cloudflare tokens, report passwords, or session secrets. Do not perform unapproved production writes.

On trading days, the job must produce either generated recommendation and focus outputs or an explicit `data_insufficient` report with recovery attempts and missing fields.

## Non-Trading-Day Skip Rule

When the calendar gate returns a non-trading day, the job status must be `skipped_non_trading_day`. The job must not run analysis, must not clean same-day outputs, must not prepare a new deploy package, and must not overwrite reports. It should only write the status JSON and job log.

## Cleanup-Before-Retry Rule

The cleanup-before-retry rule is mandatory for retry attempts. A retryable failure must be classified first, then the system cleans only the current `trade_date` before attempt 2 or attempt 3. Cleanup failure stops the retry and requires human intervention.

Cleanup is limited to same-day partial outputs:

- Supabase rows for the current `trade_date` in the approved operations tables.
- `reports/daily/YYYY-MM-DD/`.
- The same-day local archive manifest and report copy.
- The same-day local warehouse partition replacement output. Treat replacement as scoped overwrite for the target `trade_date`, never as deletion of the whole warehouse.

Never delete historical dates, a whole Supabase table, `stock_master`, the whole `local_archive`, or the whole `local_warehouse`.

## Status and Logs

The machine-readable status file is `logs/run-daily/latest-status.json`. The expected statuses include `success_with_recommendations`, `success_no_recommendations`, `skipped_non_trading_day`, `calendar_unknown`, `warning`, `failed_retryable`, and `failed_needs_human`.

Use status and logs for operations decisions. Do not paste log output into chat, tickets, or commits until it has been checked for credential values.

## Incident Handling

- `calendar_unknown`: stop and fix the calendar source before any production run.
- `failed_retryable`: allow the scheduled retry only after cleanup-before-retry succeeds.
- `failed_needs_human`: stop retries, keep the previous report online, and investigate the redacted `fix_suggestion`.
- Repeated failure through the 19:30 attempt requires human review before another run.

## Model Requirement

Every Phase 1 implementer, reviewer, and subagent must use GPT-5.5 xhigh. Do not use mini models for production automation, cleanup, trading calendars, Supabase, Cloudflare, secrets, deployment, or final review.
