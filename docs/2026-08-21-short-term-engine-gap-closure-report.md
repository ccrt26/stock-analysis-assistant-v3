# A 股短期上涨发动机第二次收口报告

**日期：** 2026-08-21

**基线：** `80b5cde117080150492f59c85d9dfe976c389382`

**范围：** 八个已确认缺口的最小修正；不重做上一轮设计

## 1. 收口结果

每日研究轨迹升级为 `daily-research-trace-v3`。每只候选现在都必须留下结构化发动机类型、状态和市场识别；已确认发动机必须引用实际形成日价格成交数值。形成日收盘后真正重大的首次披露或实质增量事件，可以在没有首个完整反应交易日时，以 `fresh_event_pending` 条件性入选，但不能写成已确认。

研究链保持不变：

```text
新信息或新需求
→ 是否形成板块传播或股票自身需求
→ 相对市场和行业的价格成交是否确认
→ 上涨路径是否仍未耗尽
→ 基本面锚和公司风险是否支持
```

程序没有接管事件语义、传播解释、价格解释或最终选股，也没有新增评分、权重、Gate、模型、数据源、服务或定时任务。

## 2. 八项缺口逐项闭合

| 缺口 | 修正 | 程序边界 | 证据 |
| --- | --- | --- | --- |
| 1. 缺结构化发动机 | v3 为每只候选新增 `engine_type`、`engine_status`、`market_recognition` | 只校验枚举、机会类型和引用一致性，不判断文本语义 | 代码、Forward 测试 |
| 2. `fresh_event_pending` 被取消 | 恢复形成日收盘后重大新事件的条件性入选通道 | 校验时点、新颖性等级、事件 ID、等待窗口和行动条件；材料性仍由 AI 判断 | 代码、Forward 测试、Skill |
| 3. 市场传播环境未结构化 | 市场 Skill 输出唯一 `market_propagation_environment`，候选市场识别引用其 ID | `supportive / neutral / adverse / unknown` 不是市场 Gate | 市场 Skill、v3 合同 |
| 4. 无板块龙头簇 | `sector_diffusion` 必须记录包含候选自身的 `sector_leader_cluster` | 使用形成日有效成员；不按代码、固定涨幅或配额选龙头 | 板块 Skill、Forward 测试 |
| 5. 无首次/重复/新增等级 | 公司 Skill 输出披露新颖性和新增信息等级及依据 | 历史不足必须写 `history_insufficient`；等级不是分数 | 公司 Skill、知识库 |
| 6. `support` 可只有标签 | `confirmed` 的价格支持必须有观察日、价格/绝对收益、成交额/比值、相对市场或行业收益 | 标签、布尔值、位置、ATR、场景名和行动条件均不够 | 代码、参数化测试 |
| 7. 事件反应时点和收盘质量不足 | 事件反应升级为 v2，按 15:00 截断日线并输出 OHLC 收盘质量、停牌、成交和基准状态 | 纯函数；不持久化、不判断事件方向 | 代码、事件反应测试 |
| 8. 无冻结日新旧验收 | 用原 2026-08-20 v1 trace、当日 Parquet 和公告历史只读重判四只入选股及第一最近落选股 | 不改原 trace，不读取 2026-08-21 行情或 D20 结果 | 本报告第 6 节 |

## 3. `DailyResearchTrace v3` 的最小合同

### 3.1 发动机字段

| 字段 | 允许值 | 含义 |
| --- | --- | --- |
| `engine_type` | `company_event / sector_diffusion / stock_specific_demand / no_valid_engine` | 主要短期需求来源；与原三类 `opportunity_type` 对应，失效候选可用 `no_valid_engine` |
| `engine_status` | `confirmed / fresh_event_pending / unconfirmed / invalidated` | 区分已确认、重大新事件待首个交易日、尚未确认和已被反证 |
| `market_recognition.status` | `confirmed / partial / absent / not_yet_observable / unknown` | 候选是否已超出市场共同变化；必须引用当日市场环境 ID |

每只候选都要填写 `research_thesis`，不再只要求入选股填写。既有 v1/v2 归档不迁移、不倒填；Forward CSV 和 D20 结算字段不变。

### 3.2 结构化市场环境

市场 Skill 每日只形成一个结构化环境，分别说明：

- 市场传播状态；
- 广度；
- 流动性；
- 风险偏好；
- 风格；
- 集中度；
- 实际依据。

它提供共同变化基线。候选仍由板块、公司和价格 Skill 发现，市场环境不会自动升级或删除股票。

### 3.3 公司信息新颖性

公司事件按截至 `as_of` 的本地可见历史分为：

- `first_disclosure`：同一经济事项第一次出现在可见历史；
- `incremental_update`：先前事项新增金额、范围、阶段、条件或风险；
- `repeat_disclosure`：主要内容此前已知；
- `history_insufficient`：本地历史不足以作出上述判断；
- `not_applicable`：命题不依赖公司新事件。

新增信息等级另分为 `major_new_information / material_increment / limited_increment / no_new_information / unknown / not_applicable`。正式报告重复此前预告中的利润变化时，正式性可以增强基本面锚，但不能把同一信息再次写成全新短期发动机。

### 3.4 板块龙头簇

`sector_leader_cluster` 保存板块代码和名称、形成日有效成员、候选角色、传播证据、最强反证和未知。它是同一传播链的紧凑事实组，不是龙头排名器。成员不足或共同推进不成立时，`sector_diffusion` 不能伪造已确认状态。

## 4. 两条正式入选路径

### 4.1 `confirmed`

已确认发动机必须引用一条价格 `support`，其 `formation_values` 至少包括：

1. `observation_date`，且不晚于形成日；
2. 一项收盘价或绝对收益数值；
3. 一项成交额或成交额比数值；
4. 一项相对市场或相对申万二级行业收益数值。

只写 `trend_continuation`、`raw_price`、`低位`、`未透支`、价格位置、ATR、布尔命中或“行动日观察”都会被拒绝。

### 4.2 `fresh_event_pending`

条件性通道同时要求：

- 事件 `available_at <= as_of`；
- 事件发生在形成日 15:00 之后；
- 公司判断为 `first_disclosure` 或 `incremental_update`；
- 新增信息为 `major_new_information` 或 `material_increment`；
- 市场识别为 `not_yet_observable`；
- 价格决定引用同一 `event_id`，保存同一 `event_available_at`、`reaction_start_date=action_date` 和 `awaiting_first_session`；
- 决定角色只能是 `action_condition`，不能伪装成 `support`。

这条通道不适用于重复披露、普通财报、有限增量、低估值、现金流、低位或无新增信息。满足结构条件也不自动入选；AI 仍须比较材料性、公司风险、公告前抢跑和最近替代股。

## 5. 事件价格反应 v2

`compute_event_reaction_features` 仍是按需纯函数，公式版本升级为 `event-price-reaction-v2`。

| 新增边界 | 行为 |
| --- | --- |
| 盘中 `as_of` | 当 `analysis_date` 与 `as_of` 同日且尚未 15:00，排除当天日线并返回 `effective_analysis_date` |
| 收盘质量 | 计算事件后 1/3/5 日平均收盘位置和上影比例 |
| 股票日线 | 区分 `complete / suspended / missing / invalid_close / not_yet_observable` |
| 成交额 | 区分 `complete / missing / not_yet_observable` |
| 市场基准 | 区分 `complete / missing / not_yet_observable` |
| 部分窗口 | 继续返回已成熟的 1 日或 3 日值，同时保持 `partial`，不补满 5 日 |

事件仍由 AI 选择。程序不扫描公告、不选择利好、不解释因果，也不新增事实表或定时任务。

## 6. 2026-08-20 冻结时点新旧逻辑验收

### 6.1 冻结边界与市场环境

- `formation_date=2026-08-20`
- `action_date=2026-08-21`
- `as_of=2026-08-21T09:10:00+08:00`
- 原始归档是 `daily-research-trace-v1`；本节只做 v3 只读映射，不修改原文件。

当日普通股票等权收益 1.28%、上涨宽度 74.90%，但 5 日等权收益 -1.21%、5 日宽度 35.82%，5 日和 20 日成交额比仅 0.900 和 0.890。结构化市场传播环境应为 `neutral`：单日广泛修复，但多日传播和流动性没有同步确认。（证据：冻结 trace、`market_context` Parquet）

### 6.2 四只原入选股和第一最近落选股

| 股票 | 原结论 | v3 发动机 / 状态 | 市场识别 | 公司新颖性 | 形成日最小价格成交证据 | v3 验收结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 方正科技 `600601.SH` | 入选 P1，公司催化 | `company_event / unconfirmed` | `absent` | 半年报主要利润变化已由 7 月业绩预增披露；正式报告提供经营锚，属于重复披露为主、有限增量 | 1 日 +0.16%，相对市场 +0.07%、相对行业 -0.87%；5 日 -2.07%，相对市场 -0.54%、相对行业 -1.26%；成交额比 0.64 | **原入选不通过 v3**；公司证据完整不能替代短期需求确认 |
| 洛阳钼业 `603993.SH` | 入选 P2，公司催化 | `company_event / unconfirmed` | `partial` | 7 月已有半年度业绩预增；正式报告和分配方案增加经营细节，但不是首次盈利信息 | 1 日 +1.50%，相对市场 +1.41%、相对行业 +0.91%；5 日 -0.76%，相对行业 -1.46%；成交额比 0.88 | **原入选不通过 v3**；单日相对表现不足以抵消多日与成交反证 |
| 银龙股份 `603969.SH` | 入选 P3，独立价格异常 | `stock_specific_demand / confirmed` | `confirmed`（短窗口） | 半年报利润变化此前已有预增，主要承担基本面锚 | 5 日 +2.84%，相对市场 +4.37%、相对行业 +4.31%；成交额比 1.89；60 日位置 0.309 | **通过 v3**；可用真实短窗口价量值确认，20 日相对行业 -11.68% 是保留反证 |
| 中粮糖业 `600737.SH` | 入选 P4，板块扩散 | `sector_diffusion / confirmed` | `confirmed` | `not_applicable`，主命题来自板块传播 | 5 日 +25.10%，相对市场 +26.63%、相对行业 +19.53%；成交额比 2.63；农产品加工 5 日收益 +5.57%、宽度 61.54% | **通过发动机确认，但剩余路径风险高**；60 日位置 1.0、5 日涨停贡献 41.28% 必须作为强反证 |
| 北方稀土 `600111.SH` | 第一最近落选股 | `no_valid_engine / invalidated` | `absent` | 半年报利润变化已由 7 月预增披露，正式报告主要增强基本面锚 | 1 日 -3.14%，相对市场 -3.23%、相对行业 -2.21%；5 日 -3.02%，相对市场 -1.50%、相对行业 -1.24%；成交额比 0.92 | **继续落选**；v3 能稳定说明落选来自发动机与市场识别不足，而非公司业绩较差 |

因此，这次冻结验收会纠正最核心偏差：方正科技和洛阳钼业不能再仅凭完整业绩证据正式入选；银龙股份的短窗口个股需求和中粮糖业的板块传播具备合格数值证据，但中粮糖业仍须在最终比较中处理明显透支反证。该验收是合同一致性检查，不是使用未来数据重跑回测。（证据：原 trace、公告元数据、`price_analysis_context`、`sector_hotspot` Parquet）

### 6.3 `sector_leader_cluster` 实例

中粮糖业的农产品加工传播簇可由形成日有效成员中的金健米业、京粮控股和中粮糖业组成；三者 5 日收益分别约 40.75%、32.57% 和 25.10%，中粮糖业可标为 `core`。板块 5 日上涨宽度为 61.54%，说明不是单一股票上涨；同时高位和集中贡献构成反证。该簇只证明传播链，不自动选择中粮糖业。（证据：历史行业成员、价格和板块 Parquet）

### 6.4 `fresh_event_pending` 实例边界

中英科技不是第一最近落选股，因此不计入上表五只验收；它仅用来核对本轮恢复的条件通道。公司从 2026 年 2 月起已经多次披露筹划重大资产重组，8 月 20 日 19:34 披露重组草案及交易金额、标的财务、估值、负债和商誉等细节，应判断为 `incremental_update / material_increment`，不是 `first_disclosure`。该时点在形成日收盘后且早于冻结 `as_of`，首个完整反应日为行动日，因此技术上可以记录 `fresh_event_pending`。

但形成日前股价已在 1 日、5 日、20 日分别上涨约 10.02%、13.88%、37.83%，成交额比 1.88，且交易仍待股东会批准并带来负债率与商誉上升。恢复通道只意味着它不再因“没有公告后日线”被机械排除；AI 仍可因公告前抢跑、价格透支和公司风险拒绝它。（证据：公告历史、原 trace、价格 Parquet）

使用本地日线、复权因子、沪深 300、交易日和形成日有效行业成员实际调用事件反应 v2，结果为：`reaction_start_date=2026-08-21`、`observed_reaction_sessions=0`、`reaction_window_status=awaiting_first_session`、`stock_observation_status=not_yet_observable`。这证明条件通道使用的是冻结时点事实，不是自由文本假设。（证据：本地事实、事件反应函数实际执行）

## 7. Skill、Prompt 和知识库一致性

| 层 | 已同步内容 |
| --- | --- |
| 总控 Skill | v3 发动机字段、两条入选路径、候选全量结构化留痕 |
| 市场 Skill | `market_propagation_environment` 与逐候选 `market_recognition` |
| 板块 Skill | 使用形成日有效成员的 `sector_leader_cluster` |
| 公司 Skill | 首次、增量、重复、历史不足与新增信息等级 |
| 价格 Skill | support 最小数值、事件反应 v2、`fresh_event_pending` 行动条件 |
| 每日 Prompt | 只生成 v3 trace，并明确两条正式入选路径 |
| 集中复盘 Prompt | 按发动机类型和状态分层，区分发动机表现与 AI 使用正确性 |
| 知识库 | 增强短期发动机分离方法和业绩披露层级，不新增收益方向规则 |

## 8. 保持不变

- 三类原 `opportunity_type`；
- 11 个价格场景的名称、公式、阈值、权限和历史验证结果；
- `price_analysis_context`、其他派生 Parquet、数据合同和 DuckDB Schema；
- Forward CSV、D20 结算和既有历史 trace；
- 本地数据源、公告保存方式和 Scheduled Task 数量。

## 9. 验证摘要

最终验证包括：

- 事件反应与 Forward 定向测试：65 项通过；
- 完整 pytest：361 项通过；
- 五个 Skill 的 `quick_validate.py`：全部通过；
- `git diff --check`：通过；
- 11 个场景实现、价格派生和市场验证结果：零差异；
- 中英科技实际事件反应 v2：成功返回 `awaiting_first_session`；
- 2026-08-20 本地冻结事实只读验收：完成，未修改历史 trace、Forward CSV 或本地事实仓。
