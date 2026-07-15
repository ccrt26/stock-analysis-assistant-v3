# V3 Direct Knowledge Supplement Implementation Plan

> **当前状态权威：** 本计划只记录知识补充实施方法，不证明生产能力或激活状态；当前状态只以 [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md) 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user selected inline execution on local `main`; do not use subagents, a branch, a worktree, activation or deployment.

**Goal:** Directly verify the frozen fifteen knowledge candidates against primary sources and the existing A-share warehouse, admit only `use` candidates, and keep every admitted item usable without building a factor engine or changing the data foundation.

**Architecture:** Add one focused supplement-validation module beside the completed thirteen-item validator. It contains only the frozen fifteen claim contracts, named formula functions, read-only warehouse queries and descriptive evidence; it never decides `use/discard` automatically. One result YAML records the scientific decisions, and the governed registry is updated only after those decisions are complete.

**Tech Stack:** Existing Python 3.11+, pandas, DuckDB, Pydantic, PyYAML and pytest; no new dependency.

**Approved Design:** [`docs/superpowers/specs/2026-07-15-v3-direct-knowledge-supplement-design.md`](../specs/2026-07-15-v3-direct-knowledge-supplement-design.md)

## Global Constraints

- Work directly on `/Users/ccrt/Documents/股票分析助手` current local `main`; do not create a branch or worktree.
- Do not modify `local_warehouse`, research contracts, schemas, acquisition jobs, derived formulas or data partitions.
- Do not add a crawler, generic factor library, generic experiment runner, factor score, weight, rank, buy probability, position rule, recommendation, report, automation or deployment.
- Scope is exactly fifteen candidates: eleven `new` and four `enhance`. Do not add a sixteenth candidate or replace a rejected source with an unapproved source.
- Verify sources only from an official current page, DOI landing page or original publisher page. Search snippets, broker manuals, factor platforms, self-media and reposts do not satisfy the source floor.
- Decisions are exactly `use` or `discard`. Do not create `limited`, `defer`, `method_only`, `insufficient_sample` or pending results for these fifteen candidates.
- A calculation failure is a code defect to fix, never a reason to mark knowledge `discard`.
- Empirical candidates use descriptive overall, earlier and later relationships plus counter-evidence. There is no fixed return, hit-rate, significance, sample-size or future-20%-gain pass line.
- Official-rule candidates are judged by source text, faithful semantics and executable fields; they are not forced through a return test.
- Portfolio theory is judged by exact correlation/concentration executability; it is not an individual-stock return predictor.
- Daily/minute price-volume data cannot identify institutions, main force, accumulation, distribution or account identity. `src_cn_program_trading_rules_2025` remains the wording boundary.
- `sector-hotspot-v2` remains hotspot evidence, not a validated final ranking.
- API facts, locally recomputed observations, model judgments and user wording remain separate trace layers.
- Store no copyrighted full text. Store only verified metadata, concise paraphrases, methods, limitations and URLs.
- Temporary source notes and large panels stay under `/private/tmp`. Only code, tests, one result YAML, registry changes, design and plan enter Git.

## Frozen Candidate Evidence

Changing a formula, outcome or source in this table requires a design amendment.

| # | Knowledge ID | Action | Validation | Required data | Required evidence |
|---|---|---|---|---|---|
| 1 | `src_cn_factor_momentum_2023` | enhance | empirical | `index_daily`, `equity_daily`, `industry_daily`, `theme_daily` | Prior-20-session relative strength followed by future-20-session relative return, split by current/prior 20-session market sign; winner-minus-loser overall, earlier and later |
| 2 | `src_cn_return_dispersion_risk` | new | empirical | `equity_daily`, `index_daily`, `industry_member` | Cross-sectional and industry daily-return dispersion versus next-20-session realized volatility and absolute move |
| 3 | `src_cn_turnover_momentum_boundary` | new | empirical | `daily_basic`, `equity_daily`, `adj_factor`, `index_daily` | Winner-minus-loser future spread within low/middle/high prior-20-session turnover groups |
| 4 | `src_cn_profitability_valuation_support` | new | empirical | financial statements, `financial_indicator`, `daily_basic`, prices | Keep ROE, ROA, gross profit/assets and asset turnover separate; compare with PE/PB/PS and future excess return |
| 5 | `src_cn_cash_accrual_quality` | new | empirical | income, balance, cash flow, indicators, prices | Cash and accrual components scaled by prior assets versus next-year same-quarter profitability and future excess return |
| 6 | `src_cn_illiquidity_operability` | new | empirical/measurement | prices, `daily_basic`, adjustment factor | `abs(adjusted_return_1d) / amount * 100000000` averaged over prior 20 sessions versus future volatility, drawdown and excess return |
| 7 | `src_cn_max_overextension` | new | empirical risk | prices, adjustment factor, valuation | Maximum adjusted daily return in prior 20 sessions versus future excess return and maximum drawdown |
| 8 | `src_cn_earnings_disclosure_hierarchy` | new | official semantics | forecast, express, formal report, announcement | Executable distinction among forecast, express, formal report and correction; no return test |
| 9 | `src_cn_margin_semantics` | new | official + observation | `margin_detail`, prices, index | Official meanings and `rzmre-rzche` net financing flow, balance change and later volatility/drawdown; no identity inference |
| 10 | `src_cn_share_reduction_rules_2024` | enhance | official semantics | `share_float`, `holder_trade`, announcement | Unlock eligibility, reduction plan and disclosed actual trade are distinct facts |
| 11 | `src_cn_pledge_conditional_risk` | new | official + observation | pledge, prices, valuation, balance, cash flow | Keep pledge ratio, price decline, liquidity, debt/assets and operating cash flow separate; never infer liquidation price |
| 12 | `src_cn_disclosed_holder_trade` | new | empirical event | holder trade, income, forecast, prices | Signed disclosed change (`IN` positive, `DE` negative) versus next reported operating change and future excess return |
| 13 | `src_cn_buyback_rules_2023` | enhance | official + event | repurchase, prices | Preserve `提议/预案/股东大会通过/实施/完成/停止/未通过`; compare actual execution with plan-only observations |
| 14 | `src_csrc_disclosure_rules_2025` | enhance | official semantics | company profile, main business, announcement | Business evidence must come from scope, segment revenue/cost/profit or formal announcement |
| 15 | `src_portfolio_common_exposure` | new | theory/method | industry/theme membership, adjusted returns | Industry/theme concentration and pairwise correlation for exactly five candidates; no optimization or positions |

Formation variables must be available at formation time. Future returns, volatility, drawdown and later reports are labels only.

The academic source floor is exactly:

```text
10.1016/j.iref.2017.04.003
10.1016/j.pacfin.2015.03.005
10.1016/j.pacfin.2019.101218
https://www.sciopen.com/article/10.26599/CJE.2022.9300405
10.1016/j.jbankfin.2017.10.001
10.1111/j.1467-646X.2011.01050.x
10.1016/S1386-4181(01)00024-6
10.1016/j.pacfin.2022.101861
10.1016/j.najef.2021.101475
10.1016/j.jbankfin.2013.10.002
10.1016/j.pacfin.2019.04.001
10.1016/j.frl.2017.12.007
10.1007/s11156-025-01419-z
10.1111/j.1540-6261.1952.tb01525.x
10.1093/rfs/hhm075
```

The validation-only scientific guards are Harvey–Liu–Zhu `10.1093/rfs/hhv059`, Hou–Xue–Zhang `10.1093/rfs/hhy131`, Jansen–Swinkels–Zhou `10.1016/j.pacfin.2021.101607`, and Liu–Stambaugh–Yuan `10.1016/j.jfineco.2019.03.008` only for microcap/shell contamination. They are not extra stock candidates.

The official source floor is exactly:

```text
https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/mainipo/c/c_20260424_10816589.shtml
https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620193.html
https://www.csrc.gov.cn/csrc/c106256/c1654005/content.shtml
https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/specific/margin/
https://www.csrc.gov.cn/csrc/c100028/c7483136/content.shtml
https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/specific/repo/c/c_20250617_10782110.shtml
https://big5.sse.com.cn/site/cht/www.sse.com.cn/lawandrules/sselawsrules2025/stocks/mainipo/c/c_20260424_10816605.shtml
```

Existing CSRC buyback, disclosure, program-trading, trading, delisting and restructuring sources remain in force and are not duplicated.

## File Responsibility Map

| File | Responsibility |
|---|---|
| `src/stock_analyzer/knowledge_validation/supplement_validation.py` | Claim inventory, named transformations, read-only loaders and evidence |
| `src/stock_analyzer/knowledge/supplement_validation_results.yaml` | Exactly fifteen source/evidence/decision records; sole supplement decision authority |
| `src/stock_analyzer/knowledge/governance_models.py` | Minimal research-design metadata and required topics |
| `src/stock_analyzer/knowledge/research_registry.yaml` | Accepted sources/entries and accepted enhancements |
| `src/stock_analyzer/knowledge/strategy_v2_migration.yaml` | Correct accepted Dechow target; preserve thirteen-item decisions |
| `tests/test_supplement_validation.py` | Inventory, formulas, as-of safety, determinism and result schema |
| `tests/test_knowledge_governance_models.py` | Research design and topic contracts |
| `tests/test_knowledge_registry.py` | Registry/result agreement and source floor |
| `tests/test_knowledge_capability.py` | Complete capability for admitted entries |
| `tests/test_knowledge_selector.py` | Scene-specific selection; no traversal or scoring |
| `tests/test_knowledge_governance_acceptance.py` | Trace layers, wording, offline use and no activation |

---

### Task 1: Freeze baseline, source floor and fifteen-claim contract

**Files:**
- Create: `src/stock_analyzer/knowledge_validation/supplement_validation.py`
- Create: `tests/test_supplement_validation.py`

**Interfaces:**
- Produces: `SupplementClaim`, `SupplementEvidence`, `SUPPLEMENT_CLAIMS`, `SOURCE_REFS`.
- Later tasks import these exact names.

- [ ] **Step 1: Capture baseline**

```bash
git status --short
git rev-parse HEAD
shasum -a 256 local_warehouse/research.duckdb > /private/tmp/v3-direct-supplement.before.sha256
PYTHONPATH=src .venv/bin/python -m pytest tests/test_direct_knowledge_validation.py tests/test_knowledge_registry.py -q
```

Expected: clean worktree, baseline tests pass, and the checksum file exists.

- [ ] **Step 2: Write the failing inventory test**

```python
from stock_analyzer.knowledge_validation.supplement_validation import SUPPLEMENT_CLAIMS

EXPECTED_ACTIONS = {
    "src_cn_factor_momentum_2023": "enhance",
    "src_cn_return_dispersion_risk": "new",
    "src_cn_turnover_momentum_boundary": "new",
    "src_cn_profitability_valuation_support": "new",
    "src_cn_cash_accrual_quality": "new",
    "src_cn_illiquidity_operability": "new",
    "src_cn_max_overextension": "new",
    "src_cn_earnings_disclosure_hierarchy": "new",
    "src_cn_margin_semantics": "new",
    "src_cn_share_reduction_rules_2024": "enhance",
    "src_cn_pledge_conditional_risk": "new",
    "src_cn_disclosed_holder_trade": "new",
    "src_cn_buyback_rules_2023": "enhance",
    "src_csrc_disclosure_rules_2025": "enhance",
    "src_portfolio_common_exposure": "new",
}

def test_contract_is_exactly_eleven_new_four_enhance():
    assert {item.knowledge_id: item.action for item in SUPPLEMENT_CLAIMS} == EXPECTED_ACTIONS
    assert sum(item.action == "new" for item in SUPPLEMENT_CLAIMS) == 11
    assert sum(item.action == "enhance" for item in SUPPLEMENT_CLAIMS) == 4
    assert len(SUPPLEMENT_CLAIMS) == 15
    assert all(item.source_refs and item.core_theory and item.required_facts for item in SUPPLEMENT_CLAIMS)
```

- [ ] **Step 3: Confirm failure**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
```

Expected: collection fails because the module is absent.

- [ ] **Step 4: Implement contracts and constants only**

```python
from dataclasses import dataclass
from typing import Literal
from stock_analyzer.data.research_contracts import ResearchDatasetId

Action = Literal["new", "enhance"]
ValidationKind = Literal["empirical", "official_semantics", "mixed", "portfolio_method"]

@dataclass(frozen=True)
class SupplementClaim:
    knowledge_id: str
    action: Action
    validation_kind: ValidationKind
    core_theory: str
    source_refs: tuple[str, ...]
    required_facts: tuple[ResearchDatasetId, ...]

@dataclass(frozen=True)
class SupplementEvidence:
    knowledge_id: str
    data_usable: bool
    overall_direction: str
    earlier_direction: str
    later_direction: str
    relationship_shape: str
    counter_evidence: str
    observations: dict[str, int | float | str]
```

Define `SOURCE_REFS` with every DOI/official URL in the approved design. Define `SUPPLEMENT_CLAIMS` in exact order 1–15, copying each complete theory and exact facts; do not shorten theories to slogans.

- [ ] **Step 5: Verify primary sources**

Open every DOI/publisher page and official page from the design. Record title, authors, journal/publisher, publication/effective date, market/sample, method and limitations in `/private/tmp/v3-supplement-source-check.md`.

If an original source cannot be verified, its candidate is later `discard`. Do not substitute a secondary source. If one of two sources fails, the other must independently support the full claim.

- [ ] **Step 6: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
git add src/stock_analyzer/knowledge_validation/supplement_validation.py tests/test_supplement_validation.py
git commit -m "test: freeze fifteen supplement knowledge claims"
```

---

### Task 2: Add only metadata required for honest source representation

**Files:**
- Modify: `src/stock_analyzer/knowledge/governance_models.py`
- Modify: `tests/test_knowledge_governance_models.py`

**Interfaces:**
- Produces: `ResearchDesign` plus ten required `KnowledgeTopic` values.
- Keeps registry schema version unchanged.

- [ ] **Step 1: Write failing tests**

```python
def test_theoretical_a_source_does_not_fake_sample_dates():
    payload = valid_a_source().model_dump()
    payload.update(
        research_design="theoretical",
        sample_start=None,
        sample_end=None,
        limitations=("This source is theoretical and claims no empirical A-share result.",),
    )
    assert SourceRecord.model_validate(payload).research_design.value == "theoretical"

def test_empirical_a_source_still_requires_sample_dates():
    payload = valid_a_source().model_dump()
    payload.update(sample_start=None, sample_end=None)
    with pytest.raises(ValidationError, match="sample"):
        SourceRecord.model_validate(payload)

def test_supplement_topics_are_exact():
    expected = {
        "market_state_reliability", "return_dispersion",
        "liquidity_trading_activity", "profitability_quality",
        "risk_overextension", "earnings_disclosure_hierarchy",
        "margin_financing", "pledge_conditional_risk",
        "disclosed_holder_trade", "portfolio_relationship",
    }
    assert expected <= {topic.value for topic in KnowledgeTopic}
```

- [ ] **Step 2: Confirm failure**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_governance_models.py -q
```

- [ ] **Step 3: Implement minimal enum/validation changes**

```python
class ResearchDesign(str, Enum):
    EMPIRICAL = "empirical"
    THEORETICAL = "theoretical"
    METHODOLOGICAL = "methodological"
```

Add `research_design: ResearchDesign = ResearchDesign.EMPIRICAL` to `SourceRecord`. Empirical A papers still require both sample dates. Theoretical/methodological A papers require no sample dates and a limitation explicitly stating that no empirical A-share result is claimed.

Add exactly the ten tested topics. Reuse existing `valuation_method`, `financial_turnaround`, `share_reduction`, `buyback_stage` and `business_transmission`.

- [ ] **Step 4: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_governance_models.py tests/test_knowledge_registry.py -q
git add src/stock_analyzer/knowledge/governance_models.py tests/test_knowledge_governance_models.py
git commit -m "feat: represent focused supplement metadata"
```

---

### Task 3: Implement market and trading formulas

**Files:**
- Modify: `src/stock_analyzer/knowledge_validation/supplement_validation.py`
- Modify: `tests/test_supplement_validation.py`

**Interfaces:**
- Produces: `market_state_observations`, `dispersion_observations`, `turnover_observations`, `illiquidity_observations`, `max_overextension_observations`, `chronological_relation`.
- Functions consume explicit DataFrames and do not read the warehouse.

- [ ] **Step 1: Write failing formula tests**

```python
def test_illiquidity_is_absolute_adjusted_return_per_amount():
    frame = pd.DataFrame({"adjusted_return_1d": [-0.02, 0.03], "amount": [2e8, 1e8]})
    out = illiquidity_observations(frame)
    assert out["amihud_illiquidity"].tolist() == pytest.approx([0.01, 0.03])

def test_market_state_uses_prior_and_current_windows_only():
    frame = pd.DataFrame({
        "formation_date": [date(2026, 1, 20)] * 5,
        "prior_market_return_20d": [-0.03] * 5,
        "market_return_20d": [0.05] * 5,
        "prior_relative_return_20d": [-2, -1, 0, 1, 2],
        "future_excess_return_20d": [-.02, -.01, 0, .02, .04],
    })
    out = market_state_observations(frame)
    assert set(out["market_state"]) == {"down_to_up"}
    assert out["relative_strength_group"].tolist() == [1, 2, 3, 4, 5]

def test_price_formulas_create_no_score_or_identity():
    forbidden = {"score", "weight", "rank_total", "institution", "main_force"}
    assert not (forbidden & set(illiquidity_observations(illiquidity_fixture()).columns))
```

- [ ] **Step 2: Confirm failure**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
```

- [ ] **Step 3: Implement exact formulas**

```python
def illiquidity_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    amount = pd.to_numeric(out["amount"], errors="coerce").replace(0, pd.NA)
    out["amihud_illiquidity"] = (
        pd.to_numeric(out["adjusted_return_1d"], errors="coerce").abs()
        / amount * 100_000_000
    )
    return out

def market_state_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    previous = out["prior_market_return_20d"].ge(0).map({True: "up", False: "down"})
    current = out["market_return_20d"].ge(0).map({True: "up", False: "down"})
    out["market_state"] = previous + "_to_" + current
    out["relative_strength_group"] = out.groupby("formation_date", group_keys=False)[
        "prior_relative_return_20d"
    ].transform(lambda values: pd.qcut(values.rank(method="first"), 5, labels=False) + 1)
    return out
```

`dispersion_observations` uses sample standard deviation (`ddof=1`) by formation date and industry. `turnover_observations` assigns within-date turnover terciles and prior-return quintiles. `max_overextension_observations` keeps prior-20-session maximum adjusted return, future excess return and future maximum drawdown separate.

`chronological_relation(frame, signal, outcome, date_col)` returns exactly `overall`, `earlier`, `later` and `observations` using Spearman correlation. Split sorted unique dates, never input row order.

- [ ] **Step 4: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
git add src/stock_analyzer/knowledge_validation/supplement_validation.py tests/test_supplement_validation.py
git commit -m "feat: add direct market and trading observations"
```

---

### Task 4: Implement profitability, valuation, cash and accrual formulas

**Files:**
- Modify: `src/stock_analyzer/knowledge_validation/supplement_validation.py`
- Modify: `tests/test_supplement_validation.py`

**Interfaces:**
- Produces: `profitability_valuation_observations`, `cash_accrual_observations`, `validate_profitability_valuation`, `validate_cash_accrual`.

- [ ] **Step 1: Write failing tests**

```python
def test_profitability_dimensions_remain_separate():
    frame = pd.DataFrame({
        "n_income_attr_p": [12.0], "total_hldr_eqy_exc_min_int": [100.0],
        "total_assets": [200.0], "revenue": [120.0], "oper_cost": [80.0],
        "assets_turn": [0.6], "pe_ttm": [20.0], "pb": [2.0], "ps_ttm": [3.0],
    })
    out = profitability_valuation_observations(frame)
    assert out.loc[0, "roe_recomputed"] == pytest.approx(0.12)
    assert out.loc[0, "roa_recomputed"] == pytest.approx(0.06)
    assert out.loc[0, "gross_profitability"] == pytest.approx(0.20)
    assert "profitability_score" not in out

def test_cash_and_accrual_use_prior_assets():
    frame = pd.DataFrame({
        "n_income_attr_p": [30.0], "n_cashflow_act": [18.0], "prior_total_assets": [120.0]
    })
    out = cash_accrual_observations(frame)
    assert out.loc[0, "cash_component"] == pytest.approx(0.15)
    assert out.loc[0, "accrual_component"] == pytest.approx(0.10)
```

- [ ] **Step 2: Confirm failure**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
```

- [ ] **Step 3: Implement formulas**

```python
def profitability_valuation_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["roe_recomputed"] = out["n_income_attr_p"] / out["total_hldr_eqy_exc_min_int"]
    out["roa_recomputed"] = out["n_income_attr_p"] / out["total_assets"]
    out["gross_profitability"] = (out["revenue"] - out["oper_cost"]) / out["total_assets"]
    out["asset_turnover"] = out["assets_turn"]
    return out

def cash_accrual_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["cash_component"] = out["n_cashflow_act"] / out["prior_total_assets"]
    out["accrual_component"] = (
        out["n_income_attr_p"] - out["n_cashflow_act"]
    ) / out["prior_total_assets"]
    return out
```

Validators report separate rank relationships for every profitability dimension and for cash/accrual, including overall/earlier/later. They return no `pass`, `score`, `weight` or `recommend`.

- [ ] **Step 4: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
git add src/stock_analyzer/knowledge_validation/supplement_validation.py tests/test_supplement_validation.py
git commit -m "feat: add direct profitability and accrual observations"
```

---

### Task 5: Implement official semantics and event observations

**Files:**
- Modify: `src/stock_analyzer/knowledge_validation/supplement_validation.py`
- Modify: `tests/test_supplement_validation.py`

**Interfaces:**
- Produces: `margin_observations`, `pledge_observations`, `holder_trade_observations`, `buyback_stage_observations`, `check_official_semantic_fields`.

- [ ] **Step 1: Write failing tests**

```python
def test_margin_net_flow_has_no_identity_claim():
    out = margin_observations(pd.DataFrame({
        "rzmre": [100.0], "rzche": [70.0], "rzye": [500.0], "rqye": [5.0], "rqyl": [2.0]
    }))
    assert out.loc[0, "financing_net_flow"] == pytest.approx(30.0)
    assert not ({"institutional_buy", "main_force"} & set(out.columns))

def test_holder_trade_uses_disclosed_direction():
    out = holder_trade_observations(pd.DataFrame({
        "in_de": ["IN", "DE"], "change_vol": [100.0, 40.0]
    }))
    assert out["signed_change_vol"].tolist() == [100.0, -40.0]

def test_buyback_preserves_provider_stages():
    stages = ["提议", "预案", "股东大会通过", "实施", "完成", "停止", "未通过"]
    out = buyback_stage_observations(pd.DataFrame({"process": stages}))
    assert out["buyback_stage"].tolist() == stages
    assert out["actual_execution"].tolist() == [False, False, False, True, True, False, False]

def test_pledge_never_calculates_liquidation_price():
    out = pledge_observations(pd.DataFrame({
        "pledge_ratio": [0.4], "return_20d": [-0.2],
        "debt_to_assets": [0.6], "n_cashflow_act": [-10.0],
    }))
    assert "liquidation_price" not in out
```

- [ ] **Step 2: Confirm failure**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
```

- [ ] **Step 3: Implement exact transformations**

```python
def margin_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["financing_net_flow"] = out["rzmre"] - out["rzche"]
    return out

def holder_trade_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    sign = out["in_de"].map({"IN": 1.0, "DE": -1.0})
    out["signed_change_vol"] = sign * out["change_vol"].abs()
    return out

def buyback_stage_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    allowed = {"提议", "预案", "股东大会通过", "实施", "完成", "停止", "未通过"}
    unknown = set(out["process"].dropna()) - allowed
    if unknown:
        raise ValueError(f"unknown repurchase stages: {sorted(unknown)}")
    out["buyback_stage"] = out["process"]
    out["actual_execution"] = out["process"].isin({"实施", "完成"})
    return out
```

`pledge_observations` keeps pledge ratio, price return, liquidity, debt/assets and operating cash flow separate; it creates no total score or liquidation price.

`check_official_semantic_fields` must require:

- item 8: forecast type/range/`available_at`; express type/yoy/`available_at`; income report/announcement/`available_at`; announcement title/time;
- item 10: `share_float.float_date`, `holder_trade.in_de/change_vol`, announcement title/time;
- item 14: `company_profile.business_scope/main_business`, `main_business.classification/item_name/bz_sales/bz_profit`, announcement title/time.

- [ ] **Step 4: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
git add src/stock_analyzer/knowledge_validation/supplement_validation.py tests/test_supplement_validation.py
git commit -m "feat: add direct event and rule observations"
```

---

### Task 6: Add read-only panels, portfolio method and orchestration

**Files:**
- Modify: `src/stock_analyzer/knowledge_validation/supplement_validation.py`
- Modify: `tests/test_supplement_validation.py`

**Interfaces:**
- Produces: `portfolio_common_exposure` and `validate_all_supplement_claims(warehouse_root: Path)`.
- Consumes all Task 3–5 functions.

- [ ] **Step 1: Write failing portfolio and read-only tests**

```python
def test_portfolio_reports_concentration_and_correlation_only():
    returns = pd.DataFrame({
        "A": [.01, .02, -.01], "B": [.01, .02, -.01],
        "C": [-.01, 0, .01], "D": [0, .01, 0], "E": [.02, -.01, .01],
    })
    result = portfolio_common_exposure(
        returns,
        industries={"A": "I1", "B": "I1", "C": "I2", "D": "I3", "E": "I4"},
        themes={"A": {"T1"}, "B": {"T1"}, "C": {"T2"}, "D": {"T3"}, "E": {"T4"}},
    )
    assert result["largest_industry_count"] == 2
    assert result["largest_theme_count"] == 2
    assert result["max_pairwise_correlation"] == pytest.approx(1.0)
    assert not ({"weights", "positions", "optimizer"} & set(result))

def test_real_validation_is_exact_deterministic_and_read_only():
    root = Path("local_warehouse")
    before = hashlib.sha256((root / "research.duckdb").read_bytes()).hexdigest()
    first = validate_all_supplement_claims(root)
    second = validate_all_supplement_claims(root)
    after = hashlib.sha256((root / "research.duckdb").read_bytes()).hexdigest()
    assert tuple(item.knowledge_id for item in first) == tuple(item.knowledge_id for item in SUPPLEMENT_CLAIMS)
    assert first == second
    assert before == after
```

- [ ] **Step 2: Confirm failure**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
```

- [ ] **Step 3: Implement only seven focused loaders**

Use these shared read-only helpers:

```python
def _fact_paths(root: Path, name: str) -> list[str]:
    paths = [
        str(path)
        for path in sorted((root / "facts" / name).glob("*/data.parquet"))
    ]
    if not paths:
        raise ValueError(f"no current fact partitions for {name}")
    return paths

def _query_frame(sql: str, parameters: list[object]) -> pd.DataFrame:
    with duckdb.connect() as connection:
        return connection.execute(sql, parameters).fetchdf()
```

Implement the seven named loaders with these exact output contracts:

| Loader | Required output columns |
|---|---|
| `_load_price_panel` | `formation_date`, `ts_code`, `industry_code`, `prior_market_return_20d`, `market_return_20d`, `prior_relative_return_20d`, `future_excess_return_20d`, `adjusted_return_1d`, `amount`, `turnover_rate_f_20d`, `max_return_20d`, `future_realized_volatility_20d`, `future_max_drawdown_20d` |
| `_load_financial_panel` | `formation_date`, `ts_code`, `report_period`, `n_income_attr_p`, `n_cashflow_act`, `prior_total_assets`, `total_assets`, `total_hldr_eqy_exc_min_int`, `revenue`, `oper_cost`, `assets_turn`, `pe_ttm`, `pb`, `ps_ttm`, `future_profitability`, `future_excess_return_20d` |
| `_load_margin_panel` | `formation_date`, `ts_code`, `rzye`, `rzmre`, `rzche`, `rqye`, `rqyl`, `financing_balance_change_20d`, `future_realized_volatility_20d`, `future_max_drawdown_20d` |
| `_load_pledge_panel` | `formation_date`, `ts_code`, `pledge_ratio`, `return_20d`, `amount_20d`, `debt_to_assets`, `n_cashflow_act`, `future_max_drawdown_20d` |
| `_load_holder_trade_panel` | `formation_date`, `ts_code`, `in_de`, `change_vol`, `next_report_profit_change`, `future_excess_return_20d` |
| `_load_buyback_panel` | `formation_date`, `ts_code`, `process`, `amount`, `vol`, `future_excess_return_20d`, `future_max_drawdown_20d` |
| `_load_official_field_map` | dictionary keys `earnings_forecast`, `earnings_express`, `income_statement`, `announcement`, `share_float`, `holder_trade`, `company_profile`, `main_business`; values are sorted schema-field tuples |

Each loader uses in-memory `duckdb.connect()` plus `read_parquet(?, union_by_name=true, hive_partitioning=false)`. Do not open the warehouse database for writes. Raise `ValueError` naming the loader and missing core column when its output contract cannot be produced.

Point-in-time rules:

- daily formation fields require `available_at` no later than formation close;
- financial records use first available company/report-period rows and same-quarter comparisons four reports apart;
- holder, pledge, repurchase, forecast and express form on disclosed `available_at` or next trading session;
- adjusted returns use both formation and future adjustment factors;
- future return, drawdown, volatility and later reports remain labels.

Use 20-session formation intervals to reduce duplicate overlapping samples, except daily dispersion keeps each date.

- [ ] **Step 4: Implement orchestration without automatic decisions**

`validate_all_supplement_claims` loads each panel once, calls the frozen functions, and returns exactly fifteen `SupplementEvidence` objects in claim order. Numerical evidence goes in `observations`. Set `data_usable=False` only when a core field/meaning is unavailable, not when the result is unfavorable. Do not add decision/pass/score/weight fields.

`portfolio_common_exposure` accepts exactly five candidate columns and raises `ValueError` otherwise.

- [ ] **Step 5: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
git add src/stock_analyzer/knowledge_validation/supplement_validation.py tests/test_supplement_validation.py
git commit -m "feat: run fifteen direct supplement validations"
```

---

### Task 7: Perform fixed scientific review and write binary results

**Files:**
- Create: `src/stock_analyzer/knowledge/supplement_validation_results.yaml`
- Modify: `tests/test_supplement_validation.py`

**Interfaces:**
- Produces schema `v3-supplement-validation-v1`.
- Consumes source notes and the Task 6 evidence.

- [ ] **Step 1: Export evidence to temporary JSON**

Run a one-off Python command importing `validate_all_supplement_claims` and serializing `dataclasses.asdict` results to `/private/tmp/v3-supplement-evidence.json`. Do not commit it.

- [ ] **Step 2: Review each candidate with fixed questions**

For every candidate, in order:

1. Was the original source verified?
2. Does the core theory preserve variables, direction, timing and conditions?
3. Can current data express each core variable without substitution?
4. What are overall, earlier and later directions?
5. Is the relation coherent or driven by one period/extreme group?
6. What is the strongest counter-evidence?
7. Is intended use no broader than evidence?

Use only if source/data pass and relevant evidence is broadly coherent without decisive counter-evidence. Discard for source failure, non-equivalent data, contradictory/unstable direction or overbroad use. Official semantics do not need return direction. No third result.

- [ ] **Step 3: Write exact result schema**

```yaml
schema_version: v3-supplement-validation-v1
generated_on: 2026-07-15
warehouse_sha256: 6da3469d3346ec23c4afa6bd72ab8673df37932048b79e3feb1d5d6288f3da5a
results:
  - knowledge_id: src_cn_factor_momentum_2023
    action: enhance
    validation_kind: empirical
    source_verification: verified
    core_theory: 完整理论原意
    required_data: [index_daily, equity_daily, industry_daily, theme_daily]
    evidence_summary: 总体、较早和较晚方向摘要
    counter_evidence: 最强反证
    decision: use
    reason: 能或不能直接用于系统的原因
```

The shown prose values illustrate required content. Final YAML must contain actual complete prose and exactly fifteen rows in claim order.

- [ ] **Step 4: Add result tests**

```python
def test_results_are_exact_binary_and_complete():
    payload = yaml.safe_load(Path(
        "src/stock_analyzer/knowledge/supplement_validation_results.yaml"
    ).read_text())
    rows = payload["results"]
    assert payload["schema_version"] == "v3-supplement-validation-v1"
    assert tuple(row["knowledge_id"] for row in rows) == tuple(
        item.knowledge_id for item in SUPPLEMENT_CLAIMS
    )
    assert all(row["decision"] in {"use", "discard"} for row in rows)
    assert all(
        row["core_theory"] and row["evidence_summary"]
        and row["counter_evidence"] and row["reason"]
        for row in rows
    )
    assert all(row["source_verification"] in {"verified", "failed"} for row in rows)
```

- [ ] **Step 5: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_supplement_validation.py -q
git add src/stock_analyzer/knowledge/supplement_validation_results.yaml tests/test_supplement_validation.py
git commit -m "data: decide fifteen supplement knowledge candidates"
```

---

### Task 8: Synchronize registry only from accepted results

**Files:**
- Modify: `src/stock_analyzer/knowledge/research_registry.yaml`
- Modify: `src/stock_analyzer/knowledge/strategy_v2_migration.yaml`
- Modify: `tests/test_knowledge_registry.py`
- Modify: `tests/test_knowledge_governance_acceptance.py`

**Interfaces:**
- Consumes result YAML as sole admission authority.
- Produces active sources/entries only for accepted new items and accepted enhancements.

- [ ] **Step 1: Replace obsolete mandatory-entry tests with result-driven tests**

```python
def test_registry_admits_exactly_accepted_new_results():
    registry = load_knowledge_registry(REAL_REGISTRY_PATH)
    entries = {entry.knowledge_id: entry for entry in registry.entries}
    rows = yaml.safe_load(Path(
        "src/stock_analyzer/knowledge/supplement_validation_results.yaml"
    ).read_text())["results"]
    for row in rows:
        if row["action"] == "new":
            assert (row["knowledge_id"] in entries) is (row["decision"] == "use")

def test_fifteen_candidates_never_use_method_only_as_escape():
    registry = load_knowledge_registry(REAL_REGISTRY_PATH)
    entries = {entry.knowledge_id: entry for entry in registry.entries}
    for claim in SUPPLEMENT_CLAIMS:
        if claim.knowledge_id in entries:
            assert entries[claim.knowledge_id].effect.value != "method_only"
```

Remove tests that require discarded Liu, Chan or Piotroski entries merely because they existed in the first migration.

- [ ] **Step 2: Register sources only for use results**

Copy exact metadata from Task 1. Use S for official sources and A for qualifying peer-reviewed sources. Mark Markowitz theoretical; empirical papers retain verified sample dates. Every source must be referenced by an accepted entry. Do not register a source whose only candidate is discarded.

- [ ] **Step 3: Add/enhance entries by fixed rules**

- accepted new: add exact ID with `analysis_evidence`, `observation_only` or `hard_boundary` according to validation kind;
- rejected new: add neither source nor entry;
- accepted `src_cn_factor_momentum_2023`: change from `method_only` to `analysis_evidence`, add Cheema support and exact validation reference;
- rejected `src_cn_factor_momentum_2023`: do not apply this enhancement; do not invent another state;
- accepted official enhancement: preserve original official primary source, add verified support, wording and fields;
- rejected official enhancement: preserve existing valid official entry unchanged;
- empirical use: `local_validation.status: validated` and a reference constructed as `f"supplement_validation_results.yaml#{row['knowledge_id']}"`;
- official semantics: `not_required` with rule/field-boundary reason;
- no score, weight, rank, position or fixed buy threshold.

Also reconcile already accepted thirteen-item foundations:

- add current `src_dechow_ge_schrand_2010` for multidimensional earnings-quality checking and change its migration target away from retired `src_piotroski_2000`;
- update `src_brown_warner_1985` with accepted Fama–Fisher–Jensen–Roll and MacKinlay supporting sources and direct-validation reference;
- do not restore any of the nine discarded legacy claims.

Other existing knowledge outside these fifteen is not revalidated or status-changed in this plan.

- [ ] **Step 4: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest   tests/test_knowledge_governance_models.py   tests/test_knowledge_registry.py   tests/test_knowledge_governance_acceptance.py -q
git add src/stock_analyzer/knowledge/research_registry.yaml   src/stock_analyzer/knowledge/strategy_v2_migration.yaml   tests/test_knowledge_registry.py tests/test_knowledge_governance_acceptance.py
git commit -m "data: admit directly validated supplement knowledge"
```

---

### Task 9: Prove capability and scene-specific use

**Files:**
- Modify: `tests/test_knowledge_capability.py`
- Modify: `tests/test_knowledge_selector.py`
- Modify: `tests/test_knowledge_governance_acceptance.py`

**Interfaces:**
- Consumes admitted registry and warehouse snapshot.
- Produces tests only; existing selector must suffice.

- [ ] **Step 1: Add real capability test**

```python
def test_every_accepted_supplement_entry_is_complete_on_current_warehouse():
    registry = load_knowledge_registry(Path(
        "src/stock_analyzer/knowledge/research_registry.yaml"
    ))
    rows = yaml.safe_load(Path(
        "src/stock_analyzer/knowledge/supplement_validation_results.yaml"
    ).read_text())["results"]
    accepted = {row["knowledge_id"] for row in rows if row["decision"] == "use"}
    snapshot = inspect_warehouse_capabilities(Path("local_warehouse"), date(2026, 7, 14))
    entries = {entry.knowledge_id: entry for entry in registry.entries}
    for knowledge_id in accepted:
        assessment = assess_entry_capability(entries[knowledge_id], snapshot)
        assert assessment.status is CapabilityStatus.COMPLETE, (knowledge_id, assessment)
```

- [ ] **Step 2: Add five representative scene tests**

Test only:

1. market environment with `market_state_reliability` and `return_dispersion`;
2. fundamentals with `profitability_quality` plus `valuation_method`;
3. event/risk topics one at a time;
4. company business with `business_transmission`;
5. portfolio with `portfolio_relationship`.

Expected IDs derive from accepted result rows. Assert a one-topic scene never returns all accepted entries. Do not create a 15×9 matrix.

- [ ] **Step 3: Prove no score or identity inference**

```python
def test_selection_has_no_factor_score_or_identity_claim():
    forbidden = {"score", "weight", "rank", "buy_probability", "position"}
    assert not (forbidden & set(KnowledgeSelection.model_fields))
    registry = load_knowledge_registry(REGISTRY_PATH)
    for entry in registry.entries:
        if any(t.value == "liquidity_trading_activity" for t in entry.topics):
            text = " ".join((entry.claim_summary, *entry.allowed_uses))
            assert "机构买入" not in text
            assert "主力" not in text
```

- [ ] **Step 4: Test and commit**

```bash
PYTHONPATH=src .venv/bin/python -m pytest   tests/test_knowledge_capability.py   tests/test_knowledge_selector.py   tests/test_knowledge_governance_acceptance.py -q
```

Expected: pass without changing `selector.py`. If existing module/topic filtering cannot satisfy tests, stop for a design amendment instead of adding a factor dispatcher.

```bash
git add tests/test_knowledge_capability.py tests/test_knowledge_selector.py tests/test_knowledge_governance_acceptance.py
git commit -m "test: verify focused supplement knowledge use"
```

---

### Task 10: Final scientific and regression verification

**Files:**
- Modify only if verification exposes a defect in a file already listed above.

- [ ] **Step 1: Run targeted suite**

```bash
PYTHONPATH=src .venv/bin/python -m pytest   tests/test_direct_knowledge_validation.py   tests/test_supplement_validation.py   tests/test_knowledge_governance_models.py   tests/test_knowledge_registry.py   tests/test_knowledge_capability.py   tests/test_knowledge_selector.py   tests/test_knowledge_use_audit.py   tests/test_knowledge_governance_acceptance.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run full suite**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Expected: all tests pass with only already-declared skips.

- [ ] **Step 3: Prove warehouse unchanged**

```bash
shasum -a 256 -c /private/tmp/v3-direct-supplement.before.sha256
```

Expected: `local_warehouse/research.duckdb: OK`.

- [ ] **Step 4: Run architecture searches**

```bash
rg -n "factor_score|buy_probability|position_size|main_force|institutional_buy"   src/stock_analyzer/knowledge src/stock_analyzer/knowledge_validation
rg -n "requests\.|httpx\.|urllib|playwright|selenium"   src/stock_analyzer/knowledge src/stock_analyzer/knowledge_validation
git diff --check
git status --short
```

Expected: no scoring/identity/network implementation in changed packages, no whitespace errors, only intended changes.

- [ ] **Step 5: Perform fixed five-part self-review**

Read all fifteen results and confirm:

1. core theory matches verified primary source;
2. each use entry has complete fields and source grade;
3. empirical use rows show overall, earlier, later and counter-evidence;
4. no decision uses a hard return or 20%-gain pass line;
5. registry wording explains meaning without institutions, guaranteed returns or automatic action.

Fix only objective discrepancies and rerun Steps 1–4.

- [ ] **Step 6: Commit only if verification caused corrections**

```bash
git add src/stock_analyzer/knowledge src/stock_analyzer/knowledge_validation tests
git commit -m "chore: finalize direct supplement verification"
```

Do not create an empty commit.

## Completion Gate

Do not claim completion until:

- exactly fifteen result rows exist;
- actions remain eleven new and four enhance;
- every row is use or discard;
- admitted new knowledge has verified S/A sources and complete current capability;
- rejected new candidates are absent from active registry;
- accepted enhancements preserve original valid boundaries;
- accepted Dechow/event foundations are callable without restoring nine discarded claims;
- no new data source, factor engine, score, recommendation, report or production integration exists;
- warehouse SHA-256 is unchanged;
- targeted and full tests pass.
