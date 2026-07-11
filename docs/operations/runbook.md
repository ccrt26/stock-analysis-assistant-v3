# Phase 1 Operations Runbook

> **Current availability:** The concrete formal production program, 82-session live backfill, precise event route, real 2026-07-10 Strategy V2 analysis, Supabase atomic activation/read-back, production report verification, launchd, Cloudflare publication, independent online smoke, and automatic publication are active. The real report remains blocked on the separate user-readability capability `REPORT-004`; technical publication success must not be reported as product readability success.

已完成 2026-07-10 真实只读主源回填与正式分析：生成 10 个每日推荐、10 个重点股状态、14 个推荐/重点股证据包和 84 个复盘任务；Supabase 迁移已应用并完成只读回查，窄账本、正式报告和本地指针已原子激活并通过强读回。正式事件能力 Gate 已通过。launchd 已加载；Cloudflare 已发布，独立在线 smoke 通过，自动发布已启用。当前未配置或调用 LLM 表达客户端，真实报告未通过用户可读性验收；从未连接经纪商或执行订单。

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

The launchd template is `ops/launchd/com.ccrt.stock-analysis-assistant.daily.plist.example`. The approved local copy is installed under `~/Library/LaunchAgents/`, uses silent runtime environment loading, and is loaded for the three slots above. Its canonical production checkout is the clean local `main` worktree resolved from Git at installation time; after loading the environment it pins `PROJECT_ROOT` to that installed checkout, so stale environment configuration cannot redirect the scheduler to a retired feature worktree. The virtual environment, logs, reports, warehouse, archive, and activated deployment artifact were migrated with source-content verification. Keep personal paths out of the versioned template and active operations documents.

## Production Run Command After Readiness Approval

After approval, change to the checked-out project root and derive `PROJECT_ROOT` from that directory:

```bash
export PROJECT_ROOT="$PWD"
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops run-daily-job --trade-date YYYY-MM-DD --scheduled-slot 18:30 --attempt 1 --prepare-deploy
```

Before installing the launchd example, replace every literal `__PROJECT_ROOT__` with the resolved absolute checkout path in the copied plist. Never edit the versioned example to a personal path.

For approved retries, keep the same `trade_date`, set `--scheduled-slot 19:00 --attempt 2` or `--scheduled-slot 19:30 --attempt 3`, and keep `--prepare-deploy`.

All three launchd slots remain installed. If an earlier slot for the same date already ended in `success_with_recommendations`, `success_no_recommendations`, or `skipped_non_trading_day`, a later slot returns that prior terminal status unchanged. It performs no cleanup, provider acquisition, analysis, report render, Supabase write, deployment, publication, or notification. Reinvoking the identical completed formal run likewise reuses the frozen `REPORT_GENERATED` receipt without increasing its revision.

Mac notification is disabled by default. Enable it only when desired with `--notify-mac` or `STOCK_ANALYZER_NOTIFY_MAC=1`; it should fire only when the final status is `failed_needs_human`.

### Strategy V2 daily run

Use fixture or dry-run for local validation:

```bash
stock-analyzer run-daily --trade-date YYYY-MM-DD --fixture-mode --strategy-v2
```

Production Strategy V2 writes require explicit approval before running without fixture mode. Do not print `.env.local`, service-role keys, Tushare tokens, Cloudflare tokens, report passwords, or session secrets. Do not perform unapproved production writes.

On trading days, a formal run produces analysis only after `READY_TO_SCREEN` and `READY_TO_ANALYZE`. If any required group is incomplete, the run stops as `blocked_needs_human`; it does not call Strategy V2 analysis or the LLM, write decision rows, render a `data_insufficient` page, prepare deploy files, or publish. The previous current and published report remains byte-for-byte unchanged.

## Formal Readiness Inspection

Blocked operational output is local-only. Read the latest redacted status with:

```bash
python -m json.tool logs/run-daily/latest-status.json
```

Set the run ID from that status or the command output, then locate its append-only receipt and immutable candidate set:

```bash
RUN_ID=july10-formal
RECEIPT_ROOT=local_warehouse/formal_evidence/run_receipts/$RUN_ID
REVISION=$(jq -r '.revision' "$RECEIPT_ROOT/latest.json")
RECEIPT_FILE="$RECEIPT_ROOT/$(printf '%06d' "$REVISION").json"
jq . "$RECEIPT_FILE"
CANDIDATE_ID=$(jq -r '.candidate_set_id' "$RECEIPT_FILE")
jq . "local_warehouse/formal_evidence/candidate_sets/$CANDIDATE_ID.json"
```

Both activation IDs must be non-null and identical, and the local active marker must name the same activation ID:

```bash
jq '{state,local_activation_id,ledger_activation_id}' "$RECEIPT_FILE"
jq . "reports/.activation/$RUN_ID.active.json"
```

For an approved read-only Supabase inspection, query `public.active_formal_run_receipt` for the same `run_id`; absence means the narrow ledger is not active and all formal consumers must ignore the run. Never infer activation from decision rows alone.

List durable backup reconciliation work without changing it:

```bash
find local_warehouse/formal_evidence/reconciliation -name '*.json' -type f -exec jq '{task_id,group_id,trade_date,status,backup_version_id,primary_version_id}' {} \;
```

A complete backup group can support analysis after the identical contract passes. Its use creates reconciliation work but no provider-value comparison and no source-difference warning. When the full primary route later passes, it becomes canonical for future replay; the frozen report and its original `input_set_id` remain unchanged.

Run the isolated July 10 acceptance without network or production writes:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_default_formal_production_entry.py -q
```

This test invokes the real `_default_run_daily()` and `build_production_formal_dependencies()` path. It replaces only Tushare, AKShare, and ledger transport boundaries with recorded/fake external runtimes; it does not patch the production factory or reuse `_sample_market`.

The default live capability-record location is `local_warehouse/formal_evidence/capabilities/formal-v2/latest.json`. A recorded evidence bundle is accepted only by recorded test mode; live mode rejects it before any provider call. After the offline gate passes and live reads are explicitly approved, create the live evidence and exact same-day immutable screening backfill with:

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops verify-formal-capabilities \
  --trade-date YYYY-MM-DD --confirm-live-read
```

The command validates all six formal groups for both provider families, records hashes and installed library versions without credentials, and writes only local capability/evidence files. It does not call analysis or an LLM, write Supabase, render/publish a report, activate launchd, or access a broker. Any incomplete route fails closed before those actions.

Passing this offline rehearsal does not itself authorize a real action. Live acquisition, Supabase mutation, Cloudflare deployment/publication, scheduler activation, broker access, and order execution remain separate scopes. The lower-level readiness regression remains available as `PYTHONPATH=src .venv/bin/python -m pytest tests/test_july10_formal_readiness_acceptance.py -q`.

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

The machine-readable status file is `logs/run-daily/latest-status.json`. The expected statuses include `success_with_recommendations`, `success_no_recommendations`, `skipped_non_trading_day`, `calendar_unknown`, `warning`, `failed_retryable`, `failed_needs_human`, and `blocked_needs_human`.

Use status and logs for operations decisions. Do not paste log output into chat, tickets, or commits until it has been checked for credential values.

## Incident Handling

- `calendar_unknown`: stop and fix the calendar source before any production run.
- `failed_retryable`: allow the scheduled retry only after cleanup-before-retry succeeds.
- `failed_needs_human`: stop retries, keep the previous report online, and investigate the redacted `fix_suggestion`.
- `blocked_needs_human`: stop before analysis, inspect the failed complete acquisition group and both route attempts, preserve the frozen candidate set if screening already completed, and keep the previous report online.
- Repeated failure through the 19:30 attempt requires human review before another run.

## Model Requirement

For this production-capability correction, the main agent owns implementation, tests, commits, and push. A subagent may be used only for an independent read-only investigation or final review when GPT-5.6 sol, high reasoning, and standard speed can be guaranteed; otherwise do not delegate.
