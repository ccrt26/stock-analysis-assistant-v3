# A 股短期上涨发动机：五 Skill 定向优化报告

**日期：** 2026-08-21

**范围：** 程序确定性计算、五个研究 Skill、本地知识库、每日与集中复盘 Prompt

**目标：** 修正“公司业绩证据最完整，被误当成未来约 20 个交易日上涨路径最强”的偏差

## 1. 结论

本轮已经把每日正式入选统一到以下研究链：

```text
新信息或新需求
→ 是否形成板块传播或股票需求
→ 相对市场和行业的价格成交是否确认
→ 上涨路径是否仍未耗尽
→ 基本面锚和公司风险是否支持
```

这条链仍由 AI 综合判断，不是程序评分器或五道 Gate。程序只新增两项确定性职责：

1. 对 AI 选定的形成日可见事件，计算事件前后价格成交反应；
2. 校验每日研究轨迹是否把催化、发动机、传播、价格确认、锚、风险和证据引用记录一致。

公司业绩、估值、现金流和低位仍可进入研究，但只能承担公司催化、基本面锚、风险背景或价格位置的角色，不能单独回答“为什么是现在”。正式入选还必须引用至少一条正向价格确认；行动日条件、没有透支、没有反证或一个场景名称都不能替代确认。

## 2. 事实基础与边界

本轮以 2026-08-21 的本地能力盘点、当日选择复盘、方正科技五 Skill 分析和 A 股业绩短期定价讨论为事实基础。

| 已确认边界 | 本轮处理 | 证据 |
| --- | --- | --- |
| 最新可正式闭合的形成日为 2026-08-19；本地日线、行业成员、市场和四类派生观察可形成日回放 | 事件反应只使用既有本地事实，并强制按 `analysis_date` 截断 | 本地能力盘点、DuckDB/Parquet 健康盘点 |
| 公告当前主要保存元数据和官方原文入口，正文按需读取 | AI 先选具体事件；程序不批量读取公告、不建立全文库 | 本地能力盘点、公司 Skill |
| `price_analysis_context` 已有相对市场、相对申万二级行业、成交推进和 11 个场景身份 | 保留现有场景定义和权限，只补事件时点附近的窄计算 | Parquet、价格代码与价格 Skill |
| 现有 Forward CSV 不适合新增复杂研究字段，但完整 trace 被 Git 忽略并逐日归档 | 研究命题和证据引用只升级完整 trace；Forward CSV 与 D20 结算字段不变 | `forward_selection.py`、本地归档盘点 |
| 当前偏差来自公司材料完整度压过了短期需求与价格路径，而不是缺少更多公司财务字段 | 五 Skill 分工和 Prompt 改为角色分离，不增加数据源 | 当日选择复盘、方正科技分析、业绩定价讨论 |

没有新增媒体、新闻、股吧、社交情绪、券商或其他数据源，也没有把接口“理论可得”写成“本地已取得”。

## 3. 程序改动

### 3.1 形成日安全的事件反应纯计算

新增 `src/stock_analyzer/analysis/event_reaction_features.py`，公开：

```python
compute_event_reaction_features(...)
```

输入由调用方明确提供：已选事件、复权所需日线、宽基指数、交易日序列、形成日有效申万二级成员、`analysis_date` 和带时区 `as_of`。程序不自行选事件，不识别利好利空，不扫描公告，不生成候选。

每个事件返回 `evidence_id=event_price_reaction`、公式版本 `event-price-reaction-v1` 以及：

| 观察 | 口径 |
| --- | --- |
| 事件前反应 | 事件首个完整交易日前 5 个交易日的个股收益、相对市场、相对申万二级行业 |
| 事件后反应 | 首个完整交易日起 1、3、5 个交易日的个股收益、相对市场、相对申万二级行业 |
| 成交反应 | 事件后 1、3、5 日平均成交额相对事件前最多 20 个交易日平均成交额 |
| 事件时点 | 09:30 前可见的事件对齐当日；其他事件对齐下一完整交易日 |
| 覆盖状态 | `complete`、`partial` 或 `awaiting_first_session`；行业比较另有完整性状态与限制说明 |

时点和质量保护包括：

- `as_of` 必须带时区，事件 `available_at` 晚于 `as_of` 时拒绝；
- 即使调用方误传未来行情，日线和指数也先截断到 `analysis_date`；
- 交易日由调用方提供，避免从可能含未来行的价格表推断日历；
- 重复事件、重复行情、窗口不足、行业成员覆盖不足和无效分母都显式处理；
- 行业收益采用形成日有效 SW2021 L2 成员的等权收益，覆盖低于 80% 时不补算；
- 不持久化新表、不修改派生任务、不增加定时任务。

这项计算只能提供“当时价格成交怎样反应”的可复算事实。AI 仍须判断事件是否经济相关、反应是否由事件解释、是否存在事件重叠，以及它是否构成尚未耗尽的上涨路径。

### 3.2 `DailyResearchTrace` 升级为 v2

`DailyResearchTrace.trace_version` 更新为 `daily-research-trace-v2`。旧的已归档 v1 文件保持原样；当前没有待提交的 v1 trace，因此无需迁移或改写个人运行产物。

每条 `TraceDecision` 新增唯一 `decision_id`。每只正式入选候选必须填写 `research_thesis`：

| 字段 | 只回答什么 |
| --- | --- |
| `catalyst` | 形成日前的新公司事实、外部信息或明确说明无独立公司催化 |
| `short_term_engine` | 为什么形成日存在新增股票需求，而不是公司材料更完整 |
| `propagation` | 板块传播、股票自身需求或传播缺失的真实状态 |
| `price_confirmation` | 相对市场和行业的价格成交确认 |
| `remaining_path` | 确认之后为何仍有可参与路径，以及透支反证 |
| `fundamental_anchor` | 业绩、估值、现金流、主营等经营支持边界 |
| `company_risk` | 公司层最强风险或反证 |
| `critical_unknown` | 哪个未知仍可能改变结论 |
| `decision_ids` | 实际支撑该命题的决定引用，不复制整行事实 |

程序新增的只是结构一致性检查：

- `decision_id` 不得重复；
- 命题引用必须存在且属于同一股票；
- 入选股必须引用公司 Skill 的证据；公司证据可以是催化、锚或风险，不等于公司必须有新公告；
- 入选股必须引用至少一条价格 Skill 的 `decision_role=support` 证据；
- `sector_diffusion` 入选命题还必须引用板块 Skill 证据；
- `event_price_reaction` 被允许作为价格证据，并保留实际形成日数值；
- 原有每只入选或最近落选股 1—2 条价格证据、候选守恒、合格股票、日期和 ResearchResult 校验继续保留。

程序不会判断 `short_term_engine` 的自然语言是否正确，也不会因字段填写完整给股票加分。语义空话或错误因果仍由总控 Skill 负责识别。

## 4. 五个 Skill 的职责调整

| Skill | 本轮新增的明确职责 | 明确不能替代的角色 |
| --- | --- | --- |
| 总控 | 按固定发动机链组织候选；入选命题分开记录八类判断并引用实际证据 | 不按报告完整度、证据数、场景数、分数或 Gate 取舍 |
| 市场 | 提供共同变化基线，判断绝对上涨是否主要来自市场同步变化 | 市场普涨或成交放大不能成为单只股票发动机 |
| 板块 | 证明新增需求是否在有效成员间传播，区分扩散、集中与衰减 | 行业/主题标签、单日普涨、少数龙头不能替代传播；板块不能替代个股价格确认 |
| 公司 | 分开输出 `company_catalyst`、`fundamental_anchor`、`company_risk` 和可能的需求传导 | 业绩、估值、现金流、低位或材料完整度不能直接写成发动机 |
| 价格 | 给出相对市场和申万二级行业的正向价格成交确认、事件反应、剩余路径和行动条件 | 低位、未透支、场景名称、缺少反证或行动条件不能替代正向确认 |

三类机会仍保留：`company_catalyst`、`sector_diffusion`、`independent_price_anomaly`。本轮没有强迫板块或独立价格机会补造公司事件；它们只需如实记录无公司催化，并让公司 Skill 核对主营、基本面锚和公司风险。

公司事件刚披露且尚无首个完整反应交易日时，价格状态为 `awaiting_first_session`。它可以留下未决问题和行动日观察条件，但不能被写成形成日已经确认的正式入选依据。

## 5. 价格 11 个场景保持不变

本轮没有修改：

- 11 个场景的名称、公式和冻结阈值；
- `supported_with_boundary`、`provisional`、`observation_only` 与禁用组合的权限；
- D20 场景评价口径；
- `price_analysis_context`、场景验证程序或历史验证结果。

新增的 `event_price_reaction` 不是第 12 个场景，不参与场景 case/control，也不生成生产阈值。它只是具体公司事件附近的确定性原始观察。场景和 `raw_price` 继续可以承担支持、反证、比较或行动条件，但正式入选的支持必须同时写出真正使用的形成日价格成交数值。

## 6. 本地知识库改动

`research_registry.yaml` 新增 `src_cn_short_term_engine_separation`。它复用已经登记的事件研究与 A 股业绩公告研究来源，登记以下边界：

- 允许分开解释催化、锚、传播、价格确认、剩余路径和公司风险；
- 允许按形成日计算事件前后相对市场、相对行业和成交反应；
- 禁止把业绩、低估值、现金流、低位、事件后绝对上涨或行动条件单独写成发动机；
- 禁止将链条变成评分、阈值、Gate 或收益承诺；
- 本地状态为 `insufficient_for_direction`：现有证据支持方法和时点边界，不支持固定反应阈值或未来 20 日方向规则。

没有修改 `supplement_validation_results.yaml`、`market_skill_validation_results.yaml` 或其他历史验证结论。

## 7. Prompt 改动

### 每日选择 Prompt

每日 Prompt 现在要求：

- 五 Skill 按固定发动机链协作；
- 对具体形成日可见事件可按需调用事件反应函数，并以 `event_price_reaction` 留痕；
- 入选股必须分开写八类研究命题；
- 每条决定使用唯一 ID，入选命题引用公司与正向价格证据；
- 仍只生成一份 pending trace，不新增附件、数据库或模型调用流程。

### 集中复盘 Prompt

D20 集中复盘除继续分开评价“场景本身”和“AI 如何使用场景”外，新增检查：

- 当时引用事件的可复算价格反应是否与发动机解释一致；
- 是否把业绩、估值、现金流、低位或行动条件误当发动机；
- `decision_ids` 能否还原支持、反证、比较和实际改变选择的证据。

复盘仍是人工发起，不新增定时任务、数据库、模型或统计平台。

## 8. 验证结果

| 验证 | 结果 | 覆盖重点 |
| --- | --- | --- |
| 事件反应单元测试 | 4 项通过 | 盘前/盘后对齐、部分窗口、未来行截断、等待首个交易日、`as_of` 拒绝 |
| Forward/trace 单元测试 | 42 项通过 | v2 正常记录、发动机命题、决定引用、公司/价格/板块角色、事件价格证据、既有 Forward 行为 |
| 价格场景、价格派生、研究派生和知识测试 | 31 项通过 | 确认 11 个场景和现有派生逻辑未被改写，知识 YAML 可读取 |
| 完整 pytest 回归 | 342 项通过 | 仓库全量测试；使用 `python -m pytest` 保证项目根目录可导入 |
| 五个 Skill 结构校验 | 全部通过 | front matter、名称和基本 Skill 结构 |
| 差异检查 | 通过 | 无空白错误；未改本地归档、数据库、CSV 或历史验证结果 |

## 9. 改动文件

程序与测试：

- `src/stock_analyzer/analysis/event_reaction_features.py`
- `src/stock_analyzer/ops/forward_selection.py`
- `tests/test_event_reaction_features.py`
- `tests/test_forward_selection.py`

五个 Skill：

- `.agents/skills/orchestrating-stock-research/SKILL.md`
- `.agents/skills/interpreting-market-macro/SKILL.md`
- `.agents/skills/researching-sectors-industries/SKILL.md`
- `.agents/skills/researching-company-events/SKILL.md`
- `.agents/skills/analyzing-price-trading/SKILL.md`

知识、架构和 Prompt：

- `src/stock_analyzer/knowledge/research_registry.yaml`
- `docs/architecture/current-v3-architecture.md`
- `docs/2026-08-21-research-knowledge-base-index.md`
- `ops/forward-selection-prompt.md`
- `ops/periodic-research-review-prompt.md`
- 本报告

## 10. 保持不变与剩余限制

本轮保持不变：事实合同、DuckDB Schema、Parquet 派生、Forward CSV、D20 结算、11 个价格场景、数据任务、公告存储、数据源和历史验证结果。

仍需 ChatGPT 后续在真实每日 trace 中检查的不是新程序参数，而是 AI 判断质量：

1. `short_term_engine` 是否真的解释新增需求，还是换词复述公司业绩；
2. `propagation` 是否有成员共同事实，还是行业标签；
3. `price_confirmation` 是否扣除了市场和行业共同变化，并区别事件前抢跑与事件后反应；
4. `remaining_path` 是否同时处理透支、成交推进效率和最接近替代股；
5. 公司催化、基本面锚和公司风险是否各自处在正确角色。

这些问题不适合继续写成程序阈值。下一步应先让新的 v2 轨迹在真实形成日运行并积累到 D20，再按现有集中复盘 Prompt 检查“发动机事实是否有效”和“AI 是否正确使用”这两个不同问题。
