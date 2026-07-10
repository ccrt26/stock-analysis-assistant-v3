# Historical Phase Roadmap — Deprecated

> This file no longer tracks current work or readiness. Its non-duplicated boundaries and execution order are consolidated into [`production-capability-matrix.md`](production-capability-matrix.md). It remains temporarily as a compatibility target for historical plans and documentation tests and will be removed when those active references are cleaned up under capability `GOV-001`.

Phase 1 is only the local production operations foundation. Phase 2, Phase 3, and Phase 4 are mandatory follow-up phases, not optional polish.

## Model and Review Governance

Every implementer, reviewer, and subagent assigned to production operations, Cloudflare automation, Strategy V2, Product UI, or whole-branch review must use GPT-5.5 xhigh. Mini models are not allowed for production safety, financial strategy, credentials, migration, deployment, automation, cleanup-before-retry, trading calendars, Supabase, or Cloudflare work.

## Phase 2: Cloudflare Automation

Cloudflare automation is mandatory, not optional. Phase 2 implementation is in progress. Phase 2 must automate publish only after a successful local production run, run online smoke after deploy, avoid overwriting the last known good online report on failure, and keep Cloudflare credentials redacted with minimum required permissions.

Phase 2 remains approval-gated. The first real one-command Cloudflare publish still requires explicit approval; after that first approved publish succeeds and online smoke passes, later successful daily production runs may use the documented automatic publish path.

## Phase 3 Strategy V2

Strategy V2 is mandatory, not optional.

Phase 3 deterministic strategy behavior and the formal fail-closed safety framework are verified offline on the `codex/v3-mvp` branch. Concrete formal production clients, contracts, dependency assembly, live route capability evidence, and production activation remain incomplete and are tracked in the production capability matrix.

Remaining future work must continue improving 5/20/40 trading-day backtests, recommendation quality calibration, industry, market-cap and liquidity constraints, and daily result review. Strategy changes must pass backtest and design review before they are used in production.

Supabase remains a narrow decision ledger for operational decisions and recommendations. Full market data stays local.

Offline formal-readiness acceptance is not production approval. Live provider acquisition, Supabase mutation, Cloudflare deployment/publication, broker access, and order execution each require separate explicit approval. A blocked required-data run remains local-only and must preserve the prior report and publication pointers.

Do not ship manual tuning directly to production without explicit approval.

broker integration, order placement, and autotrading/自动交易 are out of scope.

## Phase 4 Product UI

Product UI is mandatory, not optional.

Phase 4 must improve the report homepage, historical reports, watchlist views, evidence package review, and mobile and desktop readability. The UI must continue to protect report access and must not expose internal logs, local data, credentials, raw caches, or operational-only artifacts.

Do not publish a Product UI redesign without explicit approval and online smoke.

## Required Sequence

1. Complete Phase 1 operations review and approved local run.
2. Build Phase 2 Cloudflare automation with GPT-5.5 xhigh implementer, reviewer, and subagents.
3. Keep Phase 3 Strategy V2 on `codex/v3-mvp` under GPT-5.5 xhigh implementer, reviewer, and subagent governance; future calibration and production approval remain mandatory after Phase 2.
4. Build Phase 4 Product UI with GPT-5.5 xhigh implementer, reviewer, and subagents; this remains mandatory after Phase 2.
5. Run final whole-branch review with GPT-5.5 xhigh before enabling production automation.
