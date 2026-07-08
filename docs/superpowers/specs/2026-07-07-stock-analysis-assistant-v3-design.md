# Stock Analysis Assistant V3 Design

Date: 2026-07-07
Status: Approved design for implementation planning
Project root: `/Users/ccrt/股票分析助手`

## 1. Purpose

The third-generation stock analysis assistant helps a user who is not deeply familiar with stock investing make better follow-up decisions on Mainland China A-shares. It must automate data acquisition, processing, analysis, report generation, and later evaluation, while avoiding the two failures seen in earlier versions:

- Version 1 had many ideas but was too scattered and simple.
- Version 2 had richer modules, data, roles, gates, and knowledge assets, but became too complex to run reliably.

V3 must be a report-first, scientifically constrained analysis product. Its daily output must feel like a stock analysis report, not a system run report.

## 2. Product Positioning

V3 is a decision-support assistant, not a brokerage system and not an automatic trading system.

The system may recommend stocks for observation, but it must not output unconditional buy/sell commands, automatic position instructions, or guaranteed-return language. Its allowed action vocabulary is:

- `进入观察`
- `继续观察`
- `高风险观察`
- `降级观察`
- `剔除观察`
- `数据不足，不形成结论`

The first product stage focuses on a 2-8 week observation horizon. This horizon is short enough to support practical follow-up, but long enough to avoid pure intraday noise.

## 3. Chosen Approach

Use a two-layer stock analysis product:

- A fixed entry dashboard at `reports/index.html`.
- Daily report archives and stock-specific report pages behind that entry.

The homepage presents the latest daily decision dashboard by default and supports filtering by date and stock. The user should not need to browse dated folders manually.

The project should not recreate Version 2's large governance system. It should reuse Version 2's useful data-source and knowledge-base assets, but express them through a smaller set of runnable modules.

## 4. Core Architecture

The system has six lightweight modules.

### 4.1 Data Acquisition

Tushare is the primary structured data source. Existing credentials must be reused without exposing secret values. The current machine has `/Users/ccrt/.tushare_token`, and Version 2 also detected `TUSHARE_TOKEN` and `BIYING_LICENCE`.

Free or public sources should be used as supplements and fallbacks, including Eastmoney, AkShare, Sina, Tencent, CNINFO, and Baostock where stable and legally usable.

Data health must be split into four separate checks:

- Credential presence
- Network reachability
- API response availability
- Field-level consumability for analysis

This prevents a vague `WARN` state from hiding whether the problem is a missing token, blocked network, empty response, schema drift, or an unusable field.

### 4.2 Stock Pool Management

The system scans all A-shares after cleaning. It must remove stocks that are not suitable for a beginner-oriented 2-8 week observation workflow, including ST, delisting-risk, abnormal trading status, severe suspension, very short listing history, extremely low liquidity, and serious official risk events.

The system maintains two distinct pools:

- Daily recommendation candidates: discovery layer.
- Focus watchlist: tracking layer.

These are analysis-state concepts, not just display categories.

### 4.3 Knowledge Base

V3 officially uses selected Version 2 knowledge assets rather than leaving them as role backup material.

Version 2 contains 74 external seed knowledge sources: 16 official materials and 58 academic or research materials. Source grades include 56 S-grade, 13 A-grade, and 5 B-grade sources.

V3 enables them in tiers:

- Official S-grade materials become formal hard constraints.
- Research S/A materials become formal explanation and counter-evidence rules.
- B-grade or unclear-boundary materials remain in the observation layer.

The system must not copy Version 2's full role workflow. Knowledge must be converted into lightweight rules with source, scope, forbidden use, report phrasing, and evaluation hooks.

### 4.4 Analysis Engine

The analysis engine uses layered depth:

- Full-market lightweight screening
- Candidate deep analysis
- Final report-grade analysis for a small number of stocks

The system does not assume that more indicators mean more scientific analysis. Each factor must have stable data, independent information value, theoretical or empirical support, an evaluation method, and acceptable runtime cost.

### 4.5 Report Product

Reports must be stock-analysis-first. System state is only shown as a trust indicator, not as the main content.

The fixed report entry is:

- `reports/index.html`

Daily archives and stock pages may live behind it, for example:

- `reports/daily/YYYY-MM-DD/index.html`
- `reports/daily/YYYY-MM-DD/stocks/<code>.html`
- `reports/data/*.json`

The exact paths may be adjusted during implementation, but the fixed user entry must remain stable.

### 4.6 Evaluation and Learning

Post-evaluation is not a simple 5/20/40 day return check. It evaluates:

- Whether the original observation result was validated
- Whether the analysis method was valid
- Whether the knowledge rule should be kept, upgraded, downgraded, split, or deprecated

The goal is future transferability, not a beautiful explanation of the past.

## 5. Daily Data Flow

Daily execution should run through one main command:

```bash
python3 -m stock_analyzer run-daily --trade-date YYYY-MM-DD
```

During source-tree development before editable installation, use:

```bash
PYTHONPATH=src python3 -m stock_analyzer run-daily --trade-date YYYY-MM-DD
```

Current MVP boundary: until real market ingestion exists, the non-fixture command above must fail clearly. Local sample report generation requires explicit `--fixture-mode`.

The command performs:

1. Startup checks: trading day, credentials, source availability, network, last successful run.
2. Full A-share cleaning: status, ST/delisting risk, listing age, suspension, liquidity, major risk.
3. Lightweight feature generation: trend, liquidity, valuation, quality, industry/style, risk events.
4. Daily recommendation generation: precise candidates only, not a broad 20-50 stock list.
5. Focus watchlist state update: enter, continue, downgrade, exit, or remain empty.
6. Candidate evidence pack generation.
7. Knowledge rule matching and counter-evidence checks.
8. LLM explanation enhancement from structured evidence only.
9. Report generation for the fixed entry and daily stock pages.
10. Evaluation task registration.

If a non-trading day is detected, the system may run knowledge maintenance and post-evaluation, but it should not force a new recommendation report unless there is a clear reason.

## 6. Daily Recommendation vs Focus Watchlist

The relationship between daily recommendations and the focus watchlist must be a formal state machine.

### 6.1 Daily Recommendation Candidates

Daily recommendation candidates are the discovery layer. They answer:

> What new or reappearing opportunities are worth examining today?

Rules:

- At most around 10 stocks per day.
- The list may change daily.
- A daily recommendation is not automatically a focus stock.
- If fewer than 10 stocks satisfy standards, output fewer than 10.
- The system must never lower standards to fill a quota.

### 6.2 Focus Watchlist

The focus watchlist is the tracking layer. It answers:

> Which stocks deserve continuous 2-8 week attention now?

Rules:

- It does not need to contain 10 stocks.
- It may contain 0-5 stocks if only that many are clear enough.
- A stock does not leave the focus watchlist merely because it was not reselected as a daily recommendation the next day.
- Each focus stock must carry entry date, entry reason, original evidence, invalidation conditions, daily state updates, and exit reason.

### 6.3 Entering the Focus Watchlist

A daily recommendation may enter the focus watchlist only when all of the following hold:

- No major hard-constraint risk is present.
- The signal is repeated, persistent, or supported beyond a one-day impulse.
- At least two of macro, industry, and individual-stock layers support the case.
- Counter-evidence is controllable and explicitly recorded.
- The data quality is sufficient for a formal observation conclusion.
- The case fits a 2-8 week observation horizon, not just one-day sentiment.
- The system can state why the stock was upgraded from recommendation to focus.

### 6.4 Exiting or Downgrading the Focus Watchlist

A focus stock exits or is downgraded when any of the following hold:

- A predefined invalidation condition is hit.
- The core evidence behind the original thesis disappears.
- Market or industry environment turns materially hostile.
- An official hard-constraint risk or major negative event appears.
- Multiple evaluation windows fail to validate the original logic.
- New counter-evidence becomes stronger than supporting evidence.
- Data quality falls below the threshold for continued judgment.
- Evaluation shows the original upgrade was overfit, noisy, or mistaken.

## 7. Scientific Analysis Framework

The analysis engine has three depth levels.

### 7.1 Layer 1: Full-Market Lightweight Screening

Purpose: reduce the full A-share universe into a smaller research queue without making a final recommendation.

Analyze:

- Trading eligibility: ST, delisting risk, suspension, listing age, limit-up/limit-down anomalies.
- Liquidity: turnover, traded value, persistent low volume, extreme volatility.
- Market environment: major index trend, broad market risk appetite.
- Industry and style: relative strength by industry, large/small cap, growth/value.
- Basic trend: 20-day and 60-day direction, relative strength, drawdown.
- Basic quality: loss status, cash-flow abnormality, debt pressure, financial-report gaps.
- Obvious risk events: penalties, reductions, pledge risk, delisting, major negative announcements.

Output: internal research queue only.

### 7.2 Layer 2: Candidate Deep Analysis

Purpose: determine whether a candidate has genuine 2-8 week observation value.

Analyze:

- Macro and broad market alignment: index trend, risk appetite, liquidity environment.
- Industry alignment: relative performance, policy/event catalyst, sector fund flow.
- Technical structure: trend, price-volume behavior, volatility, support/resistance, false-breakout risk.
- Valuation and financial quality: valuation percentile, earnings quality, cash flow, leverage, growth.
- Capital and trading structure: turnover structure, margin trading, northbound/major-fund signals when reliable.
- Announcements and events: earnings preview, reduction, buyback, contracts, regulatory inquiries, penalties.
- Counter-evidence: unsupported signals, noisy signals, conflicting evidence.
- Data quality: what is trusted, what is missing, and whether missing fields affect the conclusion.

Output: candidate evidence package.

### 7.3 Layer 3: Final Report-Grade Analysis

Purpose: produce a report-grade explanation for a small number of final stocks.

Each final stock must include:

- One-sentence conclusion
- Why it is worth observing now
- Macro-industry-stock logic chain
- Supporting evidence separated by source category
- Counter-evidence and risks
- Invalidation conditions
- Follow-up observation plan
- Knowledge and method references
- Data credibility status

The report must answer five user-facing questions:

- What happened today?
- Why is it worth observing?
- What is the biggest risk?
- What should confirm the thesis later?
- What would prove the thesis wrong?

## 8. Factor Admission and Use Levels

Every factor must pass five questions before formal use:

1. Is the data stable and available?
2. Does it add independent information rather than duplicate price movement?
3. Does it have theoretical or empirical support?
4. Can it be evaluated out of sample?
5. Is the runtime and maintenance cost justified?

Approved factors are assigned a use level:

- Hard constraint: official rules and severe risk boundaries.
- Primary evidence: stable, testable, independent signals.
- Supporting evidence: useful but not strong alone.
- Background explanation: helps understanding but cannot support recommendation.
- Observation or disabled: unstable, overfit-prone, non-evaluable, or too costly.

## 9. LLM Boundary

The large model is an explanation assistant, not the decision source.

It may read:

- Structured evidence packages
- Scores and state-machine results
- Matched knowledge rules
- Allowed report templates

It may not:

- Read raw market-scale tables directly
- Invent causes, catalysts, or risks not present in evidence
- Produce unconditional trading commands
- Override hard constraints
- Promote observation knowledge into formal action rules

If evidence is missing, the LLM must express uncertainty instead of filling the gap.

## 10. Knowledge Rule Requirements

Each rule must have:

- Rule ID
- Source reference
- Source grade
- Rule type: hard constraint, explanation, counter-evidence, evaluation
- Applicable scenarios
- Forbidden scenarios
- Data requirements
- Report phrasing guidance
- Evaluation method
- Deprecation or downgrade conditions

Official S-grade materials can directly become hard constraints when their rule meaning is clear.

Research S/A materials can become explanation or counter-evidence rules, but they must not directly generate strong trading actions.

B-grade or unclear materials remain observation-only until evaluation supports promotion.

## 11. Post-Evaluation Framework

Post-evaluation has three layers.

### 11.1 Result Evaluation

Evaluates whether the original observation thesis was validated.

Windows such as 5, 20, and 40 trading days are used as observation checkpoints, not as the only metric.

Evaluate:

- Whether price behavior followed or invalidated the thesis.
- Whether invalidation conditions were hit.
- Whether predicted risks occurred.
- Whether the stock moved into expected confirmation/failure states.
- Whether performance beat relevant benchmarks such as CSI 300, CSI 500, industry index, or cleaned random baseline.

### 11.2 Method Evaluation

Evaluates whether the analysis method worked.

Evaluate:

- Trend signal validity versus false breakout.
- Price-volume signal quality versus low-liquidity noise.
- Event interpretation validity versus already-priced-in events.
- Risk rule precision versus excessive conservatism.
- Evidence independence versus repeated versions of the same price signal.
- Market-regime dependence.

### 11.3 Knowledge Evaluation

Evaluates whether matched knowledge rules should be kept, upgraded, downgraded, split, or deprecated.

Evaluate:

- Repeated success or failure across stocks.
- Cross-industry and cross-regime transferability.
- Whether failures are boundary failures or rule failures.
- Whether a rule needs a narrower scope.
- Whether a counter-evidence rule should gain weight.

### 11.4 Anti-Overfitting Requirements

Evaluation must prioritize transferability over historical fit.

Rules:

- Record the original thesis, data, evidence, rules, and invalidation conditions at recommendation time.
- Do not rewrite past reasoning after outcomes are known.
- Require out-of-sample evidence before upgrading a method or knowledge rule.
- Prefer finding failures before collecting supporting stories.
- Reject overly complex rules that fit one stock but do not generalize.
- Segment by market regime: rising, sideways, falling, high volatility, low liquidity.
- Compare against benchmarks and baselines.
- Check for data leakage, future data, wrong announcement timing, and adjustment errors.
- Downgrade, split, or deprecate repeatedly failing rules.

Manual or temporary analysis reviews, such as repeated 600114 reviews from Version 2, are valuable inputs. They may enter method evaluation records, knowledge evaluation records, counterexample records, and stock history. They cannot directly promote a rule without broader validation.

## 12. Report Design

### 12.1 Fixed Entry

The user entry is:

- `reports/index.html`

It defaults to the latest available report and supports:

- Date filtering
- Stock code/name filtering
- Latest focus watchlist
- Historical single-stock analysis

### 12.2 Homepage Sections

The homepage shows:

- Market environment: broad market, style, industry tone, whether active observation is suitable.
- Daily new recommendations: new candidates discovered today.
- Focus watchlist: currently tracked stocks and state changes.
- Risk alerts: stocks or themes to be careful with.
- Evaluation tasks: old theses or rules due for review.
- Data credibility: compact status only, not system logs.

### 12.3 Single-Stock Report Sections

Each stock report shows:

- Conclusion summary
- Why now
- What happened
- Macro-industry-stock chain
- Supporting evidence by source category
- Counter-evidence and risks
- Confirmation signals
- Invalidation signals
- Observation plan
- Knowledge and method references
- Data credibility and degradation notes

The page must not look like a pipeline dashboard.

## 13. Data Storage Architecture

Storage architecture was amended on 2026-07-08 by `2026-07-08-storage-governance-design.md` after live Supabase capacity review. The original goal of avoiding scattered local files still stands, but Supabase Free must not become a full-market data warehouse.

The storage boundary is:

- Git repository: code, tests, schema migrations, knowledge-rule definitions, report templates, and documentation.
- Local warehouse (`/Users/ccrt/股票分析助手/local_warehouse/`): DuckDB + Parquet store for full-market raw data, daily basic indicators, coarse features, coarse scores, and 180-day recomputation windows.
- Supabase Postgres: cloud decision ledger for normalized recommendation facts, focus-watchlist state, rule matches, evaluation records, report indexes, data-quality status, and only limited 120-trading-day market windows for final recommendations, focus stocks, and internal controls.
- Local archive (`/Users/ccrt/股票分析助手/local_archive/`): complete HTML reports, long-form evidence/review text, manifests, and monthly export bundles.
- Supabase Storage: not part of the Stage 1 default. It may be reconsidered later if the project upgrades or needs remote artifact storage, but Stage 1 keeps large artifacts local.
- Cloudflare Pages: published static report site and small access-control function only.

Secrets must never be committed. Existing local tokens such as Tushare and model API credentials should be reused from the user's home-directory secret files or environment variables during local runs, then later mirrored into the deployment secret manager only when remote automation is added.

The public report frontend must not receive service-role keys, raw API credentials, internal logs, or unrestricted database access. If browser-side Supabase access is introduced later, exposed tables must use Row Level Security and narrow read-only policies. In Stage 1, the safer default is to generate report HTML/JSON server-side and publish only the report artifacts.

Recommended initial Postgres areas:

- `market_calendar` and `trading_days`
- `stock_master` and `stock_status_daily`
- `daily_feature_snapshot`
- `recommendation_daily`
- `focus_watchlist_state`
- `evidence_package_index`
- `knowledge_rule`
- `knowledge_rule_match`
- `evaluation_task`
- `evaluation_result`
- `data_source_run`

## 14. Historical Data Retention for Evaluation

Historical storage exists to make post-evaluation scientific, not to hoard every raw response forever.

The system stores three evidence levels.

### 14.1 Full-Market Lightweight Snapshots

Every trading-day run stores a lightweight full-market snapshot in the local DuckDB + Parquet warehouse after cleaning. Supabase does not store full-market snapshots on the Free plan.

This snapshot should include:

- Trading eligibility and exclusion flags.
- Core factor values used by the screening model.
- Market regime and industry/style context.
- Data-quality flags.
- Rule-hit summaries.
- Source timestamps or hashes where useful.

This is required because evaluation must compare selected stocks against non-selected alternatives, benchmarks, industries, and market regimes. Without this layer, the system can only explain why chosen stocks moved, which is too easy to overfit.

Supabase stores only the small evaluation set derived from this full-market layer: daily final recommendations, focus stocks, and 15 internal near-miss/control candidates.

### 14.2 Detailed Evidence Packages

The system stores detailed evidence packages for:

- Daily final recommendations.
- Focus-watchlist entries and state changes.
- Internal near-miss candidates that almost passed the filter.
- Major failures or disputed cases discovered during evaluation.

Near-miss candidates are internal evaluation material. They are not shown as user-facing recommendations, but they help answer whether the method was too strict, too loose, or directionally wrong.

Each evidence package must freeze the original thesis, data version, matched knowledge rules, counter-evidence, confidence level, invalidation conditions, and expected confirmation path. Past reasoning must not be rewritten after outcomes are known.

### 14.3 Raw API Snapshot Retention

Raw API data is stored selectively:

- Keep full-market raw/coarse-analysis data in local warehouse for 180 days.
- Keep longer local archived text/artifacts for recommendations, focus stocks, major failures, rule disputes, and data-source anomalies.
- Store metadata, hashes, local archive paths, and structured evaluation facts in Supabase Postgres.
- Do not store large raw payloads in Supabase Storage during Stage 1.

This gives enough auditability for serious mistakes without recreating Version 2's heavy storage burden.

### 14.4 Evaluation Use

Historical records must support three evaluation questions:

- Result: did the original observation thesis validate against benchmarks and invalidation rules?
- Method: did the analysis method work out of sample, or did it overfit a pattern?
- Knowledge: should a matched knowledge rule be kept, narrowed, downgraded, split, or deprecated?

The system should evaluate 5, 20, and 40 trading-day checkpoints, but those dates are checkpoints rather than the definition of success. Manual repeated reviews from Version 2, such as the 600114 review habit, can be imported as evaluation notes and counterexample records when they preserve the original reasoning and later outcome separately.

## 15. Web Publishing and Access Boundary

The report website is a product surface for family viewing. It must expose only report content.

Recommended deployment:

- Cloudflare Pages hosts the report site on the default `*.pages.dev` URL first.
- The Cloudflare dashboard is only the management console; it is not the report URL shown to family.
- Stage 1 publishes static HTML/JSON report artifacts generated from the local warehouse plus Supabase decision-ledger state.
- A small Cloudflare Pages Function can enforce a simple shared access password and session cookie.
- No custom domain is required initially.

## 16. Stage 1 Operational Acceptance

Stage 1 is considered ready when the local runbook and the generated report surface meet all of the following:

- After editable installation, `python3 -m stock_analyzer health-check` reports four health categories.
- Without editable installation, `PYTHONPATH=src python3 -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07` generates a clearly labeled fixture report at `reports/index.html`.
- Without `--fixture-mode`, production `run-daily` fails clearly until real ingestion is implemented, and must not persist or publish sample data.
- Daily recommendations stay at or below 10 names.
- The focus watchlist remains separate from daily recommendations.
- Each recommendation produces a frozen evidence package and at least one evaluation task.
- Published report artifacts do not leak `TUSHARE_TOKEN`, `SUPABASE_SERVICE_ROLE_KEY`, `DEEPSEEK_API_KEY`, or `BIYING_LICENCE`.

The public report site may show:

- Latest daily report.
- Date-filtered reports.
- Stock-filtered reports.
- Current focus watchlist.
- Recommendation history and evaluation summaries.
- Compact data-credibility status.

The public report site must not show:

- Tokens or secret status.
- Raw API payloads.
- Internal logs.
- Scheduler controls.
- Rule-editing interfaces.
- Database administration pages.
- Internal near-miss candidates unless later promoted into an explicit evaluation report.

## 16. Runtime Boundaries

Stage 1 explicitly does not do:

- Brokerage integration
- Automatic trading
- Intraday real-time strategy
- Complex interactive frontend
- Full multi-role runtime workflow
- Full migration of old modules
- Direct LLM analysis over raw full-market tables
- Public browser access to internal database tables

Stage 1 must do:

- One-command daily execution
- Clear failure attribution
- Graceful data degradation
- No fake conclusions when key data is missing
- Recommendation and focus-watchlist state records
- Evidence and knowledge traceability for each conclusion
- Evaluation task creation for each recommendation
- Fixed report entry generation
- Supabase-backed decision state and evaluation history
- Local DuckDB + Parquet full-market warehouse with managed retention
- Cloudflare-publishable report artifacts

## 17. Testing and Verification

The first implementation stage must include tests for:

- Data-source configuration and token presence.
- Stock-pool filtering.
- Hard-constraint risk exclusion.
- Daily recommendation limit and no quota-filling.
- Focus watchlist enter/exit/downgrade state machine.
- Knowledge rule loading and matching.
- LLM input boundary: no raw full-market table input.
- Report generation: fixed entry exists and stock pages exist.
- Evaluation records: every recommendation has reviewable records.
- Supabase schema migrations and basic read/write paths.
- Historical snapshot creation in local warehouse without raw-data leakage into Supabase.
- Report publishing artifact contains no internal secrets or logs.
- Password-gated report access behavior.

Acceptance criterion:

> In one trading-day run, the system can complete data acquisition, cleaning, analysis, state updates, evidence generation, report generation, and evaluation registration, producing a small number of evidence-backed, counter-evidence-aware, follow-up-ready stock reports.

## 18. Source References

Local project references:

- `/Users/ccrt/股票分析助手`
- `/Users/ccrt/ccrt`
- `/Users/ccrt/股票分析系统`
- `/Users/ccrt/股票分析系统/21_角色与知识库`
- `/Users/ccrt/股票分析系统/20_数据资产中心`

External methodological and regulatory references consulted during design:

- Shanghai Stock Exchange business rules portal: https://www.sse.com.cn/lawandrules/sselawsrules/
- Shenzhen Stock Exchange business rules portal: https://www.szse.cn/lawrules/rule/
- CSRC laws and regulations portal: https://neris.csrc.gov.cn/falvfagui/
- State Council capital market quality guidance: https://www.gov.cn/zhengce/content/202404/content_6944877.htm
- SEC investor publication on analyst recommendations: https://www.sec.gov/investor/pubs/analysts.htm
- Testing the performance of technical trading rules in the Chinese market: https://arxiv.org/abs/1504.06397
- Supabase database overview: https://supabase.com/docs/guides/database/overview
- Supabase Row Level Security: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase Storage: https://supabase.com/docs/guides/storage
- Supabase local development and migrations: https://supabase.com/docs/guides/local-development/overview
- Cloudflare Pages: https://developers.cloudflare.com/pages/
- Cloudflare Pages Functions: https://developers.cloudflare.com/pages/functions/
- Cloudflare Workers static assets: https://developers.cloudflare.com/workers/static-assets/

## 19. Open Implementation Decisions

These are not open product questions; they are implementation-plan decisions:

- Exact package layout and module names.
- Which subset of Version 2 knowledge assets are migrated first.
- Which free data-source connectors are implemented in the first runnable slice.
- Exact score formulas and thresholds, which must start simple and be evaluation-ready.
- Exact Supabase table schema, indexes, and migration naming.
- Exact Cloudflare Pages project name.
- Exact shared-password mechanism and cookie lifetime.
- Exact implementation details for the 180-day local warehouse retention job.
- Whether local development uses Supabase local stack immediately or starts with migrations against the hosted project.

## 20. Approval

The user approved:

- Two-layer stock analysis product.
- Full A-share cleaned universe.
- Tushare primary plus free-source fallback.
- LLM as explanation assistant.
- 2-8 week observation horizon.
- Official S-grade knowledge as hard constraints.
- Research S/A knowledge as explanation and counter-evidence.
- Scientific post-evaluation with result, method, and knowledge layers.
- Three-depth analysis architecture.
- Formal distinction between daily recommendations and focus watchlist.
- One-command first-stage runtime boundary.
- Supabase as the cloud decision ledger and structured evaluation database.
- Local DuckDB + Parquet as the full-market raw/coarse-analysis warehouse.
- Cloudflare Pages default URL for report publishing.
- Simple password-gated family report access.
- Static report generation from local warehouse data plus Supabase decision-ledger state for Stage 1.
- Historical storage that preserves lightweight full-market snapshots locally, detailed structured evidence in Supabase, and long-form report/evidence artifacts in local archive for scientific evaluation.
