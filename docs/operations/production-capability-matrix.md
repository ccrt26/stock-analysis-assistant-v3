# Production Capability Matrix

**Status:** Canonical current-state authority  
**Last verified:** 2026-07-12 through live Tushare/CNINFO provider reads, a successful real formal run, Supabase atomic activation/read-back, activated-report verification, canonical-main launchd activation and read-only replay, Cloudflare publication/online smoke, and offline regression evidence
**Scope:** Stock Analysis Assistant V3 from data acquisition through analysis, storage, scheduling, and publication

## 1. Authority and Use

This file is the only document that states the current production-readiness level of the system. Design specifications define intended behavior. Implementation plans are historical execution records. Runbooks describe only operations that the matrix says are available. Neither a passing unit-test suite nor an older phase-completion statement may override this matrix.

Every corrective task, commit, review finding, live-read approval, production mutation, scheduler activation, and publication activation must cite one or more stable capability IDs from this file. A capability may advance only when the evidence required by its next level exists.

## 2. Capability Levels

| Level | Meaning |
| --- | --- |
| `NOT_IMPLEMENTED` | A required concrete production implementation is absent, is an empty stub, or is replaced by an unconditional blocker. |
| `IMPLEMENTED_UNVERIFIED` | Production code exists, but the default production path has not passed the required recorded-response or environment verification. |
| `OFFLINE_VERIFIED` | The real internal production factory, clients, contracts, and callbacks pass with external I/O replaced only at the transport boundary. |
| `LIVE_READ_VERIFIED` | Approved real read-only provider calls prove field semantics, coverage, rate-limit behavior, and post-close availability without production mutation. |
| `PRODUCTION_WRITE_VERIFIED` | Approved production migrations and writes pass narrow-scope, atomicity, idempotency, and read-back verification. |
| `ACTIVATED` | The approved recurring scheduler or publication path is enabled and has passed its operational verification. |
| `BLOCKED` | The implementation exists or is partially implemented, but a named technical or approval condition prevents advancement. |
| `NOT_APPLICABLE` | The capability is intentionally outside the product boundary. |

Levels are progressive only where the capability needs that stage. For example, a pure deterministic validator can finish at `OFFLINE_VERIFIED`; a provider route must reach `LIVE_READ_VERIFIED`; Supabase activation must reach `PRODUCTION_WRITE_VERIFIED`; launchd and automatic publication must reach `ACTIVATED`.

## 3. Approval Boundaries

The following permissions are separate and must never be inferred from one another:

1. Implement production clients, contracts, factories, migrations, and automation code.
2. Run recorded-response tests without network access.
3. Perform real read-only provider acquisition and capability verification.
4. Apply a Supabase migration.
5. Write or reconcile production decision-ledger data.
6. Perform the first Cloudflare deployment and online smoke.
7. Enable launchd and later automatic publication.
8. Connect to a broker or place an order. This remains prohibited and out of scope.

The absence of approval for steps 3-7 does not permit omission of the code and offline verification required by steps 1-2.

## 4. Current Capability Matrix

### 4.1 Documentation and Completion Governance

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `GOV-001` | One canonical current-state source | Matrix referenced by README, active design, runbook, and future plan; historical documents disclaim current-state authority | README and active runbooks reference this matrix; every historical spec/plan has a lifecycle banner; the deprecated compatibility roadmap has been removed; focused documentation tests pass | `OFFLINE_VERIFIED` | None |
| `GOV-002` | Requirement-to-code traceability | Every normative requirement maps to a production symbol, default-path test, live/activation evidence, and corrective task | Correction plan Tasks 2-13 map every capability to symbols, named tests, commands, expected results, and commit boundaries; the default-path acceptance covers the system gates | `OFFLINE_VERIFIED` | Live and activation evidence remain separately gated |
| `GOV-003` | Non-ambiguous completion reporting | Reports state separate implementation, offline, live-read, production-write, and activation levels | Active design, README, runbooks, tests, and this matrix distinguish offline completion from unexecuted live-read, production-write, scheduler, and publication actions | `OFFLINE_VERIFIED` | None |
| `GOV-004` | Runtime hardcoding governance | Run/environment values enter through validated request or configuration; approved domain invariants have one named authority; source gates reject date, candidate, identity, path, credential, endpoint-version, activation, and distributed window literals | `formal_policy.py` owns the 82/61/21/5 windows, calendar lookback, post-close boundary, and benchmark identifiers; config/request objects own runtime values; source and active-operations-document tests reject July-only runtime flow, personal paths, and duplicated formal window definitions | `OFFLINE_VERIFIED` | Provider schema/version drift remains guarded by live capability evidence rather than embedded assumptions |

### 4.2 Formal Acquisition Routes

| ID | Capability | Required production implementation | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `DATA-001` | Calendar and universe primary route | Concrete Tushare client using `trade_cal`, `stock_basic`, `suspend_d`, normalized status and exclusion semantics | Live 2026-07-10 verification passed the full contract and stored immutable capability and group versions | `LIVE_READ_VERIFIED` | None for the primary route |
| `DATA-002` | Calendar and universe backup route | Concrete approved SSE/SZSE/BSE route that proves calendar, listing, exchange, status, and suspension coverage | `AkshareFormalEndpointClient.fetch_calendar_universe()` uses the calendar, three exchange lists, delisting lists, and current spot coverage; recorded tests fail closed on unverified status | `OFFLINE_VERIFIED` | Requires approved live read and capability record before use with live mode |
| `DATA-003` | Market-decision primary route | Concrete Tushare route for 82 official sessions of `daily`, target-date `daily_basic`, and required index history with units and adjustment metadata | Live verification read and stored the exact 2026-03-12 through 2026-07-10 window with target facts and three required indexes | `LIVE_READ_VERIFIED` | None for the primary route |
| `DATA-004` | Market-decision backup route | Complete AkShare/Eastmoney route for the same whole contract, never a partial patch | Formal AKShare client obtains full equity history, current valuation/liquidity, and required indexes; default acceptance proves whole-group restart without primary records | `OFFLINE_VERIFIED` | Live field semantics, coverage, and post-close availability are unverified |
| `DATA-005` | Board and industry primary/backup routes | Concrete industry classification, membership, history, breadth, and turnover context for candidates and active focus stocks | Tushare primary passed live verification; recorded primary/backup tests pass the same contract | `BLOCKED` | Eastmoney backup was unreachable through both proxy and direct connections; no live backup capability was issued |
| `DATA-006` | Candidate company and fundamentals primary/backup routes | Concrete company profile, statements, indicators, forecast/express, principal business, announcement dates, legitimate-null rules | Tushare primary passed live verification; recorded primary/backup tests pass point-in-time and legitimate-null rules | `BLOCKED` | Eastmoney backup was unreachable and the free THS/CNINFO alternatives do not yet prove all required point-in-time fields |
| `DATA-007` | Official events and hard-risk primary/backup routes | Concrete official disclosure/exchange/regulator route and complete approved backup with proven empty coverage semantics | Tushare `anns_d` was denied and received no capability; direct raw CNINFO v2 passed a populated epoch-millisecond probe, a valid-code empty-window probe, the complete target contract, cutoff filtering, and immutable live evidence | `LIVE_READ_VERIFIED` | None for the current backup route; future Tushare permission requires its own fresh dual-probe evidence |
| `DATA-008` | Conditional concept/theme primary/backup routes | Concrete routes used only when the declared strategy module consumes concept evidence | Both formal clients and contracts exist; the default factory constructs the group only when `STOCK_ANALYZER_ENABLE_CONCEPTS` is explicitly enabled | `OFFLINE_VERIFIED` | Conditional live endpoint evidence is unverified |
| `DATA-009` | Manual holdings route | Local explicit-empty/missing/malformed semantics, wired into the default production factory | `ManualHoldingsFileRoute` is constructed by the default factory; explicit empty is valid and missing or malformed input fails closed | `OFFLINE_VERIFIED` | None |
| `DATA-010` | Durable route capability evidence | Versioned evidence for full contract, field semantics, full universe, post-close availability, and tested time for every network route | Latest contains five live routes including CNINFO v2 with two distinct semantic hashes; seven immutable capability versions preserve failed and superseded evidence | `LIVE_READ_VERIFIED` | None for the current required routes |
| `DATA-011` | Initial 82-session real backfill | Read-only acquisition for exactly 2026-03-12 through 2026-07-10, immutable local versions, coverage verification, resumability | Exact 82-session Tushare calendar/market versions were acquired, contract-validated, stored immutably, and made canonical | `LIVE_READ_VERIFIED` | None |

### 4.3 Formal Readiness and Strategy Integration

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `PIPE-001` | Shared payload contracts and validation | Deterministic field, null, uniqueness, date, OHLC, coverage, cutoff, unit, and history validation | `readiness.py` and focused tests pass | `OFFLINE_VERIFIED` | Production contract instances are tracked separately in `PIPE-002` |
| `PIPE-002` | Production acquisition-contract registry | Concrete `AcquisitionGroupContract` instances for every screening and target group, built by the default factory | `formal_contracts.py` builds `formal-v2` screening and target contracts used by the default factory; heterogeneous record, current-fact, legitimate-null, uniqueness, and history tests pass | `OFFLINE_VERIFIED` | None |
| `PIPE-003` | Atomic primary/backup acquisition | Rejected primary discarded; backup starts from the request only; identical contract; no value comparison | `AtomicGroupAcquirer` and offline tests pass | `OFFLINE_VERIFIED` | Cannot advance provider routes until `DATA-001` through `DATA-010` exist |
| `PIPE-004` | Immutable evidence, canonical versions, resume, reconciliation | Exclusive immutable versions, atomic pointers, point-in-time reads, durable backup reconciliation | Live calendar/market and event capability versions are immutable; formal run `formal-2026-07-10` froze its input set, group versions, 14 evidence hashes, and 14 report artifact hashes without rewriting prior versions | `PRODUCTION_WRITE_VERIFIED` | None |
| `PIPE-005` | READY_TO_SCREEN, frozen candidate set, READY_TO_ANALYZE | Analysis and LLM unreachable before complete gates; target failure cannot replace candidates | The real run preserved its frozen candidate set across the initial CNINFO coverage block, then reached `READY_TO_ANALYZE` only after all target contracts passed | `PRODUCTION_WRITE_VERIFIED` | None |
| `PIPE-006` | Default production dependency factory | `build_production_formal_dependencies()` returns complete real dependencies without a high-level monkeypatch | The unpatched factory assembled the live clients, contracts, callbacks, evidence store, Supabase ledger, renderer, and verifier for the successful real run | `PRODUCTION_WRITE_VERIFIED` | None |
| `PIPE-007` | Production screening callback | Converts complete formal screening payloads into the existing deterministic full-market candidate process | `screen_formal_market()` materializes formal inputs, computes full-universe cross-sectional features, and freezes candidates; focused and default-path tests pass | `OFFLINE_VERIFIED` | None |
| `PIPE-008` | Production Strategy V2 analysis callback | Converts frozen candidates and exact target payloads into recommendations, focus updates, evidence hashes, ledger rows, and pointer payloads | The real run generated 10 daily recommendations, 10 focus states, 14 recommendation/focus evidence packages, and 84 evaluation tasks from the frozen complete input set | `PRODUCTION_WRITE_VERIFIED` | None |
| `PIPE-009` | Codex analysis adapter and boundary | Required production expression analyzes each stock independently from verified evidence, adds no facts or decisions, and is never called on blocked runs | The default factory requires `CodexExpressionClient`; it invokes `gpt-5.6-sol` with high reasoning and standard speed through the logged-in local subscription, isolates credential-bearing environment variables, and validates schema, evidence/numeric whitelists, and exact Strategy V2 decision locks | `OFFLINE_VERIFIED` | Real candidate invocation and human review remain pending |
| `STRAT-001` | Deterministic daily recommendation logic | Existing approved Strategy V2 actions, evidence, risk/reward, and score-hiding behavior | Strategy V2 unit and fixture tests pass | `OFFLINE_VERIFIED` | Formal production integration remains blocked by `PIPE-008` |
| `STRAT-002` | Focus entry and daily tracking logic | Five immediately preceding formally committed eligible days; blocked/fixture/backfill breaks the window | Focus tests pass | `OFFLINE_VERIFIED` | No real formally committed production history exists |
| `STRAT-003` | Formal focus-history loading | Active dual-marker receipts only; zero-recommendation formal days count; reconciliation cannot rewrite history | In-memory/fake-Supabase tests pass | `OFFLINE_VERIFIED` | Supabase migration/read path and real formal days are unverified |

### 4.4 Storage, Reports, and Activation

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `STORE-001` | Local wide-data warehouse | Formal real payloads and derived windows persist locally with partition, resume, and audit semantics | Live calendar/market payloads, capability versions, canonical manifests, reconciliation evidence, append-only run receipts, and the frozen formal report reference are stored without overwriting historical versions | `PRODUCTION_WRITE_VERIFIED` | None |
| `STORE-002` | Supabase formal schema | Migration creates receipt, pending batch, activation marker, narrow rows, reconciliation, views, and restricted RPC | Five migrations are applied and synchronized; 15/15 Data API table/view/RPC paths and capacity RPC passed read-back; db lint and security advisors returned zero; advisor index migration removed missing-key/index findings | `PRODUCTION_WRITE_VERIFIED` | Newly created indexes report only expected `unused_index` INFO until real workload statistics exist |
| `STORE-003` | Supabase repository formal operations | Prepare/register/activate/read only through active receipts and matching hashes | The real run activated `formal-2026-07-10`; strong read-back verified the active receipt, activation marker, pending batch, ordered decision rows, receipt hash, and rows hash | `PRODUCTION_WRITE_VERIFIED` | None |
| `STORE-004` | Formal DuckDB + Parquet restoration | Wide normalized records in actual-date Parquet; DuckDB version/file/canonical/receipt/candidate/capability catalog; production has no wide-JSON fallback; full legacy graph migrates and passes pre/post-deletion audits | Copy migration `formal-json-to-duckdb-parquet-2026-07-12` passed for all 162 objects with zero unknown/failed item. Strict audit verified 18 versions, 1,825 Parquet files, 3,097,646 rows and 116 receipt revisions; real acceptance verified the canonical market version has 82 sessions from 2026-03-12 through 2026-07-10, 431,310 equity bars, 246 index bars and 5,270 daily-basic rows. Audit: `local_archive/manifests/formal-warehouse-migration-2026-07-12.json`; pre-migration DuckDB backup retained in `local_archive/warehouse.duckdb.pre-formal-migration-2026-07-12`. Legacy JSON is still present and no deletion claim is made. | `MIGRATED_NOT_DELETED` | Integrate and health-check the production reader cutover, prove zero legacy reads, generate and re-hash the exact deletion manifest, then authorize deletion separately and pass post-delete audit/replay/full tests |
| `ACT-001` | Two-phase local/report/ledger activation | Render, verify, ledger, and pointers fail closed; retries are idempotent; prior report remains active | Existing production activation remains verified; new tests split candidate preparation from activation, require `awaiting_human_acceptance`, bind the exact candidate to receipt/evidence, narrative, artifact, ledger-row and pointer hashes, and prove activation does not reacquire or reinvoke Codex | `PRODUCTION_WRITE_VERIFIED` | REPORT-004's new real candidate has not yet received human acceptance |
| `REPORT-001` | Formal report renderer | Production formal analysis renders existing Phase 3 content only from the same ready run or a committed exact receipt | The live-data Strategy V2 output rendered the activated 2026-07-10 production report with daily recommendation and focus sections | `PRODUCTION_WRITE_VERIFIED` | None |
| `REPORT-002` | Production report verification | Reject fixture/sample, incomplete evidence, visible total score, mismatched receipt/hash, or missing artifacts | Live verification passed for 10 recommendations, 14 combined evidence packages, and 84 evaluation tasks; scanning and deployment are restricted to the exact activated artifact set | `PRODUCTION_WRITE_VERIFIED` | None |
| `REPORT-003` | Manual render gate | Reject missing, blocked, uncommitted, hash-incomplete, or input-mismatched receipts | Offline bypass tests pass and the production read path resolved only the committed activated `REPORT_GENERATED` receipt | `PRODUCTION_WRITE_VERIFIED` | None |
| `REPORT-004` | User-readable decision report | The publishable HTML presents plain-language conclusions, reasons, risks, action/position conditions, and invalidation before audit detail; constrained Codex narrative is actually rendered and cannot alter structured decisions | Existing Phase 3 design is corrected in place; offline tests prove narrative appears on home/stock pages, five-session progress is evidence-bound, six-module/internal material is collapsed, missing or inconsistent narrative fails closed, and pre/post-activation readability gates reject tampering | `BLOCKED` | Generate the real candidate, pass all automated gates, obtain explicit human readability acceptance, then activate, publish, and verify online before changing this level |

### 4.5 Operations and Publication

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `OPS-001` | Daily job orchestration | Trading-day gate, stable run ID, health checks, retry cleanup, blocked handling, verify, prepare deploy | The real run resumed the same frozen formal run after fail-closed data repair, completed analysis/activation, passed production verification, and prepared the receipt-scoped deploy artifact; a post-fix identical invocation returned `success_with_recommendations` while the formal receipt remained revision 31, proving read-only terminal reuse | `PRODUCTION_WRITE_VERIFIED` | None |
| `OPS-002` | launchd scheduling | Installed service runs 18:30, 19:00, 19:30 with correct attempts and approved runtime secret loading | User plist is installed with mode 600; `launchctl print gui/501/com.ccrt.stock-analysis-assistant.daily` shows all three calendar triggers, the Git-resolved canonical main root, no retired-worktree path, `RunAtLoad=false`, and zero unscheduled runs. The copied environment resolves `stock_analyzer`, reports, warehouse, and archive under main; health-check exited 0; the completed 2026-07-10 job returned its prior success with report, receipt, status, and deploy digests unchanged | `ACTIVATED` | None |
| `OPS-003` | Human-intervention notification | Redacted notification only for actionable terminal states | Blocked default runs produce only local redacted status and optional human notification; unit and default-path tests prove analysis/report/ledger remain unreachable | `OFFLINE_VERIFIED` | Mac notification is disabled and no approved operational smoke exists |
| `PUB-001` | Deployment artifact gate | Only activated receipt artifacts; exclude evidence, staging, logs, secrets, warehouse, and internal state | The real deploy package contains exactly 14 receipt-listed report files plus the authentication middleware; historical reports, internal state, and credential files are absent | `PRODUCTION_WRITE_VERIFIED` | None |
| `PUB-002` | Cloudflare deploy, smoke, retry, rollback | One-command first publish, online auth/date/content smoke, one retry, last-known-good rollback, redaction | The receipt-scoped package was published to `https://tl-quant-reports.pages.dev`; the integrated smoke and an independent password/date/content/redaction smoke passed, and last-known-good was saved | `ACTIVATED` | None for publication mechanics; `REPORT-004` separately blocks claiming the report product is user-ready |
| `PUB-003` | Automatic publication | First approved publish enables flag; later successful jobs publish automatically | `logs/publish/auto-publish-enabled.json` records `enabled=true` only after the successful online smoke; scheduled successful future reports may auto-publish | `ACTIVATED` | None for automation mechanics; future publication still consumes only activated receipt artifacts |
| `SAFE-001` | Broker and order operations | No broker connection, order placement, or automatic trading path | No broker/order implementation exists; designs exclude it | `NOT_APPLICABLE` | Intentionally prohibited |

## 5. System-Level Gates

The project may use the following completion statements only when every listed condition is met.

### 5.1 “Formal production program implemented and default path offline verified”

- `DATA-001` through `DATA-010`, all `PIPE-*`, `STORE-001`, `ACT-001`, all `REPORT-*`, `OPS-001`, and `OPS-003` have at least their required offline evidence; later live findings may place a combined capability row at `BLOCKED` without invalidating its recorded-response implementation evidence.
- `STORE-002` has passed its approved migration and schema read-back. `STORE-003` remains `IMPLEMENTED_UNVERIFIED` until a data-ready formal run exercises pending, activation, and active-view read-back.
- The default production factory is not monkeypatched.
- External calls are replaced only at their transport boundary with recorded responses.
- The default command path completes the July 10 complete, backup, blocked, reconciliation, focus, direct-render, and atomic-failure scenarios.
- Production-path scans find no required empty stub, unconditional not-configured failure, fixture/sample reuse, or protocol without a concrete implementation.

This implementation gate is satisfied. The authorized 2026-07-10 completion run is formally data-ready: board/industry and fundamentals use their live Tushare primary routes as explicit single-source hard dependencies for this run, while their unavailable backups remain visible in `DATA-005` and `DATA-006` and any primary failure still blocks.

### 5.2 “Formal data ready”

- Every required network route is `LIVE_READ_VERIFIED` or is an explicitly approved single-source hard dependency.
- The exact 82 official sessions are acquired and stored as immutable local evidence.
- Target-date current facts and all frozen-candidate evidence pass the formal contracts.
- No Supabase mutation, publication, scheduler activation, broker access, or order action is implied by this statement.

### 5.3 “Production run verified”

- Required Supabase rows are at `PRODUCTION_WRITE_VERIFIED`.
- One real formal run passes analysis, render, verify, narrow-ledger activation, read-back, and frozen-reference checks.
- The prior valid report remains unchanged for every injected or real failure before activation.

### 5.4 “Production automation activated”

- `OPS-002` is `ACTIVATED` after the production run is verified.
- `PUB-003` becomes `ACTIVATED` only after the separately approved first Cloudflare publish and online smoke.
- Monitoring and redacted human intervention are verified.

## 6. Documentation Lifecycle

- `README.md` is the entry point and links to this matrix and the active runbooks.
- `docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md` remains the normative formal-report behavior design, amended to use this matrix for implementation status.
- Files under `docs/superpowers/specs/` are design history unless explicitly named as active normative authority here.
- Files under `docs/superpowers/plans/` are immutable historical execution records after their execution. They never establish current production readiness.
- `docs/operations/runbook.md` and `docs/operations/cloudflare-pages.md` describe executable operations and must not claim availability above this matrix.
- The former mandatory-next-phases compatibility roadmap has been removed. Its current sequencing and safety boundaries are represented by the capability IDs and system-level gates in this file; historical plans retain their original path references only as audit history.

## 7. Remaining Production Advancement Order

Implementation, default-path offline verification, `DATA-011`, the real formal analysis, Supabase atomic activation/read-back, report verification, receipt-scoped deployment, Cloudflare online smoke, automatic publication, and launchd activation are complete. Remaining product advancement is tracked separately: `REPORT-004` must restore the approved plain-language report outcome, while `DATA-005` and `DATA-006` retain the deferred backup-source resilience gaps.

No corrective task may redesign Strategy V2 decisions, position rules, report structure, or add broker/order behavior unless a new approved design explicitly changes that boundary.
