---
name: interpreting-market-macro
description: Use when point-in-time A-share candidate selection or validation needs market breadth, liquidity, risk appetite, style, volatility, concentration, macro or policy context, or market-level counterevidence.
---

# 市场与宏观解释

## 目标

判断形成日的市场结构是否有利于未来约 20 个交易日出现显著上涨股票，以及机会更可能来自广泛风险偏好、行业扩散、风格切换还是独立公司事件。

本 Skill 不直接决定最终股票，但必须缩小搜索方向并改变候选命题的可信度。市场证据是选股输入，不是市场综述，也不是一票否决开关。

“20 日约 20%”是总控的使用目标和事后评价标签，不是本 Skill 的固定市场阈值或承诺。

## 输入

取得总控提供的：

- `phase`：`discovery` 或 `validation`；
- `formation_date`、`action_date`、带时区的 `as_of`；
- 股票范围或待验证候选；
- 本轮目标、比较窗口和需要判断的机会类型。

核心指数、市场广度、成交或时间边界不可靠时，说明不足，不给正式市场解释。

## 定向使用本地知识

只在问题相关且所需数据可用时调阅 `src/stock_analyzer/knowledge/research_registry.yaml` 中：

- `src_cn_factor_momentum_2023`：市场状态只改变趋势证据可信度，上涨市场不保证追强有效；
- `src_cn_return_dispersion_risk`：分化扩大是共同上涨减弱和后续波动风险，不决定涨跌方向；
- `src_cn_t1_contrarian_2024`：区分极短期反转与可延续趋势；
- `src_cn_price_limit_momentum_2025`：涨停是制度约束下的价格结果，不是继续上涨保证。

同时遵守条目的适用范围、前提、反证、本地验证和禁止用途。不得把论文窗口、历史收益、市场状态或阈值直接复制成选股规则。

## 判断方法

只使用 `available_at <= as_of` 的历史版本，依次回答：

1. **参与程度**：指数变化与上涨面、中位数收益、新高和涨停分布是否一致？
2. **流动性支持**：成交变化是否支持价格推进，还是缩量、拥挤或高成交低进展？
3. **内部稳定性**：收益分化和波动是在扩大还是收敛，领导是否集中于少数股票？
4. **机会位置**：风格和行业相对表现是扩散、延续、切换、衰退还是尚无法判断？
5. **目标含义**：这些事实更支持寻找哪类 20 日上涨候选，又削弱哪类候选？
6. **备选解释**：相同事实还可能由什么解释，什么变化会推翻当前判断？

固定观察方法，不固定市场标签。允许混合状态和多种解释同时成立。

宏观、政策和规则事实只在它们能解释当日市场结构或改变候选搜索方向时读取。政策方向不能直接映射为公司收益。

## 发现阶段

从整体分布中输出可执行的搜索含义：

- 广度、成交和领导共同增强时，提示板块 Skill 寻找有成员扩散的方向；
- 指数稳定但分化和集中上升时，提示优先寻找独立公司事件或少数强因果链；
- 市场整体逆风时，降低依赖普遍风险偏好的命题可信度，同时保留公司独立变化；
- 证据冲突时，明确需要板块、公司或价格视角验证什么。

线索可以为空，但不能用“环境复杂”替代判断。

## 验证阶段

只围绕总控给出的少量候选判断：

- 候选需要的市场条件当前是否存在；
- 其上涨命题依赖市场、板块还是独立公司变化；
- 市场环境提高、降低还是基本不改变目标实现的可能性；
- 哪个市场事实最可能使候选失效。

市场逆风是反证，不自动删除有直接公司变化和独立价格确认的候选。

## 输出合同

每条关键事实同时保留统一的数据质量信息。`fact_as_of` 表示事实对应的日期或期间，`available_at` 表示系统何时能够取得；两者不得互换。顶层 `as_of` 仍是本轮形成日决策截止时点。`quality` 使用 `complete | partial | unreliable`，`capability_status` 使用 `supported | partial | unsupported`。查询失败、历史覆盖不足、当前快照不可回放和真实无记录分别写入 `missing_fields` 或 `unknowns`，不补猜，也不把这些状态合并成“没有”。这些字段只解释证据边界，不计分或投票。

```yaml
phase: discovery | validation
objective: ""
facts: [{claim, value, provider, dataset, fact_as_of, available_at, quality, missing_fields, capability_status}]
primary_interpretation: ""
alternative_interpretations: []
supporting_evidence: []
strongest_counter_evidence: ""
unknowns: []
search_implications:
  preferred_opportunity_types: []
  less_supported_opportunity_types: []
  reasons: []
candidate_leads:
  - lead_type: direction | group | question
    name: ""
    rationale: ""
    target_relevance: ""
    contradictory_conditions: []
    missing_evidence: []
questions_for_other_lenses: []
evidence_sufficiency: sufficient | partial | insufficient
```

`target_relevance` 必须说明市场事实为何影响未来约 20 日显著上涨机会。不得只把“强市”“弱市”“风险偏好提升”等标签换一种说法。

## 边界

- 不直接生成股票名单、买入条件、仓位或目标价；
- 不扫描公司公告或证明公司真实受益；
- 不输出市场总分、固定状态、风险 Gate 或单指标结论；
- 只有日线和分布数据时，不推断机构、主力或账户身份；
- 关键证据缺失时明确未知，不用宏观叙事补猜。
