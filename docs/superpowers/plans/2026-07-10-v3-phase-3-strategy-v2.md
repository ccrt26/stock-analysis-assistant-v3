# V3 Phase 3 Strategy V2 Implementation Plan

> **Lifecycle:** Historical execution record. It implemented deterministic Strategy V2 behavior and offline reports, while intentionally leaving several production provider methods empty. Current production status is tracked only in [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 3 Strategy V2 so every A-share trading day produces a knowledge-first daily recommendation report, a focus-stock tracking report, structured evidence snapshots, clear action and position suggestions, and explicit data-insufficient outputs when required data cannot be recovered.

**Architecture:** Keep wide market data and recalculation inputs in `local_warehouse`, and store only narrow decision-ledger records in Supabase. Add a Strategy V2 evidence layer between raw features and reports: local knowledge rules plus deterministic evidence builders create six-module evidence, action recommendations, focus-entry theses, focus daily updates, and operational status; report rendering only expresses those structured facts. LLM usage is represented as a constrained narrative boundary and must not create facts, stock promotion, unsupported catalysts, or trade instructions beyond the evidence contract.

**Tech Stack:** Python 3.12, Pydantic, Typer, pytest, Jinja2 templates, DuckDB/Parquet local warehouse, Supabase SQL migrations and repository adapters, existing Tushare provider with AkShare/Eastmoney/Sina/Tencent/local-cache source registry entries for backup paths.

## Global Constraints

- Approved design basis is `docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-design.md`.
- Approved architecture map is `docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-architecture.html`.
- Knowledge library comes first; structured data and deterministic evidence builders run before any narrative generation.
- LLM only turns structured evidence into readable analysis; it must not invent company facts, news, catalysts, policies, financials, risks, or unsupported trade instructions.
- Daily recommendation and focus-stock tracking must produce outputs on every confirmed trading day.
- If required data is missing, the system must try primary source, backup source, and local cache before producing an explicit data-insufficient output.
- Daily recommendation shows at most 10 stocks.
- Daily recommendation must not display total numeric scores to the user.
- System-selected focus watchlist has at most 5 stocks.
- Manually added focus stocks do not count against the system-selected limit.
- Focus analysis must provide clear action, quantitative position range, reasoning, required condition or confirmation, invalidation condition, and risk if wrong.
- First-version focus entry observes 5 trading days and requires at least 3 thesis-supporting days in the last 5 trading days for system entry.
- Supabase is a narrow decision ledger, not a full-market factor warehouse.
- Do not connect to a broker.
- Do not place orders or automate trading.
- Do not use rumors or low-source material as formal supporting evidence.
- Do not read, print, copy, commit, or log `.env.local`, `SUPABASE_SERVICE_ROLE_KEY`, Tushare token, Cloudflare token, report password, session secret, or any token/key file.
- Do not execute real production writes during implementation or verification unless the user gives a new explicit approval after this plan.
- Implementation tests must use in-memory repositories, fixture data, local temporary paths, or SQL text inspection.

---

## Model Assignment

| Task | Implementer | Reviewer | Model requirement |
| --- | --- | --- | --- |
| Task 1 | Strategy evidence designer | Contract reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 2 | Knowledge mapper | Knowledge-rule reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 3 | Data-source designer | Data-quality reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 4 | Storage designer | Safety reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 5 | Financial logic implementer | Financial logic reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 6 | Recommendation implementer | Strategy reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 7 | Focus logic implementer | Risk/position reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 8 | Pipeline implementer | Operations reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 9 | Ledger implementer | Supabase safety reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 10 | Report implementer | Product/finance reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 11 | Verification implementer | Production safety reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 12 | Replay implementer | Evaluation reviewer | GPT-5.5 xhigh or strongest available high-reasoning model |
| Task 13 | Documentation worker | Final reviewer | Docs formatting may use a lower-tier model only after all exact file edits and commands are specified; final review must use GPT-5.5 xhigh or strongest available high-reasoning model |

Lower-tier models are forbidden for strategy design, knowledge mapping, data-source selection, financial logic, factor selection, risk/position sizing, data-quality decisions, behavior-changing code review, and final review. If subagents are used, dispatch each task with this model requirement in the subagent prompt and record the model used in the task handoff note.

## File Structure

- Modify `src/stock_analyzer/domain/models.py` to add Strategy V2 Pydantic contracts for evidence atoms, six-module snapshots, focus-entry theses, focus daily updates, action recommendations, manual holdings, data requirements, and operational daily status.
- Create `src/stock_analyzer/analysis/strategy_v2.py` for deterministic evidence assembly from features, data coverage, knowledge matches, holdings, catalysts, and focus state.
- Create `src/stock_analyzer/analysis/action_policy.py` for action labels, quantified position ranges, staging rules, invalidation levels, and risk-if-wrong text derived from structured inputs.
- Create `src/stock_analyzer/analysis/knowledge_map.py` for loading the Strategy V2 knowledge map and matching enabled rules to modules.
- Create `src/stock_analyzer/knowledge/strategy_v2_map.yaml` for architecture-page knowledge IDs, module assignments, rule type, data status, core-impact flag, unused reason, and next action.
- Create `src/stock_analyzer/data/source_registry.py` for required/enhanced/observation data-family source mapping with primary, backup, and local-cache paths.
- Modify `src/stock_analyzer/data/models.py` to add company profile, fundamental summary, board context, event catalyst, risk event, concept tag, and data recovery models.
- Modify `src/stock_analyzer/data/provider.py` to expose provider interfaces for required Strategy V2 data families without making network calls in tests.
- Modify `src/stock_analyzer/storage/local_warehouse.py` to persist Strategy V2 enhanced local datasets and manual holding files under local warehouse paths.
- Create `src/stock_analyzer/storage/manual_holdings.py` for local-first `holdings.json` and `actions.jsonl` read/write helpers.
- Modify `src/stock_analyzer/storage/repositories.py` to add narrow decision-ledger protocol methods and Supabase/InMemory implementations.
- Create `supabase/migrations/202607100003_strategy_v2_decision_ledger.sql` for Phase 3 decision-ledger tables.
- Modify `src/stock_analyzer/analysis/recommendation.py` so internal scores remain sortable but report-facing recommendation cards hide numeric total scores.
- Modify `src/stock_analyzer/analysis/focus.py` or split to `src/stock_analyzer/analysis/focus_v2.py` for source-aware focus state, 5-day observation, manual entries, daily tracking, and invalidation.
- Modify `src/stock_analyzer/analysis/evidence.py` to build evidence packages from Strategy V2 module snapshots instead of score-only text.
- Modify `src/stock_analyzer/pipeline.py` to orchestrate Strategy V2 recommendation, focus tracking, data-insufficient outputs, local warehouse persistence, and narrow ledger writes.
- Modify `src/stock_analyzer/reports/generator.py` plus `src/stock_analyzer/reports/templates/index.html.j2` and `src/stock_analyzer/reports/templates/stock.html.j2` to render daily recommendation cards, focus report cards, action recommendations, and explicit data-insufficient sections without displaying total scores.
- Modify `src/stock_analyzer/ops/job.py`, `src/stock_analyzer/ops/verify.py`, and `src/stock_analyzer/ops/status.py` so trading-day jobs require operational status for recommendation and focus outputs.
- Modify `src/stock_analyzer/evaluation/tasks.py` and create `src/stock_analyzer/evaluation/replay.py` for 5/20/40 trading-day evaluation input and replay checks.
- Add or extend tests in `tests/test_strategy_v2_contracts.py`, `tests/test_strategy_v2_knowledge_map.py`, `tests/test_strategy_v2_source_registry.py`, `tests/test_manual_holdings.py`, `tests/test_action_policy.py`, `tests/test_strategy_v2_recommendation.py`, `tests/test_focus_strategy_v2.py`, `tests/test_pipeline_smoke.py`, `tests/test_repositories.py`, `tests/test_supabase_schema.py`, `tests/test_report_generation.py`, `tests/test_ops_job.py`, `tests/test_ops_verify.py`, and `tests/test_evidence_evaluation.py`.
- Modify `docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-architecture.html` only when implementation changes make the knowledge map more precise; preserve it as a design artifact, not as a report.
- Modify `docs/operations/runbook.md` and `docs/operations/mandatory-next-phases.md` to document Strategy V2 operation and boundaries.

## Shared Interfaces To Implement

Keep these names stable once introduced. They are intentionally narrow so each task can be implemented and reviewed independently.

```python
class EvidencePolarity(str, Enum):
    SUPPORT = "support"
    COUNTER = "counter"
    NEUTRAL = "neutral"

class EvidenceModule(str, Enum):
    COMPANY_BUSINESS = "company_business"
    FUNDAMENTALS_VALUATION = "fundamentals_valuation"
    MARKET_BOARD = "market_board"
    TREND_VOLUME = "trend_volume"
    EVENTS_CATALYSTS = "events_catalysts"
    RISK_COUNTER = "risk_counter"

class DataRequirementLevel(str, Enum):
    REQUIRED = "required"
    ENHANCED = "enhanced"
    OBSERVATION = "observation"

class DataAvailability(str, Enum):
    AVAILABLE_PRIMARY = "available_primary"
    AVAILABLE_BACKUP = "available_backup"
    AVAILABLE_LOCAL_CACHE = "available_local_cache"
    UNAVAILABLE_AFTER_RECOVERY = "unavailable_after_recovery"

class ActionDecision(str, Enum):
    NO_PARTICIPATION = "暂不参与"
    CONTINUE_WATCHING = "继续观察"
    WAIT_FOR_CONFIRMATION = "等待确认"
    AVOID_CHASING = "避免追高"
    SMALL_EXPLORATORY = "小仓试探"
    INCREASE_ATTENTION = "提高关注"
    CONDITIONAL_ADD = "确认后考虑提高仓位"
    REDUCE_OR_AVOID = "风险上升，降低或避免新增"
    CONFIRM_REMOVAL = "建议确认是否移出重点"

class FocusSource(str, Enum):
    SYSTEM = "system"
    MANUAL = "manual"

class OperationalReportState(str, Enum):
    GENERATED = "generated"
    DATA_INSUFFICIENT = "data_insufficient"
    SKIPPED_NON_TRADING_DAY = "skipped_non_trading_day"
```

`EvidenceAtom` fields:

```python
id: str
module: EvidenceModule
polarity: EvidencePolarity
headline: str
detail: str
source_grade: str
source_name: str
source_url: str | None
data_fields: list[str]
knowledge_rule_ids: list[str]
strength: float
as_of_date: date
```

`ModuleEvidence` fields:

```python
module: EvidenceModule
summary: str
support: list[EvidenceAtom]
counter: list[EvidenceAtom]
data_requirements: list[DataRequirementStatus]
conclusion: str
```

`ActionRecommendation` fields:

```python
decision: ActionDecision
position_min_pct: float
position_max_pct: float
reasoning: list[str]
required_confirmation: list[str]
invalidation_conditions: list[str]
risk_if_wrong: str
staging_plan: list[str]
holding_adjustment: str | None
```

`StrategyEvidenceSnapshot` fields:

```python
evidence_id: str
trade_date: date
ts_code: str
name: str
modules: list[ModuleEvidence]
action: ActionRecommendation
thesis: str
expected_upside_pct: float | None
expected_downside_pct: float | None
risk_reward: float | None
focus_entry_progress: str | None
display_rank_bucket: str
internal_score: float
data_insufficient: bool
data_insufficient_reason: str | None
source_versions: dict[str, str]
```

`OperationalDailyStatus` fields:

```python
trade_date: date
is_trading_day: bool
recommendation_state: OperationalReportState
focus_state: OperationalReportState
recommendation_count: int
focus_count: int
data_recovery_attempts: list[DataRecoveryAttempt]
blocking_missing_fields: list[str]
message: str
```

## Required Data Source Map

The implementation must encode this table in `src/stock_analyzer/data/source_registry.py` and test it in `tests/test_strategy_v2_source_registry.py`.

| Data family | Level | Primary collection path | Backup collection path | Local cache path |
| --- | --- | --- | --- | --- |
| Stock identity and listing | Required | `TushareMarketDataSource.fetch_stock_basic()` / Tushare `stock_basic` | AkShare `stock_info_a_code_name` plus exchange parsed from code | `local_warehouse/parquet/stock_basic/snapshot_date=<date>/data.parquet` |
| Daily OHLCV bars | Required | `TushareMarketDataSource.fetch_daily(trade_date)` / Tushare `daily` | AkShare `stock_zh_a_hist` or Sina/Tencent daily quote adapter | `local_warehouse/parquet/market_daily/trade_date=<date>/data.parquet` |
| Daily basic and valuation | Required | `TushareMarketDataSource.fetch_daily_basic(trade_date)` / Tushare `daily_basic` | AkShare/Eastmoney valuation adapters for turnover, market cap, PE, PB | `local_warehouse/parquet/daily_basic/trade_date=<date>/data.parquet` |
| Company profile and business | Required for complete focus analysis | Tushare `stock_company` | AkShare `stock_individual_info_em` or Eastmoney F10 profile adapter | `local_warehouse/parquet/company_profile/snapshot_date=<date>/data.parquet` |
| Industry and board | Required | Tushare `stock_basic.industry` plus index/industry mapping where available | AkShare Eastmoney industry board adapters | `local_warehouse/parquet/industry_board/trade_date=<date>/data.parquet` |
| Concept and theme tags | Enhanced | Tushare `concept` and `concept_detail` | AkShare Eastmoney concept board constituents | `local_warehouse/parquet/concept_tags/trade_date=<date>/data.parquet` |
| Fundamentals summary | Enhanced for daily recommendation, required for complete focus analysis | Tushare `income`, `balancesheet`, `cashflow`, `fina_indicator`, `forecast`, `express` | AkShare financial abstract or Eastmoney F10 financial summary | `local_warehouse/parquet/fundamental_summary/snapshot_date=<date>/data.parquet` |
| Market and board context | Required | Tushare index daily data and local breadth from market bars | AkShare index and board history adapters | `local_warehouse/parquet/market_context/trade_date=<date>/data.parquet` |
| Announcements and official events | Required for catalyst conclusions | Tushare announcement/holder/change APIs where available plus official exchange/CSRC cache adapters | Eastmoney announcement pages, SSE/SZSE disclosure cache adapters | `local_warehouse/parquet/event_catalysts/trade_date=<date>/data.parquet` |
| Official hard risk | Required | Tushare name/list status/suspension fields plus official exchange risk cache | SSE/SZSE/CSRC local official-risk cache adapters | `local_warehouse/parquet/risk_events/trade_date=<date>/data.parquet` |
| Manual holdings and user actions | Required for position adjustment when present | Local user-maintained files | No network backup | `local_warehouse/manual/holdings.json` and `local_warehouse/manual/actions.jsonl` |

## Task 1: Strategy V2 Domain Contracts

**Files:**
- Modify: `src/stock_analyzer/domain/models.py`
- Test: `tests/test_strategy_v2_contracts.py`

**Interfaces:**
- Produces the shared enums and Pydantic models listed above.
- Produces `RecommendationCard` with no user-facing `score` field.
- Produces `FocusEntryThesis`, `FocusDailyUpdate`, `ManualHolding`, `ManualActionRecord`, `DataRequirementStatus`, `DataRecoveryAttempt`, and `OperationalDailyStatus`.

- [ ] **Step 1: Write failing tests for contract serialization and score hiding**

Create `tests/test_strategy_v2_contracts.py`:

```python
from datetime import date

from stock_analyzer.domain.models import (
    ActionDecision,
    ActionRecommendation,
    DataAvailability,
    DataRequirementLevel,
    DataRequirementStatus,
    EvidenceAtom,
    EvidenceModule,
    EvidencePolarity,
    ModuleEvidence,
    RecommendationCard,
    StrategyEvidenceSnapshot,
)


def _atom() -> EvidenceAtom:
    return EvidenceAtom(
        id="2026-07-10-600000.SH-trend",
        module=EvidenceModule.TREND_VOLUME,
        polarity=EvidencePolarity.SUPPORT,
        headline="20 日趋势改善",
        detail="收盘价高于 20 日均线且 20 日收益强于市场中位数。",
        source_grade="A",
        source_name="local_warehouse.market_daily",
        source_url=None,
        data_fields=["trend_20d", "relative_strength"],
        knowledge_rule_ids=["RESEARCH_TREND_CONFIRMATION"],
        strength=0.72,
        as_of_date=date(2026, 7, 10),
    )


def test_strategy_snapshot_serializes_six_module_evidence_and_action():
    atom = _atom()
    status = DataRequirementStatus(
        family="daily_ohlcv",
        level=DataRequirementLevel.REQUIRED,
        availability=DataAvailability.AVAILABLE_PRIMARY,
        primary_source="tushare.daily",
        backup_source="akshare.stock_zh_a_hist",
        local_cache_path="local_warehouse/parquet/market_daily/trade_date=2026-07-10/data.parquet",
        missing_fields=[],
        recovery_attempts=[],
        blocks_complete_analysis=False,
    )
    module = ModuleEvidence(
        module=EvidenceModule.TREND_VOLUME,
        summary="趋势和量价支持观察，但不能单独构成买入依据。",
        support=[atom],
        counter=[],
        data_requirements=[status],
        conclusion="趋势证据偏积极。",
    )
    snapshot = StrategyEvidenceSnapshot(
        evidence_id="2026-07-10-600000.SH",
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        modules=[module],
        action=ActionRecommendation(
            decision=ActionDecision.WAIT_FOR_CONFIRMATION,
            position_min_pct=0.0,
            position_max_pct=3.0,
            reasoning=["趋势改善但板块确认不足"],
            required_confirmation=["板块相对强度继续改善"],
            invalidation_conditions=["跌破 20 日均线且放量"],
            risk_if_wrong="若是假突破，短线回撤可能扩大。",
            staging_plan=["未持有时等待确认后再小仓试探"],
            holding_adjustment=None,
        ),
        thesis="银行板块企稳下的 2-8 周修复观察。",
        expected_upside_pct=10.0,
        expected_downside_pct=6.0,
        risk_reward=1.67,
        focus_entry_progress="观察第 2/5 个交易日，最近 5 日支持 2 日。",
        display_rank_bucket="强观察",
        internal_score=83.25,
        data_insufficient=False,
        data_insufficient_reason=None,
        source_versions={"market_daily": "2026-07-10"},
    )

    payload = snapshot.model_dump(mode="json")

    assert payload["action"]["decision"] == "等待确认"
    assert payload["modules"][0]["support"][0]["knowledge_rule_ids"] == [
        "RESEARCH_TREND_CONFIRMATION"
    ]
    assert payload["risk_reward"] == 1.67


def test_recommendation_card_has_no_total_numeric_score():
    card = RecommendationCard(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        display_rank_bucket="强观察",
        action="等待确认",
        what_happened="趋势改善且成交额维持。",
        why_it_may_have_happened="板块企稳带动修复。",
        what_it_may_mean="进入重点观察候选，但仍需板块确认。",
        main_risk="银行板块弹性不足。",
        focus_entry_progress="观察第 2/5 个交易日，最近 5 日支持 2 日。",
        needed_before_focus_entry=["板块确认", "风险收益确认"],
        evidence_id="2026-07-10-600000.SH",
    )

    payload = card.model_dump(mode="json")

    assert "score" not in payload
    assert "internal_score" not in payload
    assert payload["display_rank_bucket"] == "强观察"
```

- [ ] **Step 2: Run the focused failing test**

Run: `pytest tests/test_strategy_v2_contracts.py -v`

Expected: FAIL with import errors for the new Strategy V2 models.

- [ ] **Step 3: Add the domain models**

Modify `src/stock_analyzer/domain/models.py` by adding the enums and Pydantic models from the shared interfaces. Preserve existing models so Phase 1/2 tests still import `Recommendation`, `FocusState`, and `EvidencePackage`.

- [ ] **Step 4: Run contract tests**

Run: `pytest tests/test_strategy_v2_contracts.py -v`

Expected: PASS.

- [ ] **Step 5: Run existing model tests**

Run: `pytest tests/test_domain_models.py tests/test_recommendation.py tests/test_focus_state_machine.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/domain/models.py tests/test_strategy_v2_contracts.py
git commit -m "feat: add strategy v2 evidence contracts"
```

## Task 2: Knowledge Map Loader and Architecture Coverage

**Files:**
- Create: `src/stock_analyzer/analysis/knowledge_map.py`
- Create: `src/stock_analyzer/knowledge/strategy_v2_map.yaml`
- Modify: `src/stock_analyzer/knowledge/__init__.py`
- Test: `tests/test_strategy_v2_knowledge_map.py`

**Interfaces:**
- Produces `StrategyKnowledgeEntry`.
- Produces `load_strategy_knowledge_map(path: Path) -> list[StrategyKnowledgeEntry]`.
- Produces `entries_for_module(entries: list[StrategyKnowledgeEntry], module: EvidenceModule) -> list[StrategyKnowledgeEntry]`.
- Consumes `EvidenceModule` and `KnowledgeRule.rule_type` categories.

- [ ] **Step 1: Write failing coverage tests**

Create `tests/test_strategy_v2_knowledge_map.py`:

```python
from pathlib import Path

from stock_analyzer.analysis.knowledge_map import (
    entries_for_module,
    load_strategy_knowledge_map,
)
from stock_analyzer.domain.models import EvidenceModule


MAP_PATH = Path("src/stock_analyzer/knowledge/strategy_v2_map.yaml")
ARCH_PATH = Path(
    "docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-architecture.html"
)


def test_strategy_knowledge_map_loads_required_core_entries():
    entries = load_strategy_knowledge_map(MAP_PATH)
    by_id = {entry.knowledge_id: entry for entry in entries}

    assert by_id["src_sse_rules_portal"].rule_type == "hard_constraint"
    assert by_id["src_jegadeesh_titman_1993"].module == EvidenceModule.TREND_VOLUME
    assert by_id["src_markowitz_1952"].module == EvidenceModule.RISK_COUNTER
    assert by_id["src_brown_warner_1985"].rule_type == "method_guard"
    assert by_id["src_piotroski_2000"].usage_status == "future_enhancement"
    assert by_id["src_short_disclose_distort_2024"].usage_status == "observation_only"


def test_each_six_module_has_at_least_one_v1_used_or_hard_constraint_entry():
    entries = load_strategy_knowledge_map(MAP_PATH)

    for module in EvidenceModule:
        module_entries = entries_for_module(entries, module)
        assert any(
            item.usage_status in {"v1_used", "hard_constraint", "partial"}
            for item in module_entries
        ), module.value


def test_architecture_ids_are_represented_in_machine_readable_map():
    html = ARCH_PATH.read_text(encoding="utf-8")
    entries = load_strategy_knowledge_map(MAP_PATH)
    mapped_ids = {entry.knowledge_id for entry in entries}
    architecture_ids = {
        token
        for token in mapped_ids
        if token.startswith("src_") and token in html
    }

    assert "src_csrc_law_rules_portal" in architecture_ids
    assert "src_cn_policy_high_quality_2024" in architecture_ids
    assert "src_lo_mackinlay_1990" in architecture_ids
    assert architecture_ids == mapped_ids
```

- [ ] **Step 2: Run the focused failing test**

Run: `pytest tests/test_strategy_v2_knowledge_map.py -v`

Expected: FAIL because `analysis.knowledge_map` and `strategy_v2_map.yaml` do not exist.

- [ ] **Step 3: Implement the loader**

Create `src/stock_analyzer/analysis/knowledge_map.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from stock_analyzer.domain.models import EvidenceModule


UsageStatus = Literal[
    "v1_used",
    "hard_constraint",
    "partial",
    "future_enhancement",
    "observation_only",
]
RuleType = Literal[
    "hard_constraint",
    "explanation",
    "counter_evidence",
    "method_guard",
    "observation",
]
NextAction = Literal[
    "use_now",
    "add_data_source",
    "keep_for_future",
    "downgrade",
    "consider_removal",
]


class StrategyKnowledgeEntry(BaseModel):
    knowledge_id: str
    title: str
    usage_status: UsageStatus
    module: EvidenceModule
    rule_type: RuleType
    data_exists: bool
    affects_core_analysis: bool
    unused_reason: str | None = None
    next_action: NextAction


def load_strategy_knowledge_map(path: Path) -> list[StrategyKnowledgeEntry]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [StrategyKnowledgeEntry.model_validate(item) for item in payload["entries"]]


def entries_for_module(
    entries: list[StrategyKnowledgeEntry],
    module: EvidenceModule,
) -> list[StrategyKnowledgeEntry]:
    return [entry for entry in entries if entry.module == module]
```

- [ ] **Step 4: Create the knowledge map YAML**

Create `src/stock_analyzer/knowledge/strategy_v2_map.yaml` with entries for every `src_*` ID in the architecture HTML. Use module assignments from the HTML table. Use `hard_constraint` for official S-grade legal/risk rules, `v1_used` for V1-used research entries, `partial` for partially used entries, `future_enhancement` for deferred important entries, and `observation_only` for B-grade or unclear-boundary observation entries.

Required first entries:

```yaml
entries:
  - knowledge_id: src_csrc_law_rules_portal
    title: 中国证监会法律法规数据库
    usage_status: hard_constraint
    module: risk_counter
    rule_type: hard_constraint
    data_exists: false
    affects_core_analysis: true
    unused_reason: null
    next_action: add_data_source
  - knowledge_id: src_sse_rules_portal
    title: 上海证券交易所业务规则库
    usage_status: hard_constraint
    module: risk_counter
    rule_type: hard_constraint
    data_exists: false
    affects_core_analysis: true
    unused_reason: null
    next_action: add_data_source
  - knowledge_id: src_szse_rules_portal
    title: 深圳证券交易所法律规则库
    usage_status: hard_constraint
    module: risk_counter
    rule_type: hard_constraint
    data_exists: false
    affects_core_analysis: true
    unused_reason: null
    next_action: add_data_source
```

Then add the remaining architecture IDs with their HTML-stated status and next action. Do not omit observation entries; they are needed to prove they are intentionally not used for V1 conclusions.

- [ ] **Step 5: Export loader from the knowledge package**

Modify `src/stock_analyzer/knowledge/__init__.py`:

```python
from stock_analyzer.analysis.knowledge_map import (
    StrategyKnowledgeEntry,
    entries_for_module,
    load_strategy_knowledge_map,
)

__all__ = [
    "StrategyKnowledgeEntry",
    "entries_for_module",
    "load_strategy_knowledge_map",
]
```

- [ ] **Step 6: Run knowledge map tests**

Run: `pytest tests/test_strategy_v2_knowledge_map.py tests/test_knowledge_rules.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stock_analyzer/analysis/knowledge_map.py src/stock_analyzer/knowledge/__init__.py src/stock_analyzer/knowledge/strategy_v2_map.yaml tests/test_strategy_v2_knowledge_map.py
git commit -m "feat: map strategy v2 knowledge usage"
```

## Task 3: Data Source Registry and Recovery Attempts

**Files:**
- Create: `src/stock_analyzer/data/source_registry.py`
- Modify: `src/stock_analyzer/data/models.py`
- Modify: `src/stock_analyzer/data/provider.py`
- Test: `tests/test_strategy_v2_source_registry.py`

**Interfaces:**
- Produces `DataFamilySourcePlan`.
- Produces `strategy_v2_source_registry() -> dict[str, DataFamilySourcePlan]`.
- Produces `record_recovery_attempt(family: str, source_name: str, status: SourceStatus, message: str) -> DataRecoveryAttempt`.
- Adds provider protocol methods for enhanced Strategy V2 datasets.

- [ ] **Step 1: Write failing source-registry tests**

Create `tests/test_strategy_v2_source_registry.py`:

```python
from datetime import date

from stock_analyzer.data.models import SourceStatus
from stock_analyzer.data.source_registry import (
    DataFamilySourcePlan,
    record_recovery_attempt,
    strategy_v2_source_registry,
)
from stock_analyzer.domain.models import DataRequirementLevel


def test_required_data_families_have_primary_backup_and_local_cache():
    registry = strategy_v2_source_registry()
    required_families = [
        "stock_identity",
        "daily_ohlcv",
        "daily_basic_valuation",
        "company_profile",
        "industry_board",
        "market_board_context",
        "official_hard_risk",
        "manual_holdings",
    ]

    for family in required_families:
        plan = registry[family]
        assert isinstance(plan, DataFamilySourcePlan)
        assert plan.level == DataRequirementLevel.REQUIRED
        assert plan.primary_path
        assert plan.local_cache_path
        if family != "manual_holdings":
            assert plan.backup_path


def test_source_registry_names_exact_collection_paths():
    registry = strategy_v2_source_registry()

    assert registry["daily_ohlcv"].primary_path == "TushareMarketDataSource.fetch_daily"
    assert registry["daily_ohlcv"].backup_path == "akshare.stock_zh_a_hist"
    assert registry["daily_basic_valuation"].primary_path == "TushareMarketDataSource.fetch_daily_basic"
    assert registry["fundamentals_summary"].primary_path == "tushare.income|balancesheet|cashflow|fina_indicator|forecast|express"
    assert registry["events_catalysts"].backup_path == "eastmoney.announcements|sse.disclosure_cache|szse.disclosure_cache"


def test_recovery_attempt_serializes_without_secrets():
    attempt = record_recovery_attempt(
        family="daily_ohlcv",
        source_name="tushare.daily",
        status=SourceStatus.FAILED,
        message="request failed without exposing token",
        trade_date=date(2026, 7, 10),
    )

    payload = attempt.model_dump(mode="json")

    assert payload["family"] == "daily_ohlcv"
    assert payload["source_name"] == "tushare.daily"
    assert payload["status"] == "failed"
    assert "token" not in payload["message"].lower()
```

- [ ] **Step 2: Run the focused failing test**

Run: `pytest tests/test_strategy_v2_source_registry.py -v`

Expected: FAIL because the registry module and recovery model do not exist.

- [ ] **Step 3: Add data models**

Modify `src/stock_analyzer/data/models.py` to add:

```python
class CompanyProfileRow(BaseModel):
    trade_date: date
    ts_code: str
    business_summary: str | None = None
    main_business_lines: list[str] = Field(default_factory=list)
    source_name: str
    source_grade: SourceGrade

class FundamentalSummaryRow(BaseModel):
    trade_date: date
    ts_code: str
    revenue_yoy: float | None = None
    profit_yoy: float | None = None
    gross_margin: float | None = None
    operating_cashflow: float | None = None
    source_name: str
    source_grade: SourceGrade

class BoardContextRow(BaseModel):
    trade_date: date
    board_name: str
    board_type: str
    relative_strength_20d: float | None = None
    breadth: float | None = None
    turnover_change: float | None = None
    source_name: str
    source_grade: SourceGrade

class ConceptTagRow(BaseModel):
    trade_date: date
    ts_code: str
    concept_name: str
    source_name: str
    source_grade: SourceGrade

class EventCatalystRow(BaseModel):
    trade_date: date
    ts_code: str
    event_type: str
    title: str
    source_reliability: str
    is_new_information: bool
    source_name: str
    source_grade: SourceGrade

class OfficialRiskEventRow(BaseModel):
    trade_date: date
    ts_code: str
    risk_type: str
    description: str
    source_name: str
    source_grade: SourceGrade
```

Add `DataRecoveryAttempt` to `domain.models.py` if Task 1 did not add it there; keep one definition only.

- [ ] **Step 4: Implement source registry**

Create `src/stock_analyzer/data/source_registry.py` with the Required Data Source Map above encoded as immutable Pydantic models. Make `manual_holdings.backup_path` an empty string because local user records have no network backup.

- [ ] **Step 5: Add provider protocol methods**

Modify `src/stock_analyzer/data/provider.py` so `MarketDataProvider` includes optional Strategy V2 methods:

```python
def load_company_profiles(self, trade_date: date, codes: list[str]) -> list[CompanyProfileRow]: ...
def load_fundamental_summaries(self, trade_date: date, codes: list[str]) -> list[FundamentalSummaryRow]: ...
def load_board_context(self, trade_date: date) -> list[BoardContextRow]: ...
def load_concept_tags(self, trade_date: date, codes: list[str]) -> list[ConceptTagRow]: ...
def load_event_catalysts(self, trade_date: date, codes: list[str]) -> list[EventCatalystRow]: ...
def load_official_risk_events(self, trade_date: date, codes: list[str]) -> list[OfficialRiskEventRow]: ...
```

For `TushareProvider`, add methods returning empty lists with source-run recovery status only if the data is not yet implemented. This preserves production behavior while Strategy V2 can mark required fields unavailable after recovery attempts.

- [ ] **Step 6: Run registry and provider tests**

Run: `pytest tests/test_strategy_v2_source_registry.py tests/test_pipeline_smoke.py::test_tushare_provider_builds_decision_ready_bundle_from_fetched_rows -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stock_analyzer/data/models.py src/stock_analyzer/data/provider.py src/stock_analyzer/data/source_registry.py tests/test_strategy_v2_source_registry.py
git commit -m "feat: define strategy v2 data source registry"
```

## Task 4: Manual Holdings and Local-First Action Records

**Files:**
- Create: `src/stock_analyzer/storage/manual_holdings.py`
- Modify: `src/stock_analyzer/storage/local_warehouse.py`
- Test: `tests/test_manual_holdings.py`

**Interfaces:**
- Produces `ManualHoldingStore`.
- Produces `ManualHoldingStore.load_holdings() -> list[ManualHolding]`.
- Produces `ManualHoldingStore.load_actions() -> list[ManualActionRecord]`.
- Produces `ManualHoldingStore.save_holdings(holdings: list[ManualHolding]) -> None`.
- Produces `ManualHoldingStore.append_action(action: ManualActionRecord) -> None`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_manual_holdings.py`:

```python
from datetime import date

from stock_analyzer.domain.models import ManualActionRecord, ManualHolding
from stock_analyzer.storage.manual_holdings import ManualHoldingStore


def test_manual_holding_store_round_trips_holdings_and_actions(tmp_path):
    store = ManualHoldingStore(tmp_path / "local_warehouse" / "manual")
    holding = ManualHolding(
        ts_code="600000.SH",
        current_state="held",
        current_position_pct=6.5,
        current_share_count=1000,
        cost_price=10.2,
        buy_date=date(2026, 7, 1),
        buy_price=10.2,
        buy_quantity=1000,
        sell_date=None,
        sell_price=None,
        sell_quantity=None,
        notes="测试持仓",
    )
    action = ManualActionRecord(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        action_type="buy",
        price=10.2,
        quantity=1000,
        position_pct_after=6.5,
        notes="首次记录",
    )

    store.save_holdings([holding])
    store.append_action(action)

    assert store.load_holdings() == [holding]
    assert store.load_actions() == [action]


def test_manual_holding_store_missing_files_return_empty_lists(tmp_path):
    store = ManualHoldingStore(tmp_path / "manual")

    assert store.load_holdings() == []
    assert store.load_actions() == []
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_manual_holdings.py -v`

Expected: FAIL because `ManualHoldingStore` does not exist.

- [ ] **Step 3: Implement local store**

Create `src/stock_analyzer/storage/manual_holdings.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from stock_analyzer.domain.models import ManualActionRecord, ManualHolding


class ManualHoldingStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.holdings_path = root / "holdings.json"
        self.actions_path = root / "actions.jsonl"

    def load_holdings(self) -> list[ManualHolding]:
        if not self.holdings_path.exists():
            return []
        payload = json.loads(self.holdings_path.read_text(encoding="utf-8"))
        return [ManualHolding.model_validate(item) for item in payload]

    def save_holdings(self, holdings: list[ManualHolding]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump(mode="json") for item in holdings]
        self.holdings_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_actions(self) -> list[ManualActionRecord]:
        if not self.actions_path.exists():
            return []
        return [
            ManualActionRecord.model_validate(json.loads(line))
            for line in self.actions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def append_action(self, action: ManualActionRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.actions_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(action.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")
```

- [ ] **Step 4: Expose store from LocalWarehouse**

Modify `src/stock_analyzer/storage/local_warehouse.py`:

```python
from stock_analyzer.storage.manual_holdings import ManualHoldingStore

def manual_holding_store(self) -> ManualHoldingStore:
    return ManualHoldingStore(self.root / "manual")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_manual_holdings.py tests/test_local_warehouse.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/storage/manual_holdings.py src/stock_analyzer/storage/local_warehouse.py tests/test_manual_holdings.py
git commit -m "feat: add local manual holding records"
```

## Task 5: Action and Position Policy

**Files:**
- Create: `src/stock_analyzer/analysis/action_policy.py`
- Test: `tests/test_action_policy.py`

**Interfaces:**
- Produces `build_action_recommendation(snapshot_inputs: ActionPolicyInput) -> ActionRecommendation`.
- Produces `ActionPolicyInput` with market support, thesis quality, risk reward, volatility, liquidity, holding state, invalidation level, and catalyst freshness.

- [ ] **Step 1: Write failing action policy tests**

Create `tests/test_action_policy.py`:

```python
from stock_analyzer.analysis.action_policy import (
    ActionPolicyInput,
    build_action_recommendation,
)
from stock_analyzer.domain.models import ActionDecision, ManualHolding


def test_action_policy_waits_when_confirmation_is_missing():
    result = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.4,
            thesis_quality=0.65,
            risk_reward=1.7,
            volatility_20d=0.24,
            liquidity_score=0.8,
            current_holding=None,
            technical_invalidation="跌破 20 日均线且放量",
            catalyst_freshness="none",
        )
    )

    assert result.decision == ActionDecision.WAIT_FOR_CONFIRMATION
    assert result.position_min_pct == 0.0
    assert result.position_max_pct <= 3.0
    assert result.required_confirmation
    assert result.invalidation_conditions == ["跌破 20 日均线且放量"]


def test_action_policy_allows_small_exploratory_position_when_evidence_is_strong():
    result = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.78,
            thesis_quality=0.82,
            risk_reward=1.9,
            volatility_20d=0.22,
            liquidity_score=0.9,
            current_holding=None,
            technical_invalidation="跌破突破平台下沿",
            catalyst_freshness="fresh_official",
        )
    )

    assert result.decision == ActionDecision.SMALL_EXPLORATORY
    assert result.position_min_pct == 2.0
    assert result.position_max_pct == 5.0
    assert "分批" in "；".join(result.staging_plan)


def test_action_policy_reduces_suggestion_for_existing_high_position():
    holding = ManualHolding(
        ts_code="600000.SH",
        current_state="held",
        current_position_pct=18.0,
        current_share_count=1000,
        cost_price=10.0,
    )
    result = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.8,
            thesis_quality=0.82,
            risk_reward=1.8,
            volatility_20d=0.25,
            liquidity_score=0.9,
            current_holding=holding,
            technical_invalidation="跌破 20 日均线",
            catalyst_freshness="fresh_official",
        )
    )

    assert result.decision in {
        ActionDecision.CONTINUE_WATCHING,
        ActionDecision.REDUCE_OR_AVOID,
        ActionDecision.WAIT_FOR_CONFIRMATION,
    }
    assert result.position_max_pct <= 18.0
    assert result.holding_adjustment
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_action_policy.py -v`

Expected: FAIL because `action_policy.py` does not exist.

- [ ] **Step 3: Implement deterministic policy**

Create `src/stock_analyzer/analysis/action_policy.py`. Use these first-version rules:

- Hard risk, liquidity below `0.25`, risk-reward below `1.0`, or volatility above `0.45` returns `NO_PARTICIPATION` or `REDUCE_OR_AVOID`.
- Strong setup requires `market_support >= 0.70`, `thesis_quality >= 0.75`, `risk_reward >= 1.5`, `volatility_20d <= 0.35`, and `liquidity_score >= 0.60`.
- Strong setup with no holding returns `SMALL_EXPLORATORY` and `2.0-5.0%`.
- Strong setup with holding below `8.0%` returns `CONDITIONAL_ADD` and current position to `min(current + 5.0, 12.0)%`.
- Holding at or above `15.0%` never receives a higher target; return watch/reduce language with `position_max_pct <= current_position_pct`.
- Medium setup returns `WAIT_FOR_CONFIRMATION` with `0.0-3.0%`.
- Overheated or extended setup returns `AVOID_CHASING` with `0.0-0.0%`.

- [ ] **Step 4: Run action tests**

Run: `pytest tests/test_action_policy.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/analysis/action_policy.py tests/test_action_policy.py
git commit -m "feat: add quantified action policy"
```

## Task 6: Strategy V2 Evidence Builder and Daily Recommendation Cards

**Files:**
- Create: `src/stock_analyzer/analysis/strategy_v2.py`
- Modify: `src/stock_analyzer/analysis/recommendation.py`
- Modify: `src/stock_analyzer/analysis/evidence.py`
- Test: `tests/test_strategy_v2_recommendation.py`
- Extend: `tests/test_recommendation.py`
- Extend: `tests/test_evidence_evaluation.py`

**Interfaces:**
- Produces `build_strategy_snapshot(...) -> StrategyEvidenceSnapshot`.
- Produces `generate_strategy_v2_recommendations(...) -> StrategyRecommendationResult`.
- Produces report-facing `RecommendationCard` values that contain no total numeric score.

- [ ] **Step 1: Write failing Strategy V2 recommendation tests**

Create `tests/test_strategy_v2_recommendation.py`:

```python
from datetime import date

from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations
from stock_analyzer.domain.models import FeatureSnapshot


def _feature(code: str, trend20: float = 0.08, trend60: float = 0.12) -> FeatureSnapshot:
    return FeatureSnapshot(
        trade_date=date(2026, 7, 10),
        ts_code=code,
        trend_20d=trend20,
        trend_60d=trend60,
        relative_strength=0.75,
        volatility_20d=0.24,
        liquidity_score=0.9,
        quality_score=0.7,
        market_regime="sideways",
        industry="测试行业",
        data_quality="ok",
    )


def test_strategy_v2_recommendations_hide_scores_and_build_evidence_cards():
    result = generate_strategy_v2_recommendations(
        features=[_feature(f"600{i:03d}.SH") for i in range(12)],
        stock_names={f"600{i:03d}.SH": f"样本{i}" for i in range(12)},
        trade_date=date(2026, 7, 10),
    )

    assert len(result.cards) == 10
    assert len(result.snapshots) == 10
    assert all("score" not in card.model_dump(mode="json") for card in result.cards)
    assert all(card.what_happened for card in result.cards)
    assert all(card.why_it_may_have_happened for card in result.cards)
    assert all(card.what_it_may_mean for card in result.cards)
    assert all(card.main_risk for card in result.cards)
    assert all(card.focus_entry_progress for card in result.cards)


def test_strategy_v2_recommendation_marks_data_insufficient_instead_of_positive_claims():
    result = generate_strategy_v2_recommendations(
        features=[
            _feature("600000.SH").model_copy(update={"data_quality": "missing_daily_basic"})
        ],
        stock_names={"600000.SH": "浦发银行"},
        trade_date=date(2026, 7, 10),
    )

    assert result.cards == []
    assert result.data_insufficient_snapshots
    assert result.data_insufficient_snapshots[0].data_insufficient is True
    assert "数据不足" in result.data_insufficient_snapshots[0].data_insufficient_reason
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_strategy_v2_recommendation.py -v`

Expected: FAIL because `strategy_v2.py` does not exist.

- [ ] **Step 3: Implement Strategy V2 evidence builder**

Create `src/stock_analyzer/analysis/strategy_v2.py` with deterministic module summaries:

- Company/business module states missing profile as incomplete and never positive.
- Fundamentals/valuation module uses `FeatureSnapshot.quality_score`, PE/PB availability, and daily basic coverage.
- Market/board module uses `market_regime`, industry, and board context when supplied.
- Trend/volume module uses trend, relative strength, volatility, liquidity, and overheat checks.
- Events/catalysts module distinguishes official events, supporting public information, and observation-only material.
- Risk/counter module aggregates official risk, liquidity risk, volatility, overextension, valuation overextension, catalyst failure, and holding concentration risk.

Use `score_feature(feature)` only as `internal_score` for sorting and evaluation. Do not place it in `RecommendationCard`.

- [ ] **Step 4: Modify recommendation integration without breaking existing tests**

Keep `generate_recommendations()` for old tests. Add `generate_strategy_v2_recommendations()` and use it from the pipeline in Task 8.

- [ ] **Step 5: Modify evidence package builder**

Modify `src/stock_analyzer/analysis/evidence.py` to add:

```python
def build_evidence_package_from_strategy_snapshot(
    snapshot: StrategyEvidenceSnapshot,
) -> EvidencePackage:
    ...
```

The package thesis must come from `snapshot.thesis`; support and counter-evidence must be flattened from module evidence; matched rules must be unique and sorted; invalidation conditions must come from `snapshot.action.invalidation_conditions`.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_strategy_v2_recommendation.py tests/test_recommendation.py tests/test_evidence_evaluation.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stock_analyzer/analysis/strategy_v2.py src/stock_analyzer/analysis/recommendation.py src/stock_analyzer/analysis/evidence.py tests/test_strategy_v2_recommendation.py tests/test_recommendation.py tests/test_evidence_evaluation.py
git commit -m "feat: build strategy v2 recommendation evidence"
```

## Task 7: Focus Watchlist V2, Entry Thesis, and Daily Tracking

**Files:**
- Modify: `src/stock_analyzer/analysis/focus.py`
- Optional create: `src/stock_analyzer/analysis/focus_v2.py`
- Test: `tests/test_focus_strategy_v2.py`
- Extend: `tests/test_focus_state_machine.py`

**Interfaces:**
- Produces `update_focus_watchlist_v2(...) -> FocusUpdateResult`.
- Produces `build_focus_entry_thesis(snapshot: StrategyEvidenceSnapshot, source: FocusSource, manual_reason: str | None) -> FocusEntryThesis`.
- Produces `build_focus_daily_update(...) -> FocusDailyUpdate`.

- [ ] **Step 1: Write failing focus V2 tests**

Create `tests/test_focus_strategy_v2.py`:

```python
from datetime import date, timedelta

from stock_analyzer.analysis.focus import update_focus_watchlist_v2
from stock_analyzer.domain.models import FocusSource
from tests.test_strategy_v2_recommendation import _feature
from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations


def _snapshot(trade_date: date, code: str = "600000.SH"):
    return generate_strategy_v2_recommendations(
        features=[_feature(code)],
        stock_names={code: "浦发银行"},
        trade_date=trade_date,
    ).snapshots[0]


def test_system_focus_enters_after_three_supporting_days_in_last_five():
    start = date(2026, 7, 6)
    history = [
        _snapshot(start + timedelta(days=offset))
        for offset in range(5)
    ]

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    assert len(result.focus_states) == 1
    assert result.entry_theses[0].source == FocusSource.SYSTEM
    assert result.entry_theses[0].expected_upside_pct >= 10.0
    assert result.entry_theses[0].risk_reward >= 1.5
    assert result.entry_theses[0].action.invalidation_conditions


def test_system_focus_is_capped_at_five_but_manual_entries_are_not_counted():
    snapshots = [_snapshot(date(2026, 7, 10), f"600{i:03d}.SH") for i in range(8)]
    manual_entries = [("000001.SZ", "已有持仓，需要验证外部推荐")]

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=snapshots,
        manual_entries=manual_entries,
        trade_date=date(2026, 7, 10),
    )

    system_count = sum(1 for thesis in result.entry_theses if thesis.source == FocusSource.SYSTEM)
    manual_count = sum(1 for thesis in result.entry_theses if thesis.source == FocusSource.MANUAL)

    assert system_count <= 5
    assert manual_count == 1


def test_manual_focus_analysis_does_not_praise_missing_evidence():
    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=[],
        manual_entries=[("000001.SZ", "外部推荐说有重大题材")],
        trade_date=date(2026, 7, 10),
    )

    thesis = result.entry_theses[0]

    assert thesis.source == FocusSource.MANUAL
    assert thesis.validation_result in {"待验证", "证据不足"}
    assert "证据不足" in "；".join(thesis.risk_notes)
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_focus_strategy_v2.py -v`

Expected: FAIL because `update_focus_watchlist_v2` does not exist.

- [ ] **Step 3: Implement source-aware focus update**

Implement:

- System candidates group by `ts_code`.
- A system candidate enters focus only when at least 3 snapshots in the last 5 trading-day observations have `data_insufficient=False`, `expected_upside_pct >= 10.0`, `risk_reward >= 1.5`, and no hard-risk counter evidence.
- System-selected active focus list is capped to 5 by `internal_score`, then thesis quality, then liquidity.
- Manual entries create or update focus records regardless of system cap.
- Manual entries preserve `source=FocusSource.MANUAL` and validate supplied reason against evidence; absent evidence yields `validation_result="证据不足"`.
- Existing focus stocks get a daily update every trading day with short-term signal, medium-term thesis status, action recommendation, invalidation, and removal confirmation when risk dominates.

- [ ] **Step 4: Run focus tests**

Run: `pytest tests/test_focus_strategy_v2.py tests/test_focus_state_machine.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/analysis/focus.py tests/test_focus_strategy_v2.py tests/test_focus_state_machine.py
git commit -m "feat: add strategy v2 focus tracking"
```

## Task 8: Pipeline Orchestration and Trading-Day Must-Produce Behavior

**Files:**
- Modify: `src/stock_analyzer/pipeline.py`
- Modify: `src/stock_analyzer/cli.py`
- Modify: `src/stock_analyzer/reports/generator.py`
- Test: extend `tests/test_pipeline_smoke.py`
- Test: extend `tests/test_cli.py`

**Interfaces:**
- `DailyRunResult` gains `operational_status: OperationalDailyStatus`.
- Pipeline writes recommendation report and focus report for trading days when data is complete.
- Pipeline writes explicit data-insufficient report for trading days when required data cannot be recovered.

- [ ] **Step 1: Add failing pipeline tests**

Extend `tests/test_pipeline_smoke.py`:

```python
def test_trading_day_pipeline_outputs_data_insufficient_report_when_live_data_missing(tmp_path):
    repo = InMemoryAnalysisRepository()

    result = run_daily_pipeline(
        date(2026, 7, 10),
        tmp_path,
        repository=repo,
        fixture_mode=False,
        market_data_provider=InsufficientProductionProvider(),
        local_warehouse=RecordingWarehouse(),
        allow_data_insufficient_output=True,
    )

    assert result.operational_status.recommendation_state.value == "data_insufficient"
    assert result.operational_status.focus_state.value == "data_insufficient"
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "daily" / "2026-07-10" / "index.html").exists()
    payload = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))
    assert payload["report_mode"] == "data_insufficient"
    assert payload["operational_status"]["blocking_missing_fields"]


def test_strategy_v2_pipeline_persists_operational_status_without_full_market_supabase_write(tmp_path):
    repo = InMemoryAnalysisRepository()
    warehouse = RecordingWarehouse()

    result = run_daily_pipeline(
        date(2026, 7, 10),
        tmp_path,
        repository=repo,
        fixture_mode=False,
        market_data_provider=ProviderWithExtraRawCode(),
        local_warehouse=warehouse,
        strategy_v2=True,
    )

    assert result.operational_status.recommendation_state.value == "generated"
    assert result.operational_status.focus_state.value == "generated"
    assert len(repo.recommendations) <= 10
    selected_codes = {item.ts_code for item in repo.recommendations} | {
        item.ts_code for item in repo.focus_states
    }
    assert {bar.ts_code for bar in repo.market_bars} <= selected_codes
```

- [ ] **Step 2: Run failing pipeline tests**

Run: `pytest tests/test_pipeline_smoke.py::test_trading_day_pipeline_outputs_data_insufficient_report_when_live_data_missing tests/test_pipeline_smoke.py::test_strategy_v2_pipeline_persists_operational_status_without_full_market_supabase_write -v`

Expected: FAIL because `allow_data_insufficient_output`, `strategy_v2`, and operational status do not exist.

- [ ] **Step 3: Modify `run_daily_pipeline`**

Add parameters:

```python
strategy_v2: bool = False
allow_data_insufficient_output: bool = False
manual_entries: Optional[list[tuple[str, str | None]]] = None
manual_holdings: Optional[list[ManualHolding]] = None
```

Behavior:

- Existing default path remains compatible for old tests.
- When `strategy_v2=True`, call `generate_strategy_v2_recommendations`, `update_focus_watchlist_v2`, and `build_evidence_package_from_strategy_snapshot`.
- When required production data is unavailable and `allow_data_insufficient_output=True`, render an explicit data-insufficient report and return `DailyRunResult` with empty recommendations and data-insufficient operational status.
- When production data is complete, save full bundle to local warehouse first, then save only selected decision windows and narrow ledger rows to repository.

- [ ] **Step 4: Modify CLI flags**

Add `--strategy-v2` and `--allow-data-insufficient-output` to `run-daily`. Keep defaults false so old operation remains stable until Phase 3 is deliberately enabled.

- [ ] **Step 5: Run pipeline and CLI tests**

Run: `pytest tests/test_pipeline_smoke.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/pipeline.py src/stock_analyzer/cli.py src/stock_analyzer/reports/generator.py tests/test_pipeline_smoke.py tests/test_cli.py
git commit -m "feat: orchestrate strategy v2 daily pipeline"
```

## Task 9: Supabase Narrow Decision Ledger

**Files:**
- Create: `supabase/migrations/202607100003_strategy_v2_decision_ledger.sql`
- Modify: `src/stock_analyzer/storage/repositories.py`
- Test: extend `tests/test_supabase_schema.py`
- Test: extend `tests/test_repositories.py`

**Interfaces:**
- Adds repository methods:
  - `save_strategy_snapshots(snapshots: list[StrategyEvidenceSnapshot]) -> None`
  - `save_focus_entry_theses(theses: list[FocusEntryThesis]) -> None`
  - `save_focus_daily_updates(updates: list[FocusDailyUpdate]) -> None`
  - `save_action_recommendations(recommendations: list[ActionRecommendationSummary]) -> None`
  - `save_manual_holding_summaries(holdings: list[ManualHoldingSummary]) -> None`
  - `save_operational_daily_status(status: OperationalDailyStatus) -> None`

- [ ] **Step 1: Write failing schema tests**

Extend `tests/test_supabase_schema.py`:

```python
STRATEGY_V2_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "202607100003_strategy_v2_decision_ledger.sql"
)


def test_strategy_v2_schema_adds_narrow_decision_ledger_tables():
    sql = STRATEGY_V2_SCHEMA_PATH.read_text().lower()
    compact_sql = re.sub(r"\s+", " ", sql)

    for table in [
        "strategy_v2_snapshot",
        "focus_entry_thesis",
        "focus_daily_update",
        "action_recommendation_summary",
        "manual_holding_summary",
        "operational_daily_status",
    ]:
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"create policy {table}_service_role_all" in sql

    assert "market_price_daily" not in compact_sql
    assert "daily_basic_indicator" not in compact_sql
    assert "unique (trade_date, ts_code)" in compact_sql
```

- [ ] **Step 2: Run failing schema tests**

Run: `pytest tests/test_supabase_schema.py::test_strategy_v2_schema_adds_narrow_decision_ledger_tables -v`

Expected: FAIL because the migration does not exist.

- [ ] **Step 3: Create migration**

Create the SQL file with:

- `strategy_v2_snapshot(evidence_id primary key, trade_date, ts_code, name, payload jsonb, action_payload jsonb, data_insufficient boolean, source_versions jsonb, sha256 text, created_at)`.
- `focus_entry_thesis(evidence_id primary key, trade_date, ts_code, source text, thesis_payload jsonb, action_payload jsonb, created_at)`.
- `focus_daily_update(trade_date, ts_code, update_payload jsonb, action_payload jsonb, created_at, unique(trade_date, ts_code))`.
- `action_recommendation_summary(trade_date, ts_code, decision text, position_min_pct numeric, position_max_pct numeric, invalidation_conditions jsonb, created_at, unique(trade_date, ts_code))`.
- `manual_holding_summary(trade_date, ts_code, held boolean, position_band text, last_action_state text, created_at, unique(trade_date, ts_code))`.
- `operational_daily_status(trade_date primary key, is_trading_day boolean, recommendation_state text, focus_state text, recommendation_count integer, focus_count integer, blocking_missing_fields jsonb, message text, created_at)`.
- RLS enabled and service_role policies only.

- [ ] **Step 4: Add in-memory and Supabase repository methods**

Modify `AnalysisRepository`, `InMemoryAnalysisRepository`, and `SupabaseAnalysisRepository` with the methods above. Supabase methods must only upsert narrow JSON rows and must not write full-market bars or full factor snapshots through these methods.

- [ ] **Step 5: Add repository tests**

Extend `tests/test_repositories.py` to assert in-memory round-trip and Supabase fake-client table names:

```python
def test_strategy_v2_repository_saves_operational_status_to_narrow_table():
    repo = InMemoryAnalysisRepository()
    status = OperationalDailyStatus(...)

    repo.save_operational_daily_status(status)

    assert repo.operational_daily_statuses[0] == status
```

- [ ] **Step 6: Run schema and repository tests**

Run: `pytest tests/test_supabase_schema.py tests/test_repositories.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations/202607100003_strategy_v2_decision_ledger.sql src/stock_analyzer/storage/repositories.py tests/test_supabase_schema.py tests/test_repositories.py
git commit -m "feat: add strategy v2 decision ledger"
```

## Task 10: Reports and JSON Contract

**Files:**
- Modify: `src/stock_analyzer/reports/generator.py`
- Modify: `src/stock_analyzer/reports/templates/index.html.j2`
- Modify: `src/stock_analyzer/reports/templates/stock.html.j2`
- Test: extend `tests/test_report_generation.py`

**Interfaces:**
- `render_reports()` accepts Strategy V2 cards, snapshots, focus entry theses, focus updates, and operational status.
- `latest.json` includes `recommendation_cards`, `strategy_snapshots`, `focus_entry_theses`, `focus_daily_updates`, and `operational_status`.
- HTML daily recommendation hides internal scores.
- Focus section displays action, position range, reasons, conditions, invalidation, and risk if wrong.

- [ ] **Step 1: Write failing report tests**

Extend `tests/test_report_generation.py`:

```python
def test_strategy_v2_report_hides_scores_and_shows_action_position(tmp_path):
    result = generate_strategy_v2_recommendations(
        features=[_strategy_feature("600000.SH")],
        stock_names={"600000.SH": "浦发银行"},
        trade_date=date(2026, 7, 10),
    )

    render_reports(
        tmp_path,
        [],
        [],
        trade_date=date(2026, 7, 10),
        strategy_v2_cards=result.cards,
        strategy_v2_snapshots=result.snapshots,
        operational_status=_generated_status(date(2026, 7, 10), recommendation_count=1, focus_count=0),
    )

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))

    assert "评分" not in html
    assert "internal_score" in payload["strategy_snapshots"][0]
    assert "internal_score" not in payload["recommendation_cards"][0]
    assert "操作建议" in html
    assert "仓位" in html
    assert "失效" in html


def test_data_insufficient_report_lists_recovery_attempts_and_impact(tmp_path):
    status = OperationalDailyStatus(
        trade_date=date(2026, 7, 10),
        is_trading_day=True,
        recommendation_state=OperationalReportState.DATA_INSUFFICIENT,
        focus_state=OperationalReportState.DATA_INSUFFICIENT,
        recommendation_count=0,
        focus_count=0,
        data_recovery_attempts=[
            DataRecoveryAttempt(
                trade_date=date(2026, 7, 10),
                family="daily_ohlcv",
                source_name="tushare.daily",
                status=SourceStatus.FAILED,
                message="no current rows",
            )
        ],
        blocking_missing_fields=["daily_ohlcv.close"],
        message="核心行情缺失，不能形成完整结论。",
    )

    render_strategy_v2_data_insufficient_report(tmp_path, status)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))

    assert payload["report_mode"] == "data_insufficient"
    assert "核心行情缺失" in html
    assert "daily_ohlcv.close" in html
```

- [ ] **Step 2: Run failing report tests**

Run: `pytest tests/test_report_generation.py::test_strategy_v2_report_hides_scores_and_shows_action_position tests/test_report_generation.py::test_data_insufficient_report_lists_recovery_attempts_and_impact -v`

Expected: FAIL because Strategy V2 report parameters and renderer do not exist.

- [ ] **Step 3: Update JSON payload**

Modify `render_reports()` to include Strategy V2 fields when supplied:

```python
"recommendation_cards": [item.model_dump(mode="json") for item in strategy_v2_cards],
"strategy_snapshots": [item.model_dump(mode="json") for item in strategy_v2_snapshots],
"focus_entry_theses": [item.model_dump(mode="json") for item in focus_entry_theses],
"focus_daily_updates": [item.model_dump(mode="json") for item in focus_daily_updates],
"operational_status": operational_status.model_dump(mode="json") if operational_status else None,
```

- [ ] **Step 4: Update templates**

In `index.html.j2`, render:

- 今日推荐: stock name, display bucket, what happened, why it may have happened, what it may mean, main risk, focus-entry progress, needed-before-focus list.
- 重点关注: source, thesis status, action decision, position range, reasoning, required confirmation, invalidation, risk if wrong, removal confirmation when present.
- Data-insufficient section: missing fields, recovery attempts, impact on analysis.

Remove visible total numeric score from Strategy V2 sections.

- [ ] **Step 5: Update stock page template**

In `stock.html.j2`, add six-module sections and action recommendation details. Keep evidence IDs and source versions in JSON, but keep user page focused on result, reasons, risks, operation conditions, and invalidation.

- [ ] **Step 6: Run report tests**

Run: `pytest tests/test_report_generation.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stock_analyzer/reports/generator.py src/stock_analyzer/reports/templates/index.html.j2 src/stock_analyzer/reports/templates/stock.html.j2 tests/test_report_generation.py
git commit -m "feat: render strategy v2 reports"
```

## Task 11: Operations Verification for Must-Produce Outputs

**Files:**
- Modify: `src/stock_analyzer/ops/verify.py`
- Modify: `src/stock_analyzer/ops/job.py`
- Modify: `src/stock_analyzer/ops/status.py`
- Test: extend `tests/test_ops_verify.py` if present or `tests/test_ops_job.py`

**Interfaces:**
- Verification passes trading-day data-insufficient reports only when operational status explicitly records missing data and recovery attempts.
- Verification fails if Strategy V2 production HTML exposes fixture text, sample text, or visible total numeric score.
- Job status reports recommendation and focus generation state separately.

- [ ] **Step 1: Write failing verification tests**

Extend `tests/test_ops_job.py` or create `tests/test_ops_verify.py`:

```python
def test_verify_strategy_v2_fails_when_score_is_visible_in_production_html(tmp_path):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        index_html="<html><body>评分 83.2</body></html>",
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "recommendation_cards": [{"ts_code": "600000.SH"}],
            "strategy_snapshots": [{"internal_score": 83.2}],
            "operational_status": {"recommendation_state": "generated", "focus_state": "generated"},
        },
    )

    verification = verify_production_result(tmp_path, FakeVerificationRepository(), trade_date)

    assert verification.passed is False
    assert _failure(verification, "visible_total_score").fix_suggestion


def test_verify_accepts_explicit_data_insufficient_trading_day_report(tmp_path):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "data_insufficient",
            "is_fixture": False,
            "recommendations": [],
            "operational_status": {
                "trade_date": trade_date.isoformat(),
                "is_trading_day": True,
                "recommendation_state": "data_insufficient",
                "focus_state": "data_insufficient",
                "recommendation_count": 0,
                "focus_count": 0,
                "data_recovery_attempts": [{"family": "daily_ohlcv", "source_name": "tushare.daily", "status": "failed"}],
                "blocking_missing_fields": ["daily_ohlcv.close"],
                "message": "核心行情缺失。",
            },
        },
    )

    verification = verify_production_result(tmp_path, FakeVerificationRepository(), trade_date)

    assert verification.passed is True
```

- [ ] **Step 2: Run failing verification tests**

Run: `pytest tests/test_ops_job.py -k "strategy_v2 or data_insufficient or visible_total_score" -v`

Expected: FAIL until verification reads Strategy V2 operational status.

- [ ] **Step 3: Update verification logic**

Modify `verify_production_result()`:

- If `report_mode == "data_insufficient"`, require `operational_status.is_trading_day=True`, both states `data_insufficient`, at least one recovery attempt, and at least one blocking missing field.
- If `recommendation_cards` exist, scan production HTML for `评分` and numeric score-like strings near recommendation cards; fail with `visible_total_score`.
- Require focus operational status on trading days.
- Keep existing recommendation count and selected-market write checks.

- [ ] **Step 4: Update job status**

Modify `run_daily_job()` final status to include `recommendation_state`, `focus_state`, and `blocking_missing_fields` when available from verification or repository status.

- [ ] **Step 5: Run ops tests**

Run: `pytest tests/test_ops_job.py tests/test_ops_status.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/ops/verify.py src/stock_analyzer/ops/job.py src/stock_analyzer/ops/status.py tests/test_ops_job.py tests/test_ops_status.py
git commit -m "feat: verify strategy v2 trading day outputs"
```

## Task 12: Evaluation Replay and 5/20/40 Outcome Inputs

**Files:**
- Modify: `src/stock_analyzer/evaluation/tasks.py`
- Create: `src/stock_analyzer/evaluation/replay.py`
- Test: extend `tests/test_evidence_evaluation.py`

**Interfaces:**
- Produces `evaluate_strategy_snapshot(snapshot: StrategyEvidenceSnapshot, future_bars: list[DailyBar]) -> EvaluationResultPayload`.
- Evaluation checks movement, invalidation occurrence, action usefulness, position aggressiveness, knowledge-rule effect, missing-data effect, and unsupported narrative flags.

- [ ] **Step 1: Write failing replay tests**

Extend `tests/test_evidence_evaluation.py`:

```python
def test_strategy_v2_replay_marks_invalidation_when_support_breaks():
    snapshot = _strategy_snapshot_with_action(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        invalidation="跌破 20 日均线且放量",
    )
    future_bars = [
        DailyBar(
            trade_date=date(2026, 7, 13),
            ts_code="600000.SH",
            close=9.4,
            pre_close=10.0,
            pct_chg=-6.0,
            amount=900000000,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        )
    ]

    result = evaluate_strategy_snapshot(snapshot, future_bars)

    assert result.invalidation_occurred is True
    assert result.action_useful in {False, None}
    assert "跌破" in "；".join(result.notes)
```

- [ ] **Step 2: Run failing replay tests**

Run: `pytest tests/test_evidence_evaluation.py -k strategy_v2_replay -v`

Expected: FAIL because replay evaluator does not exist.

- [ ] **Step 3: Implement replay evaluator**

Create `src/stock_analyzer/evaluation/replay.py`:

- Compare future high/close to entry close for upside progress.
- Compare future low/close to invalidation proxy for invalidation occurrence.
- Flag action usefulness as true when the suggested action avoided invalidated setups or allowed staged participation in successful setups.
- Flag position aggressiveness as `"too_aggressive"`, `"reasonable"`, or `"too_conservative"` using max drawdown and max favorable excursion.
- Include `knowledge_rule_effect` and `missing_data_effect` fields from snapshot evidence.

- [ ] **Step 4: Run evaluation tests**

Run: `pytest tests/test_evidence_evaluation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/evaluation/tasks.py src/stock_analyzer/evaluation/replay.py tests/test_evidence_evaluation.py
git commit -m "feat: add strategy v2 replay evaluation"
```

## Task 13: Documentation, Architecture Sync, and Final Review

**Files:**
- Modify: `docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-architecture.html`
- Modify: `docs/operations/runbook.md`
- Modify: `docs/operations/mandatory-next-phases.md`
- Test: full test suite

**Interfaces:**
- Architecture HTML stays the transparent knowledge-usage artifact.
- Operational docs state how to run Strategy V2 safely without printing secrets or performing unapproved production writes.

- [ ] **Step 1: Update architecture HTML only for implemented machine map**

Revise the architecture page to mention `src/stock_analyzer/knowledge/strategy_v2_map.yaml` as the machine-readable source of the knowledge map. Keep the table visible in the HTML and align statuses with the YAML.

- [ ] **Step 2: Update runbook**

Add Strategy V2 section to `docs/operations/runbook.md`:

```markdown
### Strategy V2 daily run

Use fixture or dry-run for local validation:

`stock-analyzer run-daily --trade-date YYYY-MM-DD --fixture-mode --strategy-v2`

Production Strategy V2 writes require explicit approval before running without fixture mode. Do not print `.env.local`, service-role keys, Tushare tokens, Cloudflare tokens, report passwords, or session secrets. On trading days, the job must produce either generated recommendation/focus outputs or a data-insufficient report with recovery attempts and missing fields.
```

- [ ] **Step 3: Update mandatory next phases**

Mark Phase 3 Strategy V2 as planned/implementation in progress and keep broker integration/autotrading out of scope.

- [ ] **Step 4: Run complete verification**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 5: Run fixture Strategy V2 smoke**

Run: `stock-analyzer run-daily --trade-date 2026-07-10 --fixture-mode --strategy-v2`

Expected: command exits 0, prints fixture completion, and writes local reports only.

- [ ] **Step 6: Review no secrets and no real production writes**

Run:

```bash
rg -n "SUPABASE_SERVICE_ROLE_KEY|TUSHARE_TOKEN|CLOUDFLARE_API_TOKEN|REPORT_PASSWORD|REPORT_SESSION_SECRET" src tests docs/superpowers/plans docs/operations
```

Expected: only safe environment-variable names or redaction tests appear; no secret values.

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 7: Final review gate**

Use GPT-5.5 xhigh or strongest available high-reasoning model to review:

- Knowledge-first ordering.
- Structured evidence before narrative.
- LLM boundary.
- Trading-day must-produce behavior.
- Daily recommendation score hiding.
- Focus action/position/invalidation clarity.
- Supabase narrow-ledger scope.
- No broker, no order placement, no unapproved production writes.

- [ ] **Step 8: Commit docs and final review fixes**

```bash
git add docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-architecture.html docs/operations/runbook.md docs/operations/mandatory-next-phases.md
git commit -m "docs: document strategy v2 operations"
```

## Self-Review Checklist

- Spec coverage: Tasks 1-13 cover knowledge-first evidence, knowledge map, data source recovery, manual holdings, quantified action/position logic, recommendation score hiding, focus entry/tracking, trading-day must-produce outputs, Supabase narrow ledger, reports, verification, evaluation, and docs.
- Placeholder scan: No task depends on unspecified file paths or unnamed interfaces; tasks define exact files, functions, test names, commands, and expected outcomes.
- Type consistency: Shared names `StrategyEvidenceSnapshot`, `RecommendationCard`, `ActionRecommendation`, `OperationalDailyStatus`, `FocusEntryThesis`, and `FocusDailyUpdate` are introduced before use in later tasks.
- Safety: Plan forbids secret reads/prints and real production writes unless the user gives a new explicit approval.
- Model allocation: Strategy, knowledge, data, finance, risk/position, and review work require GPT-5.5 xhigh or strongest available high-reasoning model.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-v3-phase-3-strategy-v2.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Use `superpowers:subagent-driven-development`, dispatch a fresh high-reasoning subagent per task, review between tasks, and keep low-tier models limited to exact mechanical docs formatting.

**2. Inline Execution** - Use `superpowers:executing-plans`, execute tasks in this session with checkpoints after each task group.

Which approach?
