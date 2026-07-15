# V3 Knowledge Governance Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task in the current session. Do not use subagents unless the user later explicitly authorizes them. Every behavior change also requires `superpowers:test-driven-development`; completion requires `superpowers:verification-before-completion`.

**Goal:** Build a data-first, versioned and auditable A-share knowledge-governance layer that admits only high-quality knowledge executable by the existing research warehouse, without changing the data foundation, recommendation logic, report output or production behavior.

**Architecture:** Add a new isolated package under `stock_analyzer.knowledge` containing strict Pydantic models, a versioned YAML registry, a read-only warehouse capability inspector, an admission gate, a scene selector and a four-state usage audit. The new package reads the existing DuckDB/Parquet manifests and schemas but never writes them. The legacy Strategy V2 knowledge map remains untouched and quarantined; the new registry is not connected to recommendations, narratives, reports, schedules or deployment in this plan.

**Tech Stack:** Python 3.12, Pydantic 2.7+, PyYAML 6+, DuckDB 1.0+, PyArrow 16+, pytest 9.x, existing research DuckDB/Parquet warehouse.

**Approved Design:** [`docs/superpowers/specs/2026-07-15-v3-knowledge-governance-refresh-design.md`](../specs/2026-07-15-v3-knowledge-governance-refresh-design.md)

**Approved Baseline:** local `main` commit `e5e7356` (`docs: approve data-first knowledge governance design`).

## Global Constraints

- Work directly on the current local `main`; do not create a branch or worktree.
- Do not read or reuse the abandoned first/second design, old Phase 3 design documents, or the discarded report-readability branch/worktree.
- Do not modify any file under `src/stock_analyzer/data/`, `src/stock_analyzer/storage/`, `src/stock_analyzer/analysis/`, `src/stock_analyzer/ops/`, `src/stock_analyzer/reports/`, `ops/`, `supabase/`, `functions/`, or `local_warehouse/`.
- Do not modify `src/stock_analyzer/knowledge/strategy_v2_map.yaml`, `src/stock_analyzer/knowledge/rules.seed.yaml`, `src/stock_analyzer/knowledge/usage_policy.py`, or `src/stock_analyzer/analysis/knowledge_map.py`.
- Do not implement scoring, ranking, recommendation, position sizing, formal reports, activation, deployment, publication or automatic trading.
- Do not add a crawler, generic web-ingestion framework, scheduled knowledge download, or new continuous industry data source.
- Do not add a Python dependency.
- Store source metadata, a concise original summary and source location only; do not copy or commit copyrighted paper full text.
- Third-party black-box “main-force inflow,” “institutional buying” and similar vendor labels are not admissible facts or knowledge sources.
- The existing research data foundation and derived-feature formulas are read-only dependencies. Knowledge work may inspect their manifests and Parquet schemas only.
- Search, reading, source comparison and structured entry preparation are Codex responsibilities. The user is not asked to screen papers or choose retrieval technology.
- The active registry admits only knowledge whose core method is structurally executable with the existing warehouse. A theory with structurally missing core data stays outside the active registry.
- Runtime `limited` and `data_insufficient_or_not_applicable` states are only for entity/date/disclosure coverage gaps, not a loophole for globally missing data.
- Empirical thresholds are never copied directly from a paper. Until local point-in-time validation is completed in a later approved analysis task, empirical research is `method_only` or `observation_only`.
- S/A/B describes source authority, not automatic weight. S policy does not prove company benefit; B knowledge cannot create a hard boundary or positive action claim.
- The target horizon stored in context is exactly 10–30 trading sessions, with 20 sessions as the center checkpoint. This plan does not predict the 20% target.
- Any implementation need outside the file allowlist, interface names, source floor, status semantics or tests in this plan is a design change: stop, document the issue and ask the user before proceeding.

## File Responsibility Map

Only the following source and test files may be created or modified:

| File | Responsibility |
|---|---|
| `src/stock_analyzer/knowledge/governance_models.py` | Enums and immutable Pydantic contracts for sources, entries, requirements, context, migration and use records |
| `src/stock_analyzer/knowledge/registry.py` | Load YAML, validate references, source grades, version ranges and active-entry invariants |
| `src/stock_analyzer/knowledge/capability.py` | Read DuckDB manifests and Parquet schemas without writing; assess data requirements |
| `src/stock_analyzer/knowledge/selector.py` | Select only date-valid, scene-relevant and data-admitted knowledge; no scoring |
| `src/stock_analyzer/knowledge/use_audit.py` | Record the four execution states, conflicts and four-layer fact-to-expression trace |
| `src/stock_analyzer/knowledge/governance_audit.py` | Produce deterministic internal audit JSON and a process exit code; no stock report |
| `src/stock_analyzer/knowledge/research_registry.yaml` | Active and historical knowledge sources/entries that passed schema and data-first admission |
| `src/stock_analyzer/knowledge/strategy_v2_migration.yaml` | One-to-one disposition record for all 74 legacy IDs; never used as analysis knowledge |
| `src/stock_analyzer/knowledge/__init__.py` | Export the new governance interfaces without changing legacy exports |
| `tests/test_knowledge_governance_models.py` | Model, conditional source-grade and invariant tests |
| `tests/test_knowledge_registry.py` | YAML loading, reference, version and source-quality tests |
| `tests/test_knowledge_capability.py` | Read-only capability inspection and admission tests |
| `tests/test_knowledge_selector.py` | Scene/date/horizon/opportunity/data filtering tests |
| `tests/test_knowledge_use_audit.py` | Four-state audit, conflict and wording-boundary tests |
| `tests/test_knowledge_migration.py` | Exact 74-ID migration and active-registry cross-reference tests |
| `tests/test_knowledge_governance_acceptance.py` | End-to-end governance scenarios and scope locks |
| `docs/operations/v3-knowledge-governance-acceptance.md` | Final internal verification evidence; explicitly states “not activated” |

No other file may change without a design amendment approved by the user.

## Frozen Public Interfaces

The following names and signatures are fixed for implementation. Changing them requires a plan amendment:

- `load_knowledge_registry(path: Path) -> KnowledgeRegistry`
- `load_legacy_migration(path: Path) -> LegacyMigrationRegistry`
- `inspect_warehouse_capabilities(warehouse_root: Path, analysis_date: date) -> CapabilitySnapshot`
- `assess_entry_capability(entry: KnowledgeEntry, snapshot: CapabilitySnapshot) -> CapabilityAssessment`
- `select_knowledge(registry: KnowledgeRegistry, context: AnalysisContext, capabilities: CapabilitySnapshot) -> tuple[KnowledgeSelection, ...]`
- `audit_knowledge_governance(registry: KnowledgeRegistry, migration: LegacyMigrationRegistry, legacy_ids: set[str], capabilities: CapabilitySnapshot) -> GovernanceAuditReport`

The fixed enums are:

```python
class SourceGrade(str, Enum):
    S = "S"
    A = "A"
    B = "B"

class KnowledgeEffect(str, Enum):
    HARD_BOUNDARY = "hard_boundary"
    ANALYSIS_EVIDENCE = "analysis_evidence"
    OBSERVATION_ONLY = "observation_only"
    METHOD_ONLY = "method_only"

class AnalysisModule(str, Enum):
    MARKET_ENVIRONMENT = "market_environment"
    SECTOR_THEME = "sector_theme"
    COMPANY_BUSINESS = "company_business"
    FUNDAMENTALS = "fundamentals"
    VALUATION = "valuation"
    PRICE_TRADING = "price_trading"
    EVENTS = "events"
    RISK = "risk"
    PORTFOLIO = "portfolio"
    TARGET_CONDITIONS = "target_conditions"

class OpportunityType(str, Enum):
    GENERAL = "general"
    INDUSTRY_TREND = "industry_trend"
    EARNINGS_RERATING = "earnings_rerating"
    CYCLE_INFLECTION = "cycle_inflection"
    COMPANY_EVENT = "company_event"
    TURNAROUND = "turnaround"

class KnowledgeTopic(str, Enum):
    TRADER_IDENTITY_BOUNDARY = "trader_identity_boundary"
    EXCHANGE_CONSTRAINTS = "exchange_constraints"
    BUSINESS_TRANSMISSION = "business_transmission"
    OFFICIAL_PUBLICATION_TIMING = "official_publication_timing"
    DELISTING_RISK = "delisting_risk"
    SHARE_REDUCTION = "share_reduction"
    BUYBACK_STAGE = "buyback_stage"
    RESTRUCTURING_STAGE = "restructuring_stage"
    MARKET_PRICE_PERSISTENCE = "market_price_persistence"
    SECTOR_PRICE_PERSISTENCE = "sector_price_persistence"
    VALUATION_METHOD = "valuation_method"
    EVENT_PRICE_REACTION = "event_price_reaction"
    EARNINGS_DRIFT = "earnings_drift"
    FINANCIAL_TURNAROUND = "financial_turnaround"
    CYCLE_SUPPLY_DEMAND = "cycle_supply_demand"

class KnowledgeUseStatus(str, Enum):
    CORRECT = "correct_execution"
    LIMITED = "limited_execution"
    INSUFFICIENT = "insufficient_execution"
    DATA_INSUFFICIENT_OR_NOT_APPLICABLE = "data_insufficient_or_not_applicable"

class CapabilityStatus(str, Enum):
    COMPLETE = "complete"
    LIMITED = "limited"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"

class MigrationAction(str, Enum):
    RETAIN = "retain"
    UPDATE = "update"
    REVALIDATE = "revalidate"
    DEFER = "defer"
    RETIRE = "retire"
```

`SourceKind` is limited to these values:

```python
class SourceKind(str, Enum):
    OFFICIAL_RULE = "official_rule"
    OFFICIAL_DISCLOSURE = "official_disclosure"
    OFFICIAL_RESEARCH = "official_research"
    PEER_REVIEWED_PAPER = "peer_reviewed_paper"
    WORKING_PAPER = "working_paper"
    INDUSTRY_RESEARCH = "industry_research"
```

The official-host allowlist is exact and may not be broadened during implementation:

```python
OFFICIAL_HOSTS = frozenset(
    {
        "www.csrc.gov.cn",
        "neris.csrc.gov.cn",
        "www.sse.com.cn",
        "www.szse.cn",
        "docs.static.szse.cn",
        "www.bse.cn",
        "www.gov.cn",
        "big5.www.gov.cn",
        "www.miit.gov.cn",
    }
)
```

Knowledge conflicts are stored in `conflicts_with: tuple[str, ...]`; `conflicted` is not a use status.

## Requirements Traceability Matrix

| ID | Approved requirement | Implemented by | Proved by |
|---|---|---|---|
| R1 | Existing data capability comes before knowledge search | Tasks 3, 4, 7, 8 | `test_active_registry_has_no_blocked_entry` |
| R2 | Structurally unavailable knowledge is not active | Tasks 4, 7, 8 | `test_globally_missing_core_dataset_is_blocked_not_limited` |
| R3 | S/A/B source rules are strict | Tasks 1, 2 | `test_s_official_rule_requires_effective_date_and_official_host`, `test_b_source_cannot_create_hard_boundary` |
| R4 | Current official-rule versions and historical ranges are explicit | Tasks 2, 7 | `test_current_rule_versions_cannot_overlap`, `test_selector_uses_rule_version_valid_on_analysis_date` |
| R5 | Only relevant knowledge is selected | Task 5 | `test_selector_filters_by_module_opportunity_topic_and_10_30_session_horizon` |
| R6 | Do not mechanically iterate 74 items | Tasks 5, 9 | `test_selector_excludes_blocked_knowledge_instead_of_returning_all_entries` |
| R7 | Four execution states have distinct meanings | Task 6 | the four status-specific `test_*_execution_*` tests |
| R8 | Knowledge conflicts are separate from execution status | Task 6 | `test_conflict_can_coexist_with_correct_execution` |
| R9 | Raw fact, local observation, model judgment and user expression stay separate | Task 6 | `test_all_four_trace_layers_are_separate_required_fields` |
| R10 | No trader-identity inference without proper data | Task 6 | `test_daily_or_minute_facts_cannot_claim_trader_identity` |
| R11 | `sector-hotspot-v2` is evidence, not a final rank | Tasks 7, 8 | acceptance scenario `test_sector_hotspot_remains_evidence_not_ranking` |
| R12 | 74 legacy entries each have an explicit disposition | Task 9 | `test_migration_ids_equal_all_legacy_ids_exactly_once` |
| R13 | No crawler or continuous data expansion | Global guard, Task 10 | `test_governance_package_has_no_network_or_ingestion_dependency` plus changed-path audit |
| R14 | No data-foundation change | Global guard, Tasks 3, 10 | `test_inspection_does_not_change_duckdb_sha256` plus final checksum |
| R15 | No scoring/report/activation/deployment | Global guard, Task 10 | `test_governance_is_not_imported_by_production_paths` |
| R16 | Knowledge sources are read and checked by Codex | Tasks 7, 8 | `test_every_active_source_has_complete_review_metadata` |
| R17 | Empirical rules require local validation before threshold use | Tasks 1, 8 | `test_empirical_threshold_requires_completed_local_validation` |

## Scientific Review Gates

These gates are mandatory. A failed gate stops execution; it is not waived to “keep moving.”

### Gate G0 — Baseline and no-write fingerprint

Before Task 1:

```bash
git status --short
git rev-parse HEAD
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_rules.py \
  tests/test_knowledge_usage_policy.py \
  tests/test_strategy_v2_knowledge_map.py \
  tests/test_research_health.py -q
shasum -a 256 local_warehouse/research.duckdb \
  > /private/tmp/v3-knowledge-governance-warehouse.before.sha256
```

Expected:

- HEAD starts from `e5e7356` plus only the approved plan commit;
- relevant baseline tests report `14 passed` or more if tests were added intentionally;
- the warehouse checksum file is created outside the repository.

### Gate G1 — Contract review

After Task 2, compare every model field and enum with the Frozen Public Interfaces section. Run the model and registry tests together. Do not continue if a required field was renamed, weakened to optional, or accepted with `extra="ignore"`.

### Gate G2 — Data-first/read-only proof

After Task 4:

- the capability inspector must open DuckDB with `read_only=True`;
- it may call `pyarrow.parquet.read_schema`, never `pandas.read_parquet` or `ResearchWarehouse.read_current`;
- all active entries must assess as `complete` against the selected real warehouse date;
- the SHA-256 of `local_warehouse/research.duckdb` must still match G0.

### Gate G3 — Source provenance review

After Tasks 7 and 8, every active source is reviewed against its original page or paper, not a search snippet. The registry must record `last_verified_on: 2026-07-15`, exact URL/DOI, issuer/authors, publication date, effective range or sample period, method, limitations, allowed uses and forbidden uses. Any source that cannot be opened or whose version cannot be resolved stays out of the active registry.

### Gate G4 — Legacy migration completeness

After Task 9, the set of migration IDs must equal the set of 74 IDs in `strategy_v2_map.yaml`, with no duplicate and no missing ID. `retain`, `update` and `revalidate` records must resolve to an admitted new entry. `defer` and `retire` records must not resolve to an active entry.

### Gate G5 — Scenario review

Task 10 must run six fixed scenarios: official hard boundary, market environment, sector hotspot, company-business transmission, earnings/event method and unavailable cycle data. Expected selected knowledge IDs and expected use statuses are asserted exactly; no ranking or recommendation is produced.

### Gate G6 — Fresh final verification

Run targeted tests, then the entire suite. Check changed paths against the allowlist, scan for placeholders, scan for forbidden architecture imports and verify the warehouse checksum again. Record exact outputs in the acceptance document.

### Gate G7 — User acceptance

Stop after committing the verified implementation and acceptance evidence. Do not connect the registry to Strategy V2, future V3 analysis, formal reports or schedules until the user reviews the result and explicitly approves the next design stage.

---

### Task 1: Define strict governance contracts

**Files:**

- Create: `src/stock_analyzer/knowledge/governance_models.py`
- Create: `tests/test_knowledge_governance_models.py`

**Interfaces:**

- Consumes: `ResearchDatasetId` from `stock_analyzer.data.research_contracts` only as an enum; it does not modify data contracts.
- Produces: all frozen enums plus `SourceRecord`, `DataRequirement`, `LocalValidation`, `KnowledgeEntry`, `KnowledgeRegistry`, `AnalysisContext`, `KnowledgeUseRecord`, `LegacyMigrationRecord` and audit result models.

- [ ] **Step 1: Write failing source-grade and knowledge-entry tests**

Create tests with fixed constructors:

```python
from datetime import date

import pytest
from pydantic import ValidationError

from stock_analyzer.knowledge.governance_models import (
    DataRequirement,
    KnowledgeEffect,
    KnowledgeEntry,
    SourceGrade,
    SourceKind,
    SourceRecord,
)


def valid_s_source() -> SourceRecord:
    return SourceRecord(
        source_id="official-program-trading",
        grade=SourceGrade.S,
        kind=SourceKind.OFFICIAL_RULE,
        title="证券市场程序化交易管理规定（试行）",
        publisher="中国证券监督管理委员会",
        url="https://www.csrc.gov.cn/csrc/c100028/c7480577/content.shtml",
        publication_date=date(2024, 5, 15),
        effective_from=date(2024, 10, 8),
        last_verified_on=date(2026, 7, 15),
        jurisdiction="中国大陆",
        market_scope=("A股",),
        method_summary="规定程序化交易报告、监测和风险管理边界。",
        limitations=("规则不能识别具体成交账户身份。",),
    )


def test_s_official_rule_requires_effective_date_and_official_host():
    payload = valid_s_source().model_dump()
    payload["effective_from"] = None
    with pytest.raises(ValidationError, match="effective_from"):
        SourceRecord.model_validate(payload)
    payload = valid_s_source().model_dump()
    payload["url"] = "https://example.com/repost"
    with pytest.raises(ValidationError, match="official host"):
        SourceRecord.model_validate(payload)


def test_b_source_cannot_create_hard_boundary():
    with pytest.raises(ValidationError, match="B source"):
        KnowledgeEntry(
            knowledge_id="bad-b-hard-rule",
            title="invalid",
            primary_source_id="working-paper",
            source_grade=SourceGrade.B,
            effect=KnowledgeEffect.HARD_BOUNDARY,
            modules=("risk",),
            opportunity_types=("general",),
            horizon_min_sessions=10,
            horizon_center_sessions=20,
            horizon_max_sessions=30,
            claim_summary="invalid",
            allowed_uses=("invalid",),
            forbidden_uses=("none",),
            prerequisites=("official fact",),
            counter_evidence=("official contradiction",),
            data_requirements=(
                DataRequirement(
                    kind="fact",
                    name="announcement",
                    required_fields=("announcement_id", "available_at"),
                ),
            ),
            local_validation={"status": "not_required", "reason": "invalid"},
        )
```

Also implement `test_empirical_threshold_requires_completed_local_validation` with one complete A-grade fixture using `equity_daily` and `stock_trading_context`. Set `effect="analysis_evidence"` and `local_validation.status="required_before_threshold"`; assert `KnowledgeEntry.model_validate` raises `ValidationError` containing `local validation`. The fixture must include authors, sample dates, method, limitations and every required `KnowledgeEntry` field so no unrelated validation error can satisfy the test.

- [ ] **Step 2: Run the tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_governance_models.py -q
```

Expected: collection fails because `governance_models.py` does not exist.

- [ ] **Step 3: Implement the exact contracts**

Use `ConfigDict(extra="forbid", frozen=True)` on every model. Define these required fields:

```python
class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    grade: SourceGrade
    kind: SourceKind
    title: str
    publisher: str
    authors: tuple[str, ...] = ()
    journal_or_series: str | None = None
    url: HttpUrl
    doi: str | None = None
    document_number: str | None = None
    publication_date: date
    effective_from: date | None = None
    effective_to: date | None = None
    last_verified_on: date
    jurisdiction: str
    market_scope: tuple[str, ...]
    sample_start: date | None = None
    sample_end: date | None = None
    method_summary: str
    limitations: tuple[str, ...]


class DataRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["fact", "derived"]
    name: str
    required_fields: tuple[str, ...]
    minimum_rows: int = Field(default=1, ge=1)
    require_as_of: bool = True


class LocalValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["not_required", "required_before_threshold", "validated"]
    reason: str
    validation_reference: str | None = None


class KnowledgeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    knowledge_id: str
    title: str
    primary_source_id: str
    supporting_source_ids: tuple[str, ...] = ()
    source_grade: SourceGrade
    version_status: Literal["current", "superseded", "historical_only"]
    supersedes: tuple[str, ...] = ()
    effective_from: date | None = None
    effective_to: date | None = None
    effect: KnowledgeEffect
    modules: tuple[AnalysisModule, ...]
    opportunity_types: tuple[OpportunityType, ...]
    topics: tuple[KnowledgeTopic, ...]
    horizon_min_sessions: int = 10
    horizon_center_sessions: int = 20
    horizon_max_sessions: int = 30
    claim_summary: str
    allowed_uses: tuple[str, ...]
    forbidden_uses: tuple[str, ...]
    prerequisites: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    data_requirements: tuple[DataRequirement, ...]
    local_validation: LocalValidation


class AnalysisContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    analysis_date: date
    module: AnalysisModule
    opportunity_type: OpportunityType
    required_topics: tuple[KnowledgeTopic, ...]
    market: Literal["A股"] = "A股"
    board: str | None = None
    question: str
    horizon_min_sessions: int = 10
    horizon_center_sessions: int = 20
    horizon_max_sessions: int = 30


class LegacyMigrationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    legacy_knowledge_id: str
    action: MigrationAction
    target_knowledge_ids: tuple[str, ...]
    source_verified: bool
    current_a_share_applicability: Literal[
        "direct", "method_only", "unsupported"
    ]
    data_gate: Literal["complete", "blocked", "not_applicable"]
    local_validation_required: bool
    reason: str


class KnowledgeRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["v3-knowledge-governance-v1"]
    generated_on: date
    sources: tuple[SourceRecord, ...]
    entries: tuple[KnowledgeEntry, ...]
    registry_hash: str = ""


class LegacyMigrationRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["v3-legacy-migration-v1"]
    entries: tuple[LegacyMigrationRecord, ...]


class KnowledgeUseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    knowledge_id: str
    source_grade: SourceGrade
    registry_hash: str
    analysis_date: date
    status: KnowledgeUseStatus
    status_reason: str
    selection_reason: str
    api_fact_refs: tuple[str, ...]
    local_observation_refs: tuple[str, ...]
    model_judgment: str
    user_expression: str
    limitations: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    omitted_steps: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    hard_boundary_triggered: bool = False
```

Add model validators proving:

- `10 <= center <= 30` and the exact approved default is `10/20/30`;
- current official rules have `effective_from` and no past `effective_to`;
- A papers require authors, method, market/sample metadata and DOI or original publisher URL;
- B entries cannot be `hard_boundary` or `analysis_evidence`;
- `analysis_evidence` based on empirical research with `required_before_threshold` is rejected; it must remain `method_only` or `observation_only`;
- all text and tuple items are nonblank;
- `data_requirements` is never empty for an active/current entry;
- `KnowledgeUseRecord` enforces the four-state rules described in Task 6.

- [ ] **Step 4: Run model tests and confirm GREEN**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_governance_models.py -q
```

Expected: all Task 1 tests pass.

- [ ] **Step 5: Review Task 1 against Gate G1 and commit**

```bash
git diff --check
git add src/stock_analyzer/knowledge/governance_models.py \
  tests/test_knowledge_governance_models.py
git commit -m "feat: define V3 knowledge governance contracts"
```

---

### Task 2: Load and validate a versioned registry

**Files:**

- Create: `src/stock_analyzer/knowledge/registry.py`
- Create: `tests/test_knowledge_registry.py`
- Modify: `src/stock_analyzer/knowledge/__init__.py`

**Interfaces:**

- Consumes: models from Task 1 and YAML paths.
- Produces: `load_knowledge_registry`, `load_legacy_migration`, deterministic registry hashes and version/reference validation.

- [ ] **Step 1: Write failing loader and version tests**

Use temporary YAML fixtures to implement these exact tests:

- `test_registry_rejects_duplicate_ids_and_unknown_sources`: duplicate `source_id`, duplicate `knowledge_id` and an unknown `primary_source_id` each raise `ValueError` containing the offending ID.
- `test_primary_source_grade_must_equal_entry_grade`: an entry declaring A with an S primary source raises `ValueError("source grade mismatch")`.
- `test_current_rule_versions_cannot_overlap`: two current entries in the same `supersedes` chain with overlapping effective intervals raise `ValueError("overlapping effective intervals")`.
- `test_supersedes_graph_rejects_cycles`: `rule-a -> rule-b -> rule-a` raises `ValueError("version cycle")`.
- `test_registry_hash_is_order_independent_and_deterministic`: loading two YAML files with reversed source/entry order produces the same 64-character lowercase SHA-256.
- `test_loader_rejects_legacy_data_exists_and_next_action_fields`: a new entry containing either legacy field raises Pydantic `extra_forbidden`.
- `test_registry_loader_never_accesses_network`: monkeypatch `httpx.get`, `httpx.Client.send` and `socket.create_connection` to raise; loading a valid local registry still succeeds.

The last test must load a payload containing `data_exists: true` and fail because the new schema forbids legacy static data flags.

- [ ] **Step 2: Run registry tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_registry.py -q
```

Expected: import or function-not-found failure.

- [ ] **Step 3: Implement deterministic loading**

Implement:

```python
def load_knowledge_registry(path: Path) -> KnowledgeRegistry:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    registry = KnowledgeRegistry.model_validate(payload)
    _validate_source_references(registry)
    _validate_version_graph(registry)
    return registry.model_copy(update={"registry_hash": _registry_hash(registry)})
```

The canonical hash input is `model_dump(mode="json", exclude={"registry_hash"})` with sources and entries sorted by ID and JSON encoded using `sort_keys=True`, UTF-8 and compact separators. Empty YAML, non-mapping roots, duplicate IDs, unknown references, self-supersession, version cycles and overlapping current effective intervals fail closed.

Export the new interfaces from `knowledge/__init__.py` while preserving all existing exports so baseline tests remain green.

- [ ] **Step 4: Run new and legacy tests**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_registry.py \
  tests/test_knowledge_rules.py \
  tests/test_knowledge_usage_policy.py \
  tests/test_strategy_v2_knowledge_map.py -q
```

Expected: all pass; no legacy map behavior changes.

- [ ] **Step 5: Run Gate G1 field-by-field review and commit**

```bash
git diff --check
git add src/stock_analyzer/knowledge/registry.py \
  src/stock_analyzer/knowledge/__init__.py \
  tests/test_knowledge_registry.py
git commit -m "feat: validate versioned knowledge registry"
```

---

### Task 3: Inspect the existing warehouse without writing it

**Files:**

- Create: `src/stock_analyzer/knowledge/capability.py`
- Create: `tests/test_knowledge_capability.py`

**Interfaces:**

- Consumes: existing tables `research_fact_partitions` and `research_derived_partitions`, and Parquet files named by their `relative_path`.
- Produces: `CapabilitySnapshot` containing fact/derived names, fields, row counts, partition coverage, formula versions, quality status and as-of support.

- [ ] **Step 1: Write failing read-only inspector tests**

Build a temporary warehouse using existing test helpers, then monkeypatch any write-capable connector to fail during inspection. Implement these exact tests:

- `test_inspector_reads_manifests_and_parquet_schema_without_loading_rows`: monkeypatch `pandas.read_parquet` and `ResearchWarehouse.read_current` to raise; inspection still returns the expected field tuple from PyArrow schema.
- `test_inspector_opens_duckdb_read_only`: wrap `connect_research_warehouse`, capture `read_only`, and assert every captured value is `True`.
- `test_fact_capability_requires_available_at_for_as_of`: a Parquet schema without `available_at` produces `as_of_supported=False` and `structurally_ready=False`.
- `test_derived_capability_requires_exact_date_formula_and_ready_quality`: a partition on the wrong date, wrong formula or `limited` quality is not structurally ready.
- `test_missing_file_or_hash_mismatch_is_not_complete`: deleting or changing the selected Parquet file produces a failed capability with an exact limitation reason.
- `test_inspection_does_not_change_duckdb_sha256`: hash the temporary DuckDB before and after inspection and assert equality.

The row-loading guard must raise if `pandas.read_parquet` or `ResearchWarehouse.read_current` is called.

- [ ] **Step 2: Run capability tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_capability.py -q
```

Expected: module/function-not-found failure.

- [ ] **Step 3: Implement the read-only inspector**

Add these exact immutable models:

```python
class CapabilityItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["fact", "derived"]
    name: str
    fields: tuple[str, ...]
    partition_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    formula_versions: tuple[str, ...] = ()
    quality_statuses: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    as_of_supported: bool
    structurally_ready: bool


class CapabilitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    analysis_date: date
    items: tuple[CapabilityItem, ...]
    snapshot_hash: str

    def lookup(self, kind: str, name: str) -> CapabilityItem | None:
        matches = [item for item in self.items if item.kind == kind and item.name == name]
        if len(matches) > 1:
            raise ValueError(f"duplicate capability item: {kind}:{name}")
        return matches[0] if matches else None


class CapabilityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    knowledge_id: str
    status: CapabilityStatus
    missing_requirements: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
```

Implement the frozen signature and these mechanics:

```python
def inspect_warehouse_capabilities(
    warehouse_root: Path,
    analysis_date: date,
) -> CapabilitySnapshot:
    db_path = warehouse_root / "research.duckdb"
    with connect_research_warehouse(db_path, read_only=True) as connection:
        facts = connection.execute(
            "select * from research_fact_partitions order by dataset_id, partition_value"
        ).fetchdf()
        derived = connection.execute(
            """
            select * from research_derived_partitions
            where analysis_date = ?
            order by feature_set, formula_version
            """,
            [analysis_date],
        ).fetchdf()
    return _build_snapshot(warehouse_root, analysis_date, facts, derived)
```

For each selected manifest row:

- confirm the file exists under `warehouse_root` and does not escape it;
- verify its SHA-256 against `file_sha256`;
- read only `pyarrow.parquet.read_schema(path).names`;
- facts are as-of capable only if `available_at` is present;
- derived capabilities use only the exact requested `analysis_date`;
- `complete_with_declared_gaps` is structurally usable but carries limitations;
- `limited`, missing, stale or hash-mismatched data is not sufficient for active-registry admission.

Do not instantiate `ResearchWarehouse` or `DerivedFeatureStore` in production inspection because their constructors are not guaranteed read-only.

- [ ] **Step 4: Run capability and existing health tests**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_capability.py \
  tests/test_research_health.py \
  tests/test_research_as_of.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit the isolated inspector**

```bash
git diff --check
git add src/stock_analyzer/knowledge/capability.py \
  tests/test_knowledge_capability.py
git commit -m "feat: inspect research capabilities read only"
```

---

### Task 4: Enforce data-first admission and deterministic governance audit

**Files:**

- Modify: `src/stock_analyzer/knowledge/capability.py`
- Create: `src/stock_analyzer/knowledge/governance_audit.py`
- Extend: `tests/test_knowledge_capability.py`

**Interfaces:**

- Consumes: `KnowledgeEntry`, `CapabilitySnapshot`, later registry/migration objects.
- Produces: `CapabilityAssessment` and `GovernanceAuditReport`; command-line execution returns 0 only when all gates pass.

- [ ] **Step 1: Write failing admission tests**

Add exact tests:

- `test_entry_is_complete_only_when_every_required_field_is_available`: remove one required field and assert the status changes from `COMPLETE` to `BLOCKED` with the exact missing field path.
- `test_globally_missing_core_dataset_is_blocked_not_limited`: require a nonexistent `industry_inventory` capability and assert `BLOCKED`, never `LIMITED`.
- `test_declared_derived_gap_is_complete_only_when_required_fields_exist`: `complete_with_declared_gaps` remains structurally usable only when every required field exists, and its limitation text is preserved.
- `test_active_registry_audit_rejects_any_blocked_entry`: one blocked current entry makes `report.passed=False` and increments `blocked_active_entry_count` to 1.
- `test_audit_report_order_and_hash_are_deterministic`: reversing source, entry and capability input order produces identical JSON and audit hash.

An entry requiring `product_price`, `inventory` or `industry_sales` must be blocked because those names do not exist in the current capability snapshot. The test must assert that it is not silently admitted as `limited`.

- [ ] **Step 2: Run the admission tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_capability.py -q
```

Expected: failures for missing assessment/audit behavior.

- [ ] **Step 3: Implement exact assessment semantics**

Add this exact immutable report model:

```python
class GovernanceAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    analysis_date: date
    registry_hash: str
    capability_snapshot_hash: str
    source_count: int = Field(ge=0)
    active_entry_count: int = Field(ge=0)
    blocked_active_entry_count: int = Field(ge=0)
    legacy_entry_count: int = Field(ge=0)
    unmapped_legacy_entry_count: int = Field(ge=0)
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            self.blocked_active_entry_count == 0
            and self.unmapped_legacy_entry_count == 0
            and not self.errors
        )
```

```python
def assess_entry_capability(
    entry: KnowledgeEntry,
    snapshot: CapabilitySnapshot,
) -> CapabilityAssessment:
    missing: list[str] = []
    limitations: list[str] = []
    for requirement in entry.data_requirements:
        capability = snapshot.lookup(requirement.kind, requirement.name)
        if capability is None or not capability.structurally_ready:
            missing.append(f"{requirement.kind}:{requirement.name}")
            continue
        absent_fields = sorted(set(requirement.required_fields) - set(capability.fields))
        missing.extend(
            f"{requirement.kind}:{requirement.name}.{field}"
            for field in absent_fields
        )
        limitations.extend(capability.limitations)
    status = CapabilityStatus.COMPLETE if not missing else CapabilityStatus.BLOCKED
    return CapabilityAssessment(
        knowledge_id=entry.knowledge_id,
        status=status,
        missing_requirements=tuple(sorted(missing)),
        limitations=tuple(sorted(set(limitations))),
    )
```

`LIMITED` is not returned by structural admission. It is reserved for a later per-stock/per-date `KnowledgeUseRecord`. The governance audit fails if any `version_status=current` entry is not `COMPLETE`.

Implement a module entry point:

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer.knowledge.governance_audit \
  --registry src/stock_analyzer/knowledge/research_registry.yaml \
  --migration src/stock_analyzer/knowledge/strategy_v2_migration.yaml \
  --legacy-map src/stock_analyzer/knowledge/strategy_v2_map.yaml \
  --warehouse-root local_warehouse \
  --analysis-date 2026-07-14 \
  --output /private/tmp/v3-knowledge-governance-audit.json
```

The command is implemented now but will not pass until Tasks 7–9 create content. It writes only to the explicit `--output` path and never accesses the network.

- [ ] **Step 4: Run tests and Gate G2 no-write check**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_capability.py -q
shasum -a 256 -c /private/tmp/v3-knowledge-governance-warehouse.before.sha256
```

Expected: tests pass and checksum reports `local_warehouse/research.duckdb: OK`.

- [ ] **Step 5: Commit admission and audit mechanics**

```bash
git diff --check
git add src/stock_analyzer/knowledge/capability.py \
  src/stock_analyzer/knowledge/governance_audit.py \
  tests/test_knowledge_capability.py
git commit -m "feat: enforce data-first knowledge admission"
```

---

### Task 5: Select knowledge by scene without scoring

**Files:**

- Create: `src/stock_analyzer/knowledge/selector.py`
- Create: `tests/test_knowledge_selector.py`

**Interfaces:**

- Consumes: `KnowledgeRegistry`, `AnalysisContext`, `CapabilitySnapshot`.
- Produces: ordered `tuple[KnowledgeSelection, ...]` containing entry IDs, source grade, effect, selection reasons and capability assessment.

- [ ] **Step 1: Write failing fixed-scene tests**

Create a small registry fixture with entries for market, hotspot, company business, earnings, cycle and risk. Implement these exact tests:

- `test_selector_filters_by_module_opportunity_topic_and_10_30_session_horizon`: only the fixture ID matching all four dimensions is returned.
- `test_selector_uses_rule_version_valid_on_analysis_date`: dates before and after a version change select the old and new IDs respectively, never both.
- `test_selector_excludes_blocked_knowledge_instead_of_returning_all_entries`: the blocked cycle entry is absent and no fallback entries appear.
- `test_selector_returns_method_only_empirical_research_without_promoting_it`: the returned `effect` remains `METHOD_ONLY`.
- `test_selector_is_deterministic_and_has_no_score_or_weight_field`: reversed input order gives identical model dumps and neither `score` nor `weight` appears.
- `test_no_matching_knowledge_returns_empty_tuple_with_no_fallback`: an unmatched module returns exactly `()`.

The expected selection for a `company_business + industry_trend` context must be an exact ID tuple defined in the fixture, not “at least one result.”

- [ ] **Step 2: Run selector tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_selector.py -q
```

Expected: module/function-not-found failure.

- [ ] **Step 3: Implement pure filtering**

Add this exact immutable result model:

```python
class KnowledgeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    knowledge_id: str
    source_grade: SourceGrade
    effect: KnowledgeEffect
    selection_reasons: tuple[str, ...]
    capability: CapabilityAssessment
```

Apply filters in this exact order:

1. version effective on `context.analysis_date`;
2. module match;
3. opportunity type is `general` or matches the context;
4. if `required_topics` is nonempty, at least one required topic matches the entry;
5. context horizon lies inside the entry horizon;
6. capability assessment is `complete`;
7. effect remains unchanged from the registry.

Sort by `knowledge_id` only for deterministic output. Do not interpret this alphabetical order as ranking and do not expose a numeric value.

- [ ] **Step 4: Run selector tests**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_selector.py \
  tests/test_knowledge_capability.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit scene selection**

```bash
git diff --check
git add src/stock_analyzer/knowledge/selector.py \
  tests/test_knowledge_selector.py
git commit -m "feat: select scene-specific knowledge"
```

---

### Task 6: Record four-state use audits and enforce expression boundaries

**Files:**

- Create: `src/stock_analyzer/knowledge/use_audit.py`
- Create: `tests/test_knowledge_use_audit.py`

**Interfaces:**

- Consumes: selected entry, concrete fact/observation references and the existing `validate_market_microstructure_wording` guard.
- Produces: immutable `KnowledgeUseRecord`; conflicts remain an independent tuple.

- [ ] **Step 1: Write failing state-invariant tests**

Implement these exact tests:

- `test_correct_execution_cannot_have_missing_data_or_omitted_steps`: either nonempty tuple raises `ValidationError`.
- `test_limited_execution_requires_entity_or_date_specific_limitation`: an empty `limitations` tuple raises `ValidationError`.
- `test_insufficient_execution_requires_an_omitted_required_step`: an empty `omitted_steps` tuple raises `ValidationError`.
- `test_data_insufficient_or_not_applicable_requires_a_reason`: blank `status_reason` raises `ValidationError`.
- `test_conflict_can_coexist_with_correct_execution`: a correct record with `conflicts_with=("second-rule",)` validates and remains `CORRECT`.
- `test_all_four_trace_layers_are_separate_required_fields`: omitting each trace field in turn raises a missing-field error; no validator copies one layer into another.

The four trace fields are exact tuples/strings:

```python
api_fact_refs: tuple[str, ...]
local_observation_refs: tuple[str, ...]
model_judgment: str
user_expression: str
```

- [ ] **Step 2: Add failing program-trading wording regressions**

```python
@pytest.mark.parametrize(
    "text",
    [
        "上涨放量，说明机构买入。",
        "成交放大，主力没有出货。",
        "收在高位，游资正在拉升。",
    ],
)
def test_daily_or_minute_facts_cannot_claim_trader_identity(text):
    with pytest.raises(MarketMicrostructureWordingError):
        build_program_trading_use_record(
            text=text,
            analysis_date=date(2026, 7, 14),
            api_fact_refs=("equity_daily:600000.SH:2026-07-14",),
            local_observation_refs=(
                "stock_trading_context:600000.SH:2026-07-14",
            ),
        )


def test_observable_result_wording_is_allowed():
    record = build_program_trading_use_record(
        text="当日成交放大并收在日内较高位置，但现有数据不能识别交易主体。",
        analysis_date=date(2026, 7, 14),
        api_fact_refs=("equity_daily:600000.SH:2026-07-14",),
        local_observation_refs=("stock_trading_context:600000.SH:2026-07-14",),
    )
    assert record.status is KnowledgeUseStatus.CORRECT
```

- [ ] **Step 3: Run tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_use_audit.py -q
```

Expected: missing module/functions.

- [ ] **Step 4: Implement use-record builders**

Reuse the existing regex guard by import; do not copy or weaken its forbidden patterns. Do not copy its legacy status mechanically: when the new knowledge entry’s core purpose is to enforce the no-identity-inference boundary and the wording respects that boundary, record `correct_execution`. Reserve `limited_execution` for an otherwise applicable company/date analysis whose required disclosed fields are locally incomplete. `execution_insufficient` may only be created by an explicit QA review function and must include `omitted_steps`; ordinary missing data never maps to it.

The user expression validator runs after record construction and before serialization. A forbidden identity claim raises `MarketMicrostructureWordingError` and no record is returned.

- [ ] **Step 5: Run new and legacy wording tests**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_use_audit.py \
  tests/test_knowledge_usage_policy.py -q
```

Expected: all pass, including legacy protection.

- [ ] **Step 6: Commit use auditing**

```bash
git diff --check
git add src/stock_analyzer/knowledge/use_audit.py \
  tests/test_knowledge_use_audit.py
git commit -m "feat: audit governed knowledge use"
```

---

### Task 7: Register the mandatory current official sources

**Files:**

- Create: `src/stock_analyzer/knowledge/research_registry.yaml`
- Extend: `tests/test_knowledge_registry.py`
- Extend: `tests/test_knowledge_capability.py`

**Interfaces:**

- Consumes: official original documents and existing facts/derived capabilities only.
- Produces: the initial S-grade sources and entries. It does not implement the rules as recommendation logic.

- [ ] **Step 1: Add failing tests for the mandatory official source IDs**

Require these IDs exactly:

```python
MANDATORY_S_SOURCE_IDS = {
    "official-csrc-program-trading-2024",
    "official-sse-program-trading-2025",
    "official-csrc-disclosure-2025",
    "official-sse-trading-rules-2026",
    "official-szse-trading-rules-2026",
    "official-bse-trading-rules-2026",
    "official-csrc-delisting-enforcement-2024",
    "official-csrc-share-reduction-2024",
    "official-csrc-buyback-2023",
    "official-csrc-restructuring-2023",
    "official-csrc-restructuring-amendment-2025",
}
```

Tests require every source to be S grade, have an official host, publication/effective dates and `last_verified_on=2026-07-15`. Every current entry must pass data admission.

Name the real-registry capability assertion `test_active_registry_has_no_blocked_entry`; it loads `research_registry.yaml`, assesses every current entry against the deterministic capability fixture and asserts every status is `CapabilityStatus.COMPLETE`.

- [ ] **Step 2: Run tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_registry.py \
  tests/test_knowledge_capability.py -q
```

Expected: missing registry file or missing source IDs.

- [ ] **Step 3: Read and register only these original sources**

Use the following original pages as the minimum source floor:

- `https://www.csrc.gov.cn/csrc/c100028/c7480577/content.shtml`
- `https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20250612_10781696.shtml`
- `https://www.csrc.gov.cn/shanghai/c105565/c7549909/content.shtml`
- `https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml`
- `https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf`
- `https://www.bse.cn/jygl_list/200028217.html`
- `https://www.csrc.gov.cn/csrc/c100028/c7473605/content.shtml`
- `https://www.csrc.gov.cn/csrc/c101953/c7483190/content.shtml`
- `https://www.csrc.gov.cn/csrc/c100028/c7449681/content.shtml`
- `https://www.csrc.gov.cn/csrc/c101953/c7121862/content.shtml`
- `https://www.csrc.gov.cn/csrc/c101953/c7558586/content.shtml`

If any URL does not expose the current original document, do not substitute a repost. Stop the task, record the broken source and return to the user.

- [ ] **Step 4: Add official knowledge entries with exact data boundaries**

Use these required mappings:

| Knowledge ID | Effect | Modules / opportunity | Topics | Core existing capability | Allowed conclusion boundary |
|---|---|---|---|---|---|
| `src_cn_program_trading_rules_2025` | `hard_boundary` | `price_trading`, `risk` / `general` | `trader_identity_boundary` | `stock_trading_context.trader_identity_status`, `equity_daily` | describe price/turnover results; forbid institution/main-force identity |
| `src_csrc_disclosure_rules_2025` | `hard_boundary` | `company_business`, `events` / `general` | `business_transmission`, `official_publication_timing` | `announcement`, `company_profile`, `main_business` | distinguish official disclosure and its publication time; policy does not prove benefit |
| `src_cn_exchange_trading_rules_2026` | `hard_boundary` | `price_trading`, `risk` / `general` | `exchange_constraints` | `security_master`, `stock_limit`, `suspension`, `equity_daily` | apply board/date-valid trading constraints only |
| `src_cn_delisting_enforcement_2024` | `hard_boundary` | `risk` / `turnaround` | `delisting_risk` | `security_master`, `announcement`, `suspension` | risk boundary; do not infer delisting without an applicable official fact |
| `src_cn_share_reduction_rules_2024` | `observation_only` | `events`, `risk` / `company_event` | `share_reduction` | `holder_trade`, `share_float`, `announcement` | describe disclosed reduction facts and restrictions; do not infer future selling intent |
| `src_cn_buyback_rules_2023` | `observation_only` | `events` / `company_event` | `buyback_stage` | `repurchase`, `announcement` | describe plan/progress/completion separately; announcement is not completed buying |
| `src_cn_restructuring_rules_2025` | `hard_boundary` | `events`, `fundamentals` / `company_event` | `restructuring_stage` | `announcement`, `income_statement`, `balance_sheet`, `main_business` | verify stage and disclosed economics; do not treat a plan as completed earnings |

Each entry must explicitly list allowed/forbidden uses and counter-evidence. No entry says that policy, reduction, buyback or restructuring automatically predicts a price rise.

- [ ] **Step 5: Run Gate G3 source and capability checks**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_registry.py \
  tests/test_knowledge_capability.py -q
```

Expected: all official source metadata and active entries pass.

- [ ] **Step 6: Commit official knowledge content**

```bash
git diff --check
git add src/stock_analyzer/knowledge/research_registry.yaml \
  tests/test_knowledge_registry.py tests/test_knowledge_capability.py
git commit -m "data: register governed A-share official knowledge"
```

---

### Task 8: Register executable A/B research methods without importing thresholds

**Files:**

- Modify: `src/stock_analyzer/knowledge/research_registry.yaml`
- Extend: `tests/test_knowledge_registry.py`
- Extend: `tests/test_knowledge_selector.py`

**Interfaces:**

- Consumes: exact original papers listed below and the capability gate.
- Produces: A/B method entries restricted to `method_only` or `observation_only` until local time-point validation exists.

- [ ] **Step 1: Add failing mandatory research-family tests**

Require at least one admitted method for each existing-data family:

```python
MANDATORY_METHOD_FAMILIES = {
    "a_share_size_value",
    "a_share_momentum_reversal",
    "price_limit_t_plus_one",
    "factor_or_industry_momentum",
    "event_study",
    "earnings_announcement_drift",
    "news_price_reaction",
    "financial_quality_turnaround",
}
```

Use these exact knowledge IDs; do not invent aliases during implementation:

```python
MANDATORY_METHOD_IDS = {
    "src_liu_stambaugh_yuan_2019": "a_share_size_value",
    "src_cn_t1_contrarian_2024": "a_share_momentum_reversal",
    "src_cn_price_limit_momentum_2025": "price_limit_t_plus_one",
    "src_cn_factor_momentum_2023": "factor_or_industry_momentum",
    "src_moskowitz_grinblatt_1999": "factor_or_industry_momentum",
    "src_brown_warner_1985": "event_study",
    "src_cn_earnings_drift_2025": "earnings_announcement_drift",
    "src_chan_2003": "news_price_reaction",
    "src_piotroski_2000": "financial_quality_turnaround",
}
```

The tests must assert:

- no A/B entry contains a numeric buy threshold in `claim_summary` or `allowed_uses`;
- empirical entries are not `hard_boundary`;
- B entries are only `method_only` or `observation_only`;
- any overseas study says `中国A股本地时点验证前仅作方法` in its limitations;
- every entry’s required dataset/derived fields exist in the capability fixture.
- every active source passes `test_every_active_source_has_complete_review_metadata`, which checks authors/publisher, dates, market/sample, method, limitations and original locator according to grade.

- [ ] **Step 2: Run tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_registry.py \
  tests/test_knowledge_selector.py -q
```

Expected: mandatory families are missing.

- [ ] **Step 3: Read the original research and register bounded methods**

The research floor is fixed to these originals; add no lower-quality substitute:

- Size/value in China: `https://hub.hku.hk/handle/10722/273695`
- T+1 and contrarian behavior in China: `https://www.sciencedirect.com/science/article/abs/pii/S1059056024006452`
- Price limits and daily momentum in China: `https://xbbjb.cufe.edu.cn/EN/Y2025/V0/I1/59`
- Factor momentum in China: `https://www.sciencedirect.com/science/article/abs/pii/S0927539823001251`
- Industry momentum method: `https://onlinelibrary.wiley.com/doi/pdf/10.1111/0022-1082.00146`
- China earnings-announcement drift working paper: `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5493686`
- News versus no-news price reaction method: `https://www.sciencedirect.com/science/article/abs/pii/S0304405X03001466`
- Event-study method: Brown and Warner (1985), DOI `10.1016/0304-405X(85)90042-X`.
- Financial-quality/turnaround method: Piotroski (2000), `https://www.sciencedirect.com/science/article/abs/pii/S0165410100000086`.

For each paper, record authors, publication venue, DOI or original URL, exact market, sample start/end, method summary and limitations after reading the original abstract/method information. SSRN-only work is grade B unless a peer-reviewed publication is found at the same DOI/title.

- [ ] **Step 4: Map methods only to existing capabilities**

Use only these existing requirements:

| Family | Facts/derived features allowed |
|---|---|
| Size/value | `daily_basic`, `financial_indicator`, `stock_trading_context` |
| Momentum/reversal | `equity_daily`, `index_daily`, `stock_trading_context` |
| Price-limit/T+1 | `equity_daily`, `stock_limit`, `stock_trading_context` |
| Factor/industry momentum | `industry_daily`, `industry_member`, `sector_hotspot` |
| Event study | `announcement`, `equity_daily`, `index_daily` |
| Earnings drift | `earnings_forecast`, `earnings_express`, `income_statement`, `financial_indicator`, `equity_daily` |
| News reaction | `announcement`, `equity_daily`, `index_daily` |
| Financial quality/turnaround | `income_statement`, `balance_sheet`, `cash_flow`, `financial_indicator` |

Freeze entry metadata as follows:

| Knowledge ID | Effect | Modules | Opportunity types | Topics |
|---|---|---|---|---|
| `src_liu_stambaugh_yuan_2019` | `method_only` | `fundamentals`, `valuation` | `general`, `turnaround` | `valuation_method` |
| `src_cn_t1_contrarian_2024` | `method_only` | `market_environment`, `price_trading` | `general` | `market_price_persistence` |
| `src_cn_price_limit_momentum_2025` | `method_only` | `market_environment`, `price_trading` | `general` | `market_price_persistence` |
| `src_cn_factor_momentum_2023` | `method_only` | `market_environment`, `sector_theme` | `general` | `market_price_persistence`, `sector_price_persistence` |
| `src_moskowitz_grinblatt_1999` | `method_only` | `sector_theme` | `general`, `industry_trend` | `sector_price_persistence` |
| `src_brown_warner_1985` | `method_only` | `events` | `company_event`, `earnings_rerating` | `event_price_reaction` |
| `src_cn_earnings_drift_2025` | `method_only` | `events`, `fundamentals` | `earnings_rerating` | `event_price_reaction`, `earnings_drift` |
| `src_chan_2003` | `method_only` | `events` | `company_event`, `earnings_rerating` | `event_price_reaction` |
| `src_piotroski_2000` | `method_only` | `fundamentals` | `turnaround` | `financial_turnaround` |

Do not add knowledge requiring product prices, industry inventory, capacity utilization, order-book identity, account identity, analyst-consensus estimates or social-media attention because those are not structurally present in the approved warehouse.

- [ ] **Step 5: Run Gate G3 and deterministic selector tests**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_registry.py \
  tests/test_knowledge_selector.py \
  tests/test_knowledge_capability.py -q
```

Expected: all active methods are data-admitted and remain bounded methods/observations.

- [ ] **Step 6: Commit research methods**

```bash
git diff --check
git add src/stock_analyzer/knowledge/research_registry.yaml \
  tests/test_knowledge_registry.py tests/test_knowledge_selector.py
git commit -m "data: register executable A-share research methods"
```

---

### Task 9: Audit and disposition all 74 legacy knowledge IDs

**Files:**

- Create: `src/stock_analyzer/knowledge/strategy_v2_migration.yaml`
- Create: `tests/test_knowledge_migration.py`
- Extend: `src/stock_analyzer/knowledge/governance_audit.py`

**Interfaces:**

- Consumes: legacy YAML as an inventory only, not the abandoned design document.
- Produces: one `LegacyMigrationRecord` per old ID and exact cross-reference checks.

- [ ] **Step 1: Write failing exact-set migration tests**

```python
def test_migration_ids_equal_all_legacy_ids_exactly_once():
    legacy = yaml.safe_load(LEGACY_PATH.read_text(encoding="utf-8"))
    expected = {row["knowledge_id"] for row in legacy["entries"]}
    migration = load_legacy_migration(MIGRATION_PATH)
    actual = {row.legacy_knowledge_id for row in migration.entries}
    assert len(migration.entries) == len(expected) == 74
    assert actual == expected
```

Add four more exact tests:

- `test_active_migration_actions_resolve_to_admitted_new_entries`: for `retain/update/revalidate`, every target exists and its capability assessment is complete.
- `test_defer_and_retire_have_no_active_target_and_a_concrete_reason`: both actions have `target_knowledge_ids == ()` and a reason of at least 20 non-whitespace characters.
- `test_no_migration_action_requests_a_new_data_source`: serialized migration text contains neither `add_data_source` nor `future_enhancement`.
- `test_legacy_data_exists_does_not_determine_the_new_action`: use two legacy fixtures with opposite old booleans but the same new capability result and assert the new action is identical.

- [ ] **Step 2: Run migration tests and confirm RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_migration.py -q
```

Expected: migration file missing.

- [ ] **Step 3: Review each legacy ID using one fixed decision sequence**

For every old entry, answer in this order and record all answers:

1. Can its original source be identified and opened?
2. Is the source S, A or B under the approved policy?
3. Is it applicable to current A shares, or only a general/overseas method?
4. Does it serve one of the approved V3 modules or five opportunity types?
5. Does the existing warehouse contain the core data and fields?
6. Does it require local point-in-time validation before use?
7. Is its action `retain`, `update`, `revalidate`, `defer` or `retire`?
8. If active, which exact new `knowledge_id` replaces or preserves it?

The YAML record requires:

```yaml
- legacy_knowledge_id: src_example
  action: defer
  target_knowledge_ids: []
  source_verified: false
  current_a_share_applicability: unsupported
  data_gate: blocked
  local_validation_required: false
  reason: "核心数据不在现有底座，按数据优先原则不进入正式知识库。"
```

Do not use `add_data_source` or “later enhancement” as an action. `defer` means inactive and uncallable.

- [ ] **Step 4: Run Gate G4**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_migration.py \
  tests/test_knowledge_registry.py \
  tests/test_knowledge_capability.py -q
```

Expected: all 74 IDs have one defensible outcome and every active target is admitted.

- [ ] **Step 5: Commit the migration inventory**

```bash
git diff --check
git add src/stock_analyzer/knowledge/strategy_v2_migration.yaml \
  src/stock_analyzer/knowledge/governance_audit.py \
  tests/test_knowledge_migration.py
git commit -m "data: audit legacy knowledge inventory"
```

---

### Task 10: Prove end-to-end behavior without activating analysis

**Files:**

- Create: `tests/test_knowledge_governance_acceptance.py`
- Create: `docs/operations/v3-knowledge-governance-acceptance.md`
- Modify: `src/stock_analyzer/knowledge/__init__.py` only if a new public symbol from Tasks 3–6 is not yet exported

**Interfaces:**

- Consumes: final registry, migration, capability inspector, selector and use audit.
- Produces: deterministic acceptance evidence only; no stock recommendation or report.

- [ ] **Step 1: Write six failing acceptance scenarios with exact expected IDs**

The tests must use the real registry and a deterministic capability fixture:

1. **Program-trading boundary:** selects `src_cn_program_trading_rules_2025`; forbidden identity wording raises; observable wording records `correct_execution` because the expression boundary was fully enforced.
2. **Market environment:** selects only market/trading method entries relevant to 10–30 sessions; returns no score, rank or action.
3. **Sector hotspot:** selects industry-momentum/hotspot methods and asserts `sector-hotspot-v2` is described as evidence, not final ranking.
4. **Company-business transmission:** selects disclosure/company-business knowledge; a concept label without `main_business` evidence cannot become a positive claim.
5. **Earnings/event:** selects event-study and earnings methods, keeps API facts, local observations, model judgment and user expression in distinct fields.
6. **Unavailable cycle data:** a synthetic inventory/commodity-price method is blocked at admission and absent from selection.

Name the hotspot scenario `test_sector_hotspot_remains_evidence_not_ranking`.

Add two static isolation tests:

- `test_governance_package_has_no_network_or_ingestion_dependency`: parse imports under the six new governance Python modules and reject `httpx`, `requests`, `urllib`, `socket`, acquisition clients and backfill modules.
- `test_governance_is_not_imported_by_production_paths`: read the frozen production-path files listed in Global Constraints and assert they contain none of `research_registry`, `select_knowledge` or `governance_audit`.

Each test asserts one exact ordered tuple of knowledge IDs checked into the fixture. If registry content changes later, the expected tuple can change only through an approved design amendment.

The six expected tuples are frozen as follows:

```python
EXPECTED_SCENARIO_SELECTIONS = {
    "program_trading_boundary": ("src_cn_program_trading_rules_2025",),
    "market_environment": (
        "src_cn_factor_momentum_2023",
        "src_cn_price_limit_momentum_2025",
        "src_cn_t1_contrarian_2024",
    ),
    "sector_hotspot": (
        "src_cn_factor_momentum_2023",
        "src_moskowitz_grinblatt_1999",
    ),
    "company_business": ("src_csrc_disclosure_rules_2025",),
    "earnings_event": (
        "src_brown_warner_1985",
        "src_chan_2003",
        "src_cn_earnings_drift_2025",
    ),
    "unavailable_cycle_data": (),
}
```

Construct those contexts with these exact `(module, opportunity_type, required_topics)` values:

| Scenario | Context tuple |
|---|---|
| `program_trading_boundary` | `price_trading`, `general`, `("trader_identity_boundary",)` |
| `market_environment` | `market_environment`, `general`, `("market_price_persistence",)` |
| `sector_hotspot` | `sector_theme`, `industry_trend`, `("sector_price_persistence",)` |
| `company_business` | `company_business`, `industry_trend`, `("business_transmission",)` |
| `earnings_event` | `events`, `earnings_rerating`, `("event_price_reaction",)` |
| `unavailable_cycle_data` | `sector_theme`, `cycle_inflection`, `("cycle_supply_demand",)` plus a synthetic blocked inventory entry |

Do not change the expected tuples or alphabetical sort order without user approval.

- [ ] **Step 2: Run acceptance tests and confirm RED where wiring is incomplete**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_governance_acceptance.py -q
```

- [ ] **Step 3: Make only minimum export/wiring corrections**

No production caller is added. `knowledge/__init__.py` may export the new pure interfaces. Do not import the new registry from `strategy_v2.py`, `formal_narrative.py`, `pipeline.py`, `cli.py` or report code.

- [ ] **Step 4: Run the deterministic real-warehouse governance audit**

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer.knowledge.governance_audit \
  --registry src/stock_analyzer/knowledge/research_registry.yaml \
  --migration src/stock_analyzer/knowledge/strategy_v2_migration.yaml \
  --legacy-map src/stock_analyzer/knowledge/strategy_v2_map.yaml \
  --warehouse-root local_warehouse \
  --analysis-date 2026-07-14 \
  --output /private/tmp/v3-knowledge-governance-audit.json
```

Validate the JSON with these exact assertions:

```python
payload = json.loads(Path("/private/tmp/v3-knowledge-governance-audit.json").read_text())
assert payload["analysis_date"] == "2026-07-14"
assert re.fullmatch(r"[0-9a-f]{64}", payload["registry_hash"])
assert payload["source_count"] > 0
assert payload["active_entry_count"] > 0
assert payload["blocked_active_entry_count"] == 0
assert payload["legacy_entry_count"] == 74
assert payload["unmapped_legacy_entry_count"] == 0
assert payload["errors"] == []
```

Do not create an entry quota to make the positive counts larger.

- [ ] **Step 5: Perform the changed-path and architecture lock audit**

```bash
git diff --name-only e5e7356...HEAD
rg -n "research_registry|select_knowledge|governance_audit" \
  src/stock_analyzer/analysis \
  src/stock_analyzer/ops \
  src/stock_analyzer/reports \
  src/stock_analyzer/pipeline.py \
  src/stock_analyzer/cli.py
git diff -- pyproject.toml \
  src/stock_analyzer/data \
  src/stock_analyzer/storage \
  src/stock_analyzer/analysis \
  src/stock_analyzer/ops \
  src/stock_analyzer/reports \
  ops supabase functions local_warehouse
```

Expected:

- changed paths are exactly the allowlist in this plan plus this plan/design/acceptance documentation;
- `rg` returns no integration references;
- the final `git diff` is empty.

- [ ] **Step 6: Run targeted verification**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_governance_models.py \
  tests/test_knowledge_registry.py \
  tests/test_knowledge_capability.py \
  tests/test_knowledge_selector.py \
  tests/test_knowledge_use_audit.py \
  tests/test_knowledge_migration.py \
  tests/test_knowledge_governance_acceptance.py \
  tests/test_knowledge_rules.py \
  tests/test_knowledge_usage_policy.py \
  tests/test_strategy_v2_knowledge_map.py \
  tests/test_research_health.py \
  tests/test_research_as_of.py -q
```

Expected: zero failures.

- [ ] **Step 7: Run the entire test suite**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Expected: zero failures. Existing unrelated failures are not ignored; first determine whether they predate this implementation. Do not modify out-of-scope code to hide them.

- [ ] **Step 8: Verify warehouse immutability and scan for plan drift**

```bash
shasum -a 256 -c /private/tmp/v3-knowledge-governance-warehouse.before.sha256
rg -n "TODO|TBD|implement later|fill in|add appropriate|similar to" \
  src/stock_analyzer/knowledge \
  tests/test_knowledge_* \
  docs/operations/v3-knowledge-governance-acceptance.md
git diff --check
git status --short
```

Expected: warehouse checksum `OK`, no placeholders, no whitespace errors, and only intentional acceptance-document changes remain.

- [ ] **Step 9: Write the internal acceptance evidence**

`docs/operations/v3-knowledge-governance-acceptance.md` must contain:

- approved design and implementation-plan links;
- baseline and final commit IDs;
- exact targeted/full test outputs and timestamps;
- registry hash, source/entry counts and migration counts;
- exact real-warehouse audit date and JSON path;
- warehouse checksum result;
- source-grade counts and 100% source-review result;
- a table mapping R1–R17 to passing tests;
- known limitations;
- the explicit statement: `知识治理层尚未接入推荐、报告、自动任务或生产运行。`;
- the explicit next gate: user acceptance before any V3 analysis integration.

- [ ] **Step 10: Fresh self-review against the approved design**

Read the approved design from top to bottom and record any uncovered requirement in the acceptance document. Recheck all new model names against Frozen Public Interfaces. Reopen every active S/A/B source once and compare `claim_summary`, `allowed_uses`, `forbidden_uses` and `limitations` to the original. If a mismatch is found, fix the registry and rerun Steps 4–8.

- [ ] **Step 11: Commit verified acceptance evidence**

```bash
git add src/stock_analyzer/knowledge/__init__.py \
  tests/test_knowledge_governance_acceptance.py \
  docs/operations/v3-knowledge-governance-acceptance.md
git commit -m "test: verify V3 knowledge governance"
```

- [ ] **Step 12: Stop for user acceptance**

Report the final commit, test counts, audit counts, registry hash, migration completeness, warehouse immutability and known limitations. Do not begin market-environment logic, scoring, report work, activation or deployment.

## Execution Stop Conditions

Stop immediately and ask the user if any of the following occurs:

- an implementation requires changing the data/storage/analysis/report/ops layers;
- an official current rule cannot be verified from its original issuer;
- a mandatory research source cannot be tied to authors, method and sample;
- an intended active entry is blocked by the real warehouse;
- source content would require a threshold not locally validated;
- the real-warehouse checksum changes;
- the 74-ID migration set does not reconcile exactly;
- the full test suite fails for a change introduced by this work;
- passing the tests would require weakening a global constraint.

## Completion Definition

This implementation is complete only when all of the following are simultaneously true:

1. All Tasks 1–10 are committed in small, reviewable commits.
2. R1–R17 each map to a passing test or explicit audit evidence.
3. Every active entry has an original S/A/B source and passes the real data capability gate.
4. No structurally unavailable method is active.
5. All 74 old IDs have exactly one migration outcome.
6. The four usage states and conflict field behave exactly as designed.
7. Program-trading wording boundaries pass regression tests.
8. Targeted and full test suites have zero failures.
9. The research warehouse checksum is unchanged.
10. No production path imports or calls the new governance layer.
11. The acceptance document states that nothing is activated.
12. The user reviews and accepts the result before any next-stage integration.
