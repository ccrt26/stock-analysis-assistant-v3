---
name: orchestrating-stock-research
description: Use when personal A-share daily selection, historical formation-date simulation, or multi-perspective stock research must turn point-in-time market, sector, company, and price evidence into a conditional zero-to-five-stock decision.
---

# 股票研究总控

## 最终目标

只使用形成日当时可见的信息，从可研究股票池中选出 0—5 只未来约 20 个交易日更可能形成可操作显著上涨路径、重点观察能否达到约 20% 涨幅的股票。

“20 日约 20%”是用户的实际目标和候选冻结后的评价标签，不是固定财务增速、价格形态、总分或筛选阈值。总控要比较哪些事实提高或降低目标实现的可能性，并对股票作出实际取舍。

正式入选还必须能说明一个形成日已经存在的“短期上涨发动机”。每只候选都结构化记录 `engine_type`、`engine_status` 和 `market_recognition`：已确认发动机说明新信息或新需求如何形成股票自身或板块层面的增量需求，并已得到相对市场或行业的真实价格成交数值确认；形成日收盘后首次披露或实质增量的重大新事件，在尚无完整反应交易日时可以是 `fresh_event_pending` 条件性发动机。公司业绩、估值、现金流和低位可以是催化或基本面锚，不能单独充当发动机。

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
- `researching-company-events`：分开证明公司催化、基本面锚、业务联系和公司风险；
- `analyzing-price-trading`：判断增量需求是否已有价格成交确认、剩余路径和行动日可参与性。

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

### 2. 按顺序独立发现线索

第一轮发现分为有先后关系的两步，不能在完成前归并股票：

1. 先让市场 Skill 根据整体分布输出搜索含义和唯一的结构化 `market_propagation_environment`：后续更应寻找板块扩散、独立公司变化还是个股独立增量，以及哪些绝对上涨更可能只是市场普涨。这一步不提供股票名单，环境状态不是 Gate。
2. 再向板块、公司和价格三个 Skill 提供相同的时间边界、完整合格股票范围、目标和已冻结的市场搜索含义。三者分别只依据自己负责的事实做横截面轻量发现，独立返回 `stock` 线索或明确的空线索。它们在提交前不接收、查看或沿用其他专业 Skill 的股票线索；不得先用价格排序缩成主要候选池，再让板块或公司视角补说明。

每个形成日都以当时完整的合格股票范围为三路发现边界；新公告、旧名单或已有叙事都不得代替这个边界。这不要求逐股深度研究。没有当日新公司事件不阻止板块或价格线索提交，但它们仍须经公司传导、反证和可交易性验证才能最终入选。

只有三路第一轮都完成后，总控才按股票代码归并候选。方向和板块不能由总控直接猜成股票，必须由对应专业 Skill 补出具体成员。第一轮不得为了完整感逐只读取全市场公告正文。

### 2A. 保留紧凑候选账

只把板块、公司或价格 Skill 实际提交的股票按标准代码去重后写入 `candidate_ledger`；市场与非股票方向只保留会改变搜索的简短上下文，不复制全部中间输出。

- 每只候选保留实际 `source_skills`，不用来源数量计分；
- 每只候选必须有且只有一个 `selected | rejected | unresolved` 去向和一条主要原因；
- 候选守恒是去重候选数 = 入选数 + 淘汰数 + 未解决数；
- 只保留实际候选和最多 3 只 `nearest_nonselections`，不为完整感扩展账本。

该账只保留已发生的研究链，不产生新候选，不计分、排名或改变选股判断。

### 3. 按上涨因果链组织候选

对每条股票线索建立：

```text
新信息或新需求
→ 是否形成板块传播或股票需求
→ 相对市场和行业的价格成交是否确认
→ 上涨路径是否仍未耗尽
→ 基本面锚和公司风险是否支持
```

“公司催化”“基本面锚”“板块传播”和“价格确认”是不同角色，不得互相代替。上涨发动机可以来自政策产业变化、板块共同增强、公司事件形成的新增需求或独立价格异常等，不设固定类型配额；业绩好、估值低、现金流好、位置低或材料完整本身都不是发动机。

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

- **公司催化**：先结构化核对 `first_disclosure | incremental_update | repeat_disclosure | history_insufficient`、新增信息等级、事件阶段、材料性、主营或非经常性以及收入、利润、现金流一致性，再明确催化将通过什么新增需求作用于股票；随后比较公告前抢跑、公告后 1/3/5 个完整交易日相对市场和申万二级行业的价格成交反应、所处价格位置和同行反应。公司故事完整但没有进一步价格推进，或成交放大只换来停滞和回落，是比材料完整度更强的反证。事件在形成日收盘后、`available_at <= as_of`，且属于首次披露或实质增量的重大新信息时，可在首个完整交易日尚不可见时用 `fresh_event_pending` 条件性入选；它必须引用同一事件的等待窗口和行动条件，不得写成已确认。重复披露、一般财报、有限增量、低估值、现金流、低位或无新增信息不适用。
- **板块扩散**：先确认上涨面、成员中位数和成交份额是否多日共同增强，再检查龙头集中度与分化是否突然恶化，并为具体候选形成使用历史有效成员的 `sector_leader_cluster`；只有共同动力仍在时，才比较候选在簇中的 `leader | core | follower | outside | unknown` 角色、流动性、板块内位置及其变化，并与成交和波动最接近的同类直接比较。优先共同动力没有快速坍缩、能够正常参与且确实超过最接近同类的成员，不因行业标签或单日普涨入选。
- **独立价格异常**：先确认 1、3、5 日相对市场和相对板块的强势具有连续性，再区分两条可比较路径：一是相对强势持续并完成真实突破，且上涨不是主要由少数涨停日贡献；二是此前位置和累计涨幅仍低、相对强势连续、成交显著激活的早期路径。反复上影或冲高回落、成交增加但价格推进低效、短期上涨几乎全由涨停贡献，或相似股票拥有更完整的连续性与剩余路径，均为优先淘汰依据。独立价量路径成立时，没有可确认的公司事件不是关键未知。

跨类型取舍时比较哪条因果链在形成日拥有更真实的增量、更清晰的市场识别和更大的剩余路径；公司材料更完整不自动优于板块扩散或独立价格异常。低位激活与高位突破是并列的剩余路径，不静态地把价格位置更低、前期涨幅更小或走势更平滑解释为剩余空间更大，也不因股票已处高位、此前上涨更多或存在一定上影和回落就默认透支。先判断形成日前的新增趋势是否仍在产生：多窗口相对市场、行业或同类的强势是否继续，是否形成真实突破，成交增加后是否仍能推动收盘，以及是否仍有新的公司或板块事实强化命题。若这些增量仍在，高位和此前已涨更多应理解为市场确认的一部分；真正需要降低的是强势已经衰减、成交推进变差、上涨主要依赖少数涨停且缺少新增事实继续强化的候选。上影、冲高回落、涨停贡献和透支仍是反证，但不能单独盖过真实突破、持续相对增量、有效成交推进与新增公司或板块强化；这也不降低公司催化对真实公司因果和材料性的要求。

### 5. 独立共同验证

把同一批少量候选卡交给四个专业 Skill，只补充能够改变选择的问题。四个 Skill 分别依据自己负责的事实验证，提交前不读取或沿用其他专业 Skill 的结论：

- 上涨命题在形成日前是否真实存在；
- 候选的绝对上涨中，哪些更像市场普涨、板块共同变化或个股自身增量；可用基准不足时保留未知；
- 公司是否确实涉及相关业务且传导具有材料性；
- 板块共同动力是扩散还是集中退潮；
- 价格是确认、尚未充分反映还是已经透支；
- 行动日是否可能正常参与；
- 最强反证和关键未知是什么。

只允许一轮定向补证。补证不能借机重新扫描全市场。四个 Skill 不重复输出大段相同事实；每个 Skill 对每只深度候选最多保留 1—2 条真正改变取舍的证据。总控在四路提交后解决冲突，不按投票、证据数量、场景数量或固定分数排序。

### 6. 作出最终取舍

输出 0—5 只：

- 能清楚说明形成日的短期上涨发动机及其增量需求来源；
- 关键因果链有形成日前证据，催化、基本面锚、传播和价格确认没有混写；
- 与同类相比存在明确增量优势；
- `engine_status: confirmed` 至少引用一条价格 `support`，并保存形成日观察日期、绝对价格或收益、成交额或成交额比以及相对市场或行业收益的真实数值；低位、未透支、行动条件或场景名称不能替代该确认；`fresh_event_pending` 则必须引用形成日收盘后重大新事件和同一事件的 `awaiting_first_session` 行动条件，明确它尚未确认；
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

每日只输出一份完整 `DailyResearchTrace`，不再另写紧凑 pending ResearchResult：

```yaml
trace_version: daily-research-trace-v3
formation_date: YYYY-MM-DD
action_date: YYYY-MM-DD
as_of: "带时区时间"
market_search_context: ""
market_propagation_environment:
  environment_id: "market-<formation_date>"
  propagation_state: supportive | neutral | adverse | unknown
  breadth: ""
  liquidity: ""
  risk_appetite: ""
  style: ""
  concentration: ""
  evidence_basis: []
candidate_ledger:
  - ts_code: ""
    name: ""
    opportunity_type: company_catalyst | sector_diffusion | independent_price_anomaly
    source_skills: [researching-sectors-industries]
    final_fate: selected | rejected | unresolved
    primary_reason: ""
    research_thesis:  # 每只候选必填
      engine_type: company_event | sector_diffusion | stock_specific_demand | no_valid_engine
      engine_status: confirmed | fresh_event_pending | unconfirmed | invalidated
      market_recognition:
        status: confirmed | partial | absent | not_yet_observable | unknown
        market_environment_id: "market-<formation_date>"
        basis: ""
      company_information_novelty:
        disclosure_novelty: first_disclosure | incremental_update | repeat_disclosure | history_insufficient | not_applicable
        new_information_level: major_new_information | material_increment | limited_increment | no_new_information | unknown | not_applicable
        basis: ""
        event_id: null
        event_available_at: null
      sector_leader_cluster: null
      action_condition_decision_id: null
      catalyst: ""
      short_term_engine: ""
      propagation: ""
      price_confirmation: ""
      remaining_path: ""
      fundamental_anchor: ""
      company_risk: ""
      critical_unknown: ""
      decision_ids: [company-anchor-risk, price-confirmation]
decision_trace:
  - decision_id: company-anchor-risk
    ts_code: ""
    source_skill: interpreting-market-macro | researching-sectors-industries | researching-company-events | analyzing-price-trading
    evidence_id: ""
    evidence_version: ""
    evidence_status_at_use: supported_with_boundary | provisional | observation_only
    decision_role: discovery | support | counter | comparison | action_condition
    decision_changed: created_lead | promoted | demoted | rejected | no_change
    formation_values: {}
research_result:
  research_completed: true
  point_in_time_evidence_verified: true
  failure_reason: ""
  skills_used:
    - orchestrating-stock-research
    - interpreting-market-macro
    - researching-sectors-industries
    - researching-company-events
    - analyzing-price-trading
  selected_stocks: []
  nearest_nonselections: []
  empty_reason: "空名单时填真实原因；有入选时留空"
```

`research_result` 继续严格符合现有 `ResearchResult`，其中 `skills_used` 为实际使用的五个 Skill。每条 `decision_trace` 使用唯一 `decision_id` 并引用候选账中的股票；`formation_values` 只放真正用于当时判断的少量标量，不保存整行派生事实。每只候选都必须有结构化 `research_thesis` 并引用同一 `market_propagation_environment`。`confirmed` 入选必须引用本股票的公司证据和至少一条满足最小原始数值合同的价格 `support`；`fresh_event_pending` 必须引用公司重大新事件和同一事件的价格 `action_condition`，不得伪装成支持；`sector_diffusion` 还须有包含候选自身的 `sector_leader_cluster` 并引用板块证据。实际入选股和 `nearest_nonselections` 每只保留 1—2 条价格证据，场景不合适时可使用 `raw_price`。

没有合适股票时，`selected_stocks` 返回空数组并填写真实 `empty_reason`，不得补位。研究或形成日事实验证失败时，按现有失败合同留空两组候选，不把执行失败伪装成空名单。

程序只校验日期、合格股票、候选守恒、结构化枚举、证据引用、角色一致性、确认价格的最小数值、`fresh_event_pending` 的时点/新颖性/等待窗口和 ResearchResult 结构，再从这一份 trace 抽取现有 Forward 记录；它不判断事件语义、材料性、发动机、传播或价格解释是否正确，也不把这些字段变成评分、阈值或 Gate。

正式每日运行只将该 JSON 写入 `local_archive/forward_selection/pending-trace-<formation_date>.json`，再使用 prepare 冻结的原日期和 `as_of` 调用 `record-trace`。不再另生成 pending ResearchResult JSON。

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
