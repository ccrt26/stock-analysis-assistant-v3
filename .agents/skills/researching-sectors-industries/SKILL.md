---
name: researching-sectors-industries
description: Use when point-in-time A-share candidate selection, validation, or post-selection review needs sector or industry breadth, leadership, concentration, dispersion, rotation, historical membership, peer comparison, or group-to-stock discovery.
---

# 板块与行业研究

## A股短周期发动机 V4 最终合同（优先级最高）

必须把 `sector_broad_diffusion` 与 `sector_leader_cluster` 分开，按成员数、成交份额、单股贡献和板块内百分位留痕。只有 `leader_confirmed` 和 `core_diffusion_member` 可正式入选，不能用“补涨”升级。

## 唯一职责和固定比较顺序

板块 Skill 独占板块共同动力、历史有效成员、扩散或领导集群，以及成员在同一传播链中的角色。固定顺序是：共同动力 → leader/core 角色 → 同板块近邻。

1. 先用板块相对收益、成员中位数、上涨面、成交份额、集中和分化证明共同动力；共同动力不成立时，不从板块标签生成股票线索。
2. 再只在形成日有效成员中判断 `leader_confirmed | core_diffusion_member | follower | outside | unknown`；小样本、高贡献集中或扩散收缩必须降低角色确信度并形成明确反证。
3. 最后与共享同一板块动力、流动性和波动最接近的成员直接比较，说明为什么提交这一成员而不是近邻。

候选自身价量只用于描述板块内角色和相对位置；本 Skill 不判断候选完整的个股连续性、剩余路径或最终淘汰，这些交给价格 Skill 和总控。板块成立只生成研究线索，不能等同具体股票成立。


## 目标

发现正在形成共同上涨动力的行业或主题，并从有效成员中找出比同类更值得继续研究的具体股票。

本 Skill 必须为最终选股提供增量辨别：判断一个方向是早期扩散、持续增强、少数龙头集中、内部退潮还是只有标签共振，并说明为什么继续研究某只股票而不是同类。

板块共同动力只有在形成新增需求并传播到足够多有效成员时，才可能成为短期上涨发动机的一部分。行业名称、主题标签、单日普涨或少数龙头上涨都不是传播证据；板块 Skill 证明传播，价格 Skill 另行证明候选自身的相对价格成交确认。

“20 日约 20%”是总控的使用目标和事后评价标签，不是板块涨幅、广度或成员表现的固定筛选阈值。

## 输入

取得总控提供的：

- `phase`：`discovery`、`validation` 或 `review`；
- `formation_date`、`action_date`、带时区的 `as_of`；
- 股票范围或待验证候选；
- 本轮目标、板块问题和所需同类比较对象。

缺少可靠时间边界或历史成员关系时，停止相关归属判断并写明未知。

## 定向使用本地知识

只在问题相关且数据可用时调阅 `src/stock_analyzer/knowledge/research_registry.yaml` 中：

- `src_cn_factor_momentum_2023`：用一组股票的共同表现判断趋势，检查广度、相对收益、成交份额和集中度；
- `src_moskowitz_grinblatt_1999`：拆分个股表现中的行业共同成分与公司自身成分，仅借鉴方法，不移植海外收益结论；
- `src_cn_return_dispersion_risk`：把成员分化作为内部脆弱性和后续波动证据；
- `src_csrc_disclosure_rules_2025`：行业或主题标签不能替代公司真实业务和收入证据。

同时遵守条目的适用范围、前提、反证、本地验证和禁止用途。不得把论文组合、固定窗口、历史收益或阈值直接变成选股规则。

## 判断方法

只使用形成日有效且 `available_at <= as_of` 的行业、主题、成员和行情版本。

申万一级行业的参考收益来自 `industry_daily_proxy`：它用前一交易日自由流通市值加权已有个股日收益，只读取 `proxy_index_return_*`、`proxy_relative_return_*`、`proxy_index_status` 和 `proxy_method`。这是本地可回放代理，不是官方申万指数；对应 `official_index_*` 应为空。主题仍读取真实官方指数行情，申万二级/三级仍以成员自下而上的共同表现观察。代理缺失、方法不符或窗口不连续时明确未知，不用旧 `industry_daily` 补位。

### 0. 先缩小确定性输入

先用 DuckDB 对形成日 `sector_hotspot` 做字段投影和条件过滤，只取判断相对收益、成员中位数、上涨面、成交份额、集中和分化所需字段，返回可能值得解释的少量板块；再只查这些板块形成日有效的成员。不把全部板块行和全部字段送入模型，不重算 `sector_hotspot`，也不把盘中字段当作每日必需输入。

申万行业是主要板块证据，主题只作辅助。无有效成员、覆盖不足或只有标签的主题不形成正式板块扩散命题。

### 1. 判断共同动力

结合问题所需窗口，比较：

- 板块相对市场的 1、5、20 日表现；
- 成员上涨面和中位数收益；
- 新高、涨停和成交份额变化；
- 前三强贡献和强势成员集中度；
- 高成交低进展、量价背离、窄参与和冲高回落；
- 收益分化及其变化。

行业代理或主题指数上涨但多数成员不支持时，解释为领导集中，不写成全面增强。没有权重或贡献数据时，不声称某只股票贡献了板块大部分涨幅。

### 2. 判断所处阶段

根据连续事实解释为：

- `broad_diffusion`：多窗口相对表现、成员中位数和上涨面共同增强，且不是少数成员独占贡献；
- `early_diffusion`：短窗口共同表现和参与面开始扩大，更长窗口尚未完整确认；
- `narrow_leadership`：板块收益主要来自少数强势成员，而成员中位数或上涨面不同步，集中度偏高；
- `diffusion_decay`：此前的共同动力在短窗口走弱，参与、相对表现或成交份额回落，同时集中或分化恶化；
- 行业与主题解释冲突或证据不足时，保留冲突或未知。

这些透明条件只写在 Skill 中，由 AI 根据当日原值和基线解释；它们不是 Python 分类器、固定阈值或状态机。

### 3. 从板块走向股票

对有效成员比较：

- 相对板块、市场和同类的位置；
- 表现是否来自板块共同推动或公司自身变化；
- 是否有足够流动性和正常交易历史供价格 Skill 继续验证；
- 是已经透支的领涨者、得到确认的核心成员，还是尚待公司事实解释的跟随者；
- 哪个成员最能代表当前因果链，哪个只是概念标签。

板块证据可以产生具体股票线索，但真实业务联系必须交给公司与事件 Skill；候选完整的 1/3/5 日连续性、单日脉冲、成交推进、剩余价格空间和行动日可参与性必须交给价格与交易 Skill。板块内相对表现只用于确认成员角色，不能替代这一独立价格验证。

## 发现阶段

输出 0 个或多个方向和具体股票线索。只保留能够说明共同证据、同类位置和后续验证问题的成员，不按固定数量凑名单。

候选相对板块落后既可能表示未被充分识别，也可能表示不受益；必须交给公司和价格视角区分，不能自动当成补涨逻辑。

## 验证阶段

只围绕总控给出的少量候选：

- 核对形成日有效的行业和主题归属；
- 比较候选与最接近同类，而不是只与板块指数比较；
- 判断板块共同动力是否仍能支持候选命题；
- 明确传播证据如何形成候选需求，以及它是扩散、集中还是衰减；
- 识别候选是否仅由标签、少数龙头或一次普涨带动；
- 对每条板块股票线索形成 V4 `sector_broad_diffusion` 或 `sector_leader_cluster`：使用形成日有效成员列出实际共同推进成员，标明候选是 `leader_confirmed | core_diffusion_member | lagging_unverified | label_only`，并分别保留传播事实、最强反证和未知；
- 给出板块视角下为什么选择它、为什么可能不该选择它。

`sector_leader_cluster` 是对同一传播链中实际成员的紧凑归组，不是固定龙头榜、行业配额或排序器。不能按股票代码、单一涨幅阈值或当前成员快照指定龙头；成员不足、历史归属不足或共同推进不成立时，不得补造该簇，相关候选只能保持未确认。

## Review 阶段

`phase: review` 只复盘已有记录，不重新推荐股票。核对当时同一行业多只股票共同走强的情况是否持续，上涨股票比例、成员中位数、相对市场表现和成交份额是否减弱，是否从多数股票共同走强变成少数股票上涨，以及被复盘股票仍处在行业前列还是已经落后。

若同一次研究中存在代码或名称能够严格匹配的备选股票，同时比较推荐股和备选股；不能可靠匹配时明确不知道，不根据模糊文字猜代码。不得用行业名称、“补涨”“卡位”或“龙头”替代实际成员表现，也不得因为一只股票上涨就宣布整个行业仍强。

## 输出合同

每条关键事实同时保留统一的数据质量信息。`fact_as_of` 表示事实对应的日期或期间，`available_at` 表示系统何时能够取得；两者不得互换。顶层 `as_of` 仍是本轮形成日决策截止时点。`quality` 使用 `complete | partial | unreliable`，`capability_status` 使用 `supported | partial | unsupported`。历史成员缺失、数据源不支持历史查询、查询失败、当前成员快照不可回放和真实无成员记录必须分开写入 `missing_fields` 或 `unknowns`。这些字段只解释证据边界，不计分或投票。

```yaml
phase: discovery | validation | review
objective: ""
facts: [{claim, value, provider, dataset, fact_as_of, available_at, quality, missing_fields, capability_status}]
primary_interpretation: ""
alternative_interpretations: []
supporting_evidence: []
strongest_counter_evidence: ""
unknowns: []
candidate_leads:
  - lead_type: group | stock | question
    name: ""
    ts_code: ""
    rationale: ""
    target_relevance: ""
    comparative_reason: ""
    propagation_evidence: ""
    propagation_limit: ""
    sector_leader_cluster:  # stock 且依赖 sector_diffusion 时必填
      cluster_id: ""
      group_code: ""
      group_name: ""
      members: []
      candidate_role: leader_confirmed | core_diffusion_member | lagging_unverified | label_only
      propagation_evidence: ""
      strongest_counterevidence: ""
      unknowns: []
    strongest_counter_evidence: ""
    missing_evidence: []
questions_for_other_lenses: []
evidence_sufficiency: sufficient | partial | insufficient
```

股票线索必须说明板块共同证据、传播到候选的路径、候选的同类位置、为什么是它而不是同类，以及最强反证。它是总控需要比较的候选，不是价格确认或最终买入结论。

## 边界

- 不把行业、主题或概念标签写成公司收入和利润证据；
- 不判断公司公告阶段或行动日价格条件；
- 不输出热点总分、固定广度阈值、市场 Gate 或最终推荐；
- 不用当前成员关系覆盖历史成员关系；
- 数据不足时保留未知，不把单只强势股扩写成板块机会。
