# Production Capability Matrix

**Status:** Canonical current-state authority  
**Last verified:** 2026-07-10 at commit `8e252ad48296dcc4375c10cacb5b81ff30663709`  
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
| `GOV-002` | Requirement-to-code traceability | Every normative requirement maps to a production symbol, default-path test, live/activation evidence, and corrective task | Prior plans map mostly to unit tests and filenames, not to default production construction | `NOT_IMPLEMENTED` | Corrective plan must consume capability IDs and exact acceptance evidence |
| `GOV-003` | Non-ambiguous completion reporting | Reports state separate implementation, offline, live-read, production-write, and activation levels | Active design, README, runbooks, and this matrix now use separate levels; historical handoffs did not | `IMPLEMENTED_UNVERIFIED` | Corrective plan must add review and handoff checks that reject unqualified phase-wide “complete” claims |

### 4.2 Formal Acquisition Routes

| ID | Capability | Required production implementation | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `DATA-001` | Calendar and universe primary route | Concrete Tushare client using `trade_cal`, `stock_basic`, `suspend_d`, normalized status and exclusion semantics | Only `FormalEndpointClient` protocol and generic route wrapper exist | `NOT_IMPLEMENTED` | Concrete formal primary client and production contract are absent |
| `DATA-002` | Calendar and universe backup route | Concrete approved SSE/SZSE/BSE route that proves calendar, listing, exchange, status, and suspension coverage | Route ID exists; no production client exists | `NOT_IMPLEMENTED` | Exact endpoints, parser, recorded responses, and capability evidence are absent |
| `DATA-003` | Market-decision primary route | Concrete Tushare route for 82 official sessions of `daily`, target-date `daily_basic`, and required index history with units and adjustment metadata | Legacy `TushareProvider` loads daily/daily_basic, but no formal route client or complete formal contract exists | `NOT_IMPLEMENTED` | Formal client, index path, 82-session production factory, and coverage contract are absent |
| `DATA-004` | Market-decision backup route | Complete AkShare/Eastmoney route for the same whole contract, never a partial patch | Route ID and generic wrapper exist only | `NOT_IMPLEMENTED` | Concrete client, valuation/liquidity/index adapters, parser, and capability evidence are absent |
| `DATA-005` | Board and industry primary/backup routes | Concrete industry classification, membership, history, breadth, and turnover context for candidates and active focus stocks | Registry strings and protocol method exist; no production clients exist | `NOT_IMPLEMENTED` | Exact endpoints, calculations, contracts, and recorded capability cases are absent |
| `DATA-006` | Candidate company and fundamentals primary/backup routes | Concrete company profile, statements, indicators, forecast/express, principal business, announcement dates, legitimate-null rules | Legacy Strategy V2 provider methods return empty lists; formal production clients do not exist | `NOT_IMPLEMENTED` | Both complete routes, point-in-time filters, and normalized production models are absent |
| `DATA-007` | Official events and hard-risk primary/backup routes | Concrete official disclosure/exchange/regulator route and complete approved backup with proven empty coverage semantics | Generic protocol and synthetic empty-event test exist | `NOT_IMPLEMENTED` | No official or backup production client, publication-time parser, or full target coverage proof |
| `DATA-008` | Conditional concept/theme primary/backup routes | Concrete routes used only when the declared strategy module consumes concept evidence | Route IDs and protocol method exist | `NOT_IMPLEMENTED` | No production client or explicit runtime rule proving when the group is required |
| `DATA-009` | Manual holdings route | Local explicit-empty/missing/malformed semantics, wired into the default production factory | `ManualHoldingsFileRoute` and focused tests exist | `IMPLEMENTED_UNVERIFIED` | Default production dependency factory never constructs or consumes it |
| `DATA-010` | Durable route capability evidence | Versioned evidence for full contract, field semantics, full universe, post-close availability, and tested time for every network route | Pydantic model and synthetic test factories exist | `NOT_IMPLEMENTED` | No production capability record format, loader, recording workflow, or approved evidence |
| `DATA-011` | Initial 82-session real backfill | Read-only acquisition for exactly 2026-03-12 through 2026-07-10, immutable local versions, coverage verification, resumability | Constant and synthetic acceptance provide 82 dates | `NOT_IMPLEMENTED` | No production backfill command or live route capable of producing the full groups |

### 4.3 Formal Readiness and Strategy Integration

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `PIPE-001` | Shared payload contracts and validation | Deterministic field, null, uniqueness, date, OHLC, coverage, cutoff, unit, and history validation | `readiness.py` and focused tests pass | `OFFLINE_VERIFIED` | Production contract instances are tracked separately in `PIPE-002` |
| `PIPE-002` | Production acquisition-contract registry | Concrete `AcquisitionGroupContract` instances for every screening and target group, built by the default factory | No production code constructs `AcquisitionGroupContract` | `NOT_IMPLEMENTED` | Required fields, null semantics, current facts, history, and runtime coverage are not assembled |
| `PIPE-003` | Atomic primary/backup acquisition | Rejected primary discarded; backup starts from the request only; identical contract; no value comparison | `AtomicGroupAcquirer` and offline tests pass | `OFFLINE_VERIFIED` | Cannot advance provider routes until `DATA-001` through `DATA-010` exist |
| `PIPE-004` | Immutable evidence, canonical versions, resume, reconciliation | Exclusive immutable versions, atomic pointers, point-in-time reads, durable backup reconciliation | `LocalEvidenceStore` and offline tests pass | `OFFLINE_VERIFIED` | No live route has produced a real immutable group version |
| `PIPE-005` | READY_TO_SCREEN, frozen candidate set, READY_TO_ANALYZE | Analysis and LLM unreachable before complete gates; target failure cannot replace candidates | Formal coordinator and synthetic acceptance pass | `OFFLINE_VERIFIED` | Default production callbacks and contracts are absent |
| `PIPE-006` | Default production dependency factory | `build_production_formal_dependencies()` returns complete real dependencies without a high-level monkeypatch | Function unconditionally raises `HumanInterventionJobError` | `NOT_IMPLEMENTED` | Concrete clients, contracts, callbacks, capability loader, store, and ledger assembly are absent |
| `PIPE-007` | Production screening callback | Converts complete formal screening payloads into the existing deterministic full-market candidate process | Only injected test callbacks exist | `NOT_IMPLEMENTED` | No production `screen` adapter or model conversion exists |
| `PIPE-008` | Production Strategy V2 analysis callback | Converts frozen candidates and exact target payloads into recommendations, focus updates, evidence hashes, ledger rows, and pointer payloads | Strategy functions exist; only injected formal `analyze` callbacks exist | `NOT_IMPLEMENTED` | No production adapter binds formal payloads to Strategy V2 and focus history |
| `PIPE-009` | LLM expression adapter and boundary | Optional production expression consumes structured analysis only, adds no facts, and is never called on blocked runs | Formal coordinator supports an injected optional callback; no production adapter exists | `NOT_IMPLEMENTED` | Client selection, structured prompt/input contract, output validation, and default binding are absent |
| `STRAT-001` | Deterministic daily recommendation logic | Existing approved Strategy V2 actions, evidence, risk/reward, and score-hiding behavior | Strategy V2 unit and fixture tests pass | `OFFLINE_VERIFIED` | Formal production integration remains blocked by `PIPE-008` |
| `STRAT-002` | Focus entry and daily tracking logic | Five immediately preceding formally committed eligible days; blocked/fixture/backfill breaks the window | Focus tests pass | `OFFLINE_VERIFIED` | No real formally committed production history exists |
| `STRAT-003` | Formal focus-history loading | Active dual-marker receipts only; zero-recommendation formal days count; reconciliation cannot rewrite history | In-memory/fake-Supabase tests pass | `OFFLINE_VERIFIED` | Supabase migration/read path and real formal days are unverified |

### 4.4 Storage, Reports, and Activation

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `STORE-001` | Local wide-data warehouse | Formal real payloads and derived windows persist locally with partition, resume, and audit semantics | Legacy local warehouse and formal evidence store exist separately | `IMPLEMENTED_UNVERIFIED` | Default formal path does not write real provider data through the intended warehouse boundary |
| `STORE-002` | Supabase formal schema | Migration creates receipt, pending batch, activation marker, narrow rows, reconciliation, views, and restricted RPC | Migration SQL and static schema tests exist | `IMPLEMENTED_UNVERIFIED` | Migration application, Data API exposure/permissions, advisors, and read-back are not verified |
| `STORE-003` | Supabase repository formal operations | Prepare/register/activate/read only through active receipts and matching hashes | Fake-client repository tests pass | `IMPLEMENTED_UNVERIFIED` | No real Supabase connection or RPC verification has run |
| `ACT-001` | Two-phase local/report/ledger activation | Render, verify, ledger, and pointers fail closed; retries are idempotent; prior report remains active | In-memory activation and injected-failure tests pass | `OFFLINE_VERIFIED` | Default production renderer, verifier, and real ledger are not assembled together |
| `REPORT-001` | Formal report renderer | Production formal analysis renders existing Phase 3 content only from the same ready run or a committed exact receipt | Existing renderer and receipt gate tests exist | `IMPLEMENTED_UNVERIFIED` | No default formal render callback binds analysis output to the renderer |
| `REPORT-002` | Production report verification | Reject fixture/sample, incomplete evidence, visible total score, mismatched receipt/hash, or missing artifacts | Verification unit tests pass | `OFFLINE_VERIFIED` | No default recorded-response formal run has produced and verified the complete report tree |
| `REPORT-003` | Manual render gate | Reject missing, blocked, uncommitted, hash-incomplete, or input-mismatched receipts | Offline tests pass | `OFFLINE_VERIFIED` | Real active receipt and repository path remain unverified |

### 4.5 Operations and Publication

| ID | Capability | Required evidence | Current evidence | Level | Blocking gap |
| --- | --- | --- | --- | --- | --- |
| `OPS-001` | Daily job orchestration | Trading-day gate, stable run ID, health checks, retry cleanup, blocked handling, verify, prepare deploy | Unit tests pass with injected job dependencies | `IMPLEMENTED_UNVERIFIED` | Default production run stops at `PIPE-006`; no recorded default-entry acceptance exists |
| `OPS-002` | launchd scheduling | Installed service runs 18:30, 19:00, 19:30 with correct attempts and approved runtime secret loading | Example plist exists; `launchctl` reports no loaded service | `BLOCKED` | Production path is not offline/live ready and launchd activation is not approved |
| `OPS-003` | Human-intervention notification | Redacted notification only for actionable terminal states | Notification wrapper unit tests exist | `IMPLEMENTED_UNVERIFIED` | Runtime notification is disabled and no approved operational smoke exists |
| `PUB-001` | Deployment artifact gate | Only activated receipt artifacts; exclude evidence, staging, logs, secrets, warehouse, and internal state | Artifact tests pass | `OFFLINE_VERIFIED` | No real activated formal report exists |
| `PUB-002` | Cloudflare deploy, smoke, retry, rollback | One-command first publish, online auth/date/content smoke, one retry, last-known-good rollback, redaction | Publish tests pass with fake runner/smoke | `OFFLINE_VERIFIED` | No approved real first deployment or online smoke has run |
| `PUB-003` | Automatic publication | First approved publish enables flag; later successful jobs publish automatically | Auto-publish code exists; enable flag is absent | `BLOCKED` | Requires successful formal production, first deployment approval, and online smoke |
| `SAFE-001` | Broker and order operations | No broker connection, order placement, or automatic trading path | No broker/order implementation exists; designs exclude it | `NOT_APPLICABLE` | Intentionally prohibited |

## 5. System-Level Gates

The project may use the following completion statements only when every listed condition is met.

### 5.1 “Production program implemented”

- All required `DATA-*`, `PIPE-*`, `STORE-*`, `ACT-*`, `REPORT-*`, and `OPS-001` rows are at least `OFFLINE_VERIFIED`.
- The default production factory is not monkeypatched.
- External calls are replaced only at their transport boundary with recorded responses.
- The default command path completes the July 10 complete, backup, blocked, reconciliation, focus, direct-render, and atomic-failure scenarios.
- Production-path scans find no required empty stub, unconditional not-configured failure, fixture/sample reuse, or protocol without a concrete implementation.

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

## 7. Corrective Program Order

The detailed corrective execution plan must follow this order and may not skip a gate:

1. Close documentation authority and traceability gaps `GOV-001` through `GOV-003`.
2. Implement exact production contracts, clients, and capability-record workflow for `DATA-001` through `DATA-010` and `PIPE-002`.
3. Assemble the default production factory and real screening/analysis/expression adapters `PIPE-006` through `PIPE-009`.
4. Prove the complete default internal path offline, then advance eligible rows to `OFFLINE_VERIFIED`.
5. With separate approval, perform live read-only capability checks and the 82-session acquisition `DATA-011`.
6. With separate approval, apply and verify Supabase migration/write capabilities `STORE-002` and `STORE-003`.
7. Run and verify one real formal analysis and activation without enabling recurring automation.
8. With separate approval, activate launchd, then perform the separately approved first Cloudflare publish and enable automatic publication only after smoke passes.

No corrective task may redesign Strategy V2 decisions, position rules, report structure, or add broker/order behavior unless a new approved design explicitly changes that boundary.
