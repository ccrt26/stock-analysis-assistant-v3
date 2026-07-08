# Tushare Ingestion V1 Design

Date: 2026-07-08
Status: Draft approved in conversation, pending implementation plan
Project root: `/Users/ccrt/股票分析助手`

## 1. Purpose

Tushare ingestion V1 opens the production `run-daily` path without letting sample data enter Supabase or published reports. It gives the assistant a real full-A-share data base while keeping the V3 MVP small enough to run reliably.

This is not "only first-layer analysis". It keeps the three-layer analysis design:

- Layer 1 becomes real: full A-share screening from live structured data.
- Layer 2 becomes a usable basic version: trend, liquidity, turnover, valuation/size, data quality, support and counter-evidence.
- Layer 3 remains structurally connected: evidence IDs, evaluation tasks, and future learning hooks are generated from real evidence, while deep announcement/news/industry interpretation stays outside V1.

## 2. Scope

V1 uses Tushare as the primary source and keeps backup paths narrow.

In scope:

- Full A-share stock universe from Tushare `stock_basic`.
- Trading calendar from Tushare `trade_cal`.
- Daily price/volume data from Tushare `daily`.
- Daily basic indicators from Tushare `daily_basic`.
- Retry, fallback, cache, and resume behavior for those datasets.
- Supabase writes for stock master, daily status, feature snapshots, recommendations, focus state, evidence packages, evaluation tasks, and data-source run records.
- Report warnings when data is degraded or cached.

Out of scope for V1:

- Full announcement ingestion and article-level interpretation.
- Deep financial statement factor library.
- News sentiment.
- Industry-chain graph analysis.
- Intraday or real-time trading.
- Automatic buy/sell instructions.

## 3. Data Source Priority

### 3.1 Primary Source

Tushare is the authoritative V1 source.

Required token locations:

- `TUSHARE_TOKEN` environment variable if present.
- Otherwise `TUSHARE_TOKEN_PATH`, defaulting to `/Users/ccrt/.tushare_token`.

The system must never print token values.

### 3.2 Backup Sources

Backup sources are only used after Tushare retry fails.

Allowed V1 backups:

- AkShare for daily price/volume fallback.
- Sina or Tencent public quote data for recent price/volume fallback if AkShare is unavailable.
- Local trusted cache from the last successful ingestion, but only for continuity checks and data-unavailable reporting.

Backup boundaries:

- Backup market data may support Layer 1 and basic Layer 2 features.
- Backup data must carry a lower source grade than Tushare.
- Backup data must not silently replace official financial, announcement, or hard-risk data.
- If a recommendation depends on backup data, the evidence package and report must say so.
- Cache data must not create new daily recommendations, upgrade a stock into the focus watchlist, or increase confidence. It can only maintain existing observation context or explain that current data is insufficient.

## 4. Failure Policy

The system should try hard to run, but it must not fabricate confidence.

Failure order:

1. Retry Tushare.
2. Try approved backup source for eligible market data.
3. Use recent trusted cache only for continuity checks and data-unavailable reporting.
4. Produce a formal recommendation report only if live primary or live backup data is sufficient and clearly labeled.
5. Fail without report publication if data is insufficient.

Hard failures:

- No Tushare token and no usable backup/cache for the required market data.
- Empty full-market universe.
- Empty daily market data for the target trade date after retry/fallback/cache.
- Feature coverage below the minimum threshold.
- Supabase persistence failure before recommendations, evidence, and evaluation tasks are complete.

Degraded run:

- May publish a report only with visible `数据降级` / `使用缓存` warning.
- Must reduce recommendation confidence.
- Must not create strong recommendation language.
- May output `数据不足，不形成结论` when uncertainty is high.
- Must not create new daily recommendations from cache-only data.
- Must not promote a stock from daily recommendation into the focus watchlist from cache-only data.
- May keep an existing focus stock in `继续观察` only when the report clearly says the state is carried forward because current live data is unavailable.

## 5. Retry and Resume

Every dataset stage has a run record in `data_source_run`.

Stages:

- `stock_basic`
- `trade_cal`
- `daily`
- `daily_basic`
- `feature_snapshot`
- `recommendation`
- `report`

Retry behavior:

- Each API call is retried up to 3 times.
- Delay uses small exponential backoff.
- Each failure records source, stage, attempt, message, and timestamp.

Resume behavior:

- Re-running `run-daily` for the same trade date resumes from available successful stage outputs.
- Supabase writes use upsert where possible.
- A second run must not duplicate recommendations, focus states, evidence packages, or evaluation tasks.

## 6. Cache Policy

Cache is a controlled continuity aid, not a hidden source of truth.

Cache records must include:

- Source name.
- Source grade.
- Original fetch time.
- Trade date covered.
- Field coverage.
- Freshness status.

Freshness limits:

- `stock_basic`: 7 days.
- `trade_cal`: 30 days.
- `daily`: target trade date only, or latest valid trade date for non-trading-day checks.
- `daily_basic`: target trade date only.

Cache use in reports:

- Report JSON includes `data_status`.
- HTML displays a visible warning if cache or backup source was used.
- Evidence packages include `source_versions`.
- Cache-only runs publish no new formal recommendations. They either maintain existing focus context with a warning, or publish `数据不足，不形成结论`.

## 7. Three-Layer Analysis Mapping

### 7.1 Layer 1: Full-Market Screening

Inputs:

- `stock_basic`
- `trade_cal`
- `daily`
- `daily_basic`

Outputs:

- `StockSnapshot`
- `FeatureSnapshot`
- excluded-stock counts and reasons

Hard exclusions:

- ST or name contains ST-like risk marker.
- Delisting-risk marker.
- Suspended or no valid daily bar.
- Listing age below 120 days.
- Turnover below minimum threshold.
- Amount below minimum threshold.

The goal is not to maximize stock count. It is to produce a clean candidate base.

### 7.2 Layer 2: Basic Evidence and Counter-Evidence

Inputs:

- Trend over 20 and 60 trading days.
- Relative strength against the candidate universe or broad-market proxy.
- 20-day volatility.
- Turnover and traded amount.
- Market value or valuation fields if available from `daily_basic`.

Outputs:

- recommendation reasons
- risks
- confidence level
- expected confirmation path
- invalidation conditions

V1 explanations must be plain-language analysis, not indicator dumps.

### 7.3 Layer 3: Evaluation and Learning Hook

Inputs:

- evidence package
- recommendation action
- focus watchlist state

Outputs:

- evaluation tasks for result, method, and knowledge-rule layers
- trading-day due dates
- frozen source versions

V1 does not optimize knowledge rules automatically, but it records enough evidence for later evaluation.

## 8. Production Command Behavior

`run-daily` without `--fixture-mode` becomes production ingestion.

Required configuration:

- `TUSHARE_TOKEN` or valid token file.
- `SUPABASE_URL`.
- `SUPABASE_SERVICE_ROLE_KEY`.

Production command:

```bash
PYTHONPATH=src python3 -m stock_analyzer run-daily --trade-date YYYY-MM-DD
```

Fixture command remains explicit:

```bash
PYTHONPATH=src python3 -m stock_analyzer run-daily --fixture-mode --trade-date YYYY-MM-DD
```

Production must never call `_sample_market()`.

## 9. Report Requirements

If production data is complete, the report is a normal production report.

If backup data is used, the report must show:

- source status
- backup/cache warning
- freshness
- reduced confidence
- whether recommendations are formal observations or only weak observations

If cache-only data is used, the report must not present new candidates. It must show one of:

- existing focus watchlist maintained with `数据不足` warning
- no formal conclusion because current live data is unavailable

If data is insufficient, the system must not publish a normal report.

## 10. Testing Strategy

Unit tests:

- token resolution without leaking token values
- Tushare client mapping from DataFrame to domain models
- retry behavior
- fallback behavior
- cache freshness decisions
- feature calculations
- data-quality exclusion

Integration-style tests with fake clients:

- successful production run writes all required Supabase rows
- Tushare failure then backup success creates degraded evidence/report
- Tushare and backup failure then fresh cache creates no new recommendations and only a data-unavailable/focus-maintenance report
- stale cache causes failure without a normal report
- rerun does not duplicate daily rows
- production command no longer raises "ingestion not implemented"
- production command never writes sample data

Manual smoke:

- Tushare token health check against one known stock.
- Supabase rollback write check.
- Fixture report generation still works and remains visibly labeled.

## 11. Acceptance Criteria

V1 is complete when:

- `run-daily` production path uses Tushare primary data, not sample data.
- Full A-share pool can be fetched from Tushare or a live backup source, or the run refuses to create new recommendations.
- At most about 10 recommendations are generated, and fewer are allowed.
- Reports show production/degraded/cache status clearly, and cache-only reports never look like formal recommendation reports.
- Supabase stores complete recommendation, evidence, focus, and evaluation state.
- Re-running the same date is idempotent.
- Tests and one live Tushare smoke pass.
- If all live sources fail, no fake production recommendation report is generated.

## 12. Open Follow-Ups After V1

- Add announcement ingestion from CNINFO/Tushare announcement interfaces.
- Add deeper financial indicators.
- Add industry and macro context.
- Add post-evaluation runner.
- Add Cloudflare scheduled deployment after production reports are stable.
