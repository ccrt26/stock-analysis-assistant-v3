# 正式推荐复盘 Skill“分析员化”优化——Codex执行指令 V1.0

> 直接执行本文件。
>
> 本轮只优化复盘 Skill 和调用 Prompt，让AI把现有数据写成一篇连贯的观点更新稿。
>
> **不得修改Python复盘代码，不得增加schema，不得再次搭建复盘系统。**

---

## 一、仓库与基线

```text
仓库：https://github.com/ccrt26/stock-analysis-assistant-v3
基线分支：main
基线提交：bd4b2e8320601c07cc71521d3b100e1b7fab96f1
新分支：codex/analyst-style-review-skill-20260902
```

从实际项目根目录创建worktree：

```bash
git fetch origin --prune

test "$(git rev-parse origin/main)" = \
  "bd4b2e8320601c07cc71521d3b100e1b7fab96f1"

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BASE_HEAD="$(git rev-parse origin/main)"
WORKTREE="$PROJECT_ROOT/.worktrees/analyst-style-review-skill-20260902"

git worktree add \
  "$WORKTREE" \
  -b codex/analyst-style-review-skill-20260902 \
  "$BASE_HEAD"

cd "$WORKTREE"

test "$(git rev-parse HEAD)" = "$BASE_HEAD"
test -z "$(git status --short)"
```

将本文件原样保存为：

```text
docs/2026-09-02-analyst-style-review-skill-prompt.md
```

---

## 二、唯一目标

把当前正式复盘从：

```text
固定栏目
→ 平铺事实
→ 逐项解释
→ 通用状态句
→ 条件清单
```

改为：

```text
一句话观点更新
→ 2—4个决定性事实形成完整分析
→ 说明原推荐判断怎样变化
→ 给出下一阶段基准判断
```

当前数据已经足够。本轮不得以“需要更多数据”为理由修改程序。

---

## 三、允许与禁止范围

### 允许修改

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
.agents/skills/reviewing-stock-recommendations/agents/openai.yaml
ops/forward-monitor-prompt.md

tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py

docs/2026-09-02-analyst-style-review-skill-prompt.md
research/skill-optimization/analyst-style-review-skill-20260902/
```

### 禁止修改

```text
src/
tools/
数据库与schema
AGENTS.md
ops/forward-selection-prompt.md
五个选股Skill
20%目标和D20定义
入口价格
自动任务
```

不得：

- 新增Pydantic字段；
- 新增报告版本；
- 新增评分、权重、概率；
- 新增第二个复盘Skill；
- 修改选股逻辑；
- 重新生成或覆盖历史正式报告；
- 为文字质量增加程序Gate；
- 给普通文档增加哈希；
- 修改液冷研究分支。

---

## 四、执行纪律

本轮修改正式复盘合同。按`AGENTS.md`：

- 实施前恰好启动一次`gpt-5.6-sol`、`xhigh`独立审查；
- 只检查目标是否仍是Skill写作与分析方法、是否误改Python或扩建系统；
- 审查不实施；
- 主智能体采用一次审查意见后连续完成；
- 不再启动其他子智能体。

---

## 五、开始前读取

完整读取：

```text
AGENTS.md
.agents/skills/reviewing-stock-recommendations/SKILL.md
.agents/skills/reviewing-stock-recommendations/agents/openai.yaml
ops/forward-monitor-prompt.md

tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py

research/skill-optimization/causal-recommendation-review-20260902/review-sample-v2.md
local_archive/forward_monitor/monitor-report-2026-09-01.json
local_archive/forward_monitor/snapshot-2026-09-01.json
```

如本地最新实际报告日期不同，再读取最新报告，但不得覆盖历史文件。

运行基线：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py

./.venv/bin/python -m pytest -q
```

---

## 六、Task 1：形成当前写作诊断

创建：

```text
research/skill-optimization/analyst-style-review-skill-20260902/current-review-writing-diagnosis.md
```

必须使用当前`review-sample-v2.md`逐只说明：

- 哪些句子在展示推理流程；
- 哪些事实被平均铺开；
- 哪些段落缺少中心判断；
- 哪些后续展望只是条件清单；
- 哪些股票其实已有较好的分析核心，但被模板语言削弱。

至少覆盖：

```text
华昌化工
中信银行
金岭矿业
德尔股份
海油工程
```

诊断目标是写作和分析组织，不检查代码边界。

---

## 七、Task 2：重写复盘 Skill

修改：

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
```

保留：

- 只复盘明确正式推荐；
- 不参与选股；
- 不修改历史推荐；
- 使用现有`ForwardEpisodeReviewV1`；
- 不新增schema；
- 不推断主力、机构或唯一真实原因。

删除或弱化当前十项固定问答和每只股票完全相同的推理展示。

加入以下方法。

### 1. 每只股票先选一个核心问题

只允许一个中心问题，例如：

```text
突破是否站稳
上涨是否仍由股票自身推动
行业共同上涨是否还在
盘中回吐是否已经变成明显卖压
公司新消息是否真正改变经营判断
推荐是否能够执行
```

其他事实只有在解释中心问题时才使用。

### 2. 先写一句话观点更新

`current_review`第一句话必须能独立作为标题。

要求：

- 包含股票当前最重要的变化；
- 包含方向判断；
- 不写通用状态标签。

允许：

```text
强势还在，但已经从快速上涨转入高位消化。
仍有小幅盈利，但突破没有站稳，推荐依据明显减弱。
行业解释了大部分上涨，个股仍有少量领先，走势偏强但不快。
```

禁止：

```text
最有证据的解释是……
核心预期目前得到支持。
当前阶段是……
部分预期已经发生。
仍需观察。
```

### 3. 只选2—4个决定性事实

不得平均复述市场、行业、公司、价格四路信息。

每个事实必须直接服务于：

```text
为什么这样涨跌
为什么观点维持或改变
为什么下一步更可能这样发展
```

### 4. 与上一次复盘比较

优先读取`previous_episode_review`。

若观点改变，必须自然说明：

```text
相比上一次，判断从……调整为……，原因是……
```

若没有实质变化：

- 不重写完整长文；
- 简短说明判断未变；
- 只写最新的一项支持或风险。

### 5. 形成完整观点更新稿

`current_review`建议由2—3个自然段组成：

1. 结论与主要原因；
2. 原推荐判断被怎样验证或削弱；
3. 后续基准判断。

不要把这三项写成固定小标题。

### 6. 后续必须先给基准判断

先写：

```text
按现在的表现，未来几个交易日更可能……
```

再解释原因和转折条件。

不得只写两个条件后结束。

### 7. 事实与观点分开

- 事实：涨跌、相对表现、成交、回撤、公告。
- 观点：主要原因、阶段、后续判断。

使用“更像”“更可能”“目前看”的方式表达推断，不把观点冒充事实。

---

## 八、Task 3：按触发类型控制写作深度

在Skill中加入：

### 普通固定检查且观点未变

80—160个中文字，重点写变化。

### D3/D5或观点改变

180—350个中文字，写完整观点更新。

### D10

250—450个中文字，说明20%目标是否仍现实，但不按线性速度评价。

### D20

350—600个中文字，只回答：

- 是否达到目标；
- 推荐理由是否成立；
- 具体股票是否选对；
- 时机是否合理；
- 最大成功或错误。

### 新公告触发

只写与原推荐有关的公告；例行公告不进入正文。

字符数只是写作参考，不增加自动校验。

---

## 九、Task 4：更新调用Prompt

修改：

```text
ops/forward-monitor-prompt.md
```

加入并锁定：

```markdown
`reviewing-stock-recommendations`生成的是观点更新稿，不是推理步骤展示。

`current_review`必须做到：
- 第一句直接给出本次观点；
- 只围绕一个中心问题；
- 只使用2—4个决定性事实；
- 说明与上次复盘相比是否改变；
- 给出后续基准判断；
- 不平均复述市场、行业、公司和价格四路内容；
- 不以“最有证据的解释是、当前阶段是、核心预期得到支持”作为固定句式。
```

明确：

- `best_supported_explanation`等枚举仍在内部填写；
- 最终文字不解释这些字段；
- `current_review`不需要逐项证明其他解释全部错误；
- 只说明为什么当前主判断最合理；
- 数据限制只有会改变结论时才写一句；
- 例行公告不写入分析。

不要修改现有JSON合同、流程和定时任务。

---

## 十、Task 5：更新Skill入口说明

修改：

```text
.agents/skills/reviewing-stock-recommendations/agents/openai.yaml
```

使默认说明强调：

```text
形成一篇以观点更新为中心的复盘短评，不逐项复述数据。
```

不增加工具和字段。

---

## 十一、Task 6：形成V3样例

创建：

```text
research/skill-optimization/analyst-style-review-skill-20260902/review-sample-v3.md
```

只使用`review-sample-v2.md`和对应本地JSON已经存在的事实，不增加新行情，不改历史判断。

至少重写：

```text
华昌化工
中信银行
金岭矿业
德尔股份
海油工程
建霖家居
建新股份
四川九洲
```

每只格式：

```markdown
### 股票名称：一句话观点更新

2—3个自然段。
```

不再固定显示：

```text
推荐日期和当时判断
到今天走到哪里
我的分析
接下来更可能怎样
```

但正文仍需包含必要日期、目标进展和后续判断。

重点：

- 德尔股份围绕“强势是否已转为高位消化”；
- 金岭矿业围绕“突破没有站稳”；
- 中信银行围绕“上涨还在但速度和领先优势收窄”；
- 海油工程围绕“行业解释大部分上涨，个股略有领先”；
- 华昌化工围绕“推荐无法执行，控制权变化不能直接预测复牌方向”。

禁止每只都使用完全相同的开头和结尾。

---

## 十二、Task 7：轻量测试

修改：

```text
tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py
```

只检查Skill和Prompt存在以下要求：

```text
一个中心问题
一句话观点更新
2—4个决定性事实
与上一次复盘比较
后续基准判断
观点更新稿
不平均复述市场、行业、公司和价格四路内容
```

同时检查不再强制使用以下固定开头：

```text
最有证据的解释是
当前阶段是
核心预期目前得到支持
```

不要对未来自然语言建立复杂正则Gate，不修改`src/`测试。

---

## 十三、Task 8：验证

运行：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py

./.venv/bin/python -m pytest -q
git diff --check
```

逐字阅读`review-sample-v3.md`，确认：

- 每只股票只有一个中心；
- 结论先行；
- 不是平均罗列数据；
- 能看到观点相对上一轮的变化；
- 后续有基准判断；
- 不能换股票名称后继续成立。

---

## 十四、Task 9：提交、合并与清理

提交：

```bash
git add \
  docs/2026-09-02-analyst-style-review-skill-prompt.md \
  .agents/skills/reviewing-stock-recommendations/SKILL.md \
  .agents/skills/reviewing-stock-recommendations/agents/openai.yaml \
  ops/forward-monitor-prompt.md \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py \
  research/skill-optimization/analyst-style-review-skill-20260902

git commit -m \
  "docs: make stock reviews read like analyst updates"

git push -u origin codex/analyst-style-review-skill-20260902
FEATURE_HEAD="$(git rev-parse HEAD)"
```

快进合并：

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

删除本轮分支：

```bash
git fetch origin --prune
git merge-base --is-ancestor \
  origin/codex/analyst-style-review-skill-20260902 \
  origin/main

git push origin --delete \
  codex/analyst-style-review-skill-20260902

git worktree remove \
  "$PROJECT_ROOT/.worktrees/analyst-style-review-skill-20260902"

git branch -d \
  codex/analyst-style-review-skill-20260902

git fetch origin --prune
```

不得强制删除。保留：

```text
main
research/ai-liquid-cooling-2026h2
```

---

## 十五、最终汇报格式

```markdown
已完成：正式推荐复盘Skill分析员化优化

## GitHub
- 基线：`bd4b2e8320601c07cc71521d3b100e1b7fab96f1`
- main最终提交：`<HEAD>`
- 对比链接：<URL>
- 写作诊断：<URL>
- V3样例：<URL>

## 方法变化
- 是否仍是固定检查表：否
- 每只是否只围绕一个中心问题：是
- 是否先给一句话观点更新：是
- 是否只使用2—4个决定性事实：是
- 是否比较上一轮观点：是
- 是否给出后续基准判断：是

## 工程范围
- Python代码修改：0
- schema修改：0
- 数据库修改：0
- 新定时任务：0
- 选股逻辑修改：0

## 样例
- 德尔股份：<一句观点>
- 金岭矿业：<一句观点>
- 中信银行：<一句观点>
- 海油工程：<一句观点>
- 华昌化工：<一句观点>

## 验证
- 基线测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- `git diff --check`：<结果>
- main本地/远端一致：是/否
- 功能分支已删除：是/否
```
