# V3 Phase 3 Strategy V2 Design

Date: 2026-07-10

Status: approved design basis, pending implementation plan

Related artifacts:

- Architecture map: `docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-architecture.html`
- V3 base design: `docs/superpowers/specs/2026-07-07-stock-analysis-assistant-v3-design.md`
- Phase 2 deployment design: `docs/superpowers/specs/2026-07-09-v3-phase-2-cloudflare-automation-design.md`

## 1. Purpose

Phase 3 upgrades V3 from a report generator into a trading-decision assistant.

The system must produce a fresh daily recommendation report and fresh focus-stock tracking analysis on every trading day. The goal is not to output generic stock commentary. The goal is to help decide which A-share stocks may have meaningful 2-8 week upside, whether they deserve continued attention, what action range is reasonable, how large the position could be, and what would prove the thesis wrong.

The first version optimizes for useful decision support:

- Daily recommendation discovers opportunities.
- Focus watchlist tracks high-priority stocks.
- Focus analysis must support trading decisions with clear action suggestions, quantitative position ranges, reasons, and invalidation conditions.
- The system must use local knowledge and structured evidence first; the LLM only turns evidence into readable analysis.

This design does not connect to a broker, does not auto-trade, and does not execute orders.

## 2. Core Principles

### 2.1 Knowledge First, LLM Second

Analysis must start from local knowledge, structured data, and deterministic evidence generation.

The LLM may:

- Explain structured evidence in plain language.
- Organize evidence into the approved report structure.
- Translate indicators into "what happened, why it may have happened, what it may mean."
- Draft action suggestions from explicit evidence, risk boundaries, holding state, and invalidation conditions.

The LLM must not:

- Invent company business facts, news, catalysts, policies, financials, or risks.
- Promote a stock based on model intuition.
- Override official hard constraints.
- Create unsupported trade instructions.
- Hide missing data behind fluent language.

### 2.2 Knowledge Library Must Be Used Deliberately

The V2 knowledge base is not decorative. Phase 3 must map it into the analysis framework before implementation.

V3 uses the already-approved knowledge policy:

- Official S-grade knowledge becomes hard constraints.
- Research S/A knowledge becomes explanation and counter-evidence rules.
- B-grade or unclear-boundary knowledge remains observation or future enhancement.

The architecture HTML must list which knowledge entries are used, where they are used, which are not yet used, why they are not used, and whether missing data blocks core analysis.

If a selected knowledge entry lacks required data, the system must first try to obtain that data from a primary source, a backup source, or local cache. Only after that can it mark the entry as temporarily unavailable.

### 2.3 Wide Data Local, Narrow Evidence Cloud

Large-scale data and repeated calculations stay local.

`local_warehouse` is the calculation warehouse:

- Full market historical bars.
- Daily basic data.
- Stock basic data.
- Technical indicators.
- Market, board, industry, concept, valuation, risk, and event datasets as they are added.
- Backtests and recalculations.

Supabase is the decision ledger:

- Daily recommendation evidence snapshots.
- Focus watchlist state.
- Entry thesis.
- Daily tracking summary.
- Action recommendation summary.
- Manual holding summary.
- 5/20/40 trading-day evaluation results.

Reports are the user-facing product layer.

### 2.4 Reports Are Results, Not Knowledge Dumps

Daily reports and focus reports should not list long literature citations or knowledge-rule inventories. They should show the analysis result, recommendation, reason, risk, action range, and invalidation condition.

The separate HTML architecture page is where knowledge usage is made transparent for design and optimization.

## 3. Product Outputs

Every trading day must produce:

1. Daily recommendation report.
2. Focus watchlist tracking report.
3. Machine-readable evidence snapshots for recommendations and focus stocks.
4. Operational status for whether recommendation and focus reports were generated.

If required data is missing, the system still produces an explicit data-insufficient output with attempted recovery steps and impact. It must not silently skip a trading day.

## 4. Daily Recommendation

Daily recommendation is the discovery layer. It is not the focus watchlist.

Phase 3 V1 constraints:

- Show at most 10 stocks.
- Do not display total numeric scores to the user.
- Internal ranking scores may exist for sorting and evaluation, but they must be decomposable into explicit evidence.
- Each recommended stock shows a short evidence card.
- Each evidence card must explain:
  - What happened.
  - Why it may have happened.
  - What it may mean.
  - Main risk.
  - What is still needed before focus-watchlist entry.
  - Focus-entry progress.

Example focus-entry progress:

- Observation day 2 of 5.
- Met focus criteria on 2 of the last 5 trading days.
- Still needs board confirmation, company data completion, or risk-reward confirmation.

Daily recommendation may use broader local screening. This includes technical, price-volume, valuation, liquidity, board strength, event, and risk factors. The user-facing report must not mechanically repeat indicators.

## 5. Focus Watchlist

The focus watchlist is the tracking layer.

Definition:

> A focus stock is a stock that the system or user believes may produce meaningful upside in the next 2-8 weeks, or a shorter window, and therefore deserves daily decision-oriented tracking.

Phase 3 V1 constraints:

- System-selected focus watchlist has at most 5 stocks.
- Manually added focus stocks do not count against the system-selected limit.
- Frontend does not split "system focus" and "manual focus" into separate pools.
- Internal records must preserve source: system entry or manual entry.
- Manually added stocks are analyzed honestly; the system must not praise them just because the user added them.

## 6. Focus Entry Logic

Focus entry must start from a 2-8 week upside thesis, not from a raw score.

A valid focus-entry thesis answers:

- What is the upside driver?
- Why now?
- Is market or board context supportive?
- Does price-volume behavior confirm rather than contradict the thesis?
- Are risk and liquidity acceptable?
- Is the upside/downside balance attractive enough?

First-version target:

- Expected upside: roughly 10% or more.
- Reference risk-reward: upside/downside near or above 1.5:1.
- These are decision guides, not mechanical gates. The final requirement is sufficient evidence and clear reasoning.

System entry:

- Observe for 5 trading days.
- In the last 5 trading days, at least 3 must support the focus-entry thesis.
- Generate and freeze a full entry thesis report when the stock enters focus.

Manual entry:

- User may add by stock code only.
- Optional attention reason may be supplied, such as theme, existing holding, unusual move, or external recommendation.
- If supplied, the system validates that reason during analysis.

## 7. Focus Analysis Framework

Focus analysis uses six modules.

### 7.1 Company and Business

Answers:

- What does the company do?
- What are the main business lines?
- Which board and industry does it belong to?
- Does a market concept correspond to real business, or is it mostly imagination?

Required first-version data:

- Stock code and name.
- Exchange and board.
- Company profile or business summary.
- Industry classification.
- Concept or theme tags where available.

### 7.2 Fundamentals and Valuation

Answers:

- Is there business or financial support for the upside thesis?
- Is performance improving, stable, or deteriorating?
- Is valuation reasonable, expensive, or speculation-heavy?

Required first-version data:

- Market cap or float market cap.
- PE/PB where available.
- Revenue/profit summary where available from primary or backup sources.
- Profitability and cash-flow summary where available.

If reliable fundamentals are not available, the report must state that fundamental support is incomplete and must not use fundamentals as a strong positive claim.

### 7.3 Market and Board Context

Answers:

- Is the market environment supportive?
- Is the stock's industry, board, or concept moving with it?
- Is the stock isolated, or part of a broader group move?

First-version analysis:

- Broad market state.
- Board/industry/concept relative strength.
- Market breadth and volume context where available.
- Whether risk appetite supports the type of stock.

### 7.4 Trend and Price-Volume

Answers:

- Is the stock technically close to a usable opportunity?
- Is it breaking out, confirming, pulling back constructively, topping, or showing false strength?
- Is it too extended to chase?

First-version indicators may include:

- Moving averages.
- 20/60 day trend.
- Relative strength.
- MACD.
- RSI.
- KDJ.
- ATR or volatility.
- Volume and turnover.
- Support/resistance and invalidation level.
- Gap, limit-up/limit-down, abnormal move, and overheat checks.

These are not independent votes if they derive from the same price series. The analysis must avoid counting repeated technical evidence as separate independent proof.

### 7.5 Events and Catalysts

A-share short and medium-term moves often depend on policy, themes, announcements, and catalysts. This module is part of Phase 3 V1, not a late optional add-on.

Evidence levels:

- Strong evidence: official company announcements, regulator or exchange information, official policy documents.
- Supporting evidence: concept tags, industry news, high-quality public information.
- Observation only: rumors, social media heat, low-source material. These do not support a formal conclusion in V1.

The report must distinguish:

- What happened.
- Source reliability.
- Whether the event is new or already priced in.
- Why the event matters for the next 2-8 weeks.
- What would show the catalyst failed.

### 7.6 Risk and Counter-Evidence

Answers:

- What could prove the thesis wrong?
- What risk is the market ignoring?
- Is the stock too volatile, illiquid, extended, expensive, or event-dependent?
- Is there official or company-level risk?

Risk categories:

- Official hard risk.
- Liquidity and trading risk.
- Technical invalidation.
- Board or concept fading.
- Fundamental deterioration.
- Event/catalyst failure.
- Valuation overextension.
- Holding concentration risk.

Every action recommendation must include invalidation or reverse-signal conditions.

## 8. Focus Daily Tracking

Every focus stock must be tracked every trading day.

Tracking purpose:

> Decide whether the stock is getting closer to a usable trading opportunity, moving away from it, or becoming too risky.

Tracking separates:

- Short-term signal: 1-5 trading days.
- Medium-term thesis: 2-8 weeks.

Each focus update must cover:

- What changed today or recently.
- Whether the original upside thesis is stronger, weaker, or unchanged.
- Whether any new policy, announcement, news, concept, board, or risk change matters.
- What action range is reasonable now.
- What invalidates that action range.
- Whether the user needs to confirm continued focus or removal.

## 9. Action and Position Suggestions

The system must provide clear, quantified decision support. Empty phrases such as "may rise, watch risks" are not acceptable.

Allowed suggestions include:

- No participation for now.
- Continue watching.
- Wait for confirmation.
- Avoid chasing.
- Small exploratory position.
- Increase attention.
- Consider raising position if confirmation occurs.
- Risk rising; reduce exposure or avoid new exposure.
- Suggest confirming whether to remove from focus.

Suggestions must include:

- Suggested action.
- Suggested position range when relevant.
- Reasoning.
- Required condition or confirmation.
- Invalidation condition.
- Risk if wrong.

No hard universal position cap is set. Position sizing depends on:

- Market condition.
- Board strength.
- Stock-specific thesis quality.
- Risk-reward.
- Volatility.
- Liquidity.
- User's manually synced holding state.

The system may suggest aggressive positioning only when the report explains why the evidence is sufficient, what could go wrong, and how to stage the action. A high position suggestion must be part of the daily focus report, not a separate report.

The system does not place trades.

## 10. Manual Holdings and User Action Records

The first version does not connect to a broker. The user manually syncs actions.

Local holding/action records include:

- Stock code.
- Current state: held, sold, partially sold.
- Current position percentage.
- Current share count.
- Cost price.
- Buy date.
- Buy price.
- Buy quantity.
- Sell date.
- Sell price.
- Sell quantity.
- Notes.

Records are local-first. Supabase stores only the summary needed by reports, such as held/not held, approximate position band, and last action state.

The system must adjust suggestions based on holding state. A stock not yet held and a stock already held at a high percentage must not receive the same suggestion.

## 11. Data Requirements

### 11.1 Data Levels

Data is divided into:

- Required data: core fields without which focus analysis cannot be complete.
- Enhanced data: improves analysis but does not block all conclusions.
- Observation data: useful for future optimization but not relied on for Phase 3 V1 conclusions.

A field can be marked required only if it has:

- A primary source.
- A backup source or reliable local-cache fallback.
- A clear impact on analysis quality.

If required data is unavailable:

1. Try primary source.
2. Try backup source.
3. Try local cache or existing materials.
4. If still unavailable, produce a data-insufficient analysis and explain what is missing, why it matters, and what source must be added.

### 11.2 Primary and Backup Sources

Tushare remains the primary source where available.

Backup sources may include AkShare, Eastmoney, Sina, Tencent Finance, local knowledge assets, existing reports, and local cache, depending on data type and reliability.

The implementation plan must map each required data family to exact primary and backup collection paths before coding.

## 12. Supabase and Local Storage

Local warehouse stores wide data and recalculation inputs.

Supabase stores decision ledger data:

- Recommendation snapshot.
- Focus entry thesis.
- Focus daily update.
- Action recommendation summary.
- Manual holding summary.
- Knowledge-rule match summary.
- Evaluation tasks and results.

Supabase must not become the full-market factor warehouse in Phase 3 V1.

## 13. Knowledge Usage Architecture Page

The HTML architecture page is a permanent design and optimization artifact.

It must show:

- Daily recommendation flow.
- Focus analysis flow.
- Six analysis modules.
- Which knowledge entries are used.
- Which module each knowledge entry supports.
- Rule type: hard constraint, explanation, counter-evidence, method guard, or observation.
- Whether required data exists.
- Whether missing data affects core analysis.
- Which knowledge entries are not yet used.
- Why unused entries are unused: missing data, out of scope, first-version deferral, unclear boundary, observation-only, or deletion candidate.
- Next action: use now, add data source, keep for later, downgrade, or consider removal.

Reports do not show this full knowledge map.

## 14. Evaluation

Every focus entry freezes its original thesis and evidence. Later outcomes append evaluation; the system must not rewrite past reasoning.

Evaluation windows:

- 5 trading days.
- 20 trading days.
- 40 trading days.

Evaluation checks:

- Did the stock move as expected?
- Did the invalidation condition occur?
- Was the action suggestion useful?
- Was the position suggestion too conservative or too aggressive?
- Did the knowledge rule help or mislead?
- Did missing data affect result quality?
- Did the LLM add unsupported content?

Evaluation should improve future rules and data priorities.

## 15. Subagent and Model Allocation Guidance

Phase 3 design, financial-analysis logic, knowledge mapping, data-source selection, safety review, and final code review require high-accuracy models. The default for these tasks should be GPT-5.5 xhigh or the strongest available equivalent.

Lower-cost models may be used only when the task is fully specified and low judgment:

- Mechanical file edits from an approved plan.
- Formatting documentation.
- Running tests.
- Producing simple static HTML from an already approved structure.

Do not assign lower-tier models to:

- Strategy design.
- Financial logic.
- Factor selection.
- Knowledge-to-module mapping.
- Risk/positioning logic.
- Data-quality decisions.
- Code review for behavior changes.

The implementation plan must specify model expectations per task so execution agents do not improvise.

## 16. Implementation Boundaries

Phase 3 design approval does not authorize immediate production trading automation.

Allowed in Phase 3 implementation:

- Improve recommendation logic.
- Add focus analysis framework.
- Add data-source mapping and fallback strategy.
- Add local holding/action records.
- Add focus tracking reports.
- Add HTML architecture map.
- Add Supabase narrow evidence writes.
- Add tests and review.

Not allowed in Phase 3 V1:

- Broker connection.
- Auto-order placement.
- Unreviewed use of rumors as evidence.
- LLM-only stock promotion.
- Full-market factor writes to Supabase.
- Silent report generation when required data is missing.

## 17. User Handoff for Next Thread

When this design and the architecture HTML are committed, the next coding thread should start from this instruction:

> Continue stock-analysis-assistant-v3 Phase 3 Strategy V2 implementation from `docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-design.md` and `docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-architecture.html`. Use Superpowers writing-plans first. Create a detailed implementation plan before coding. Use GPT-5.5 xhigh for strategy, knowledge mapping, data-source design, financial logic, and review tasks; only use lower-tier models for fully specified mechanical work. Preserve the rule that local knowledge and structured evidence come before LLM explanation. Do not run real production writes without explicit user approval.

## 18. Open Implementation Decisions

The implementation plan must still specify:

- Exact primary and backup APIs per required data family.
- Exact local file or table format for manual holding/action records.
- Exact Supabase schema additions for Phase 3 narrow evidence.
- Exact report JSON contract.
- Exact HTML report page changes.
- Backtest and replay scope for first validation.
- Which existing tests are extended and which new tests are required.

