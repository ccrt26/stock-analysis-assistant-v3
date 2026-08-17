---
name: researching-sectors-industries
description: Use when point-in-time A-share candidate selection or validation needs sector or industry breadth, leadership, concentration, dispersion, rotation, historical membership, peer comparison, or group-to-stock discovery.
---

# 板块与行业研究

## 目标

发现正在形成共同上涨动力的行业或主题，并从有效成员中找出比同类更值得继续研究的具体股票。

本 Skill 必须为最终选股提供增量辨别：判断一个方向是早期扩散、持续增强、少数龙头集中、内部退潮还是只有标签共振，并说明为什么继续研究某只股票而不是同类。

“20 日约 20%”是总控的使用目标和事后评价标签，不是板块涨幅、广度或成员表现的固定筛选阈值。

## 输入

取得总控提供的：

- `phase`：`discovery` 或 `validation`；
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

### 1. 判断共同动力

结合问题所需窗口，比较：

- 板块相对市场的 1、5、20 日表现；
- 成员上涨面和中位数收益；
- 新高、涨停和成交份额变化；
- 前三强贡献和强势成员集中度；
- 高成交低进展、量价背离、窄参与和冲高回落；
- 收益分化及其变化。

板块指数上涨但多数成员不支持时，解释为领导集中，不写成全面增强。没有权重或贡献数据时，不声称某只股票贡献了板块大部分涨幅。

### 2. 判断所处阶段

根据连续事实区分：

- 共同表现刚开始扩散；
- 多窗口和成员证据持续增强；
- 上涨仍在但参与面收窄；
- 少数龙头拉动且拥挤上升；
- 行业与主题解释冲突；
- 证据不足，无法判断。

这些是当次解释，不是固定状态机。

### 3. 从板块走向股票

对有效成员比较：

- 相对板块、市场和同类的位置；
- 表现是否来自板块共同推动或公司自身变化；
- 是否有足够流动性和正常交易历史供价格 Skill 继续验证；
- 是已经透支的领涨者、得到确认的核心成员，还是尚待公司事实解释的跟随者；
- 哪个成员最能代表当前因果链，哪个只是概念标签。

板块证据可以产生具体股票线索，但真实业务联系必须交给公司与事件 Skill，剩余价格空间和行动日可参与性必须交给价格与交易 Skill。

## 发现阶段

输出 0 个或多个方向和具体股票线索。只保留能够说明共同证据、同类位置和后续验证问题的成员，不按固定数量凑名单。

候选相对板块落后既可能表示未被充分识别，也可能表示不受益；必须交给公司和价格视角区分，不能自动当成补涨逻辑。

## 验证阶段

只围绕总控给出的少量候选：

- 核对形成日有效的行业和主题归属；
- 比较候选与最接近同类，而不是只与板块指数比较；
- 判断板块共同动力是否仍能支持候选命题；
- 识别候选是否仅由标签、少数龙头或一次普涨带动；
- 给出板块视角下为什么选择它、为什么可能不该选择它。

## 输出合同

候选使用统一机会类型词汇 `company_catalyst | sector_diffusion | independent_price_anomaly | null`。本 Skill 主要负责 `sector_diffusion`：核心起点必须是形成日可见的板块共同增强和有效成员扩散，并检查成员关系、广度、中位数收益、集中、分化、退潮、同类增量和真实业务归属。`sector_diffusion 不要求形成日存在新公司公告`；公司 Skill 只需确认身份、主营联系和重大反证，不得把“没有新公告”本身当作淘汰理由。若核心起点实际来自公司变化或独立量价异常，则分别交由 `company_catalyst` 或 `independent_price_anomaly` 的证据责任处理。

机会类型不是 Gate、配额、评分、优先级、投票或补位规则。该字段只描述因果起点，不改变本 Skill 的线索职责或最终取舍权。

每条关键事实同时保留统一的数据质量信息。`fact_as_of` 表示事实对应的日期或期间，`available_at` 表示系统何时能够取得；两者不得互换。顶层 `as_of` 仍是本轮形成日决策截止时点。`quality` 使用 `complete | partial | unreliable`，`capability_status` 使用 `supported | partial | unsupported`。历史成员缺失、数据源不支持历史查询、查询失败、当前成员快照不可回放和真实无成员记录必须分开写入 `missing_fields` 或 `unknowns`。这些字段只解释证据边界，不计分或投票。

```yaml
phase: discovery | validation
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
    strongest_counter_evidence: ""
    missing_evidence: []
questions_for_other_lenses: []
evidence_sufficiency: sufficient | partial | insufficient
```

股票线索必须说明板块共同证据、候选的同类位置、对目标的相关性、为什么是它而不是同类，以及最强反证。它是总控需要比较的候选，不是最终买入结论。

## 边界

- 不把行业、主题或概念标签写成公司收入和利润证据；
- 不判断公司公告阶段或行动日价格条件；
- 不输出热点总分、固定广度阈值、市场 Gate 或最终推荐；
- 不用当前成员关系覆盖历史成员关系；
- 数据不足时保留未知，不把单只强势股扩写成板块机会。
