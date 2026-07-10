# V3 Formal Report Data Readiness Design

**Date:** 2026-07-10  
**Status:** Approved design, pending implementation plan  
**Scope:** Repair data acquisition, validation, historical reuse, and formal-report eligibility after Phase 3 Strategy V2  
**Out of scope:** Strategy scoring, financial decision rules, position sizing, LLM writing style, broker integration, and automated orders

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

- The primary market-decision route may call Tushare `stock_basic`, `trade_cal`, `daily`, `daily_basic`, and `index_daily`.
- The backup market-decision route may call approved AkShare/Eastmoney adapters for the complete stock universe, daily history, current post-close snapshot, valuation/liquidity fields, and index history.

The system may not combine a partial primary market route with a partial backup market route and call the result complete.

### 4.3 Canonical Version and Frozen Evidence

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

### 4.4 Formal Report

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

Rules:

- the unverified generic name `tushare.announcements` is not an executable source contract
- event title, type, issuer code, official publication time, source reliability, and source URL or stable source identifier are required
- rumors, social-media heat, and low-reliability material cannot satisfy this group
- absence of a hard-risk event is valid only after the route proves coverage for the target code set and time window
- any hard-risk conclusion uses official facts available by the report cutoff

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
2. Run deterministic screening only to freeze the provisional recommendation set and combine it with active/manual focus codes.
3. Acquire and validate complete company, fundamental, event, concept-if-used, risk, and holdings groups for that frozen target set.
4. Apply the final data-readiness gate.
5. Only then build Strategy V2 structured evidence, recommendations, focus updates, and LLM expression.

The system must not skip a provisional candidate because its required data is missing and promote a lower-ranked candidate. That would make data availability an undeclared ranking factor.

## 10. Run State Machine

The scheduled and manual production paths use these states:

```text
PENDING
  -> ACQUIRING_PRIMARY
  -> ACQUIRING_BACKUP        # only after primary route rejection
  -> VALIDATING
  -> READY_TO_ANALYZE
  -> ANALYZING
  -> ANALYSIS_COMPLETE_NO_RECOMMENDATIONS | REPORT_GENERATED

Any exhausted required-group recovery
  -> BLOCKED_NEEDS_HUMAN
```

Rules:

- Only `READY_TO_ANALYZE` may call strategy/evidence builders.
- Only `ANALYZING` may call the LLM expression boundary.
- Only a complete analysis with publishable recommendations/focus output may render and publish a formal report.
- A complete analysis that honestly produces zero recommendations must not force a stock pick. It records `ANALYSIS_COMPLETE_NO_RECOMMENDATIONS` and follows the existing no-publication policy.
- `BLOCKED_NEEDS_HUMAN` writes internal status only and leaves the prior published report/current pointer unchanged.
- A blocked run writes no new recommendation, focus state, evidence snapshot, evaluation task, report index, or decision-ledger row.
- Raw local acquisition diagnostics may be retained outside the publishable report tree.

## 11. Human-Intervention Status

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

- Only snapshots produced by a `REPORT_GENERATED` run count toward the five-trading-day focus observation window.
- The pipeline must load prior valid Strategy V2 snapshots before evaluating focus entry.
- At least three of the last five valid trading-day snapshots must support the entry thesis under the existing Strategy V2 rules.
- Blocked days, fixture runs, incomplete snapshots, and backfill-only acquisitions do not count as live observation days.
- A primary-source reconciliation can update canonical historical inputs and replay metrics, but cannot retroactively create an observation day or silently change a frozen focus decision.
- Manual focus entries remain visible internally, but no operation or position recommendation is produced for them until their required target groups pass validation.

## 13. Storage Design

The local warehouse remains the wide-data source of truth. Supabase remains a narrow decision ledger.

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

Historical bars must not be stored only under the report target-date partition. Each row remains queryable by its actual trade date.

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
5. Focus path: only prior formally generated snapshots count toward the five-day observation rule.

Live data acquisition and any real production write require separate explicit user approval after implementation and offline verification.

## 16. Acceptance Criteria

This repair is complete when:

- every required acquisition group has executable, tested route adapters rather than source-name strings or empty provider stubs
- primary/backup switching is atomic by acquisition group
- backup data can support analysis only after satisfying the same complete contract
- historical cache is readable, versioned, point-in-time safe, and forbidden for missing current-day facts
- recovered primary versions replace canonical history without deleting provenance or rewriting frozen reports
- the pipeline cannot reach analysis or report rendering before data readiness
- blocked runs produce internal diagnostics and human intervention only
- prior valid focus history is loaded and incomplete days never count
- formal report generation is demonstrated offline for July 10
- no secret, broker connection, order execution, or production write is introduced

## 17. Design Boundary Summary

The three approved repair areas are:

1. **Data-readiness gate:** incomplete required data prevents analysis and reports.
2. **Executable acquisition:** typed contracts, 82-session history, atomic primary/backup routes, historical cache, and later primary reconciliation.
3. **Downstream enforcement:** valid focus history, blocked-run operations, tests, and formal-report publication gates.

All three exist solely to ensure accurate, evidence-backed analysis. They do not redesign Strategy V2 conclusions or presentation.
