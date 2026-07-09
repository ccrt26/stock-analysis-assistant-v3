# Mandatory Next Phases

Phase 1 is only the local production operations foundation. Phase 2, Phase 3, and Phase 4 are mandatory follow-up phases, not optional polish.

## Model and Review Governance

Every implementer, reviewer, and subagent assigned to production operations, Cloudflare automation, Strategy V2, Product UI, or whole-branch review must use GPT-5.5 xhigh. Mini models are not allowed for production safety, financial strategy, credentials, migration, deployment, automation, cleanup-before-retry, trading calendars, Supabase, or Cloudflare work.

## Phase 2: Cloudflare Automation

Cloudflare automation is mandatory, not optional. Phase 2 must automate publish only after a successful local production run, run online smoke after deploy, avoid overwriting the last known good online report on failure, and keep Cloudflare credentials redacted with minimum required permissions.

Phase 2 remains approval-gated. Do not enable automatic Cloudflare deployment without explicit approval.

## Phase 3: Strategy V2

Strategy V2 is mandatory, not optional.

Phase 3 must add 5/20/40 trading-day backtests, recommendation quality scoring, industry, market-cap and liquidity constraints, and daily result review. Strategy changes must pass backtest and design review before they are used in production.

Do not ship manual tuning directly to production without explicit approval.

## Phase 4: Product UI

Product UI is mandatory, not optional.

Phase 4 must improve the report homepage, historical reports, watchlist views, evidence package review, and mobile and desktop readability. The UI must continue to protect report access and must not expose internal logs, local data, credentials, raw caches, or operational-only artifacts.

Do not publish a Product UI redesign without explicit approval and online smoke.

## Required Sequence

1. Complete Phase 1 operations review and approved local run.
2. Build Phase 2 Cloudflare automation with GPT-5.5 xhigh implementer, reviewer, and subagents.
3. Build Phase 3 Strategy V2 with GPT-5.5 xhigh implementer, reviewer, and subagents.
4. Build Phase 4 Product UI with GPT-5.5 xhigh implementer, reviewer, and subagents.
5. Run final whole-branch review with GPT-5.5 xhigh before enabling production automation.
