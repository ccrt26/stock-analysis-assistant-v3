# V3 Second-Round Knowledge Expansion Implementation Plan

> **Current status authority:** This plan does not prove production activation; current status is authoritative only in [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task. The user selected inline execution and does not authorize subagents unless later stated. Use `superpowers:test-driven-development` for every behavior or schema change and `superpowers:verification-before-completion` before completion.

**Goal:** Add the approved high-authority A-share knowledge supplements, including nine concise factor perspectives, while using only the frozen data foundation and keeping all new empirical knowledge non-scoring and locally bounded.

**Architecture:** Extend the existing governed YAML registry and its strict Pydantic contracts only where required for theoretical/methodological papers and missing topics. Reuse existing entries whenever possible, add only nonduplicative source/knowledge records, prove every active entry is executable against the current warehouse capability snapshot, and keep the selector scene-driven. No runtime network access, factor engine or production integration is added.

**Tech Stack:** Existing Python 3.11+, Pydantic, PyYAML, pytest and knowledge-governance package; no new dependency.

**Prerequisite:** Every task in [`2026-07-15-v3-local-knowledge-validation.md`](2026-07-15-v3-local-knowledge-validation.md) has passed, results are accepted by the user, and no study is `execution_failed`.

**Approved Design:** [`docs/superpowers/specs/2026-07-15-v3-local-validation-and-knowledge-expansion-design.md`](../specs/2026-07-15-v3-local-validation-and-knowledge-expansion-design.md)

## Global Constraints

- Work directly on current local `main`; do not create a branch/worktree.
- Do not change the data foundation, derived formulas, analysis/recommendation/report code, jobs, deployment or production activation.
- Do not add a crawler, runtime web call, automatic document download, generic factor library, factor total score, fixed weight, buy threshold or position rule.
- New factor sources must be official S or high-authority A. B sources are forbidden for the nine-factor group.
- Academic metadata is checked on the original publisher page or DOI, never a search snippet or secondary summary.
- Only concise metadata, method summary, limitations and URLs are committed; no copyrighted paper full text.
- Overseas results are `method_only` unless an exact accepted local validation reference applies; paper returns, deciles, holding periods and thresholds are never copied.
- All entries must pass current data capability assessment. Structurally unavailable data means rejection, not `limited` admission.
- Nine factor perspectives are comparison lenses, not nine mandatory per-stock steps. A selector test must prove scene-specific subsets.
- Existing `src_cn_program_trading_rules_2025` remains a hard wording boundary: daily/minute price-volume facts cannot identify institutions, main force, accumulation or distribution.

## Approved Nine-Factor Coverage

| Perspective | Runtime topic | Registry action |
|---|---|---|
| Market environment | `market_state_comparison` | add one method entry using Fama-French and Liu-Stambaugh-Yuan |
| Industry relative strength | existing `sector_price_persistence` | enhance existing two entries; no duplicate |
| Price trend and reversal | existing `market_price_persistence` | add Jegadeesh-Titman as contrast; retain A-share reversal boundary |
| Valuation | existing `valuation_method` | enhance `src_liu_stambaugh_yuan_2019` |
| Profitability and quality | `profitability_quality` | add cash-backed profitability entry; reuse Piotroski |
| Growth and improvement | `growth_improvement` | enhance Piotroski and official disclosure timing |
| Liquidity and trading activity | `liquidity_trading_activity` | add daily-data liquidity observation entry |
| Risk and overextension | `risk_overextension` | add volatility/MAX risk entry with replication warning |
| Portfolio relationship | `portfolio_relationship` | add simple concentration/correlation entry; no optimizer |

## Frozen New Academic Source IDs

```text
paper-fama-french-common-factors-1993
paper-jegadeesh-titman-momentum-1993
paper-ball-gerakos-linnainmaa-nikolaev-2016
paper-amihud-illiquidity-2002
paper-ang-hodrick-xing-zhang-volatility-2006
paper-bali-cakici-whitelaw-max-2011
paper-markowitz-portfolio-selection-1952
paper-demiguel-garlappi-uppal-2009
paper-harvey-liu-zhu-2016
paper-hou-xue-zhang-replication-2020
```

Their exact DOI floor is:

```python
FACTOR_DOI_FLOOR = {
    "paper-fama-french-common-factors-1993": "10.1016/0304-405X(93)90023-5",
    "paper-jegadeesh-titman-momentum-1993": "10.1111/j.1540-6261.1993.tb04702.x",
    "paper-ball-gerakos-linnainmaa-nikolaev-2016": "10.1016/j.jfineco.2016.03.002",
    "paper-amihud-illiquidity-2002": "10.1016/S1386-4181(01)00024-6",
    "paper-ang-hodrick-xing-zhang-volatility-2006": "10.1111/j.1540-6261.2006.00836.x",
    "paper-bali-cakici-whitelaw-max-2011": "10.1016/j.jfineco.2010.08.014",
    "paper-markowitz-portfolio-selection-1952": "10.1111/j.1540-6261.1952.tb01525.x",
    "paper-demiguel-garlappi-uppal-2009": "10.1093/rfs/hhm075",
    "paper-harvey-liu-zhu-2016": "10.1093/rfs/hhv059",
    "paper-hou-xue-zhang-replication-2020": "10.1093/rfs/hhy131",
}
```

The already registered Liu-Stambaugh-Yuan, Moskowitz-Grinblatt and Piotroski sources remain part of the floor. Jansen-Swinkels-Zhou (2021), broker factor manuals, platform articles and self-media are recorded as rejected/unused, not active factor authority.

## Frozen New Official Source IDs

```text
official-sse-listing-rules-2026
official-sse-margin-trading-2023
official-sse-stock-pledge-repurchase-2025
official-sse-buyback-guideline-2025
```

Use the official current pages frozen in design review:

- `official-sse-listing-rules-2026`: `https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/mainipo/c/c_20260424_10816589.shtml`; earnings forecast/express/correction and truthful disclosure stages.
- `official-sse-margin-trading-2023`: `https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/specific/margin/c/c_20250616_10782015.shtml`; financing and securities-lending definitions and account/contract boundaries.
- `official-sse-stock-pledge-repurchase-2025`: `https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/specific/repo/c/c_20250617_10782110.shtml`; pledge is financing collateral with conditional default/liquidity/legal risks.
- `official-sse-buyback-guideline-2025`: `https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/mainipo/c/c_20250516_10779134.shtml`; proposal, report, execution, completion/termination are distinct stages.

Existing CSRC reduction, repurchase and disclosure sources remain authoritative for unlock, holder trade and disclosure boundaries.

## File Responsibility Map

| File | Responsibility |
|---|---|
| `src/stock_analyzer/knowledge/governance_models.py` | Add source research-design distinction and six missing topics only |
| `src/stock_analyzer/knowledge/research_registry.yaml` | New/updated sources and active entries |
| `tests/test_knowledge_governance_models.py` | Theoretical/methodological source rules and topic enum tests |
| `tests/test_knowledge_registry.py` | DOI/source floor, nine-factor coverage, no-B/no-threshold/no-duplication tests |
| `tests/test_knowledge_capability.py` | Every new/updated active entry is complete on frozen warehouse capability |
| `tests/test_knowledge_selector.py` | Scene subsets, no mechanical traversal and no score/weight output |
| `tests/test_knowledge_governance_acceptance.py` | Offline, no production integration and complete review metadata |
| `docs/operations/v3-second-round-knowledge-review.md` | Fifteen analysis questions, accepted/rejected sources, uses and remaining gaps |
| `docs/operations/v3-second-round-knowledge-acceptance.md` | Final tests, hashes and “not activated” evidence |

---

### Task 1: Baseline and minimal source/topic contract extension

**Files:** Modify governance model and model tests.

- [ ] Capture prerequisite and warehouse baseline:

```bash
git status --short
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_validation_acceptance.py tests/test_knowledge_governance_models.py -q
shasum -a 256 local_warehouse/research.duckdb > /private/tmp/v3-knowledge-expansion.before.sha256
```

- [ ] Write failing tests for theoretical/methodological sources:

```python
def test_theoretical_a_paper_does_not_fake_sample_dates():
    source = SourceRecord.model_validate({**a_paper(), "research_design": "theoretical", "sample_start": None, "sample_end": None})
    assert source.research_design.value == "theoretical"

def test_empirical_a_paper_still_requires_sample_dates():
    with pytest.raises(ValidationError, match="sample"):
        SourceRecord.model_validate({**a_paper(), "research_design": "empirical", "sample_start": None, "sample_end": None})
```

- [ ] Implement:

```python
class ResearchDesign(str, Enum):
    EMPIRICAL = "empirical"
    THEORETICAL = "theoretical"
    METHODOLOGICAL = "methodological"
```

Add `research_design: ResearchDesign = EMPIRICAL`. Only empirical A papers require both sample dates; theoretical/methodological A papers require both absent and a limitation stating no empirical A-share result is claimed.

- [ ] Add only six missing `KnowledgeTopic` values: `market_state_comparison`, `profitability_quality`, `growth_improvement`, `liquidity_trading_activity`, `risk_overextension`, `portfolio_relationship`. Reuse the other three existing topics.
- [ ] Run model/governance regression tests; expected PASS. Commit `feat: support focused factor knowledge metadata`.

### Task 2: Register and verify the ten high-authority academic sources

**Files:** Modify registry and registry tests; create review document.

- [ ] Write failing tests requiring exact ten source IDs/DOIs, grade A, `peer_reviewed_paper`, authors, journal/publisher URL, method summary, limitations, and `last_verified_on: 2026-07-15`.
- [ ] Test that Markowitz is `theoretical`, Harvey-Liu-Zhu is `methodological`, and empirical sources have original sample periods. Test every non-A-share source contains the local-boundary sentence and no B source is in `FACTOR_SOURCE_IDS`.
- [ ] Open each original publisher page/DOI, record only metadata and concise paraphrases. If an original page cannot be verified, omit that source and stop the dependent factor entry; never substitute a secondary page.
- [ ] Add the ten `SourceRecord` YAML items. Do not add knowledge entries yet.
- [ ] Record Jansen-Swinkels-Zhou, broker manuals, platform articles and self-media in `v3-second-round-knowledge-review.md` as not used, with the reason “not needed because a higher-authority primary source covers the method” or “below source floor.”
- [ ] Run registry tests and offline-loader test; expected PASS. Commit `data: register high-authority factor sources`.

### Task 3: Add four current official sources and direct-rule boundaries

**Files:** Modify registry, registry tests and review document.

- [ ] Write failing tests requiring official SSE hosts, document/version dates, effective dates and exact current source IDs. Existing historical versions must not overlap current versions where they represent one rule lineage.
- [ ] Add official source records from the official pages only.
- [ ] Add/update these entries, all with `effect: hard_boundary` or `observation_only`, never a positive-return claim:

```text
src_cn_earnings_disclosure_hierarchy_2026
src_cn_margin_financing_semantics_2023
src_cn_pledge_conditional_risk_2025
src_cn_company_theme_disclosure_boundary_2026
```

- [ ] Update existing buyback entry with the 2025 SSE guideline as supporting source and state that proposal, intended amount, actual executed amount and completion are different facts.
- [ ] Update existing share-float/reduction knowledge to state unlock eligibility is not an executed sale. Add holder-trade knowledge only for disclosed actual change records (`holder_trade`); do not infer undisclosed selling.
- [ ] Required data remains existing `earnings_forecast`, `earnings_express`, `announcement`, `margin_detail`, `pledge`, `repurchase`, `share_float`, `holder_trade`, `company_profile` and `main_business`. If a required field is structurally absent, stop that entry.
- [ ] Run source/version/capability tests; expected PASS. Commit `data: add current A-share rule boundaries`.

### Task 4: Add nine factor perspectives without a factor engine

**Files:** Modify registry and registry/capability tests.

- [ ] Write failing exact coverage test:

```python
FACTOR_COVERAGE = {
    "market_environment": {"src_factor_market_environment"},
    "industry_relative_strength": {"src_cn_factor_momentum_2023", "src_moskowitz_grinblatt_1999"},
    "price_trend_reversal": {"src_cn_t1_contrarian_2024", "src_cn_price_limit_momentum_2025"},
    "valuation": {"src_liu_stambaugh_yuan_2019"},
    "profitability_quality": {"src_cash_backed_profitability_2016", "src_piotroski_2000"},
    "growth_improvement": {"src_piotroski_2000"},
    "liquidity_trading_activity": {"src_daily_liquidity_observation_2002"},
    "risk_overextension": {"src_risk_overextension_method"},
    "portfolio_relationship": {"src_portfolio_relationship_method"},
}
```

- [ ] Add only five new factor entries: `src_factor_market_environment`, `src_cash_backed_profitability_2016`, `src_daily_liquidity_observation_2002`, `src_risk_overextension_method`, `src_portfolio_relationship_method`. Enhance existing entries for the other four perspectives instead of duplicating them.
- [ ] Market entry requires `market_context` fields `equal_weight_return_20d`, `breadth_20d`, `return_dispersion_1d`, `realized_volatility_20d_annualized`, `market_turnover_amount`; it describes state and evidence requirements, not bull/bear labels or positions.
- [ ] Profitability entry requires income, balance, cash flow and financial indicators and compares cash-supported profitability; it cannot copy foreign factor returns.
- [ ] Liquidity entry requires `equity_daily` return/amount and `daily_basic` turnover. It explicitly calls Amihud a rough daily proxy, not order-book impact or trader identity.
- [ ] Risk entry requires `stock_trading_context` fields `realized_volatility_20d_annualized`, `atr_ratio_20d`, `price_location_60d`, `return_20d`, plus daily high/close/limits. MAX/volatility are counterevidence, not automatic negative scores; Hou-Xue-Zhang is a supporting replication warning.
- [ ] Portfolio entry requires candidate daily return history, industry/theme membership, beta/correlation. It permits concentration/correlation checks only and forbids optimized weights/positions.
- [ ] Every empirical new entry is `method_only` unless it exactly inherits an accepted result from Plan 1; even inherited validation cannot change `effect` to a score or action rule.
- [ ] Run registry and real capability tests. Every new/updated active entry must assess `complete`; otherwise remove it and record the gap. Commit `data: add nine focused factor perspectives`.

### Task 5: Prove scene-specific selection and prohibit scoring

**Files:** Modify selector tests and acceptance tests. `selector.py` is outside this task's change set.

- [ ] Write failing scene tests:

```python
def test_portfolio_question_selects_portfolio_method_not_all_factor_entries():
    selections = select_for(module="portfolio", topics=["portfolio_relationship"])
    assert {s.knowledge_id for s in selections} == {"src_portfolio_relationship_method"}

def test_liquidity_question_cannot_select_trader_identity_claim():
    selections = select_for(module="price_trading", topics=["liquidity_trading_activity"])
    assert "src_daily_liquidity_observation_2002" in ids(selections)
    assert all("institutional" not in " ".join(s.selection_reasons).lower() for s in selections)
```

- [ ] Add tests for one market, valuation, profitability and risk context. No context may return all nine perspectives unless it explicitly requests all topics; normal contexts return only intersecting topics.
- [ ] Assert `KnowledgeSelection` has no `score`, `weight`, `rank`, `buy_probability` or `position` field. Search the knowledge package for a sum of factor outputs.
- [ ] Run selector and acceptance tests. They must pass without modifying `selector.py`; if filtering is wrong, stop and request a design amendment rather than adding a factor dispatcher. Commit `test: verify scene-specific factor knowledge selection`.

### Task 6: Complete the simple fifteen-question knowledge review

**Files:** Finalize review document and registry tests.

- [ ] For each of the fifteen analysis questions in the design, record: practical question, current data, active knowledge IDs, what the knowledge can answer, what it cannot answer, and remaining gap. This is a linear checklist, not a 15x9 matrix.
- [ ] Include the agreed direct additions: market state/dispersion; turnover not equal momentum; profitability+valuation; cash-backed earnings; liquidity; MAX/overextension; disclosure hierarchy; margin semantics; unlock not sale; pledge conditional risk; disclosed holder trades; actual buyback stage; company-hotspot disclosure link; simple portfolio concentration.
- [ ] Explicitly reject topics requiring new continuous product prices, inventory, production, industry sales, social sentiment, analyst forecasts, order book, tick orders or account identity.
- [ ] Add a test that every current knowledge ID named in the review exists and every rejected structurally unavailable topic is absent from active registry requirements.
- [ ] Run registry/capability tests; expected PASS. Commit `docs: complete second-round knowledge review`.

### Task 7: Final scientific and architecture acceptance

**Files:** Create `docs/operations/v3-second-round-knowledge-acceptance.md` only.

- [ ] Run targeted suite:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_governance_models.py tests/test_knowledge_registry.py \
  tests/test_knowledge_capability.py tests/test_knowledge_selector.py \
  tests/test_knowledge_use_audit.py tests/test_knowledge_governance_acceptance.py \
  tests/test_knowledge_validation_acceptance.py -q
```

- [ ] Run full suite and immutable checks:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
shasum -a 256 -c /private/tmp/v3-knowledge-expansion.before.sha256
rg -n "score|weight|buy_probability|position_size" src/stock_analyzer/knowledge
rg -n "stock_analyzer.knowledge" src/stock_analyzer/analysis src/stock_analyzer/ops src/stock_analyzer/reports || true
```

Expected: all tests pass; warehouse hash unchanged; no new score/weight; no new production integration.

- [ ] Acceptance document records exact new/updated source and knowledge IDs, rejected sources, factor coverage, capability results, selector scenarios, test counts, warehouse hashes and: “新增知识仍未接入评分、推荐、正式报告、自动任务或生产。”
- [ ] Commit `docs: verify second-round knowledge expansion`.

## Stop Conditions

Stop if an original source cannot be verified; a source falls below the approved floor; a factor needs unavailable core data; a new data interface/formula is proposed; a B source would be required; two entries duplicate the same use; selector would need a score; warehouse hash changes; a production import appears; or any full-suite regression fails.

After this plan passes, return to joint design of market environment and selection logic. Do not proceed automatically into scoring, ranking, recommendation or report implementation.
