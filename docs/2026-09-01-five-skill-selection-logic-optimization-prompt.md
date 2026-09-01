# A股五个 Skill 选股逻辑优化——Codex 完整执行指令 V1.0

> **给 Codex：直接执行本文件，不要把它改写成另一份泛化计划，也不要把任务转换成“审计规则优化”“边界检查”或“系统加固”。**
>
> 本任务是对现有个人 A 股助手的**选股逻辑**进行一次有证据、可复查、不过度工程化的优化。审计、测试和数据边界只是验证手段，不是交付目标。

---

## 一、任务基线

### 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

### 唯一基线分支

```text
codex/skill-optimization-dataset-20260831
```

### 唯一基线提交

```text
e03677c6b57b0288adf3c24caffa3f31c6ddbfac
```

### 新工作分支

```text
codex/five-skill-selection-logic-optimization-20260901
```

### 工作目录

从基线提交创建独立 worktree。不得直接修改 `main`，不得在原数据包分支上继续堆提交。

建议命令：

```bash
git worktree add \
  .worktrees/five-skill-selection-logic-optimization-20260901 \
  -b codex/five-skill-selection-logic-optimization-20260901 \
  e03677c6b57b0288adf3c24caffa3f31c6ddbfac
```

进入新 worktree 后先核对：

```bash
git rev-parse HEAD
git branch --show-current
git status --short
```

必须分别得到：

```text
e03677c6b57b0288adf3c24caffa3f31c6ddbfac
codex/five-skill-selection-logic-optimization-20260901
空工作区
```

如基线提交或分支不一致，不得自行换成其他提交继续。

---

## 二、唯一目标

利用已经冻结并上传的 2026-08-20 至 2026-08-31 选股样本，优化以下五个 Skill 对股票的：

1. 发现；
2. 因果解释；
3. 同类比较；
4. 淘汰；
5. 最终 0—5 只取舍；
6. 条件性事件与已确认机会的区分；
7. 后续用事实评价选股逻辑的能力。

目标不是提高历史报表数字，也不是增加更多规则，而是让助手更稳定地回答：

```text
为什么是这只，而不是同一上涨原因下最接近的另一只？
这条上涨原因现在是否真实存在？
价格和成交是在连续确认，还是只有一次脉冲？
上涨路径是否仍在产生新增趋势，而不是已经耗尽？
最强反证为什么没有推翻它？
为什么名单到这里应当停止，而不是继续补到 5 只？
```

最终必须出现**实质性的选股逻辑变化**。如果只做以下事情，视为任务失败：

- 删除旧术语；
- 增加文字扫描测试；
- 增加边界校验；
- 增加数据安全检查；
- 增加更多日志；
- 修改报告标题；
- 重写审计规则；
- 增加防御性异常处理；
- 只整理文档但不改变候选比较和最终取舍方法。

总控 Skill 与价格 Skill 必须有真正影响候选优先级、淘汰、条件性处理或停止增加名单的改动；公司、板块和市场 Skill 做与选股结果直接相关的配套优化。

---

## 三、任务性质：选股逻辑优化，不是审计工程

### 本轮要做

- 用现有样本找出可重复的选股判断问题；
- 修正五个 Skill 中会影响实际选股的逻辑；
- 把“已经确认的正式机会”和“尚待首日确认的事件线索”分开；
- 强化同一发动机、同一板块、同一事件类型内的直接比较；
- 强化总控停止增加名单的判断；
- 用现有本地数据补充候选股结果对照，方便后续 D20 继续评价；
- 编写必要测试，证明代码和输出行为符合新的选股逻辑。

### 本轮不要做

- 不新建评分器、总分、权重、排名模型或机器学习模型；
- 不增加第六个 Skill；
- 不增加新的发动机类型；
- 不修改七种 `engine_type`、四种 `engine_status` 和 11 个价格场景；
- 不重新搜索技术指标参数；
- 不建立回测平台、监控平台、数据中台或审批流程；
- 不新增数据库表、迁移、外部数据源或 API；
- 不重构整个 `forward_selection.py` 或 `forward_monitor.py`；
- 不优化自动交易、仓位、止盈止损；
- 不把任务扩大为时点安全、权限、安全、哈希、审计或合规改造；
- 不因单只股票后来上涨而编写股票专用规则；
- 不用 8 月 31 日之后的信息回写形成日理由；
- 不因为目前 D20 尚未成熟而放弃本轮可确认的逻辑优化；
- 也不在 D20 尚未成熟时删除发动机或拟合固定阈值。

测试只用于锁住本轮选股行为，不得演变成一套新的审计框架。

---

## 四、开始前必须读取的文件

按以下顺序完整读取，不能只搜索关键词：

1. `AGENTS.md`
2. `docs/architecture/current-v3-architecture.md`
3. `docs/architecture/a-share-short-horizon-engine-contract-v4.md`
4. `.agents/skills/orchestrating-stock-research/SKILL.md`
5. `.agents/skills/interpreting-market-macro/SKILL.md`
6. `.agents/skills/researching-sectors-industries/SKILL.md`
7. `.agents/skills/researching-company-events/SKILL.md`
8. `.agents/skills/analyzing-price-trading/SKILL.md`
9. `ops/forward-selection-prompt.md`
10. `ops/forward-monitor-prompt.md`
11. `src/stock_analyzer/ops/forward_selection.py`
12. `src/stock_analyzer/ops/forward_monitor.py`
13. `tools/export_skill_optimization_dataset.py`
14. `tools/build_skill_optimization_workbook.mjs`
15. `tools/validate_skill_optimization_dataset.py`
16. `tests/test_engine_contract_v4.py`
17. `tests/test_engine_contract_knowledge_v4.py`
18. `tests/test_v4_operational_prompts.py`
19. `tests/test_forward_selection.py`
20. `tests/test_forward_monitor.py`
21. `tests/test_forward_monitor_prompt.py`
22. `tests/test_export_skill_optimization_dataset.py`
23. `research/skill-optimization/selection-sample-2026-08-20-to-2026-08-31/README.md`
24. 该样本目录下全部 `data/*.csv`、`data/*.jsonl`、`manifest.json`

将本执行文件原样保存进仓库：

```text
docs/2026-09-01-five-skill-selection-logic-optimization-prompt.md
```

它是本轮任务的唯一目标说明。后续不能另写一份更宽、更抽象的 Prompt 取代它。

---

## 五、现有样本的使用原则

当前样本包含：

- 8 个行动日；
- 29 次正式入选；
- 28 只不同股票；
- 78 条候选记录；
- 126 条决策证据；
- 截至 2026-08-31 的早期价格路径；
- 26 条已形成的逐 episode 复盘；
- 2026-08-20 的旧版记录不具备完整 V4 结构。

本轮使用样本时必须区分：

### 可以立即用来修改的内容

这些问题不需要等满 D20：

- 五个 Skill 对同一候选采用互相矛盾的选择口径；
- 待首日确认的事件与已确认机会被同口径展示、计数或评价；
- 同类候选比较没有真正区分多日连续推进与单日脉冲；
- 成交放大没有与收盘推进绑定；
- “剩余空间”被单一 ATR 或低位概念代替；
- 强反证、关键未知只写在文字里，却不改变取舍；
- 总控继续加入“剩余候选中最好的一只”，形成隐性补位；
- 板块成立后，具体股票没有再次证明自身路径；
- 公司事件真实，但事件阶段、当前影响和价格接受没有分开；
- 数据通道缺失时，从其他通道补足推荐数量。

### 暂时不能据此做的内容

- 删除某一种发动机；
- 修改 11 个价格场景；
- 调整固定阈值；
- 根据短期收益拟合规则；
- 宣称某一种发动机长期无效；
- 根据少数股票的 D1—D8 结果得出 D20 结论。

---

## 六、执行纪律

这是会修改正式选股逻辑的任务。按 `AGENTS.md`：

- 在实施前，**恰好使用一次**独立审查子智能体；
- 模型为 `gpt-5.6-sol`；
- 推理强度为 `xhigh`；
- 它只审查本轮拟修改内容是否符合本文件、是否存在漂移、遗漏或过度工程化；
- 它不实施、不启动其他子智能体；
- 主智能体采用审查后的最小修订方案；
- 除这一次强制审查外，不再启动其他子智能体。

不得因为任务复杂而拆成大量代理。主智能体连续完成分析、修改、验证、提交和推送。

除非遇到以下真实阻碍，否则不要中途询问用户：

- 基线提交无法取得；
- 本地事实仓完全不存在，导致既有导出工具也无法运行；
- 无 GitHub 推送权限；
- 现有仓库规则与本文件出现不可同时满足的硬冲突。

普通代码选择、文件位置和测试写法由 Codex自行完成。

---

# 第一阶段：形成最小、可证据化的基线诊断

## Task 1：记录基线

在任何修改前运行：

```bash
git status --short
git rev-parse HEAD
python -m pytest -q
```

如项目固定使用 `.venv`，沿用现有解释器；不要重建环境或升级依赖。

在最终报告中记录：

- 基线提交；
- 基线测试总数；
- 通过/失败结果；
- 本地样本可读取情况；
- 本地事实仓是否足以重新导出样本。

## Task 2：编写选股逻辑基线诊断

创建：

```text
research/skill-optimization/five-skill-selection-logic-optimization-20260901/baseline-diagnosis.md
```

诊断只围绕“为什么会错选、弱选、混选或继续补位”，不要写成合同审计报告。

必须至少覆盖以下四组案例：

### A. 条件性事件组

全部检查：

- 融发核电；
- 丽珠集团；
- 亚康股份；
- 中国船舶。

重点回答：

- 形成日事件是否真实；
- 是否已经有事件后的价格确认；
- 当时应属于正式已确认机会，还是待确认事件线索；
- 是否存在可靠参与价格；
- 原行动条件后来是否满足；
- 当前系统是否把“事件值得研究”误写成“已经正式可执行”。

### B. 独立价格组

至少选择 6 个案例，必须同时包含后续得到支持和后续减弱的股票。优先覆盖：

- 宝新能源；
- 建新股份；
- 国缆检测；
- 奥克股份；
- 洛阳钼业；
- 中国广核；
- 金岭矿业；
- 杭氧股份；
- 中钢国际。

重点回答：

- 多日连续性是否真实；
- 最大单日对 3 日、5 日涨幅贡献多少；
- 放量是否推动多个收盘；
- 形成日是否仍在推进，还是已经出现放量停滞；
- 剩余路径判断是否依赖单一指标；
- 与同发动机替代股比较是否充分。

### C. 板块传播组

至少覆盖：

- 四川九洲；
- 瑞丰新材；
- 另一个板块入选或近邻落选案例。

重点回答：

- 板块发动机是否成立；
- 板块成立是否被错误等同于具体股票成立；
- 小样本、高前三贡献或扩散收缩是否真正影响取舍；
- 候选自身的成交、收盘和剩余路径是否单独成立。

### D. 近邻落选与比较组

至少选择 4 个 `rejected` 或 comparator，优先使用样本已有近邻比较。

重点回答：

- 后来表现更好时，是形成日发现遗漏、总控比较错误，还是合理未选；
- 原比较是否跨了不同发动机，导致“不是同一种机会”的无效比较；
- 是否存在“因为财务更好，所以覆盖了价格更差”的替代问题；
- 是否存在“因为价格更低，所以自动认为空间更大”的问题。

## Task 3：形成问题—责任 Skill—最小修改表

`baseline-diagnosis.md` 必须包含一张表：

```text
问题
→ 影响的选股结果
→ 形成日样本证据
→ 唯一或主要责任 Skill
→ 本轮最小修改
→ 明确不做什么
```

问题只允许归到以下五类：

1. 市场环境对搜索重点的误用；
2. 板块成立与具体股票成立混写；
3. 公司事件质量与价格接受混写；
4. 价格连续性、成交有效性和剩余路径区分不足；
5. 总控同类比较、条件性处理和停止增加名单不足。

不要新增一套复杂错误分类法。

## Task 4：执行唯一一次独立审查

将以下内容交给唯一审查子智能体：

- 本文件；
- `baseline-diagnosis.md`；
- 拟修改文件列表；
- 每一批的最小修改摘要。

审查只回答：

```text
目标是否仍是优化选股逻辑？
是否把任务错误扩大成审计/边界/平台工程？
哪些修改与样本证据没有直接关系？
是否存在应由一个 Skill 负责却被重复写入多个 Skill 的问题？
三批修改是否能够独立验证？
```

采用审查给出的最小修订后继续，不再复审。

---

# 第二阶段：第一批修改——先修正会直接影响选股结果的语义混用

> 本批不是“合同审计”。只修正那些会让模型采用两套选股逻辑，或把待确认事件当成正式已确认股票的问题。

## Task 5：只保留一套当前选股语义

检查五个 Skill、V4 合同和日常执行 Prompt。

允许修改：

```text
.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/interpreting-market-macro/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/researching-company-events/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md
docs/architecture/a-share-short-horizon-engine-contract-v4.md
ops/forward-selection-prompt.md
ops/forward-monitor-prompt.md
```

要求：

- 当前执行逻辑只使用 V4 七种 `engine_type`；
- 当前执行逻辑只使用 V4 四种 `engine_status`；
- 当前执行逻辑只使用 V4 六种市场传播模式；
- 当前执行逻辑只使用 V4 的公司新增信息等级；
- 输出示例不得继续展示 V3 trace 或旧状态；
- 历史说明可以保留，但必须明确“只用于读取旧记录，不参与新选股”。

不要新建通用文本扫描器。只在现有测试中增加少量直接断言，防止正式执行段重新出现旧输出结构。

## Task 6：把 active 与 conditional 在选股结果中真正分开

### 固定业务含义

#### 已确认正式推荐

必须同时满足：

```text
engine_status = active
market_recognition.status = confirmed
存在符合 V4 的价格 support
行动日有可能正常参与
```

这部分才进入：

- “今天新推荐的股票”；
- 正式推荐数量；
- 正式推荐收益统计；
- 以可靠入口价格开始的 D1—D20 结果。

#### 待确认事件线索

满足：

```text
engine_type = fresh_event_pending
engine_status = conditional
market_recognition.status = pending
事件后完整交易日为 0
```

这部分必须单独展示为：

```text
等待首个交易日确认的事件线索
```

不得与 active 使用同一口径：

- 不计入“已确认正式推荐数量”；
- 不因为事件重大就生成正式收益；
- 不使用行动日开盘价自动假设已经参与；
- 不把 `awaiting_first_session` 写成已经晋升；
- 不把首日高开本身写成条件满足；
- 行动条件未满足时，保留事件研究记录，但不得回填成一次正式执行。

### 实现原则

优先使用现有：

- `engine_type`
- `engine_status`
- `market_recognition`
- `action_condition_decision_id`
- monitor 中已有价格、成交和收盘观察

派生展示和评价类别。

不要增加新数据库表，不要建立持久化状态机，不要新增第五种发动机状态。

如现有 trace 为兼容性仍需保留 `final_fate=selected`，可以保留；但用户输出、正式推荐计数和收益评价必须按 `engine_status` 分开。

只有在现有字段无法表达展示类别时，才允许增加一个**派生字段**，并且只用于报告/导出，不进入数据库迁移。

## Task 7：可靠入口价格与条件满足

代码行为必须满足：

1. active 股票有可靠入口时，正常开启结果记录；
2. active 股票无可靠入口时，结果状态明确为不可评价，不虚构收益；
3. conditional 事件在首个交易日条件未观察前，不开启正式收益；
4. conditional 条件不满足时，不按行动日开盘价回算；
5. conditional 条件满足且能够识别可靠参与价格时，才从该可靠时点开始评价；
6. 不得把后来的盘中价格倒推成早晨可参与价格；
7. 不需要实现自动交易或自动买入动作。

如果当前代码无法无状态地完成第 5 项，只需：

- 准确记录 `满足 / 不满足 / 未知`；
- 有可靠入口时记录入口；
- 无可靠入口时保持不评价。

不要为此建设自动转换服务。

## Task 8：第一批测试

优先修改现有测试，不要新建大量测试文件。

至少验证：

- active 出现在正式推荐区；
- conditional 不进入 active 推荐数量；
- conditional 出现在独立的待确认事件区；
- `awaiting_first_session` 不能被当作价格 support；
- 无可靠入口价格不生成正式收益；
- 条件不满足不回填行动日开盘收益；
- 旧 V4 记录仍可读取；
- 没有新增发动机、状态或数据库表。

建议运行：

```bash
python -m pytest -q \
  tests/test_engine_contract_v4.py \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_selection.py \
  tests/test_forward_monitor.py \
  tests/test_forward_monitor_prompt.py
```

通过后提交：

```bash
git add \
  docs/2026-09-01-five-skill-selection-logic-optimization-prompt.md \
  research/skill-optimization/five-skill-selection-logic-optimization-20260901/baseline-diagnosis.md \
  .agents/skills \
  docs/architecture/a-share-short-horizon-engine-contract-v4.md \
  ops \
  src/stock_analyzer/ops \
  tests

git commit -m "fix: separate confirmed picks from conditional events"
```

提交前只加入实际修改文件，不要使用无差别 `git add .`。

---

# 第三阶段：第二批修改——实质优化五个 Skill 的选股判断

> 这是本轮核心。必须改变候选比较与最终取舍，不能只改术语。

## Task 9：市场 Skill——只改变搜索重点，不直接决定股票

市场 Skill 保留现有六种传播模式，但必须明确其对后续选股的实际作用：

### `broad_sustained_participation`

- 市场普涨会降低个股绝对涨幅的信息量；
- 独立价格型候选必须继续证明相对市场、相对行业和成交推进；
- 不因为环境好就放宽到普通跟涨股。

### `one_day_repair`

- 单日上涨不能证明 3 日、5 日趋势；
- 优先排查市场修复带来的假独立强势；
- 要求候选的多窗口相对增量仍存在。

### `sector_rotation`

- 板块候选可以提高研究优先级；
- 但必须由板块 Skill 证明共同传播，并由价格 Skill 证明具体股票自身路径；
- 不把行业标签当成入选理由。

### `concentrated_speculation`

- 提高对单日脉冲、涨停贡献、成交拥挤和可参与性的关注；
- 不是一票否决；
- 真正连续、非涨停依赖的个股仍可入选。

### `weak_or_fragmented`

- 普通绝对上涨可信度较低；
- 只有清晰的独立需求、已确认事件重估或真实板块传播才应继续；
- 不以“逆市上涨”四个字替代多日确认。

### `unclear`

- 保持市场解释未知；
- 不得因为市场未知而自动选择或淘汰股票。

市场 Skill 仍不得输出股票，不增加市场评分或仓位建议。

## Task 10：板块 Skill——板块成立与股票成立必须分两步

板块 Skill 的判断顺序固定为：

```text
板块共同动力是否成立
→ 候选在板块中是否为真实领导或核心成员
→ 候选自身价格路径是否仍在推进
→ 与同板块、同发动机最接近成员相比为什么更好
```

必须增加以下选股逻辑：

1. 板块扩散成立，只代表这个方向值得继续研究，不自动产生入选股；
2. 候选必须是 `leader_confirmed` 或 `core_diffusion_member`；
3. “它比龙头涨得少”不能单独证明剩余空间；
4. 小样本行业、前三只贡献接近上限、广度正在收缩时，需要候选有更强的自身价格连续性；
5. 候选自身若出现放量不进、冲高回落或相对行业转弱，即使板块仍强，也应降低或淘汰；
6. 同一板块必须优先直接比较成员，不要拿不同发动机股票替代同类比较；
7. 公司风险明显更差时，需要价格和板块角色存在足够清晰的不对称优势，不能只写成附带风险。

不建立板块评分，不增加固定行业配额。

## Task 11：公司 Skill——先判断事件质量，再交给价格验证

公司事件固定按以下顺序研究：

```text
是否首次或实质新增
→ 当前处于什么法律/业务阶段
→ 与主营是否直接相关
→ 材料性是否可解释
→ 收入、利润和现金流可能怎样传导
→ 兑现需要多久
→ 哪些条款可能使传导失败
→ 交给价格 Skill 判断市场是否接受
```

必须明确区分：

- 预中标；
- 中标通知；
- 正式合同签署；
- 合同生效；
- 开始交付；
- 验收；
- 收入确认；
- 现金回收。

对合同事件至少比较：

- 金额相对近期收入或对应业务规模；
- 履约期限；
- 是否一次性交付或多年服务；
- 付款、预付、验收或终止条件；
- 是否需要大量先期采购、融资或建设；
- 公司是否明确对当期利润无重大影响；
- 客户和执行条件是否足够清楚。

对业绩披露：

- 正式报告只是先前预告或快报确认时，不得再次算新催化；
- 利润高增必须同时看低基数、现金流和负债；
- 基本面锚可以支持价格命题，但不能替代新增需求。

公司 Skill 只证明事件和传导，不得自己宣布价格已经确认。

## Task 12：价格 Skill——加强相似强势股之间的区分力

不得增加新指标，不得修改 11 个价格场景。使用现有字段完成以下改动。

### 12.1 多日连续性与单日脉冲分开

每只深度候选至少回答：

- 1 日、3 日、5 日相对市场表现；
- 1 日、3 日、5 日相对行业表现；
- 最大单日上涨占 3 日或 5 日累计涨幅的比例；
- 涨停日贡献；
- 有几个交易日真正形成上涨且收盘位置有效；
- 最近一个形成日是在继续增强，还是已经回落。

不能只凭“5 日上涨 + 放量”判断连续需求。

### 12.2 成交放大必须证明有效

成交放大需要同时回答：

- 放量出现在哪些交易日；
- 有几次放量真正推动收盘上移；
- 是否存在放量滞涨；
- 是否存在冲高回落；
- 形成日成交仍在推动，还是此前一天脉冲后的衰减；
- 成交恢复正常后，相对强势是否还在。

“成交额为 20 日均值若干倍”不能单独作为支持。

### 12.3 剩余路径必须是组合判断

至少同时使用：

- 3 日、5 日、20 日累计涨幅；
- 最大单日贡献；
- 涨停贡献；
- 距离 60 日、82 日或 250 日前高；
- 当前价格区间位置；
- `target_atr_distance_20pct`；
- 突破是否仍在产生新增趋势；
- 成交增加后收盘效率是否继续。

不得把以下任何一项单独写成“空间充足”：

- 位置低；
- 20 日涨幅小；
- 距离目标需要较多 ATR；
- 没有涨停；
- 未到历史高点。

### 12.4 强反证必须改变选择

每个 `critical_unknown` 或最强价格反证必须产生以下至少一种实际后果：

- 淘汰；
- 降低同类优先级；
- 转为 conditional；
- 设置明确、可观察的行动条件；
- 使总控停止增加名单。

不得继续出现“风险很明显，但总体较强所以仍选”的空泛处理。

### 12.5 同发动机比较优先

独立价格型候选必须优先与独立价格型候选比较。

比较至少覆盖：

- 路径连续性；
- 成交有效性；
- 收盘质量；
- 剩余路径；
- 形成日是否仍在增强；
- 公司风险是否明显恶化。

没有合适同发动机替代股时，可以明确写“当日没有可比对象”，但不得用完全不同原因的股票假装完成比较。

## Task 13：总控 Skill——同类先比、跨类后比，并真正停止增加名单

总控固定采用：

```text
第一步：按主要发动机分组
第二步：同发动机内直接比较
第三步：每组只留下真正成立的少量候选
第四步：跨发动机比较最终机会质量
第五步：逐只判断是否仍达到当前正式名单的绝对质量
第六步：停止，而不是补足 5 只
```

### 每只入选股必须回答

1. 新增需求或新信息是什么；
2. 是市场、板块、公司事件还是股票自身需求在传播；
3. 价格和成交已经确认到什么程度；
4. 剩余路径依据是什么；
5. 最强反证是什么；
6. 为什么没有被最强反证推翻；
7. 为什么它优于同发动机最接近替代；
8. 为什么它与当前最弱入选股仍处于同一机会质量层级。

### 停止增加名单的硬问题

加入下一只股票前，必须回答：

```text
它是一个独立成立的机会，
还是仅仅是剩余候选中最好的一只？
```

如果只能证明“它比剩下的更好”，而不能证明它与当前正式名单处于相近绝对质量，停止增加名单。

### 禁止隐性补位

- 公司通道缺失时，不得多选价格股补数量；
- 行业数据缺失时，不得多选公司事件补数量；
- 当日可以只有 0、1、2 只；
- conditional 事件不得占据 active 正式推荐数量；
- 不设置发动机配额；
- 不要求每天每种类型都出现。

### 关键未知必须有决策后果

总控不能只保存 `critical_unknown` 文本。它必须明确说明该未知造成：

- rejected；
- unresolved；
- conditional；
- priority lowered；
- action condition；
- stop adding。

不新增评分字段。

## Task 14：第二批语义验收案例

创建：

```text
research/skill-optimization/five-skill-selection-logic-optimization-20260901/selection-impact-matrix.csv
```

必须覆盖全部 29 条正式入选事件，一行一条，不得只挑成功案例。

字段固定为：

```text
event_key
formation_date
action_date
ts_code
name
trace_version
original_engine_type
original_engine_status
original_output_class
revised_output_class
primary_selection_logic_issue
revised_formation_day_decision
same_engine_comparator
decisive_support
decisive_counterevidence
action_condition_effect
early_outcome_used_only_for_evaluation
notes
```

要求：

- 2026-08-20 旧记录标记 `legacy_v1_not_rewritten`；
- `revised_formation_day_decision` 只能根据形成日冻结证据填写；
- 形成日修订结论写完后，才允许填写早期结果评价；
- 不用未来结果倒推理由；
- 不要求为了显得有变化而强行改判；
- 但必须清楚展示新逻辑在哪些案例改变了分类、优先级、条件或最终取舍。

如果矩阵显示所有案例都完全没有任何选择行为变化，说明修改仍停留在文字层面，第二批不得视为完成。

## Task 15：第二批测试与提交

对代码可确定行为编写测试；不要伪造“LLM 一定会按文档思考”的自动化测试。

测试重点：

- 同发动机比较信息能够进入最终理由或近邻比较；
- conditional 不补 active 名单；
- 关键未知能够体现在最终状态或行动条件；
- 用户输出能够区分 active 与 conditional；
- 现有 V4 schema 仍有效；
- 没有新增评分、权重或发动机；
- 11 个价格场景未修改。

建议运行：

```bash
python -m pytest -q \
  tests/test_engine_contract_v4.py \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_selection.py \
  tests/test_forward_monitor.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_price_analysis_features.py \
  tests/test_price_indicator_features.py \
  tests/test_price_scenario_validation.py \
  tests/test_market_context_features.py
```

通过后提交：

```bash
git add \
  .agents/skills \
  docs/architecture/a-share-short-horizon-engine-contract-v4.md \
  ops \
  src/stock_analyzer/ops \
  tests \
  research/skill-optimization/five-skill-selection-logic-optimization-20260901/selection-impact-matrix.csv

git commit -m "feat: strengthen five-skill stock selection logic"
```

---

# 第四阶段：第三批修改——补齐用于继续优化选股逻辑的结果对照

> 本批不是建设审计平台。只扩充现有导出工具，让以后能够回答“是发现漏了，还是总控选错了”。

## Task 16：保留原始样本，不覆盖基线

不要覆盖：

```text
research/skill-optimization/selection-sample-2026-08-20-to-2026-08-31
```

该目录是本轮基线证据。

新增分析输出放在：

```text
research/skill-optimization/five-skill-selection-logic-optimization-20260901/
```

## Task 17：最小扩展现有导出工具

优先修改：

```text
tools/export_skill_optimization_dataset.py
tests/test_export_skill_optimization_dataset.py
```

只有工作簿确实需要同步展示新增字段时，才修改：

```text
tools/build_skill_optimization_workbook.mjs
```

不要为了本轮重新设计工作簿。

### 新增 `candidate_outcomes.csv`

覆盖全部候选账记录，而不只是正式入选股。

至少包含：

```text
run_id
formation_date
action_date
ts_code
name
final_fate
opportunity_type
engine_type
engine_status
selection_as_of
outcome_through_date
outcome_trading_day_count
outcome_data_status
outcome_close_return
outcome_max_close_return
outcome_max_high_return
outcome_mae
outcome_close_drawdown_from_peak
relative_market_return_if_available
relative_sector_return_if_available
```

用途是比较：

- selected；
- rejected；
- unresolved。

不得据此自动生成新评分。

### 新增 `conditional_event_outcomes.csv`

只覆盖 `fresh_event_pending + conditional`。

至少包含：

```text
event_key
formation_date
action_date
ts_code
name
event_id
event_available_at
original_action_condition
first_observable_session
condition_result
reliable_entry_available
reliable_entry_date
reliable_entry_price
formal_return_started
outcome_data_status
outcome_close_return
outcome_max_close_return
outcome_mae
notes
```

`condition_result` 只能是：

```text
met
not_met
unknown
```

这只是导出结果分类，不增加新的发动机状态。

规则：

- 不能观察时写 `unknown`；
- 行动条件不满足时，`formal_return_started=false`；
- 没有可靠入口价时，不计算正式收益；
- 不得默认使用行动日开盘价；
- 不得从后续最高价倒推参与。

### `undiscovered_outcome_leads.csv`

只有当现有本地仓库已经能够按形成日重建完整合格股票范围时才生成。

目的：

- 找到形成日未进入 78 条候选账，但后续出现较强可执行路径的股票；
- 为以后区分 `discovery miss` 与 `decision miss` 提供线索。

只使用现有数据和现有股票范围逻辑，不新增数据源或全新回测系统。

如果现有仓库无法可靠重建某个形成日的完整范围：

- 不建设新平台；
- 不补猜；
- 在最终报告中写清缺少哪个现有输入；
- `candidate_outcomes.csv` 和 `conditional_event_outcomes.csv` 仍必须完成。

## Task 18：第三批数据只用于反馈，不立即调阈值

本轮新增结果对照只用于回答：

- 哪些弱选来自条件性事件混入；
- 哪些来自价格连续性判断不足；
- 哪些来自板块对了但成员选错；
- 哪些来自同类比较不足；
- 哪些来自总控继续补位；
- 哪些可能是发现漏掉。

不得根据当前短窗口：

- 删除发动机；
- 增加硬阈值；
- 修改 11 个价格场景；
- 宣称 D20 已验证；
- 继续进行第二轮规则调参。

## Task 19：第三批测试与提交

至少验证：

- 原始样本导出仍可运行；
- 新候选结果覆盖 selected/rejected/unresolved；
- conditional 无可靠入口时无正式收益；
- 原始冻结理由没有被结果数据覆盖；
- 输出不包含本地绝对路径；
- 原始样本目录未被改写；
- 不新增数据库或依赖。

建议运行：

```bash
python -m pytest -q tests/test_export_skill_optimization_dataset.py
```

随后使用现有本地数据执行一次真实导出，并运行：

```bash
python tools/validate_skill_optimization_dataset.py --help
```

根据现有脚本参数运行真实验证，不要另写第二个验证器。

通过后提交：

```bash
git add \
  tools/export_skill_optimization_dataset.py \
  tools/build_skill_optimization_workbook.mjs \
  tools/validate_skill_optimization_dataset.py \
  tests/test_export_skill_optimization_dataset.py \
  research/skill-optimization/five-skill-selection-logic-optimization-20260901

git commit -m "feat: export candidate outcomes for selection tuning"
```

只加入实际发生变化的文件。

---

# 第五阶段：总体验证、报告与 GitHub 上传

## Task 20：编写最终实施报告

创建：

```text
research/skill-optimization/five-skill-selection-logic-optimization-20260901/README.md
```

必须包含以下内容。

### 1. 唯一目标

明确写：

```text
本轮优化的是五个 Skill 的选股逻辑，不是审计规则、边界系统或交易系统。
```

### 2. 基线证据

- 样本数量；
- 行动日；
- V4 与旧记录区别；
- 当前结果窗口限制。

### 3. 三批修改结果

逐批说明：

- 修改了什么；
- 为什么会影响选股；
- 使用了哪些形成日案例；
- 哪些文件负责；
- 哪些事情刻意没有做。

### 4. 五个 Skill 的实质变化

分别写清：

- 市场 Skill 如何改变搜索重点；
- 板块 Skill 如何分开“板块成立”和“股票成立”；
- 公司 Skill 如何判断事件质量与兑现路径；
- 价格 Skill 如何区分连续推进和单日脉冲；
- 总控 Skill 如何进行同发动机比较并停止补位。

不得只写“完善了规则”“增强了准确性”。

### 5. active 与 conditional 的最终行为

用具体例子说明：

- 哪些属于已确认正式推荐；
- 哪些属于待确认事件线索；
- 条件不满足时如何处理；
- 无可靠入口时如何评价。

### 6. 样本影响

汇总 `selection-impact-matrix.csv`：

- 分类发生变化的数量；
- 优先级或行动条件发生变化的数量；
- 保持不变的数量；
- 旧 V1 无法重建的数量；
- 不得声称短期结果就是长期改进。

### 7. 数据扩展

- `candidate_outcomes.csv` 记录数；
- `conditional_event_outcomes.csv` 记录数；
- 是否生成 `undiscovered_outcome_leads.csv`；
- 如未生成，缺少的现有输入是什么。

### 8. 测试与验证

原样记录：

- 基线测试；
- 第一批定向测试；
- 第二批定向测试；
- 第三批导出测试；
- 完整测试；
- `git diff --check`；
- 数据包验证结果。

### 9. 明确未修改

至少写明：

- 没有增加评分器；
- 没有增加新发动机；
- 没有修改 11 个价格场景；
- 没有新增数据库表；
- 没有接入交易；
- 没有根据短期结果调固定阈值；
- 没有把任务扩大成审计工程。

### 10. D20 后再决定的事项

只列未来需要用成熟结果回答的问题，不在本轮提前下结论。

---

## Task 21：运行完整验证

依次运行：

```bash
git diff --check
python -m pytest -q
git status --short
git diff --stat e03677c6b57b0288adf3c24caffa3f31c6ddbfac...HEAD
git diff e03677c6b57b0288adf3c24caffa3f31c6ddbfac...HEAD -- \
  .agents/skills \
  docs/architecture/a-share-short-horizon-engine-contract-v4.md \
  ops \
  src/stock_analyzer/ops \
  tools \
  tests \
  research/skill-optimization/five-skill-selection-logic-optimization-20260901
```

逐项核对：

- 完整测试全部通过；
- 最终测试数不得少于基线；
- 没有未解释的失败或跳过；
- 没有新依赖；
- 没有无关重构；
- 没有修改 `main`；
- 没有覆盖原始样本；
- 没有本地绝对路径、密钥或事实仓原始文件；
- 代码改动与五个 Skill 新逻辑一致；
- 最终报告与实际 diff 一致。

如发现只改了文档但代码仍把 conditional 当 active 统计，任务未完成。

如发现代码改了输出，但五个 Skill 仍允许总控补位或只看单日放量，任务未完成。

## Task 22：最终提交

如最终报告在前三个提交后补充，提交：

```bash
git add \
  research/skill-optimization/five-skill-selection-logic-optimization-20260901/README.md \
  research/skill-optimization/five-skill-selection-logic-optimization-20260901

git commit -m "docs: report five-skill selection logic optimization"
```

检查提交历史：

```bash
git log --oneline --decorate -5
```

建议最终保持 3—4 个清晰提交，不要把每个小改动拆成十几个提交，也不要把全部内容压成无法审查的单一提交。

## Task 23：上传 GitHub

推送：

```bash
git push -u origin codex/five-skill-selection-logic-optimization-20260901
```

不得合并 `main`，不得删除原分支。

推送后核对远端：

```bash
git rev-parse HEAD
git ls-remote --heads origin codex/five-skill-selection-logic-optimization-20260901
git status --short
```

远端分支哈希必须与本地 HEAD 一致，工作区必须干净。

---

# 六、允许修改范围

只有与本任务直接相关时才允许修改：

```text
docs/2026-09-01-five-skill-selection-logic-optimization-prompt.md

.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/interpreting-market-macro/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/researching-company-events/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md

docs/architecture/a-share-short-horizon-engine-contract-v4.md
ops/forward-selection-prompt.md
ops/forward-monitor-prompt.md

src/stock_analyzer/ops/forward_selection.py
src/stock_analyzer/ops/forward_monitor.py

tools/export_skill_optimization_dataset.py
tools/build_skill_optimization_workbook.mjs
tools/validate_skill_optimization_dataset.py

tests/test_engine_contract_v4.py
tests/test_engine_contract_knowledge_v4.py
tests/test_v4_operational_prompts.py
tests/test_forward_selection.py
tests/test_forward_monitor.py
tests/test_forward_monitor_prompt.py
tests/test_export_skill_optimization_dataset.py
tests/test_price_analysis_features.py
tests/test_price_indicator_features.py
tests/test_price_scenario_validation.py
tests/test_market_context_features.py

research/skill-optimization/five-skill-selection-logic-optimization-20260901/
```

如果实际实现不需要修改其中某个文件，不要为了对齐清单而触碰。

如确实需要修改清单外文件，最终报告必须逐个解释：

```text
为什么不修改它就无法实现某一条明确的选股逻辑目标
```

不得使用“顺便整理”“便于未来扩展”“统一架构”作为理由。

---

# 七、最终验收标准

必须全部满足。

## 选股逻辑

- [ ] 总控与价格 Skill 出现实质性选择逻辑变化，不只是术语更新；
- [ ] active 与 conditional 不再同口径展示、计数和评价；
- [ ] 同发动机比较优先于跨发动机比较；
- [ ] 多日连续性与单日脉冲被明确区分；
- [ ] 成交放大与收盘推进绑定；
- [ ] 剩余路径不由单一 ATR、位置或涨幅决定；
- [ ] 强反证和关键未知会改变状态、优先级、条件或是否入选；
- [ ] 板块成立不自动等于股票成立；
- [ ] 公司事件真实不自动等于价格已经接受；
- [ ] 总控可以在 0、1、2 只时停止，不隐性补到 5 只；
- [ ] 数据能力缺失不会导致其他通道补数量。

## 不过度工程化

- [ ] 没有评分器、权重、模型；
- [ ] 没有新发动机和新价格场景；
- [ ] 没有数据库迁移；
- [ ] 没有新数据源；
- [ ] 没有重构整个选股或跟踪模块；
- [ ] 没有新增安全、审批、权限或审计系统；
- [ ] 除仓库要求的一次审查外，没有其他子智能体；
- [ ] 没有为了测试而创建复杂模拟平台。

## 证据与验证

- [ ] 全部 29 条正式入选进入影响矩阵；
- [ ] 条件性事件案例全部覆盖；
- [ ] selected/rejected/unresolved 获得同口径候选结果；
- [ ] 形成日判断与未来评价分开；
- [ ] 原始样本未被覆盖；
- [ ] 定向测试通过；
- [ ] 完整测试通过；
- [ ] 工作区干净；
- [ ] GitHub 远端哈希与本地一致。

## GitHub 交付

- [ ] 新分支已推送；
- [ ] 没有合并 main；
- [ ] Prompt 本身已提交；
- [ ] 基线诊断已提交；
- [ ] 修改后的五个 Skill 已提交；
- [ ] 必要代码和测试已提交；
- [ ] 选择影响矩阵和结果数据已提交；
- [ ] 最终实施报告已提交。

---

# 八、Codex 最终汇报格式

执行完成后只按以下结构汇报，不写泛化总结。

```markdown
已完成：A股五个 Skill 选股逻辑优化

## GitHub
- 分支：`codex/five-skill-selection-logic-optimization-20260901`
- 基线提交：`e03677c6b57b0288adf3c24caffa3f31c6ddbfac`
- 最终提交：`<HEAD>`
- 分支链接：<GitHub branch URL>
- 对比链接：<base...branch compare URL>
- 实施报告：<README URL>
- 选择影响矩阵：<selection-impact-matrix.csv URL>

## 三批修改
1. 第一批：<active/conditional 和执行语义的实际变化>
2. 第二批：<五个 Skill 选股逻辑的实际变化>
3. 第三批：<候选结果对照数据的实际变化>

## 五个 Skill
- 市场：<一句具体变化>
- 板块：<一句具体变化>
- 公司：<一句具体变化>
- 价格：<一句具体变化>
- 总控：<一句具体变化>

## 样本影响
- 29 条正式入选全部完成影响矩阵：是/否
- 分类改变：<数量>
- 优先级或行动条件改变：<数量>
- 保持不变：<数量>
- 旧 V1 不重建：<数量>
- conditional 事件记录：<数量>
- 候选结果记录：<数量>
- 未发现强路径文件：已生成/未生成及原因

## 验证
- 基线测试：<结果>
- 定向测试：<结果>
- 完整测试：<结果>
- 数据导出验证：<结果>
- `git diff --check`：<结果>
- 本地/远端 HEAD 一致：是/否
- 工作区干净：是/否

## 明确未做
- 未增加评分器、权重或新发动机
- 未修改 11 个价格场景
- 未新增数据库或数据源
- 未接入交易或仓位
- 未根据短期结果拟合固定阈值
- 未把任务扩大成审计工程

## 尚待 D20
<只列必须等待成熟样本才能判断的事项>
```

只有 GitHub 推送成功、远端哈希一致、完整测试通过并且最终报告已上传，才可以声称任务完成。
