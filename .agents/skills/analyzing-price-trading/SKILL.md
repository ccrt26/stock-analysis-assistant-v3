---
name: analyzing-price-trading
description: Use when point-in-time A-share candidate selection or validation needs price and volume confirmation, relative performance, remaining price path, overextension, liquidity, tradability, or conditional action-date participation checks.
---

# 价格与交易研究

## 目标

判断价格和成交是否正在确认候选的上涨命题、市场已经反映多少、是否仍有合理上涨路径，以及行动日能否正常参与。

本 Skill 必须帮助总控区分“正在被有效识别”与“已经透支、背离或无法参与”。它可以发现具体股票线索，也可以否定量价上缺乏现实路径的候选。

“20 日约 20%”是总控的使用目标和事后评价标签。本 Skill 评估实现该目标的价格路径是否有依据，不使用固定技术指标或历史涨幅直接预测结果。

## 输入

取得总控提供的：

- `phase`：`discovery` 或 `validation`；
- `formation_date`、`action_date`、带时区的 `as_of`；
- 股票范围或待验证候选；
- 比较基准、候选原始命题和需要回答的交易问题。

形成日研究不得查询 `action_date` 及之后实际行情。只制定行动日可观察条件；未来表现必须等候选和理由冻结后再评价。

## 定向使用本地知识

只在问题相关且数据可用时调阅 `src/stock_analyzer/knowledge/research_registry.yaml` 中：

- `src_cn_t1_contrarian_2024`：区分极短期反转与中期趋势，近期强势不能自动外推；
- `src_cn_price_limit_momentum_2025`：涨停和连板不是继续上涨保证；
- `src_cn_turnover_momentum_boundary`：高换手本身不确认趋势，也不能识别交易主体；
- `src_cn_illiquidity_operability`：日收益相对成交额只用于粗粒度可操作性比较；
- `src_cn_max_overextension`：近期最大单日上涨是透支反证，不是机械淘汰线；
- `src_cn_margin_semantics`：融资变化只描述信用交易和潜在拥挤，不代表机构观点；
- `src_fama_fisher_jensen_roll_1969`、`src_brown_warner_1985`、`src_mackinlay_1997`：事件附近价格变化要扣除市场共同变化并检查事件重叠。

同时遵守条目的适用范围、前提、反证、本地验证和禁止用途。不得复制论文窗口、收益、分组或阈值。

## 判断方法

只使用 `available_at <= as_of` 的复权日线、估值、成交额、换手、涨跌停、停牌和交易状态。分钟数据不是默认必需输入。

### 1. 拆分价格来源

按问题选择必要窗口，分别比较：

- 绝对收益；
- 相对市场收益；
- 相对所属板块和最接近同类的收益；
- 相对自身历史的价格位置、波动和成交变化。

当市场或板块普遍修复时，先判断短窗口绝对变化中由共同变化解释的部分；个股与市场、所属板块或最接近同类大致同步时，只写市场或板块带动的修复或跟随，不写成个股独立启动。只有在可用比较中存在清晰的个股增量时，才结合成交推进、事件时点和反证，按证据强度描述个股自身确认；基准不足时保留来源未知，不用绝对涨幅补判。弱市中绝对涨幅不大但相对强势清晰时，仍可作为个股增量证据。

### 2. 检查市场识别

判断成交变化是否伴随有效价格推进：

- 成交增加且价格持续推进，可作为市场正在识别的证据；
- 高成交但价格停滞、冲高回落或上影反复，是背离和供给压力反证；
- 低成交造成的大幅波动降低信号可信度和可操作性；
- 融资和换手变化只能描述活动与潜在拥挤，不能推断主体身份或意图。

### 3. 判断剩余路径

结合候选原始命题，说明：

- 当前价格变化发生在事实之前、同时还是之后；
- 近期上涨是初步确认、持续重估、加速，还是已经大幅消耗预期；
- 最大单日上涨、连续拉升、波动和价格位置是否增加追涨透支风险；
- 公司或板块催化是否仍在强化，足以反驳单纯的过热解释；
- 什么价格事实会使未来约 20 日显著上涨路径不再可信。

20 日负收益、前期跌幅或低历史位置只描述既有路径，不能单独证明“还没涨”、“有补涨空间”或“已经启动”。“重新活跃”、“初步确认”和“有效识别”等用语必须与前述价格来源和证据强度一致，不把它们变成固定阶段或硬阈值；高位也仍需结合因果、同类比较和透支反证判断。

### 4. 检查可参与性

核对停牌、涨跌停、上市阶段、成交额和正常成交限制。行动日条件必须可观察，例如：

- 是否存在正常双向成交；
- 是否出现明显脱离原命题的跳空和透支；
- 成交增加是否仍带来价格推进；
- 是否出现新公告或价格事实推翻原命题。

没有经验或证据依据时，不发明 `+2%`、`-3%` 一类精确条件。一字涨停、停牌或无法正常成交时，明确不可参与。

## 发现阶段

寻找 0 个或多个具体股票线索：独立相对强势、事件后有效确认、尚未充分反映、量价加速、显著背离或透支风险。

价格线索必须提出需要公司、板块或市场解释的原始问题。单一指标尾部不能直接成为最终候选。

## 验证阶段

只围绕总控给出的少量候选：

- 检查原始上涨命题是否得到相对价格和成交确认；
- 比较候选与最接近替代股票的价格路径；
- 说明为什么仍可能有空间，或为什么市场已经充分甚至过度反映；
- 给出最强价格反证和行动日参与、放弃条件。

## 输出合同

每条关键事实同时保留统一的数据质量信息。`fact_as_of` 表示行情或交易状态对应的交易日，`available_at` 表示系统何时能够取得；两者不得互换。顶层 `as_of` 仍是本轮形成日决策截止时点。`quality` 使用 `complete | partial | unreliable`，`capability_status` 使用 `supported | partial | unsupported`。复权、基准、行业归属、成交状态或历史窗口缺失，以及查询失败、当前快照不可回放和真实无记录，必须分别写入 `missing_fields` 或 `unknowns`。这些字段只解释证据边界，不计分或投票。

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
  - lead_type: stock | question
    name: ""
    ts_code: ""
    rationale: ""
    target_relevance: ""
    comparative_reason: ""
    remaining_path_reasoning: ""
    strongest_counter_evidence: ""
    action_day_observations: []
    missing_evidence: []
questions_for_other_lenses: []
evidence_sufficiency: sufficient | partial | insufficient
```

股票线索必须把量价事实与候选原始命题连接起来，并说明剩余路径、同类比较和最强反证。它是总控需要取舍的候选，不是自动买入信号。

## 边界

- 不从量价推断机构、主力、游资或账户意图；
- 不代替公司 Skill 证明业务和公告影响，不代替板块 Skill 判断共同因果；
- 不输出技术总分、固定信号、目标价、仓位或自动交易动作；
- 不把盘中瞬间触及当作可执行收益；
- 核心价格、复权、基准或交易状态不足时明确未知。
