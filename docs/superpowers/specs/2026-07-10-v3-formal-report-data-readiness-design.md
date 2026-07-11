# V3 Formal Report Data Readiness Design

**Date:** 2026-07-10  
**Status:** Active normative data-readiness design; real formal run, Supabase activation/read-back, launchd, Cloudflare publication/smoke, and automatic publication complete; user-readable report correction remains blocked under Phase 3 authority

**Scope:** Repair data acquisition, validation, historical reuse, and formal-report eligibility after Phase 3 Strategy V2  
**Out of scope:** Strategy scoring, financial decision rules, position sizing, LLM writing style, broker integration, and automated orders

## 0. Correction Governance and Current-State Authority

This design remains the normative authority for formal-report behavior. It does not by itself prove that a production capability is implemented, verified, written to production, or activated. Current status is tracked only in [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md).

The implementation completed through commit `8e252ad48296dcc4375c10cacb5b81ff30663709` established generic route wrappers, atomic failover, immutable evidence, readiness states, focus-history rules, receipt gates, and two-phase activation under recorded or synthetic tests, but it lacked the concrete production program. The correction through default-entry evidence commit `0cd98dd` added the production contracts, Tushare and AKShare clients, durable capability records, screening/analysis/expression adapters, report bindings, Supabase hardening, and a functioning `build_production_formal_dependencies()` factory.

正式生产程序已完成实现并通过默认入口离线验证。已完成 2026-07-10 真实只读主源回填，共覆盖 2026-03-12 至 2026-07-10 的 82 个正式交易日；Supabase 迁移已应用并完成只读回查。正式事件能力 Gate 已通过：Tushare `anns_d` 权限拒绝且未获凭证，直连 CNINFO 备源通过真实非空毫秒时间戳、有效代码空窗口和完整目标合同。真实正式运行已完成 Strategy V2 每日推荐与重点股分析、Supabase 窄账本和报告原子激活、强读回及生产报告验证；launchd 已加载。凭证范围报告已发布至 `https://tl-quant-reports.pages.dev`，独立在线 smoke 通过并启用自动发布。可选 LLM 表达客户端仍未配置或调用，用户已判定真实 HTML 难以理解；该产品缺口由 Phase 3 设计和能力矩阵 `REPORT-004` 接管。经纪商连接和订单操作均未执行。

The following terms are distinct and must not be collapsed into a single “complete” status:

- **Implemented:** concrete production code exists without required empty stubs or unconditional blockers.
- **Offline verified:** the default production factory and internal call path pass while only external transports are replaced by recorded responses.
- **Live-read verified:** approved real read-only provider calls prove the route contract and capability evidence.
- **Production-write verified:** separately approved Supabase migration and narrow writes pass atomic read-back verification.
- **Activated:** separately approved recurring scheduling or automatic publication is enabled and operationally verified.

Lack of permission for live acquisition, Supabase mutation, Cloudflare deployment, or launchd activation never removes the requirement to implement and offline-test the concrete production program. Tests may replace an HTTP/API transport, but they may not replace the default production dependency factory, production route clients, production contracts, screening adapter, analysis adapter, renderer binding, or ledger binding.

Historical specifications and implementation plans remain audit records. They must not be used as current production-readiness evidence when they conflict with the production capability matrix.

### 0.1 2026-07-11 Production-Completion Amendment

The remaining production work is one continuous completion sequence under this design; it is not a new strategy phase and does not reopen Strategy V2 decisions, position rules, report structure, or broker/order scope.

The existing Tushare credential was tested through a redacted, read-only `anns_d` probe and does not have that independently licensed permission. Tushare remains the preferred primary event route if the permission is later granted, but production completion must not depend on assuming that access.

The approved immediate backup is a direct CNINFO disclosure route. A live read of the CNINFO raw response for 2026-07-10 proved that `announcementTime` is an epoch-millisecond value with sub-day precision; the loss of precision observed in the revoked route occurred in a third-party normalized wrapper. The production route must therefore consume the raw CNINFO value, retain its exact Asia/Shanghai timestamp, and reject missing, date-only, malformed, or timezone-ambiguous values. It must not recover precision by assigning midnight or any other invented time.

Provider selection for `official_events_risk` is fixed as follows:

1. Use Tushare `anns_d` only when a current live capability record proves permission, a populated precise-time response, and an empty covered window.
2. Otherwise discard the complete Tushare event-group attempt and start the direct CNINFO backup route from the original request.
3. Use iFinD or another provider only through a later capability-onboarding change that passes the identical contract; a credential or documented field name alone is not approval.
4. Never combine the rejected primary payload with the backup payload. The complete CNINFO backup recipe independently refetches current `suspend_d` and `stock_basic` status evidence through their already authorized Tushare endpoints, then fetches raw CNINFO generic and risk-category disclosures from the original request. Those calls form one declared backup route; no record from the failed primary attempt is reused. If either the shared status component or CNINFO disclosure component fails, the whole backup group fails.

This amendment is pre-approved by the user's instruction to test the existing Tushare permission and use a qualified backup when it is absent. Implementation still follows the detailed Superpowers plan and test-first gates; it does not require another strategy-design discussion.

## 1. Objective

The system must generate a formal Strategy V2 analysis report only when the data needed for accurate analysis is complete, timely, internally consistent, and traceable to an approved acquisition route.

Data acquisition exists to support analysis. Producing an artifact is never a reason to relax a data requirement, merge incomplete sources, infer current facts from stale cache, force a recommendation, or invoke the LLM without complete structured evidence.

This design repairs the gap between the data-source declarations introduced in Phase 3 and the executable production path. It preserves the approved Strategy V2 analysis, action, position, and report contracts, but places a strict data-readiness gate before any analysis or report generation.

## 2. Policy Precedence and Corrections

This specification restores and strengthens the fail-closed boundary from the Tushare Ingestion V1 design:

- Insufficient current-day required data stops the decision pipeline.
- No stock-analysis HTML, report JSON, recommendation, focus update, LLM narrative, publication, or decision-ledger write is produced for a blocked run.
- A blocked run may write an internal operational status and send a human-intervention notification. That status is not an analysis report and must not be placed in the publishable report tree.
- Historical cache can support historical windows, replay, audit, and same-run resume. It cannot replace missing current-day facts.

It also supersedes the earlier requirement to show a user-facing warning solely because an approved backup route supplied a complete group. Source route and freshness remain frozen in internal evidence metadata. A backup-supported report is allowed only when the backup group passes the same complete contract; the system does not compare providers or manufacture a source-difference warning.

The following Phase 3 behavior is superseded for production formal-report runs:

- A trading day is no longer required to render a public `data_insufficient` report.
- `report_mode=data_insufficient` is not a valid formal-report outcome.
- Per-stock data-insufficient snapshots are not a substitute for the pre-analysis data-readiness gate.
- A production provider failure must become an internal blocked run, not an empty public report.

Development fixtures may continue to exercise incomplete-data models, but scheduled production and formal local production runs must follow this specification.

## 3. Non-Goals

This project does not:

- Redesign ranking, risk-reward, focus-entry, or position-sizing rules.
- Add new LLM facts or allow the LLM to fill missing evidence.
- Compare primary and backup values or treat source disagreement as a strategy signal.
- Publish an operational failure page as if it were a market analysis.
- Connect to a broker or place an order.
- Read, print, persist, or log secret values.

## 4. Core Concepts

### 4.1 Acquisition Group

An acquisition group is the smallest data unit that can switch atomically between complete acquisition routes. It is identified by:

- `group_id`
- target `trade_date` or `as_of_date`
- analysis universe or target-code set
- required fields and legitimate-null rules
- freshness and publication-cutoff rules
- completeness and uniqueness rules
- one complete primary route
- one complete backup route where a backup is approved
- historical-cache policy

No record or field from a failed primary route may be patched with records or fields from the backup route inside the same group version.

### 4.2 Acquisition Route

An acquisition route is a complete recipe for one acquisition group. A route may call multiple APIs owned by one or more approved providers, but it must return the entire normalized group and pass the same data contract. Route composition is fixed in configuration and code; it is not selected by the LLM.

Examples:

- The primary calendar/universe route may call Tushare `stock_basic`, `trade_cal`, and `suspend_d`.
- The primary market-decision route may call Tushare `daily`, `daily_basic`, and `index_daily`.
- The backup market-decision route may call approved AkShare/Eastmoney adapters for complete daily history, the current post-close snapshot, valuation/liquidity fields, and index history.

The system may not combine a partial primary market route with a partial backup market route and call the result complete.

An acquisition group is not formal-report ready until both its primary and approved backup routes have executable capability evidence. If no complete backup route exists, the group is an explicit single-source hard dependency and requires user approval; a primary failure then blocks the run.

### 4.3 Report Cutoff

Each run freezes a `report_cutoff` timestamp in Asia/Shanghai when the post-close production run begins. The cutoff must be after the target market close. All market dates, publication timestamps, financial announcement dates, event timestamps, cache freshness checks, and point-in-time filters compare against that frozen cutoff. A retry for the same run keeps the same cutoff; a new run receives a new run ID and cutoff.

### 4.4 Canonical Version and Frozen Evidence

Raw successful acquisition versions are immutable. A canonical pointer identifies the preferred complete version for future feature calculation and replay.

If a backup route was used and the primary route later recovers:

1. Re-fetch the entire acquisition group through the primary route.
2. Validate it independently against the same contract. Do not compare it value-by-value with the backup version.
3. Store it as a new immutable version.
4. Move the canonical pointer to the validated primary version.
5. Mark the prior canonical version as superseded, not deleted.
6. Recompute affected derived features and replay inputs.
7. Keep the original report and evidence snapshot frozen with their original `input_set_id`.

A recovered primary version must never silently rewrite the facts cited by an already generated report.

Every backup-sourced canonical version creates a durable reconciliation task. The task remains pending until a later primary health check can fetch and validate the full group, or an operator closes it with a recorded reason. Reconciliation never performs provider-value comparison.

### 4.5 Run Receipt

Every production run creates an immutable run receipt containing:

- run ID, target date, and frozen `report_cutoff`
- acquisition-contract and screening versions
- exact acquisition-group version IDs and the resulting `input_set_id`
- candidate-set ID when screening has occurred
- state transitions and artifact hashes
- final activation state

Stored analysis rows alone are never authority to render or publish. The initial renderer must be invoked by the same run while its receipt is in `READY_TO_ANALYZE`; a later manual `render-report` must require a final committed run receipt whose input set and evidence hashes are complete.

### 4.6 Formal Report

A formal report is an analysis artifact generated only after `READY_TO_ANALYZE`. It contains recommendations or focus analysis backed by complete structured evidence. Internal run status, source diagnostics, and human-intervention notifications are not formal reports.

## 5. Acquisition Groups

### 5.1 Calendar and Universe Group

Purpose:

- Confirm whether the target date is an A-share trading day.
- Define the active listed universe and exchange mapping.
- Identify listing dates, names, statuses, and officially suspended codes.

Required normalized fields:

- calendar date and open/closed state
- stock code, name, exchange, listing date, listing status
- official special-treatment and delisting-risk status for every active code
- official suspension state for the target date

Primary route candidates:

- Tushare `trade_cal`
- Tushare `stock_basic`
- Tushare `suspend_d`

Backup route candidates:

- approved SSE/SZSE/BSE listed-security and suspension adapters
- AkShare `stock_info_a_code_name` only when the route can also supply the required exchange and status fields

Completeness rule:

- codes are unique and exchange-normalized
- the target date is present in the calendar response
- missing current market rows are excused only for codes proven suspended or otherwise ineligible by a validated official status record
- an unproven missing market row is a data failure, not an inferred suspension

### 5.2 Market Decision Group

Purpose:

- Build the complete full-market screening input.
- Calculate 20-day and 60-day trend, relative strength, 20-day volatility, liquidity, market regime, and ranking features.

Required normalized fields:

- target-date and historical `open`, `high`, `low`, `close`
- previous close or enough adjacent closes to derive it
- volume and amount with declared units
- target-date turnover rate, total market value, circulating market value
- PE TTM and PB fields with legitimate-null semantics for nonmeaningful values
- broad-market and required board/index daily bars
- source name, route ID, fetched time, covered date, field coverage, and content hash
- adjustment basis for any adjusted price series

Primary route:

- Tushare `daily`
- Tushare `daily_basic`
- Tushare `index_daily`

Backup route candidates:

- AkShare `stock_zh_a_hist`
- AkShare `stock_zh_a_spot_em` for the completed target-date snapshot
- AkShare `stock_zh_index_daily_em`
- approved Eastmoney valuation/liquidity adapters

Completeness rule:

- target-date rows cover 100% of the expected tradable universe after validated suspension and eligibility exclusions
- each analysis-eligible stock has at least 61 valid trading-day bars
- the initial July 10 backfill targets the 82 official trading sessions from 2026-03-12 through 2026-07-10, not 120 undifferentiated calendar partitions
- `(trade_date, ts_code)` keys are unique
- OHLC relationships, nonnegative volume/amount, units, dates, and finite numeric values pass internal validation
- required columns must exist even when a field permits a legitimate null

The backup route is not accepted merely because its API names are registered. It must pass a recorded capability test for full-universe coverage, field semantics, rate limits, and post-close availability.

### 5.3 Board and Industry Context Group

Purpose:

- Map stocks to industry and approved board classifications.
- Calculate board strength, breadth, and turnover context without relying on narrative inference.

Primary route candidates:

- Tushare `stock_basic.industry`
- Tushare `index_classify`
- Tushare `index_member_all`
- Tushare `index_daily`

Backup route candidates:

- approved AkShare Eastmoney industry-board name, constituent, and history adapters
- AkShare index-history adapters where applicable

Completeness rule:

- every provisional recommendation and active focus stock has a current industry mapping
- every board conclusion has enough constituent and history coverage to calculate the declared metric
- no board or concept label may be inferred from free text

### 5.4 Candidate Company and Fundamental Group

Purpose:

- Support company/business and fundamentals/valuation modules for provisional recommendations and active focus stocks.

Primary route candidates:

- Tushare `stock_company`
- Tushare `income`
- Tushare `balancesheet`
- Tushare `cashflow`
- Tushare `fina_indicator`
- Tushare `forecast`
- Tushare `express`
- Tushare `fina_mainbz`

Backup route candidates:

- AkShare `stock_individual_info_em`
- approved AkShare/Eastmoney financial-abstract and F10 adapters

Required normalized facts:

- company/business summary and principal business lines
- latest publicly available reporting period and announcement date
- revenue and profit growth inputs
- gross-margin input where used
- operating-cash-flow input where used
- valuation context needed by the current strategy

Point-in-time rule:

- only information whose official publication time is on or before the report cutoff may be used
- later restatements may become a new historical version but must not leak backward into the original evidence snapshot

The provisional candidate set is frozen before this group is fetched. A candidate with incomplete required company/fundamental evidence blocks the formal report; it may not be silently removed and replaced by the next ranked stock.

### 5.5 Events, Catalysts, and Official Risk Group

Purpose:

- Supply only official or approved high-reliability events and hard-risk evidence.

Primary route candidates:

- official SSE/SZSE/BSE disclosure adapters
- official exchange and regulator risk adapters
- Tushare `suspend_d`, `stock_basic` status/name fields, `forecast`, `express`, `stk_holdertrade`, and other individually verified event endpoints

Backup route candidates:

- approved Eastmoney/AkShare announcement adapters such as `stock_notice_report` when their coverage and publication timestamps pass capability testing
- direct CNINFO `hisAnnouncement/query` plus `szse_stock.json`, with the raw epoch-millisecond `announcementTime`, stable `announcementId`, official PDF path, and per-code/category pagination retained without third-party timestamp normalization

2026-07-11 live correction: Eastmoney `stock_notice_report` and the AkShare-normalized CNINFO route returned date-only values and therefore did not pass the 18:30 point-in-time contract. The corresponding capability evidence was removed from `latest.json`; historical evidence remains audit-only. A subsequent direct read of the CNINFO raw endpoint proved that its unwrapped `announcementTime` contains epoch-millisecond precision. The direct route is a distinct implementation and route ID; it may advance only after both a populated non-midnight response and a proven-empty valid-code window pass the same cutoff contract. Tushare `anns_d`, iFinD `ctime`, or another official route remains subject to the identical onboarding rule.

Rules:

- the unverified generic name `tushare.announcements` is not an executable source contract
- event title, type, issuer code, official publication time, source reliability, and source URL or stable source identifier are required
- rumors, social-media heat, and low-reliability material cannot satisfy this group
- absence of a hard-risk event is valid only after the route proves coverage for the target code set and time window
- any hard-risk conclusion uses official facts available by the report cutoff
- an empty provider response can prove only empty-window coverage; it can never prove timestamp field semantics
- live event capability evidence must persist separate hashes for one populated precise-time probe and one valid-code empty-window probe
- every CNINFO page must agree with the requested code and date window; pagination totals, duplicate announcement IDs, missing PDF paths, and malformed timestamps fail the complete route. The legacy `szse_stock.json` mapping is an optimization, not an authoritative security universe: when a frozen target code is absent, the route must query the official endpoint with that exact six-digit code in `searchkey`, completely paginate the declared result, and reject any returned row whose `secCode` differs. It must never send a blank `orgId` in `stock` (which CNINFO interprets as an all-market query), silently treat the missing mapping as a proven empty result, or replace the frozen candidate.
- risk-category queries are part of the complete CNINFO route and may mark an announcement as hard risk; generic title text is not used to invent a risk category

### 5.6 Concept and Theme Group

Concept tags are enhanced data by default. They may not support a formal positive conclusion when missing. If a recommendation thesis explicitly depends on a concept/theme claim, the concept group becomes required for that report.

Primary route candidates:

- Tushare `concept`
- Tushare `concept_detail`

Backup route candidates:

- approved AkShare Eastmoney concept-board constituent adapters

### 5.7 Manual Holdings Group

Manual holdings and actions remain local-first. A valid explicit empty holdings file means no registered holding. A missing, malformed, or unreadable holdings file blocks only personalized holding-adjustment output; it must never be interpreted as an explicit empty portfolio.

## 6. Data Requirement Semantics

Requirements are bound to analysis claims, not to report layout.

- **Required:** a fact without which the relevant market screen, recommendation, focus analysis, risk conclusion, or position adjustment cannot be accurate.
- **Enhanced:** a fact that may improve analysis but is not used to justify a conclusion when absent.
- **Observation-only:** a fact retained for later study and prohibited from supporting a current formal conclusion.

An enhanced datum automatically becomes required for a report when any generated thesis, catalyst statement, risk statement, or action recommendation depends on it.

Required-column presence and required-value presence are separate. PE may be legitimately null for a loss-making company, but the source must still provide the field and the normalization must record why the value is unavailable. Missing columns, unclassified nulls, and unknown units fail validation.

## 7. Primary and Backup Behavior

Primary and backup exist only to improve acquisition availability.

- Call the primary route first.
- Retry only failures classified as transient.
- If the primary route fails or returns an incomplete group, reject the entire primary group version.
- Call the complete backup route from the beginning.
- Do not merge primary and backup rows or fields within one group version.
- Do not fetch both merely to compare them.
- Do not alert because values differ between sources.
- Validate whichever route succeeds against the same completeness, freshness, semantic, and internal-consistency contract.
- Record source lineage for audit, not as a strategy factor.

A backup route that meets the full contract may support a formal report. Its use is retained in internal evidence metadata; the user-facing report does not need a difference warning solely because a backup route was used.

## 8. Historical Cache and Same-Run Resume

Historical cache is a point-in-time evidence store, not a current-day fallback.

Permitted uses:

- build the 82-session historical feature window
- reuse the latest official low-frequency fact when its `as_of` date and freshness contract remain valid
- resume a successful stage for the same target date and same acquisition contract version
- replay and evaluate decisions using the exact input set frozen at recommendation time
- explain internally when the last successful acquisition occurred

Forbidden uses:

- fill missing target-date price, volume, amount, turnover, valuation, board state, suspension state, announcement, or hard-risk facts
- infer current movement from the previous trading day
- upgrade or remove a focus stock from stale current-state evidence
- create a report that appears current when the current-day required group failed

Every cached version records:

- acquisition group and route ID
- source and source grade
- covered trade date or `as_of` date
- original publication time where relevant
- fetched time
- field coverage and legitimate-null classification
- adjustment and unit metadata
- content hash
- schema/contract version
- canonical/superseded state

## 9. Two-Stage Acquisition and Candidate Freeze

The formal daily run uses two data stages:

1. Acquire and validate calendar, universe, market decision, board/industry, and official hard-risk groups for the screening universe.
2. Enter `READY_TO_SCREEN` and run deterministic market screening only. This step cannot create a recommendation, action, focus decision, evidence package, report, or LLM text.
3. Persist an immutable candidate-set artifact before target acquisition. It contains the ordered provisional codes, active/manual focus codes, screening contract/version, upstream `input_set_id`, and content hash. Retry and resume must consume that exact candidate set.
4. Acquire and validate complete company, fundamental, event, concept-if-used, risk, and holdings groups for that frozen target set.
5. Apply the final data-readiness gate and enter `READY_TO_ANALYZE`.
6. Only then build Strategy V2 structured evidence, recommendations, focus updates, and LLM expression.

The system must not skip a provisional candidate because its required data is missing and promote a lower-ranked candidate. That would make data availability an undeclared ranking factor.

## 10. Run State Machine

The scheduled and manual production paths use these states:

```text
PENDING
  -> ACQUIRING_SCREENING_PRIMARY
  -> ACQUIRING_SCREENING_BACKUP   # only after primary route rejection
  -> VALIDATING_SCREENING
  -> READY_TO_SCREEN
  -> SCREENING
  -> TARGET_SET_FROZEN
  -> ACQUIRING_TARGET_PRIMARY
  -> ACQUIRING_TARGET_BACKUP      # only after primary route rejection
  -> VALIDATING_TARGET
  -> READY_TO_ANALYZE
  -> ANALYZING
  -> RENDERING
  -> VERIFYING
  -> COMMITTING
  -> ANALYSIS_COMPLETE_NO_RECOMMENDATIONS | REPORT_GENERATED

Any exhausted required-group recovery
  -> BLOCKED_NEEDS_HUMAN
```

Rules:

- Only `READY_TO_SCREEN` may run provisional deterministic screening.
- Only `READY_TO_ANALYZE` may call strategy/evidence builders.
- Only `ANALYZING` may call the LLM expression boundary.
- The initial render path requires the current run receipt in `READY_TO_ANALYZE` and the exact `input_set_id`. A later manual `render-report` requires a final committed `REPORT_GENERATED` receipt; repository rows alone cannot authorize rendering.
- Only a complete analysis with publishable recommendations/focus output may enter `RENDERING`.
- A complete analysis that honestly produces zero recommendations must not force a stock pick. It records `ANALYSIS_COMPLETE_NO_RECOMMENDATIONS` and follows the existing no-publication policy.
- `BLOCKED_NEEDS_HUMAN` writes internal status only and leaves the prior published report/current pointer unchanged.
- A blocked run writes no new recommendation, focus state, evidence snapshot, evaluation task, report index, or decision-ledger row.
- Raw local acquisition diagnostics may be retained outside the publishable report tree.

### 10.1 Two-Phase Formal Activation

Report and decision-ledger activation must be idempotent and fail closed across local files and the narrow ledger:

1. Render into a new immutable staging directory keyed by run ID.
2. Verify report mode, evidence completeness, secret safety, artifact hashes, and run-receipt linkage.
3. Write all narrow-ledger rows for the run in one database transaction as pending and invisible to formal consumers.
4. Verify that staged artifacts and pending ledger rows match the run receipt.
5. Activate the run through a two-phase commit marker. Report and ledger readers must ignore a run unless both activation markers agree.
6. Advance local/current and published pointers only after activation; pointer changes are atomic and idempotent.

Any failure before complete activation leaves prior current and published pointers byte-for-byte unchanged. Pending artifacts and ledger rows remain invisible and are cleaned or completed by an idempotent retry. The run records `FAILED_RETRYABLE` or `FAILED_NEEDS_HUMAN`; it never reports `REPORT_GENERATED` with a partial commit.

When a complete run produces no new recommendations but does produce valid focus tracking, its decision rows and final run receipt commit in one transaction without changing a recommendation-report or publication pointer. That committed focus analysis is eligible for the observation window.

## 11. Human-Intervention Status

Blocked status is written only to `logs/run-daily/<run_id>.json`, with `logs/run-daily/latest-status.json` as the local latest summary, plus the local operator-notification channel. It is excluded from Supabase decision-ledger tables, report trees, report archives, deployment artifacts, and published pages.

The internal blocked status includes:

- target date and failed acquisition group
- primary and backup route attempts
- failure classification: permission, transport, rate limit, schema, missing fields, incomplete universe, stale data, invalid semantics, storage, or unknown
- exact missing or invalid fields
- affected code/date coverage
- whether historical cache was allowed and why it could not satisfy the current requirement
- impact on analysis modules
- retry eligibility
- concise operator action
- redacted diagnostic message

It contains no recommendation, thesis, position suggestion, LLM narrative, or publishable report page.

## 12. Focus History

- Evaluate the five immediately preceding eligible A-share trading dates, not the last five available snapshots.
- A blocked, fixture, incomplete, or backfill-only trading date breaks the five-day window and cannot be skipped. Observation resumes from day one after the break.
- A complete formally committed focus analysis counts even when the run produces zero new recommendations; external publication policy is separate from focus-observation validity.
- The pipeline must load prior valid Strategy V2 snapshots before evaluating focus entry.
- At least three snapshots from those five immediately preceding eligible trading dates must support the entry thesis under the existing Strategy V2 rules.
- A primary-source reconciliation can update canonical historical inputs and replay metrics, but cannot retroactively create an observation day or silently change a frozen focus decision.
- Manual focus entries remain visible internally, but no operation or position recommendation is produced for them until their required target groups pass validation.

## 13. Storage Design

The local warehouse remains the wide-data source of truth. Supabase remains a narrow decision ledger.

Wide formal records MUST NOT be stored as JSON. `FormalWarehouse` registers immutable versions, canonical pointers, receipts, candidates, capabilities, and audits in `warehouse.duckdb`; normalized wide rows live in Parquet. JSON is limited to published report contracts, operator status, and explicitly approved small manual inputs.

Required local datasets include versioned partitions for:

- calendar and stock universe
- daily market bars by actual covered trade date
- daily valuation/liquidity by actual covered trade date
- index and board history
- company profiles
- fundamental snapshots
- industry and concept membership
- events/catalysts
- official risk events
- source-run and acquisition-group manifests
- canonical-version pointers
- run receipts and immutable candidate sets

Historical bars must not be stored only under the report target-date partition. Each row remains queryable by its actual covered trade date through DuckDB, with the underlying Parquet partition using that actual date.

Replacing a backup canonical version with a recovered primary version updates a pointer or manifest transactionally. It does not delete immutable raw versions.

Derived features and evidence records carry an `input_set_id` that resolves to exact acquisition-group versions.

## 14. Verification and Test Gates

### 14.1 Adapter Contract Tests

Each executable adapter must prove:

- required field mapping and units
- target-date/as-of semantics
- pagination and rate-limit handling
- code/exchange normalization
- legitimate-null handling
- duplicate and malformed-row rejection
- secret-safe diagnostics

Naming an API in the registry is not acceptance evidence.

### 14.2 Atomic Failover Tests

Tests must prove:

- complete primary group succeeds without backup calls
- transient primary failure retries before backup
- partial primary group is rejected in full
- backup starts from an empty group and returns the entire group
- no primary row or field survives in a backup group version
- no primary/backup value-difference comparison or alert occurs
- incomplete backup ends in `BLOCKED_NEEDS_HUMAN`

### 14.3 Cache and Reconciliation Tests

Tests must prove:

- historical cache supplies prior sessions only
- current-day cache cannot satisfy a current-decision group
- same-run checkpoints are tied to target date and contract version
- recovered primary data creates a new immutable version and canonical pointer
- frozen reports retain their original `input_set_id`
- derived history is invalidated/recomputed without rewriting historical reports
- point-in-time financial/event tests reject look-ahead data

### 14.4 Coverage Edge Cases

Tests must distinguish:

- officially suspended stocks from unexplained missing daily rows
- newly listed/hard-excluded stocks from history coverage failure
- legitimate valuation nulls from missing columns
- complete no-event coverage from an event API failure
- explicit empty holdings from a missing holdings file

### 14.5 Pipeline and Report Gates

Any required-group failure must assert:

- strategy builders were not called
- LLM expression was not called
- no report HTML or report JSON was created or replaced
- no publication occurred
- no recommendation/focus/evidence/evaluation decision rows were written
- an internal redacted blocked status was recorded

Additional escape and atomicity tests must prove:

- manual `render-report` rejects missing, blocked, uncommitted, or mismatched run receipts
- a blocked retry with an existing current report preserves all prior report and publication pointers
- render, verification, ledger, or pointer failure never exposes a partially committed run
- retry can idempotently complete or clean pending artifacts and rows
- target-evidence failure for any frozen provisional candidate blocks the run instead of promoting the next-ranked code
- retry and resume use the same immutable candidate-set ID
- provisional screening cannot call final strategy/action builders, LLM expression, report rendering, or decision-ledger persistence

A successful formal run must assert:

- all required group manifests are complete
- every provisional candidate and active focus code has required target evidence
- report evidence resolves to exact input versions
- no fixture/sample marker exists
- no user-facing numeric total score exists
- focus action contains decision, position range, reasons, confirmation, invalidation, and risk if wrong

## 15. July 10 Readiness Acceptance

Implementation is not complete until an isolated end-to-end rehearsal for 2026-07-10 proves both paths using recorded or synthetic responses:

1. Complete path: 82 official trading sessions plus complete July 10 current and low-frequency target evidence pass the gate and produce a formal Strategy V2 report.
2. Primary failover path: a deliberately partial primary group is discarded, the complete backup route succeeds atomically, and the report uses only the backup group version.
3. Blocked path: primary and backup both fail completeness; no analysis/report artifacts are created and an internal human-intervention status is recorded.
4. Reconciliation path: the primary route later succeeds for the backup date, becomes canonical for future replay, and does not rewrite the frozen report.
5. Focus path: only prior formally committed focus snapshots count, and any blocked eligible trading date breaks rather than stretches the five-day window.
6. Direct-render path: stored rows without a final committed `REPORT_GENERATED` run receipt cannot generate a formal report.
7. Atomic-failure path: injected render, verify, ledger, and pointer failures leave the prior report and all formal consumers unchanged.

Live data acquisition and any real production write require separate explicit user approval after implementation and offline verification.

That approval was granted on 2026-07-11 for provider reads, the formal 2026-07-10 run, Supabase narrow formal writes, first report publication, and scheduler activation after all preceding gates pass. It does not authorize broker connectivity or order operations. Production mutations remain sequenced and fail closed; the approval does not permit skipping capability, test, receipt, hash, capacity, or smoke verification.

## 16. Acceptance Criteria

This repair is complete when:

- every required acquisition group has executable, tested route adapters rather than source-name strings or empty provider stubs
- primary/backup switching is atomic by acquisition group
- backup data can support analysis only after satisfying the same complete contract
- historical cache is readable, versioned, point-in-time safe, and forbidden for missing current-day facts
- recovered primary versions replace canonical history without deleting provenance or rewriting frozen reports
- the pipeline cannot reach analysis or report rendering before data readiness
- the manual render path cannot bypass the committed run receipt
- formal report and decision-ledger activation is two-phase, idempotent, and invisible until complete
- blocked runs produce internal diagnostics and human intervention only
- prior valid focus history is loaded and incomplete days never count
- formal report generation is demonstrated offline for July 10
- no secret, broker connection, order execution, or write outside the approved narrow formal receipt/ledger/report activation flow is introduced

### 16.1 Production-Completion Acceptance

The current `/goal` is complete only when all of the following have fresh evidence:

1. The existing Tushare credential has a redacted `anns_d` permission result; when denied, no Tushare event capability is issued.
2. The direct CNINFO route has immutable live evidence for a populated raw millisecond timestamp and a valid-code empty response, passes the full target contract, and is the only active CNINFO event route in `latest.json`.
3. The already stored 82 official sessions remain complete and canonical; the formal run reuses them or refetches a whole primary group when validation requires it, never patches them with another route.
4. One real 2026-07-10 run reaches `READY_TO_ANALYZE`, executes the existing deterministic daily recommendation and focus analysis, renders and verifies its formal report, prepares and atomically activates its Supabase narrow rows, and confirms active-view read-back against the same receipt and hashes.
   The outer production verifier must validate the combined output contract: every daily recommendation has a matching evidence package; additional evidence packages for active focus stocks are valid; and each actual evidence package, whether recommendation or focus, owns the complete six-task evaluation schedule. It must reject missing recommendation evidence, duplicate/unknown evidence references, or incomplete task schedules, but must not equate evidence-package count with recommendation count.
5. The first Cloudflare publish deploys only the activated artifact, passes online date/content/password/redaction smoke, and enables automatic publication only after that success.
   Verification and deploy staging are scoped to the exact relative paths and SHA-256 hashes in the activated receipt. Historical frozen reports remain preserved locally but are neither attributed to the current run nor copied into its Cloudflare artifact. Any unsafe receipt path, missing/hash-mismatched current artifact, or fixture/score leak inside the activated set fails closed.
6. The generated launchd service contains the resolved checkout path only in the local installed copy, loads successfully, exposes no secret value, and its executable command passes a non-mutating configuration/health smoke before scheduling is declared active.
   After the feature branch is merged, the canonical production checkout is the clean local `main` worktree resolved from Git at installation time; launchd, editable package resolution, local runtime state, and generated output paths must all resolve there before the feature worktree or branch is removed. Loading `.env.local` must not be allowed to override that installed checkout root. The resolved absolute path belongs only in the generated local plist, never in production source or an active operational document.
   Reinvoking a `REPORT_GENERATED` run with the identical date, cutoff, contract, and run ID is a read-only terminal reuse: it performs no acquisition, screening, analysis, render, ledger write, or pointer change. Likewise, the 19:00 and 19:30 retry slots are no-ops when an earlier slot for that date already ended successfully or as a confirmed non-trading day; they return the prior terminal status without cleanup or status overwrite.
7. Targeted tests, one complete test suite, source hardcoding scans, secret scans, production Gate checks, and an independent read-only final review have no unresolved Critical or Important finding.
8. The worktree is clean and every design, plan, implementation, evidence-status, and operational change has been committed and pushed to `origin/codex/v3-mvp`.

If a required external credential for Supabase or Cloudflare is unavailable, invalid, or cannot be used without exposing it, the pipeline stops before that mutation and reports the exact external blocker. It must not mark later production-completion items satisfied.

## 17. Design Boundary Summary

The three approved repair areas are:

1. **Data-readiness gate:** incomplete required data prevents analysis and reports.
2. **Executable acquisition:** typed contracts, 82-session history, atomic primary/backup routes, historical cache, and later primary reconciliation.
3. **Downstream enforcement:** valid focus history, blocked-run operations, tests, and formal-report publication gates.

All three exist solely to ensure accurate, evidence-backed analysis. They do not redesign Strategy V2 conclusions or presentation.
