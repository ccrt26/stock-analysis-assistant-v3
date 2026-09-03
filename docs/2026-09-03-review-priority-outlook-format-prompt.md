# 每日推荐与复盘展示的最后一轮实质调整——Codex 执行指令 V1.0

> **直接执行本文件，不要改写成另一份泛化方案。**
>
> 本轮只解决四个已经在真实日报中复现的问题：
>
> 1. 没有复牌、没有可参与价格、也没有实质新变化的股票，仍反复占用最多8只“重点复盘”名额；
> 2. “接下来更可能怎样”只有方向标签和正反条件，没有AI基于当前事实形成的方向判断理由；
> 3. 正式推荐说明把行业、价格、经营和风险挤在一个长段落里，阅读负担大；
> 4. 没有进入正式推荐的盘前事件线索仍出现在用户报告中。
>
> 这是个人股票助手，不是研究平台。只做实现上述四个目标所需的最小修改，不扩大为新的评分体系、消息平台或第二套复盘流程。

---

# 一、仓库、基线与分支

## 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

## 唯一基线

```text
分支：main
提交：29d22491edd4f5bbda85513268819a8a3ace45b3
```

## 新功能分支

```text
codex/review-priority-outlook-format-20260903
```

## 开始命令

在实际项目根目录执行：

```bash
git fetch origin --prune

test "$(git rev-parse origin/main)" = \
  "29d22491edd4f5bbda85513268819a8a3ace45b3"

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BASE_HEAD="$(git rev-parse origin/main)"
WORKTREE="$PROJECT_ROOT/.worktrees/review-priority-outlook-format-20260903"

git worktree add \
  "$WORKTREE" \
  -b codex/review-priority-outlook-format-20260903 \
  "$BASE_HEAD"

cd "$WORKTREE"

test "$(git rev-parse HEAD)" = "$BASE_HEAD"
test "$(git branch --show-current)" = \
  "codex/review-priority-outlook-format-20260903"
test -z "$(git status --short)"
```

将本文件原样保存到：

```text
docs/2026-09-03-review-priority-outlook-format-prompt.md
```

---

# 二、已经确认的根因

## 1. 华昌化工反复进入重点，不是写作问题

当前 `forward_monitor.py` 的行为是：

- 固定检查日会产生 `checkpoint`；
- 任何新公告都会产生 `new_official_event`；
- 数据限制首次出现、发生变化或碰到检查日会产生 `data_problem`；
- 只要正式推荐股票进入 `attention_stocks`，且正式重点股票不超过8只，`record` 就要求全部进入详细提醒。

所以，一只行动日没有可靠价格的历史正式推荐，即使仍在停牌，只要出现一份后续权益变动文件、例行进展公告或固定检查日，也会被强制写成长篇重点复盘。

这与“今天是否真的有值得用户重新阅读的变化”不是一回事。

## 2. “接下来更可能怎样”缺少理由，是当前数据合同缺字段

当前 `ForwardMonitorAlertV2` 只有：

```text
outlook_1_3d
confirmation_condition
invalidation_condition
```

Python只能把 `outlook_1_3d` 映射成：

```text
更可能继续走强
更可能横盘整理
更可能继续回落
```

然后拼上两个条件。

它没有专门字段保存：

```text
为什么在当前信息下，更可能向上、横盘或向下
```

所以继续只改 Skill，无法让这个栏目稳定出现判断理由。

本轮允许增加一个**向后兼容的可选文字字段**，只保存AI的方向判断理由；不增加评分、概率或新状态。

## 3. 事件线索对外展示是 Prompt 明确要求的，不是偶发现象

当前 `forward-selection-prompt.md` 仍要求最终用户报告展示：

```text
等待首个交易日确认的事件线索
```

因此中国船舶、北京科锐被写出来，是执行了当前合同。

用户已经明确不需要这部分。应从用户报告移除，但继续保留在内部 V4 trace 和研究记录中。

## 4. 正式推荐长成一个大段，是输出合同仍不够明确

当前Prompt虽然要求详细解释，但没有稳定要求：

```text
行业或外部变化
股票自身表现
公司经营
不利因素
综合判断
```

分别成段。

本轮只调整最终用户格式，不改变选股逻辑和名单。

---

# 三、唯一目标

完成后必须达到：

1. 没有可靠参与价格的正式推荐，只在首次确认无法执行、真正影响判断的新事件、恢复实际交易或D20结案时进入详细复盘；没有实质变化时不占8只名额；
2. 公告只是例行披露或旧事项重复进展时，可留在内部记录，不强制进入用户详细复盘；
3. “接下来更可能怎样”先明确回答未来1—3个交易日更可能向上、横盘、向下或暂时无法判断，再解释为什么；
4. 正反条件可以保留，但只作为如何验证判断，不能代替方向判断和理由；
5. 正式推荐按不同证据维度分段，正面与负面分开；
6. `conditional_event`、盘前事件线索、最近未选和比较股不出现在最终用户报告；
7. 内部 trace、snapshot、JSON 和事件线索全部继续保存。

---

# 四、明确不做

不得：

- 修改五个 Skill 的选股逻辑；
- 修改七种 `engine_type`、四种 `engine_status` 和11个价格场景；
- 修改20%目标、D20计算或入口价格；
- 增加股票评分、预测概率或信心分；
- 新增数据库表或外部数据源；
- 新增定时任务；
- 新增第二套注意池；
- 用公告标题硬编码一套“重大公告词典”；
- 用程序推测涨跌原因；
- 删除内部 `conditional_event`；
- 把“最多8只”改成无限数量；
- 修改Automation；当前最终输出链路已经恢复；
- 重写历史正式推荐或历史复盘；
- 修改液冷研究分支。

---

# 五、允许修改

```text
src/stock_analyzer/ops/forward_monitor.py

.agents/skills/reviewing-stock-recommendations/SKILL.md

ops/forward-monitor-prompt.md
ops/forward-selection-prompt.md

tests/test_forward_monitor.py
tests/test_forward_monitor_prompt.py
tests/test_v4_operational_prompts.py

docs/2026-09-03-review-priority-outlook-format-prompt.md

research/skill-optimization/review-priority-outlook-format-20260903/
```

只有现有测试辅助函数因新增字段需要同步时，才允许在同一个测试文件中做最小调整。

不得修改其他 `src/` 文件或其他 Skill。

---

# 六、执行纪律

本轮会修改正式复盘合同，并对 `ForwardMonitorAlertV2` 增加一个向后兼容字段。

按 `AGENTS.md`：

- 实施前恰好使用一次 `gpt-5.6-sol`、`xhigh` 独立审查；
- 只审查：
  - 是否真正解决四个目标；
  - 是否把例行公告错误做成程序关键词过滤；
  - 新字段是否为最小必要改动；
  - 是否误改选股、D20或历史结果；
  - 是否过度工程化；
- 审查不实施，不调用其他子智能体；
- 主智能体采用一次审查后的最小修订；
- 此后不再启动其他子智能体。

---

# 七、开始前完整读取

```text
AGENTS.md

src/stock_analyzer/ops/forward_monitor.py

.agents/skills/reviewing-stock-recommendations/SKILL.md

ops/forward-monitor-prompt.md
ops/forward-selection-prompt.md

tests/test_forward_monitor.py
tests/test_forward_monitor_prompt.py
tests/test_v4_operational_prompts.py

local_archive/forward_monitor/
  最新 snapshot JSON
  最新 monitor-report JSON
  最新 monitor-report Markdown
```

运行基线：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_forward_monitor.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_v4_operational_prompts.py

./.venv/bin/python -m pytest -q
```

记录真实结果。

---

# 八、Task 1：形成真实问题诊断

创建：

```text
research/skill-optimization/review-priority-outlook-format-20260903/
  current-production-diagnosis.md
```

必须写清：

## 华昌化工为什么进入重点

从最新 snapshot 读取华昌化工：

```text
episode_id
day_number
entry_open
formal_return_started
attention_reasons
new_announcements
data_limitations
previous_episode_review
```

明确它本次是由：

```text
checkpoint
new_official_event
data_problem
或其他原因
```

中的哪一项触发。

再读取新增公告，说明：

- 是否出现新的复牌日期或恢复交易事实；
- 是否改变控制权安排的核心条款；
- 是否只是旧事项继续推进或权益变动配套文件；
- 为什么这次是否值得占用用户重点复盘名额。

不得只根据用户感觉下结论。

## 未来判断为什么只有条件

指出当前：

```text
ForwardMonitorAlertV2
_render_public_outlook()
```

只能保存方向枚举和两个条件，没有AI判断理由的独立字段。

## 事件线索为什么出现

定位 `forward-selection-prompt.md` 中要求对外展示事件线索的原句。

## 推荐说明为什么合成长段

对照当前Prompt与实际输出，指出哪些段落边界没有被锁定。

---

# 九、Task 2：先写失败测试——无实质变化的不可执行股票不反复占位

修改：

```text
tests/test_forward_monitor.py
```

至少增加以下测试。

## 2.1 持续无法执行，不碰固定检查点

构造正式推荐记录：

```text
selection_output_class=confirmed_active
entry_open=None
previous snapshot 已经包含相同 missing_price_path / incomplete_price_path
今天无新公告
今天不是D20
```

期望：

```text
attention_reasons 为空
```

## 2.2 持续无法执行，碰到D3/D5/D10

构造同样记录，今天为D3、D5或D10，且：

```text
没有新事实
数据限制与上次相同
仍无可靠入口
```

期望：

```text
不因为普通 checkpoint 或重复 data_problem 进入 attention
```

## 2.3 首次发现无法执行

前一日没有该限制或没有previous snapshot。

期望：

```text
data_problem 仍然触发一次
```

## 2.4 D20必须结案

即使一直没有可靠入口：

```text
day_number=20
frozen_twenty_day_review=None
```

期望：

```text
pending_final_review 触发
```

## 2.5 后来出现真实交易

前一日没有价格，本日首次出现可观察交易事实。

如果现有字段可以稳定识别，增加一个明确提醒；若现有结构不能无歧义识别，不新增复杂状态，只依靠新公告/实际价格变化进入AI候选，并在诊断中说明。

先运行新增测试，确认修改前失败。

---

# 十、Task 3：最小修正不可执行记录的提醒规则

修改：

```text
src/stock_analyzer/ops/forward_monitor.py
```

## 3.1 定义不可执行正式记录

在 `_attention_reasons()` 中使用：

```python
is_non_executable_formal = (
    _episode_selection_output_class(current)
    in PUBLIC_FORMAL_OUTPUT_CLASSES
    and current.get("entry_open") is None
)
```

## 3.2 普通检查点不再反复触发

当前：

```python
if current["checkpoint"]:
    reasons.append("checkpoint")
```

改为：

```text
可执行正式记录：保留D1/D3/D5/D10/D20等原检查点；
不可执行正式记录：
- 首次发现问题时可以提醒；
- D20必须结案；
- D3/D5/D10等普通检查点不单独触发详细提醒。
```

不得修改 `CHECKPOINTS` 全局定义。

## 3.3 持续相同的数据问题不重复触发

当前数据限制在检查日也会再次产生 `data_problem`。

改为：

```text
- 限制首次出现：触发；
- 限制内容发生变化：触发；
- 可执行记录到检查点：可继续触发；
- 不可执行记录且限制完全未变：普通检查点不再触发；
- D20由pending_final_review负责。
```

不得把数据问题全部隐藏。

---

# 十一、Task 4：区分“必须详细复盘”和“公告候选”

当前 `record_forward_monitor()` 在正式attention股票不超过8只时，强制全部出现在日报。

这会使任何新公告都强制占位，即使公司 Skill 已判断公告不改变原推荐。

## 4.1 增加最小常量

在常量区增加：

```python
MANDATORY_FORMAL_REVIEW_REASONS = frozenset(
    {
        "pending_final_review",
        "checkpoint",
        "target_hit_first_time",
        "relative_state_changed",
        "scenario_changed",
        "breakout_changed",
        "sector_state_changed",
        "late_activation_candidate",
        "overheat_candidate",
        "data_problem",
    }
)
```

故意不包含：

```text
new_official_event
```

原因：

- 程序只能确认有公告；
- 公告是否改变原判断必须由公司 Skill 和复盘 Skill做语义判断；
- 不用标题关键词替代研究。

## 4.2 修改正式重点强制校验

把：

```text
所有formal_attention_codes不超过8只时必须全部报告
```

改为：

```text
所有mandatory formal attention不超过8只时必须全部报告；
超过8只时，8个位置只能先由mandatory formal使用；
仅由new_official_event触发的正式股票属于可选候选：
- 公告实质改变原推荐、执行状态、控制权核心安排、收入利润现金流判断时，可以进入详细复盘；
- 例行披露、重复进展、没有新条款的配套文件，不进入详细复盘；
- 不要求凑满8只。
```

内部 snapshot 和 `attention_stocks` 仍保留公告记录。

## 4.3 测试

增加：

1. 一只正式股票只有 `new_official_event`，报告不包含它时，`record`可以通过；
2. 同一股票若AI判断公告重要并主动包含，`record`也可以通过；
3. `pending_final_review`、checkpoint、目标首次达到、价格或行业状态变化等mandatory记录被漏掉时，仍然失败；
4. 8只可选公告不能挤掉1只mandatory正式记录；
5. 内部JSON和snapshot仍保存全部事件候选。

---

# 十二、Task 5：给未来判断增加一个最小理由字段

## 5.1 修改数据模型

在：

```python
class ForwardMonitorAlertV2(ForwardMonitorAlertV1):
```

增加：

```python
outlook_reason_plain_language: str | None = Field(
    default=None,
    min_length=1,
    max_length=300,
)
```

设计原则：

- 可选字段保证历史V2报告仍可读取；
- 新生成报告必须填写；
- 不增加报告版本；
- 不增加概率、评分或新方向枚举；
- 只保存AI对 `outlook_1_3d` 的理由。

## 5.2 新报告必须填写

在 `record_forward_monitor()` 校验新 pending report：

```text
每条新alert都必须有非空outlook_reason_plain_language。
```

历史已保存报告缺少该字段时仍能读取，不回写历史。

## 5.3 字段内容要求

修改：

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
ops/forward-monitor-prompt.md
```

要求AI填写：

```text
未来1—3个交易日为什么更可能向上、横盘或向下。
```

具体要求：

- 先作出一个方向判断；
- 使用当前最重要的1—3项事实解释；
- 不写“如果……就……”；
- 不重复两个验证条件；
- 不重复整段 `current_review`；
- 不声称确定预测；
- 与 `outlook_1_3d`、`current_assessment` 和 `current_review` 一致；
- 没有可交易价格或证据冲突时可以写“目前无法判断方向”，并说明缺少什么。

示例：

```text
当前仍保留大部分推荐后涨幅，但最近两日冲高回落增多，
成交增加也没有再带来更高收盘，因此短期更像高位整理。
```

不合格：

```text
若上涨就向上，若下跌就向下。
```

## 5.4 直接回答向上、横盘或向下

保留现有 `outlook_1_3d` 七类内部枚举，但用户句子映射改为：

```text
strengthening
→ 未来1—3个交易日更可能继续向上

continuation_possible
→ 未来1—3个交易日更可能震荡偏上

range_or_wait
→ 未来1—3个交易日更可能横盘整理

weakening
→ 未来1—3个交易日更可能震荡偏下

overheated
→ 未来1—3个交易日更可能高位震荡，短线偏下

invalidated
→ 未来1—3个交易日更可能继续偏弱

event_pending
→ 目前没有足够的可交易事实判断方向
```

---

# 十三、Task 6：重写“接下来更可能怎样”的公开渲染

修改：

```text
src/stock_analyzer/ops/forward_monitor.py
```

调整 `_render_public_outlook()`。

最终顺序固定为：

```text
方向判断
→ 判断理由
→ 什么表现会支持这个判断
→ 什么表现会要求改变判断
```

建议输出：

```markdown
未来1—3个交易日更可能横盘整理。

主要原因是：当前仍保留大部分推荐后涨幅，但最近两日冲高回落增多，
成交增加也没有再带来更高收盘，因此上涨速度已经放慢。

支持这个判断的后续表现：回落时成交缩小，收盘仍守在近期高位。

需要改变判断的后续表现：成交明显增加并连续收低，或跌破推荐后主要涨幅区间。
```

实现时：

- 不机械添加“如果”或“若”，避免“如果若”；
- 清理末尾重复标点；
- `outlook_reason_plain_language` 缺失的历史记录可退回旧映射；
- 新报告因record校验不会缺失；
- 不把模型理由改成程序规则。

## 测试

至少验证：

1. 公开Markdown包含方向、理由、支持表现、改变表现；
2. 理由出现在两个条件之前；
3. 不出现“判断增强条件”“判断改变条件”旧式硬标签；
4. 不出现“如果若”或连续两个句号；
5. `outlook_reason_plain_language` 与JSON一致；
6. 历史缺字段对象仍能兼容渲染。

---

# 十四、Task 7：复盘 Skill 对未来判断的职责

修改：

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
```

保留现有“一个主要问题、最少事实、事实追溯、上一轮锚点”。

增加：

## 未来方向不是条件清单

复盘必须先判断：

```text
向上
震荡偏上
横盘
震荡偏下
向下
暂时无法判断
```

再说明：

- 哪些当前事实使这个方向比另外两个方向更合理；
- 这个判断针对未来1—3个交易日，不是20日收益承诺；
- 条件只负责以后验证，不能代替当前判断。

## 20日目标的可实现性

`current_review` 可用一句话说明：

```text
按当前状态，20%目标仍有现实可能；
需要重新加速才有可能；
目前已明显变得困难；
已经不再以完成目标为主要判断；
无法计算。
```

不增加结构化字段，不按每天1%线性推算。

---

# 十五、Task 8：移除用户报告中的事件线索

修改：

```text
ops/forward-selection-prompt.md
tests/test_v4_operational_prompts.py
tests/test_forward_monitor_prompt.py
```

## 内部继续保留

以下全部不变：

```text
fresh_event_pending
conditional_event
事件公司证据
首个交易日观察条件
内部trace
内部候选比较
```

## 用户最终报告不再展示

删除最终用户输出中的：

```text
等待首个交易日确认的事件线索
```

用户报告中不得出现：

- 中国船舶这类盘前事件线索；
- 北京科锐这类盘前事件线索；
- conditional名单或数量；
- 最近未选；
- 比较股。

最终合并报告只保留：

```text
今天的市场情况
正式推荐股票的走势复盘
目前仍开放的正式推荐股票数量
今天明确推荐的股票
```

当天没有正式推荐时，直接说明没有正式推荐，不用事件线索填充。

修改旧测试中强制要求事件线索对外展示的断言；新增测试确认：

```text
conditional仍在内部合同
但不在唯一用户输出格式中
```

---

# 十六、Task 9：把正式推荐按维度分段

修改：

```text
ops/forward-selection-prompt.md
```

每只正式推荐必须使用以下可读结构，不能合并成一个大段：

```markdown
### 1. 股票名称（代码）

**公司主要做什么**

一小段。

**为什么会选它**

只写真正存在的正面维度，每个维度单独成段：

**行业或外部变化**
……

**股票自身表现**
……

**公司经营**
……

没有某个维度的可靠支持，就不写该小标题，不得凑齐三项。

**主要不利因素**

把已经存在的不利事实单独成段，不与正面依据混写。

**综合判断**

明确说明：
- 哪些支持最重要；
- 为什么它们暂时超过不利因素；
- 是否属于较早确认、正常启动或已经偏晚；
- 为什么仍值得正式推荐。

**什么情况会改变判断**

只保留一小段。
```

规则：

- 每段最多2—4句话；
- 一个段落只讲一个维度；
- 不把好坏信息交叉塞进同一句；
- 可以用必要数字，但每个数字必须解释意义；
- 不是每只股票都必须出现行业、公司、价格三个正面段落；
- 纯价格型股票可以只有“股票自身表现”；
- 公司经营只是基础时，要明确它不能单独证明短期上涨；
- 总字数约350—650字，作为参考，不做程序校验；
- 不重新选股，不改变顺序。

## 推荐样例要求

在新的验收样例中，把中航西飞改写为：

```text
公司业务
行业/国防方向
股票自身多日表现
公司经营不利事实
综合判断
改变判断
```

分别成段。

---

# 十七、Task 10：生成与真实用户输出一致的验收样例

创建：

```text
research/skill-optimization/review-priority-outlook-format-20260903/
  expected-user-report-v5.md
  implementation-diagnosis.md
```

使用最新本地冻结归档和trace，不重新选股、不读取未来行情。

样例至少覆盖：

## 正式复盘

1. 一只未来更可能向上；
2. 一只更可能横盘；
3. 一只更可能向下；
4. 一只暂时无法判断；
5. 华昌化工在“没有实质新变化”的假设下不出现在重点复盘；
6. 如华昌化工确有改变执行或控制权核心条款的新信息，再展示一个“应该进入”的对照说明。

每只“接下来更可能怎样”必须包含：

```text
方向
理由
支持该判断的后续表现
需要改变判断的后续表现
```

## 正式推荐

使用中航西飞和万兴科技当前冻结事实，按新分段格式展示。

## 不得出现

```text
等待首个交易日确认的事件线索
中国船舶
北京科锐
最近未选
比较股
Git状态
工作区状态
```

`implementation-diagnosis.md` 说明：

- 为什么这次必须有一个最小理由字段；
- 为什么没有用公告标题关键词过滤；
- 为什么只放宽“公告单独触发”的强制公开要求；
- 为什么内部记录仍完整；
- 为什么没有重做选股或复盘系统。

---

# 十八、Task 11：测试清单

## 定向测试

```bash
./.venv/bin/python -m pytest -q \
  tests/test_forward_monitor.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_v4_operational_prompts.py
```

必须覆盖：

- 不可执行正式记录的首次提醒；
- 不可执行记录D3/D5/D10不重复提醒；
- 不可执行记录D20仍结案；
- 公告单独触发可由AI判断是否公开；
- mandatory正式重点仍不能漏；
- 非正式记录不能挤掉mandatory正式重点；
- 新报告必须提供未来判断理由；
- 历史报告兼容；
- 用户未来栏目有方向和理由；
- 事件线索仍内部保存但不对外；
- 正式推荐分段格式存在。

## 完整测试

```bash
./.venv/bin/python -m pytest -q
git diff --check
```

不得删除旧测试换取通过。

---

# 十九、Task 12：人工验收

完整阅读：

```text
expected-user-report-v5.md
```

逐项回答：

1. 华昌化工没有交易、没有实质新变化时，是否不再占用户重点复盘名额；
2. 有真正影响执行或公司判断的新变化时，是否仍能被复盘；
3. 每只股票是否明确判断更可能向上、横盘、向下或不知道；
4. 是否先给理由，再给验证条件；
5. 条件是否只是验证方法，而不是取代判断；
6. 中航西飞是否按行业、股票、经营和风险分段；
7. 好的方面和差的方面是否分开；
8. 最终用户报告是否完全没有事件线索；
9. 内部JSON是否仍保留事件和attention候选；
10. 是否仍只展示最多8只真正重要的正式推荐复盘。

---

# 二十、Task 13：提交与合并

## 提交

```bash
git add \
  docs/2026-09-03-review-priority-outlook-format-prompt.md \
  src/stock_analyzer/ops/forward_monitor.py \
  .agents/skills/reviewing-stock-recommendations/SKILL.md \
  ops/forward-monitor-prompt.md \
  ops/forward-selection-prompt.md \
  tests/test_forward_monitor.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_v4_operational_prompts.py \
  research/skill-optimization/review-priority-outlook-format-20260903

git commit -m \
  "fix: prioritize meaningful reviews and explain short-term outlook"
```

推送：

```bash
git push -u origin codex/review-priority-outlook-format-20260903
FEATURE_HEAD="$(git rev-parse HEAD)"
```

## 快进合并到 main

```bash
cd "$PROJECT_ROOT"

git switch main
git fetch origin --prune
git pull --ff-only origin main

test -z "$(git status --short)"

git merge --ff-only "$FEATURE_HEAD"

./.venv/bin/python -m pytest -q
git diff --check

git push origin main
```

核对：

```bash
test "$(git rev-parse main)" = "$FEATURE_HEAD"
test "$(git rev-parse origin/main)" = "$FEATURE_HEAD"
test -z "$(git status --short)"
```

## 删除本轮功能分支

```bash
git fetch origin --prune

git merge-base --is-ancestor \
  origin/codex/review-priority-outlook-format-20260903 \
  origin/main

git push origin --delete \
  codex/review-priority-outlook-format-20260903

git worktree remove \
  "$PROJECT_ROOT/.worktrees/review-priority-outlook-format-20260903"

git branch -d \
  codex/review-priority-outlook-format-20260903

git fetch origin --prune
```

不得强制删除。

保留：

```text
main
research/ai-liquid-cooling-2026h2
```

---

# 二十一、最终验收标准

## 重点复盘

- [ ] 没有可靠入口且没有实质变化的股票不反复占位；
- [ ] 首次无法执行仍提醒；
- [ ] D20仍形成最终结论；
- [ ] 单独出现新公告只进入候选，由AI判断是否改变原推荐；
- [ ] 不用标题关键词替代语义判断；
- [ ] mandatory正式重点不能被漏掉；
- [ ] 不要求凑满8只。

## 未来判断

- [ ] 明确回答向上、横盘、向下或无法判断；
- [ ] 有AI写出的当前判断理由；
- [ ] 理由在正反条件之前；
- [ ] 条件只负责以后验证；
- [ ] 没有概率和评分；
- [ ] 与当前分析和结构化方向一致。

## 正式推荐

- [ ] 公司业务单独成段；
- [ ] 行业、股票自身和经营按实际存在分别成段；
- [ ] 好的方面与不利因素分开；
- [ ] 有综合取舍，不是堆事实；
- [ ] 不形成一整块长段落。

## 用户输出

- [ ] 不显示盘前事件线索；
- [ ] 不显示conditional、最近未选或比较股；
- [ ] 内部记录全部保留；
- [ ] Automation仍直接交付完整正式报告；
- [ ] 不追加Git与技术摘要。

## 工程范围

- [ ] 只增加一个向后兼容的文字字段；
- [ ] 不增加报告版本；
- [ ] 不新增数据库、表、任务、评分或数据源；
- [ ] 不修改五个选股Skill；
- [ ] 不修改20%目标、D20、入口价格或11个价格场景；
- [ ] 完整测试通过；
- [ ] main本地与远端一致；
- [ ] 功能分支删除；
- [ ] 液冷研究分支不变。

---

# 二十二、Codex最终汇报格式

```markdown
已完成：重点复盘、未来判断和荐股展示调整

## GitHub
- 基线：`29d22491edd4f5bbda85513268819a8a3ace45b3`
- main最终提交：`<HEAD>`
- 对比链接：<URL>
- 生产问题诊断：<URL>
- V5用户报告样例：<URL>

## 华昌化工问题
- 本次真实attention原因：<列表>
- 无实质变化时是否仍占重点名额：否
- 首次无法执行是否提醒：是
- D20是否仍结案：是
- 真正重要的新事件是否仍可进入：是
- 是否使用公告标题关键词过滤：否

## 未来判断
- 新字段：`outlook_reason_plain_language`
- 是否向后兼容：是
- 是否明确向上/横盘/向下/未知：是
- 是否先给理由再给条件：是
- 是否新增评分或概率：否

## 正式推荐
- 是否按行业/股票/经营等实际维度分段：是
- 是否将正面与不利因素分开：是
- 是否有综合判断：是
- 是否仍为一个大段：否

## 用户输出
- 盘前事件线索是否隐藏：是
- conditional内部记录是否保留：是
- 最近未选和比较股是否隐藏：是
- 最终输出链路是否保持：是

## 验证
- 基线定向测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- `git diff --check`：<结果>
- main本地/远端一致：是/否
- 功能分支已删除：是/否
- 工作区干净：是/否

## 明确未做
- 未修改五个选股Skill
- 未修改七种发动机、四种状态和11个价格场景
- 未修改20%目标、D20和入口价格
- 未新增数据库、数据源、定时任务、评分器或预测概率
- 未修改液冷研究分支
```
