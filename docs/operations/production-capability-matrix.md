# Production Capability Matrix

**Status:** Canonical current-state authority  
**Last verified:** 2026-07-10 through offline default-entry evidence commit `0cd98dd`
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
| `DATA-001` | Calendar and universe primary route | Concrete Tushare client using `trade_cal`, `stock_basic`, `suspend_d`, normalized status and exclusion semantics | `TushareFormalEndpointClient.fetch_calendar_universe()` and its production contract pass recorded-response validation | `OFFLINE_VERIFIED` | Requires approved live read and capability record before use with live mode |
| `DATA-002` | Calendar and universe backup route | Concrete approved SSE/SZSE/BSE route that proves calendar, listing, exchange, status, and suspension coverage | `AkshareFormalEndpointClient.fetch_calendar_universe()` uses the calendar, three exchange lists, delisting lists, and current spot coverage; recorded tests fail closed on unverified status | `OFFLINE_VERIFIED` | Requires approved live read and capability record before use with live mode |
| `DATA-003` | Market-decision primary route | Concrete Tushare route for 82 official sessions of `daily`, target-date `daily_basic`, and required index history with units and adjustment metadata | Formal Tushare client, 82-session contract, three-index coverage, unit normalization, and default-path recorded run pass | `OFFLINE_VERIFIED` | Exact 2026-03-12 through 2026-07-10 data have not been read from the live provider |
| `DATA-004` | Market-decision backup route | Complete AkShare/Eastmoney route for the same whole contract, never a partial patch | Formal AKShare client obtains full equity history, current valuation/liquidity, and required indexes; default acceptance proves whole-group restart without primary records | `OFFLINE_VERIFIED` | Live field semantics, coverage, and post-close availability are unverified |
| `DATA-005` | Board and industry primary/backup routes | Concrete industry classification, membership, history, breadth, and turnover context for candidates and active focus stocks | Both formal clients implement the group and pass the same production contract with recorded responses | `OFFLINE_VERIFIED` | Live field semantics, coverage, and post-close availability are unverified |
| `DATA-006` | Candidate company and fundamentals primary/backup routes | Concrete company profile, statements, indicators, forecast/express, principal business, announcement dates, legitimate-null rules | Both formal clients implement point-in-time profiles and financial records; production materialization and Strategy V2 integration pass recorded tests | `OFFLINE_VERIFIED` | Live null patterns, announcement timing, and full target coverage are unverified |
| `DATA-007` | Official events and hard-risk primary/backup routes | Concrete official disclosure/exchange/regulator route and complete approved backup with proven empty coverage semantics | Both formal clients emit structured event and hard-risk facts with cutoff filtering and explicit coverage; recorded empty and populated cases pass | `OFFLINE_VERIFIED` | Live empty-result coverage and publication timing are unverified |
| `DATA-008` | Conditional concept/theme primary/backup routes | Concrete routes used only when the declared strategy module consumes concept evidence | Both formal clients and contracts exist; the default factory constructs the group only when `STOCK_ANALYZER_ENABLE_CONCEPTS` is explicitly enabled | `OFFLINE_VERIFIED` | Conditional live endpoint evidence is unverified |
| `DATA-009` | Manual holdings route | Local explicit-empty/missing/malformed semantics, wired into the default production factory | `ManualHoldingsFileRoute` is constructed by the default factory; explicit empty is valid and missing or malformed input fails closed | `OFFLINE_VERIFIED` | None |
| `DATA-010` | Durable route capability evidence | Versioned evidence for full contract, field semantics, full universe, post-close availability, and tested time for every network route | `LocalCapabilityStore` validates immutable recorded/live evidence bundles; default recorded acceptance consumes them and live mode rejects recorded evidence before provider calls | `OFFLINE_VERIFIED` | Approved live evidence has not been recorded |
| `DATA-011` | Initial 82-session real backfill | Read-only acquisition for exactly 2026-03-12 through 2026-07-10, immutable local versions, coverage verification, resumability | The default production code path and contracts fetch and verify the exact 82-session window; recorded-response acceptance passes | `BLOCKED` | The separately approved real read-only acquisition and immutable evidence capture have not been executed |

### 4.3 Formal Readiness and Strategy Integration

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `PIPE-001` | Shared payload contracts and validation | Deterministic field, null, uniqueness, date, OHLC, coverage, cutoff, unit, and history validation | `readiness.py` and focused tests pass | `OFFLINE_VERIFIED` | Production contract instances are tracked separately in `PIPE-002` |
| `PIPE-002` | Production acquisition-contract registry | Concrete `AcquisitionGroupContract` instances for every screening and target group, built by the default factory | `formal_contracts.py` builds `formal-v2` screening and target contracts used by the default factory; heterogeneous record, current-fact, legitimate-null, uniqueness, and history tests pass | `OFFLINE_VERIFIED` | None |
| `PIPE-003` | Atomic primary/backup acquisition | Rejected primary discarded; backup starts from the request only; identical contract; no value comparison | `AtomicGroupAcquirer` and offline tests pass | `OFFLINE_VERIFIED` | Cannot advance provider routes until `DATA-001` through `DATA-010` exist |
| `PIPE-004` | Immutable evidence, canonical versions, resume, reconciliation | Exclusive immutable versions, atomic pointers, point-in-time reads, durable backup reconciliation | `LocalEvidenceStore` and offline tests pass | `OFFLINE_VERIFIED` | No live route has produced a real immutable group version |
| `PIPE-005` | READY_TO_SCREEN, frozen candidate set, READY_TO_ANALYZE | Analysis and LLM unreachable before complete gates; target failure cannot replace candidates | Formal coordinator and synthetic acceptance pass | `OFFLINE_VERIFIED` | Default production callbacks and contracts are absent |
| `PIPE-006` | Default production dependency factory | `build_production_formal_dependencies()` returns complete real dependencies without a high-level monkeypatch | The factory assembles concrete clients, contracts, routes, callbacks, evidence store, ledger, renderer, and verifier; the real default job entry passes recorded transport-boundary acceptance | `OFFLINE_VERIFIED` | Live capability evidence and external runtime credentials are intentionally still required for live mode |
| `PIPE-007` | Production screening callback | Converts complete formal screening payloads into the existing deterministic full-market candidate process | `screen_formal_market()` materializes formal inputs, computes full-universe cross-sectional features, and freezes candidates; focused and default-path tests pass | `OFFLINE_VERIFIED` | None |
| `PIPE-008` | Production Strategy V2 analysis callback | Converts frozen candidates and exact target payloads into recommendations, focus updates, evidence hashes, ledger rows, and pointer payloads | `analyze_formal_inputs()` binds frozen candidates and target groups to Strategy V2, exact five-day formal history, evidence hashes, and narrow rows; default-path tests pass | `OFFLINE_VERIFIED` | Real formal history remains unavailable until live and production-write gates pass |
| `PIPE-009` | LLM expression adapter and boundary | Optional production expression consumes structured analysis only, adds no facts, and is never called on blocked runs | `express_formal_analysis()` validates evidence IDs and bounded string output; factory binding is optional and blocked runs never invoke it | `OFFLINE_VERIFIED` | No live expression client is configured or invoked; deterministic analysis does not depend on it |
| `STRAT-001` | Deterministic daily recommendation logic | Existing approved Strategy V2 actions, evidence, risk/reward, and score-hiding behavior | Strategy V2 unit and fixture tests pass | `OFFLINE_VERIFIED` | Formal production integration remains blocked by `PIPE-008` |
| `STRAT-002` | Focus entry and daily tracking logic | Five immediately preceding formally committed eligible days; blocked/fixture/backfill breaks the window | Focus tests pass | `OFFLINE_VERIFIED` | No real formally committed production history exists |
| `STRAT-003` | Formal focus-history loading | Active dual-marker receipts only; zero-recommendation formal days count; reconciliation cannot rewrite history | In-memory/fake-Supabase tests pass | `OFFLINE_VERIFIED` | Supabase migration/read path and real formal days are unverified |

### 4.4 Storage, Reports, and Activation

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `STORE-001` | Local wide-data warehouse | Formal real payloads and derived windows persist locally with partition, resume, and audit semantics | Default formal acquisition writes immutable group versions, canonical manifests, receipts, candidate sets, reconciliation tasks, and frozen report references through `LocalEvidenceStore`; recorded end-to-end tests pass | `OFFLINE_VERIFIED` | No live provider payload has yet been stored |
| `STORE-002` | Supabase formal schema | Migration creates receipt, pending batch, activation marker, narrow rows, reconciliation, views, and restricted RPC | Migration SQL and static schema tests exist | `IMPLEMENTED_UNVERIFIED` | Migration application, Data API exposure/permissions, advisors, and read-back are not verified |
| `STORE-003` | Supabase repository formal operations | Prepare/register/activate/read only through active receipts and matching hashes | Fake-client repository tests pass | `IMPLEMENTED_UNVERIFIED` | No real Supabase connection or RPC verification has run |
| `ACT-001` | Two-phase local/report/ledger activation | Render, verify, ledger, and pointers fail closed; retries are idempotent; prior report remains active | The default recorded path assembles renderer, verifier, ledger, local markers, and pointer activation; six injected failure points preserve prior public consumers | `OFFLINE_VERIFIED` | Production Supabase write and read-back remain unverified |
| `REPORT-001` | Formal report renderer | Production formal analysis renders existing Phase 3 content only from the same ready run or a committed exact receipt | `render_formal_report()` binds the formal analysis payload and run evidence to the existing Phase 3 renderer; default July 10 acceptance produces the report tree | `OFFLINE_VERIFIED` | No report has been generated from live data |
| `REPORT-002` | Production report verification | Reject fixture/sample, incomplete evidence, visible total score, mismatched receipt/hash, or missing artifacts | `verify_staged_formal_report()` and default acceptance validate receipt IDs, hashes, fixture markers, secret names, and hidden score before activation | `OFFLINE_VERIFIED` | No live-data report has been verified |
| `REPORT-003` | Manual render gate | Reject missing, blocked, uncommitted, hash-incomplete, or input-mismatched receipts | Offline tests and default-entry acceptance reject direct rendering without the exact committed `REPORT_GENERATED` receipt | `OFFLINE_VERIFIED` | Production Supabase read path remains unverified |

### 4.5 Operations and Publication

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `OPS-001` | Daily job orchestration | Trading-day gate, stable run ID, health checks, retry cleanup, blocked handling, verify, prepare deploy | The real `_default_run_daily()` path reaches the complete production factory and passes July 10 complete, backup, blocked, reconciliation, focus, render-gate, and atomic-failure acceptance with recorded transports | `OFFLINE_VERIFIED` | A real daily job has not been run |
| `OPS-002` | launchd scheduling | Installed service runs 18:30, 19:00, 19:30 with correct attempts and approved runtime secret loading | Example plist exists; `launchctl` reports no loaded service | `BLOCKED` | Live read, production write, and explicit scheduler activation remain pending |
| `OPS-003` | Human-intervention notification | Redacted notification only for actionable terminal states | Blocked default runs produce only local redacted status and optional human notification; unit and default-path tests prove analysis/report/ledger remain unreachable | `OFFLINE_VERIFIED` | Mac notification is disabled and no approved operational smoke exists |
| `PUB-001` | Deployment artifact gate | Only activated receipt artifacts; exclude evidence, staging, logs, secrets, warehouse, and internal state | Artifact tests pass | `OFFLINE_VERIFIED` | No real activated formal report exists |
| `PUB-002` | Cloudflare deploy, smoke, retry, rollback | One-command first publish, online auth/date/content smoke, one retry, last-known-good rollback, redaction | Publish tests pass with fake runner/smoke | `OFFLINE_VERIFIED` | No approved real first deployment or online smoke has run |
| `PUB-003` | Automatic publication | First approved publish enables flag; later successful jobs publish automatically | Auto-publish code exists; enable flag is absent | `BLOCKED` | Requires successful formal production, first deployment approval, and online smoke |
| `SAFE-001` | Broker and order operations | No broker connection, order placement, or automatic trading path | No broker/order implementation exists; designs exclude it | `NOT_APPLICABLE` | Intentionally prohibited |

## 5. System-Level Gates

The project may use the following completion statements only when every listed condition is met.

### 5.1 “Formal production program implemented and default path offline verified”

- `DATA-001` through `DATA-010`, all `PIPE-*`, `STORE-001`, `ACT-001`, all `REPORT-*`, `OPS-001`, and `OPS-003` are `OFFLINE_VERIFIED`.
- `STORE-002` and `STORE-003` contain production code and static/fake-client evidence but remain `IMPLEMENTED_UNVERIFIED` until the separately approved Supabase environment check; this statement does not imply a production write.
- The default production factory is not monkeypatched.
- External calls are replaced only at their transport boundary with recorded responses.
- The default command path completes the July 10 complete, backup, blocked, reconciliation, focus, direct-render, and atomic-failure scenarios.
- Production-path scans find no required empty stub, unconditional not-configured failure, fixture/sample reuse, or protocol without a concrete implementation.

This gate is satisfied by the correction through `0cd98dd`. It does not satisfy any gate in sections 5.2 through 5.4.

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

Implementation and default-path offline verification in former steps 1-4 are complete. Remaining work must follow this order and may not skip a gate:

1. With separate approval, perform live read-only capability checks and the 82-session acquisition `DATA-011`.
2. With separate approval, apply and verify Supabase migration/write capabilities `STORE-002` and `STORE-003`.
3. Run and verify one real formal analysis and activation without enabling recurring automation.
4. With separate approval, activate launchd, then perform the separately approved first Cloudflare publish and enable automatic publication only after smoke passes.

No corrective task may redesign Strategy V2 decisions, position rules, report structure, or add broker/order behavior unless a new approved design explicitly changes that boundary.
