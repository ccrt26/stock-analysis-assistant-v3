---
name: orchestrating-stock-research
description: Use when personal A-share daily selection, historical formation-date simulation, or multi-perspective stock research must turn point-in-time market, sector, company, and price evidence into a conditional zero-to-five-stock decision.
---

# 股票研究总控

## 最终目标

只使用形成日当时可见的信息，从可研究股票池中选出 0—5 只未来约 20 个交易日更可能形成可操作显著上涨路径、重点观察能否达到约 20% 涨幅的股票。

“20 日约 20%”是用户的实际目标和候选冻结后的评价标签，不是固定财务增速、价格形态、总分或筛选阈值。总控要比较哪些事实提高或降低目标实现的可能性，并对股票作出实际取舍。

最终允许空名单。不能承诺收益，也不能因为结论需要证据就把工作退化为只检查研究文本是否合规。

## 职责

总控承担最终选股责任：

- 冻结研究目标、股票范围和时间边界；
- 根据问题定向选择本地知识；
- 让市场、板块、公司、价格四个专业 Skill 分别发现和验证线索；
- 按上涨因果链汇合候选并比较同类；
- 判断关键未知是否阻断命题；
- 输出 0—5 只最终股票和行动日条件；
- 在历史模拟中先冻结候选和理由，再把未来行情交给评价步骤。

专业 Skill 负责各自判断方法，总控不在内部复制四套研究规则。程序只返回事实和确定性计算，不拥有最终选股权。

## 开始条件

先取得：

```yaml
task_type: daily_selection | historical_simulation
research_objective: "未来约20个交易日形成可操作显著上涨路径，重点观察约20%涨幅"
formation_date: YYYY-MM-DD
action_date: YYYY-MM-DD
as_of: ISO-8601 timestamp with timezone
selection_universe: ""
exclusions: []
```

默认沿用项目当前范围：上海主板、深圳主板和创业板；不含科创板、北交所和场内基金，并排除 ST/*ST、退市整理、停牌、无可靠报价及行动日明确无法正常参与的股票。用户明确指定其他范围时，以用户要求为准。

`action_date` 是形成日之后第一个真实交易日，`as_of` 必须严格早于行动日开盘。核心行情、交易日、股票身份或时间边界不可靠时停止正式选股；次要证据不足时可以继续，但必须减少结论并保留未知。

## 专业 Skill

按以下名称使用：

- `interpreting-market-macro`：判断市场结构支持哪类机会；
- `researching-sectors-industries`：发现共同增强的方向并比较具体成员；
- `researching-company-events`：证明公司真实变化、业务联系和财务或预期传导；
- `analyzing-price-trading`：判断市场识别、剩余路径和行动日可参与性。

四个视角不是四道 Gate，也不是四票表决。市场可以逆风、板块可以中性，只要独立公司变化和价格路径足够有说服力；反过来，市场和板块都强也不能替代公司联系与价格空间。

## 定向使用本地知识

先识别候选机会类型和需要回答的问题，再从 `src/stock_analyzer/knowledge/research_registry.yaml` 调阅相关条目。知识只有实际改变研究问题、证据解释、候选比较或反证时才算使用。

遵守：

- `method_only` 只提供比较方法，不提供收益方向；
- `analysis_evidence` 只能在前提和数据满足时使用；
- `observation_only` 只约束事实语义；
- `forbidden_uses`、`counter_evidence` 和 `local_validation` 必须进入判断；
- `direct_validation_results.yaml` 中 `decision: discard` 的规模价值、海外个股动量、固定财务评分和业绩漂移等关系不得重新包装成选择规则。

候选接近 5 只时使用 `src_portfolio_common_exposure` 检查行业、主题和历史收益共同暴露，只说明是否重复押注同一机会，不建立优化器或仓位权重。

ST、退市和重大官方风险使用 `rules.seed.yaml` 中的正式边界。其他知识不得变成总分、权重或固定 Gate。

## 工作流程

### 1. 冻结研究简报

在读取任何未来行情前记录：

- 目标、形成日、行动日、`as_of` 和股票范围；
- 当日需要验证的市场、板块、公司和价格问题；
- 哪些关键事实缺失时命题只能是未知；
- 可能推翻选择的主要反证。

这里只需要可复现的简要记录，不生成 SHA、评分表或复杂状态文件。

### 2. 分别发现线索

向四个专业 Skill 提供相同的时间边界、股票范围和目标。每个形成日都以当时完整的合格股票范围为候选边界，使用现有结构化事实做横截面轻量发现；新公告、旧名单或已有叙事都不得代替这个候选边界。这不要求逐股深度研究。

- 市场的 `direction`、`group` 和 `question` 用于缩小搜索方向；
- 板块、公司和价格分别独立提交 `stock` 线索进入候选池；没有当日新公司事件不阻止板块或价格线索入池，但它们仍须经公司传导、反证和可交易性验证才能最终入选；
- 方向和板块不能由总控直接猜成股票，必须由对应专业 Skill 补出具体成员；
- 第一轮不得为了完整感逐只读取全市场公告正文。

### 2A. 保留候选链审计账

在同一份研究回答中保留四个专业 Skill 实际输出的全部 `candidate_leads`；某个 Skill 没有线索时显式记录空输出。每条线索记录 `lead_id`、来源 Skill、类型、名称、股票代码和原始理由。

- `stock` 线索按标准股票代码去重；只有名称且形成日无法可靠映射时记为未解决，不用当前身份信息倒填。
- `direction`、`group` 和 `question` 线索逐条记录为已转换到哪些股票、有理由未转换或未解决。方向本身不能被总控猜成股票。
- 去重后的每只股票保留全部 `source_lead_ids`，并在共同验证后记录市场、板块、公司和价格四个视角的支持、反证与未知。
- 每只去重候选必须有且只有一个最终去向 `selected | rejected | unresolved`、去向阶段和一条主要原因。未解决只用于关键事实确实无法判断，不用来回避取舍。
- 输出前核对：去重候选数 = 入选数 + 淘汰数 + 未解决数；每条股票线索可追到候选；每条非股票线索有去向；去重不丢失来源。

该账只保留已发生的研究链，不产生新候选，不计分、排名或改变选股判断。

### 3. 按上涨因果链组织候选

对每条股票线索建立：

```text
形成日前出现了什么新变化
→ 为什么能影响公司业务、收入、利润、现金流或预期
→ 市场或板块是否开始识别
→ 当前价格是否仍有可参与的剩余路径
→ 什么事实最可能使命题失败
```

上涨原因可以来自政策产业变化、板块共同增强、公司事件、业绩重估、周期或困境改善、独立价格异常等，不设固定类型配额。

### 4. 同一因果链内比较

先比较共享同一上涨原因的候选，再比较不同原因的最终机会。每只深度候选必须回答：

- 为什么是它，而不是最接近的同类；
- 它拥有的增量事实是什么；
- 市场已经反映多少；
- 哪个候选只有标签、跟涨或更严重的透支；
- 哪个反证足以改变选择。

不按证据条数、报告完整度或多视角赞成票排序。没有完美证据时仍应作相对判断；只有关键因果环节无法确认时才停止正式选择。

### 4A. 按机会类型比较剩余路径

先依据形成日前的主要传导来源，把候选归为 `company_catalyst | sector_diffusion | independent_price_anomaly`。同一股票同时符合多类时只确定一个主类型，并在证据中披露重叠来源；不得把“没有公司原因”写成公司催化，也不得要求板块或独立价量候选事后补成公司故事。

类型内按以下事实顺序比较，不计算总分或固定阈值：

- **公司催化**：先核对首次披露、重复披露、事件阶段、材料性、主营或非经常性以及收入、利润、现金流一致性；再比较公告前市场是否已经抢跑、公告后价格与成交是否继续有效推进、所处价格位置和同行反应。公司故事完整但公告后没有进一步价格推进，或成交放大只换来停滞和回落，是比故事完整度更强的剩余路径反证；形成日刚披露、尚无公告后交易时，转为行动日条件，不把零日反应写成已经确认。
- **板块扩散**：先确认上涨面、成员中位数和成交份额是否多日共同增强，再检查龙头集中度与分化是否突然恶化；只有共同动力仍在时，才比较候选的流动性、板块内排名及其变化，并与成交和波动最接近的同类直接比较。优先共同动力没有快速坍缩、能够正常参与且确实超过最接近同类的成员，不因行业标签或单日普涨入选。
- **独立价格异常**：先确认 1、3、5 日相对市场和相对板块的强势具有连续性，再区分两条可比较路径：一是相对强势持续并完成真实突破，且上涨不是主要由少数涨停日贡献；二是此前位置和累计涨幅仍低、相对强势连续、成交显著激活的早期路径。反复上影或冲高回落、成交增加但价格推进低效、短期上涨几乎全由涨停贡献，或相似股票拥有更完整的连续性与剩余路径，均为优先淘汰依据。独立价量路径成立时，没有可确认的公司事件不是关键未知。

跨类型取舍时比较哪条因果链在形成日拥有更真实的增量、更清晰的市场识别和更大的剩余路径；公司材料更完整不自动优于板块扩散或独立价格异常。

### 5. 共同验证

把同一批少量候选交回四个专业 Skill，只补充能够改变选择的问题：

- 上涨命题在形成日前是否真实存在；
- 公司是否确实涉及相关业务且传导具有材料性；
- 板块共同动力是扩散还是集中退潮；
- 价格是确认、尚未充分反映还是已经透支；
- 行动日是否可能正常参与；
- 最强反证和关键未知是什么。

只允许一轮定向补证。补证不能借机重新扫描全市场。

### 6. 作出最终取舍

输出 0—5 只：

- 关键因果链有形成日前证据；
- 与同类相比存在明确增量优势；
- 市场或价格已经提供必要识别，或者有充分理由解释尚未识别；
- 价格路径尚未被明显透支且行动日可能参与；
- 最强反证尚未足以推翻命题。

最终名单不是候选排序的前 N 名。每增加一只股票，都要重新判断它是否仍达到与当前已入选股票相近的绝对机会质量，不能因为它是剩余候选中最好的一只就继续补位。若新增候选虽然自身逻辑成立，但在核心增量、市场识别或未来剩余路径上已经明显弱于当前最弱的入选股，则停止增加名单并将其保留为近邻落选。只有它拥有独立成立的上涨命题，并且整体机会质量与已有入选股处于同一层级，才继续加入。不得预设只能选 1 只或 2 只，也不得因为属于 P3 以后自动淘汰。

这些是需要综合判断的问题，不是五项固定 Gate。某个视角中性或次要信息未知不等于自动淘汰。

## 未知的处理

区分：

- **关键未知**：形成日时间边界或可交易性无法确认时不得正式选择；公司真实业务联系、变化和核心传导只在公司催化或明确依赖公司受益的命题中是关键未知；板块扩散以历史成员、共同动力和同类位置为关键，独立价格异常以市场和板块调整后的连续价量增量、剩余路径和可参与性为关键。没有公司事件本身不阻断后两类命题；
- **次要未知**：影响规模的精确值、非核心窗口或辅助比较不足。可以选择，但必须说明它可能怎样改变结论。

数据没有记录、覆盖不足、查询失败和真实不存在是不同状态。公告只有标题没有正文时，只确认标题和公告存在，正文影响保持未知。

## 最终输出

```yaml
research_objective: ""
formation_date: YYYY-MM-DD
action_date: YYYY-MM-DD
as_of: ""
selection_universe: ""
market_search_context: ""
candidate_chain:
  skill_leads:
    - lead_id: ""
      source_skill: market | sector | company | price
      lead_type: direction | group | stock | question
      name: ""
      ts_code: ""
      rationale: ""
  non_stock_lead_fates:
    - lead_id: ""
      fate: converted_to_stock | not_converted_with_reason | unresolved
      mapped_ts_codes: []
      reason: ""
  candidate_ledger:
    - ts_code: ""
      name: ""
      opportunity_type: company_catalyst | sector_diffusion | independent_price_anomaly
      opportunity_type_reason: ""
      type_evidence: []
      type_confidence: high | medium | low
      source_lead_ids: []
      lens_reviews:
        market: {support: "", counter: "", unknown: ""}
        sector: {support: "", counter: "", unknown: ""}
        company: {support: "", counter: "", unknown: ""}
        price: {support: "", counter: "", unknown: ""}
      final_fate: selected | rejected | unresolved
      fate_stage: discovery | joint_validation | final_decision
      primary_reason: ""
  candidate_conservation:
    deduped_candidates: 0
    selected: 0
    rejected: 0
    unresolved: 0
    stock_leads_traced: true | false
    non_stock_leads_traced: true | false
    sources_preserved: true | false
data_quality_issues:
  - fact_or_dataset: ""
    status: missing | failed | unsupported | current_only | unavailable_at_cutoff | genuinely_absent
    effect_on_decision: ""
selected_stocks:
  - ts_code: ""
    name: ""
    opportunity_type: company_catalyst | sector_diffusion | independent_price_anomaly
    opportunity_type_reason: ""
    type_evidence: []
    type_confidence: high | medium | low
    new_change: ""
    target_thesis: ""
    causal_chain: ""
    evidence_by_lens: {market: [], sector: [], company: [], price: []}
    why_this_over_alternatives: ""
    strongest_counter_evidence: ""
    key_unknowns: []
    secondary_unknowns: []
    action_day_participation_conditions: []
    abandonment_conditions: []
representative_non_selections:
  - ts_code: ""
    name: ""
    reason_not_selected: ""
common_exposure_note: ""
data_limitations: []
```

`representative_non_selections` 不能代替 `candidate_chain`：前者帮助用户快速理解最典型的取舍，后者负责让所有已提交线索和候选可追溯。

`target_thesis` 必须直接说明为什么形成日前的新变化可能在未来约 20 个交易日触发进一步重估。`why_this_over_alternatives` 必须体现实际比较，不能只重复支持证据。

没有合适股票时，`selected_stocks` 返回空数组，并说明主要原因。不得用低质量候选补位。

## 历史评价边界

历史模拟中，先冻结研究简报、候选、理由、反证、未知和行动条件，再查询行动日及之后行情。未来 20 日结果只评价选择，不得回写形成日理由。

评价由独立步骤完成，至少区分可执行的目标达成、最大涨幅路径、达到目标所需时间、20 日终点及相对市场收益、达标前最大不利变化。它们不进入形成日 Skill 的选股规则。

历史调优时，在冻结形成日输出后，对当时完整合格范围生成一次 `selected / rejected / undiscovered` 三组对照：

- `selected`：最终入选；
- `rejected`：进入候选池但未入选，`unresolved` 保留其状态后归入本组；
- `undiscovered`：属于当时合格范围但没有进入候选池。

三组互斥且覆盖合格范围；候选链断裂、代码无法映射或处理错误单独报告，不能静默算作 `undiscovered`。三组使用相同入口、可执行性和收益口径，分别报告组内数量、目标达成比例、前 10 个交易日达标、第 11—20 个交易日才达标、最大收盘路径、20 日终点、相对市场收益及达标前最大不利变化。未发现组远大于候选组时，同时比较比例和逐形成日市场基准，不能用赢家绝对数量判定发现失败。

只在开发样本中倒查后来达标但未入选的股票，并依次给出一个主要原因：

- `non_executable`：行动日按既有口径不能正常参与；
- `future_catalyst`：决定性事实形成日截止后才可获得；
- `data_capability_miss`：当时外部已有关键事实，但系统历史能力没有取得；
- `discovery_miss`：系统已有形成日证据，但股票没有进入候选池；
- `decision_miss`：股票已进入候选，形成日证据达到绝对入选标准，且相对实际入选股票存在可说明的不对称取舍；
- `no_point_in_time_case`：形成日前证据不足，只能依靠事后价格或未来叙事解释。

未来结果只用于确定倒查对象和评价取舍，不能制造形成日理由。`decision_miss` 必须与当时实际入选股票作形成日证据对照；当日不足 5 只也不能因为有空位而降低标准。原因分类和三组报告是调优诊断，不增加候选、评分、Gate 或日常选股工作量。

显式要求历史调优时，另返回紧凑诊断块；普通每日选股不返回：

```yaml
historical_tuning_diagnostics:
  group_comparison:
    selected: {stocks: 0, executable: 0, target_hits: 0, target_rate: null, day_1_10_hits: 0, day_11_20_hits: 0, terminal_relative_market: null, max_adverse_move: null}
    rejected: {stocks: 0, executable: 0, target_hits: 0, target_rate: null, day_1_10_hits: 0, day_11_20_hits: 0, terminal_relative_market: null, max_adverse_move: null}
    undiscovered: {stocks: 0, executable: 0, target_hits: 0, target_rate: null, day_1_10_hits: 0, day_11_20_hits: 0, terminal_relative_market: null, max_adverse_move: null}
  integrity_errors: []
  missed_winner_attribution:
    - ts_code: ""
      primary_reason: non_executable | future_catalyst | data_capability_miss | discovery_miss | decision_miss | no_point_in_time_case
      formation_date_evidence: []
      comparison_with_selected: ""
```

## 边界

- 不连接券商、自动交易、决定仓位或承诺收益；
- 不建设评分器、固定阈值、Gate、关注池、扫描平台或报告系统；
- 不让程序或单一专业 Skill代替总控作最终选择；
- 不把知识来源数量、证据条数或研究文本完整度当作选股优势；
- 关键证据不足时明确未知或空名单，不猜测。
