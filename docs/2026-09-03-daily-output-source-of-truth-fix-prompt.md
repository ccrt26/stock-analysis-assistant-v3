# 每日股票任务最终输出链路诊断与修复——Codex执行指令 V1.0

> 历史记录：本文保留当时方案与事实，不作为当前运行入口或调度依据。当前时序以 `docs/architecture/current-v3-architecture.md` 和 `ops/forward-selection-prompt.md` 为准。

> **直接执行本文件。**
>
> 当前 `main` 中的选股说明和复盘 Skill 已经更新，但 2026-09-03 用户收到的自动任务回复又变成：
>
> - `今日正式候选`
> - `既有推荐复盘`
> - 每只股票一行摘要
> - 展示最近未选股票
> - 最后汇报 HEAD、工作区和临时文件
>
> 本轮目标不是再次修改选股或复盘方法，而是找出并修复：
>
> **仓库中的正式报告规则已经更新，但自动任务最终消息仍绕过正式报告、重新生成执行摘要。**
>
> 这是个人助手。不要扩建部署系统、日志平台、报告服务或新的数据层。

---

## 一、基线

```text
仓库：https://github.com/ccrt26/stock-analysis-assistant-v3
分支：main
基线提交：3ed239c3a5e27c1ff7261bd14150ee4982276373
新分支：codex/daily-output-source-of-truth-fix-20260903
```

在实际项目根目录执行：

```bash
git fetch origin --prune

test "$(git rev-parse origin/main)" = \
  "3ed239c3a5e27c1ff7261bd14150ee4982276373"

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BASE_HEAD="$(git rev-parse origin/main)"
WORKTREE="$PROJECT_ROOT/.worktrees/daily-output-source-of-truth-fix-20260903"

git worktree add \
  "$WORKTREE" \
  -b codex/daily-output-source-of-truth-fix-20260903 \
  "$BASE_HEAD"

cd "$WORKTREE"

test "$(git rev-parse HEAD)" = "$BASE_HEAD"
test -z "$(git status --short)"
```

将本文件原样保存为：

```text
docs/2026-09-03-daily-output-source-of-truth-fix-prompt.md
```

---

## 二、明确不做

不得修改：

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
其他五个选股 Skill
src/
tools/
数据库与 schema
20%目标
D20规则
入口价格
选股方法
复盘分析方法
```

不得：

- 再增加“说人话”规则；
- 再生成一版复盘样例来替代诊断；
- 新增报告模型；
- 新增定时任务；
- 新增后台服务；
- 为自然语言建立评分器；
- 把工程状态继续放进每日股票报告；
- 在没有确认根因前修改文件。

---

## 三、实施前审查

本轮涉及自动任务说明和 `AGENTS.md` 的输出优先级，实施前恰好启动一次：

```text
模型：gpt-5.6-sol
推理：xhigh
```

只审查：

1. 是否先定位“归档报告、最终消息、自动任务指令”哪一层出错；
2. 是否把根因错误归给复盘 Skill；
3. 是否只做最小入口修复；
4. 是否避免新增平台和程序。

审查不实施，不启动其他子智能体。

---

# 第一阶段：用最新实际产物定位故障层

## Task 1：确认实际运行目录和版本

实际自动任务目录应为：

```text
/Users/ccrt/股票分析助手
```

在该目录执行：

```bash
TASK_ROOT="/Users/ccrt/股票分析助手"

printf 'root=%s\n' "$(git -C "$TASK_ROOT" rev-parse --show-toplevel)"
printf 'branch=%s\n' "$(git -C "$TASK_ROOT" branch --show-current)"
printf 'head=%s\n' "$(git -C "$TASK_ROOT" rev-parse HEAD)"
printf 'origin_main=%s\n' "$(git -C "$TASK_ROOT" rev-parse origin/main)"
git -C "$TASK_ROOT" status --short
```

判断：

- `HEAD != 3ed239c...`：本地运行版本未部署；
- `HEAD == 3ed239c...`：继续排查，不得再归因于GitHub未合并。

## Task 2：确认当前规则确实存在

```bash
grep -nF "最多4个、不设最低数量" \
  "$TASK_ROOT/.agents/skills/reviewing-stock-recommendations/SKILL.md"

grep -nF "current_review 只负责" \
  "$TASK_ROOT/ops/forward-monitor-prompt.md"

grep -nF "今天明确推荐的股票" \
  "$TASK_ROOT/ops/forward-selection-prompt.md"

grep -nF "不得新增候选、删除股票、改变顺序" \
  "$TASK_ROOT/ops/forward-selection-prompt.md"
```

任何一项没有匹配，说明实际目录没有当前文件。

## Task 3：检查归档JSON中的AI分析

读取：

```text
$TASK_ROOT/local_archive/forward_monitor/monitor-report-2026-09-02.json
```

运行：

```bash
REPORT_JSON="$TASK_ROOT/local_archive/forward_monitor/monitor-report-2026-09-02.json"

./.venv/bin/python - <<PY
import json
from pathlib import Path

path = Path("$REPORT_JSON")
payload = json.loads(path.read_text(encoding="utf-8"))

for alert in payload.get("alerts", []):
    name = alert.get("name", alert.get("ts_code", ""))
    for review in alert.get("episode_reviews", []):
        print("=" * 72)
        print(name, review.get("episode_id", ""))
        print("assessment:", review.get("current_assessment"))
        print("explanation:", review.get("best_supported_explanation"))
        print("review:")
        print(review.get("current_review", ""))
PY
```

判断：

### A. `current_review` 已是观点更新稿

例如包含：

```text
观点从什么调整为什么
为什么这样涨跌
推荐时哪一项判断实现或减弱
```

则说明：

```text
新复盘 Skill 已经被使用
```

问题位于最终消息层，不得再修改 Skill。

### B. `current_review` 仍只有：

```text
原判断继续得到支持
部分支持
仍需观察
```

则说明每日任务没有按当前 Prompt 调用新 Skill，继续检查自动任务自身的指令。

## Task 4：检查正式归档 Markdown

```bash
REPORT_MD="$TASK_ROOT/local_archive/forward_monitor/monitor-report-2026-09-02.md"

grep -nE \
  '^## |^### |^\*\*(推荐日期和当时判断|到今天走到哪里|我的分析|接下来更可能怎样)\*\*$' \
  "$REPORT_MD"

sed -n '1,280p' "$REPORT_MD"
```

判断：

### A. Markdown是当前四段格式，最终通知却是一行一个股票

根因已经确定：

```text
归档报告正确
→ 自动任务在最后一步重新摘要
→ 用户看到的是执行摘要，不是正式报告
```

### B. JSON观点正确，但Markdown不正确

检查是否读取了错误日期、旧报告或不同目录；不得先改Skill。

### C. JSON和Markdown都旧

根因是当前自动任务没有重新读取当前 Prompt/Skill。

## Task 5：定位自动任务保存的旧指令

先做定向搜索：

```bash
grep -RIn \
  --exclude-dir=.git \
  --exclude='*.log' \
  -E '今日正式候选|既有推荐复盘|今日研究已冻结|HEAD未变化|最近未选为' \
  "$HOME/.codex" \
  "$HOME/Library/Application Support/Codex" \
  2>/dev/null || true
```

如果本地文件搜索没有结果，打开当前 Codex Automation 的编辑面板，读取它实际保存的：

```text
Name
Instructions / Prompt
Schedule
Working directory
```

不能根据记忆推断。

创建诊断文件：

```text
research/skill-optimization/daily-output-source-of-truth-20260903/
  root-cause-diagnosis.md
```

必须写出：

```text
实际TASK_ROOT
实际HEAD
归档JSON是否使用新Skill
归档Markdown是否为新格式
用户最终消息是否为归档Markdown
自动任务Instructions中的最终回复要求
最终根因
```

---

# 第二阶段：按实际根因做最小修复

## Task 6：消除两个最终回复来源

当前必须只保留一个正式来源：

```text
AGENTS.md
→ 自动任务入口
→ ops/forward-selection-prompt.md
→ ops/forward-monitor-prompt.md
→ 当前Skill
→ 归档JSON/Markdown
→ 用户收到完整报告
```

自动任务自身不得复制选股、复盘和输出格式细则。

### 自动任务保存的Instructions替换为

```text
在 /Users/ccrt/股票分析助手 运行当前个人A股助手的每日09:05任务。

每次运行必须：
1. 确认工作区无未提交改动；执行 git fetch origin --prune。若本地 main 落后，只允许 git pull --ff-only origin main；无法快进时停止并说明。
2. 从当前HEAD重新完整读取 AGENTS.md 和 ops/forward-selection-prompt.md。
3. 严格执行 ops/forward-selection-prompt.md；它要求读取的 ops/forward-monitor-prompt.md 和各Skill也必须读取当前HEAD中的文件。
4. 正常完成时，最终回复就是 ops/forward-selection-prompt.md 要求的完整股票报告，不是任务执行摘要。
5. 不得把正式推荐和复盘压缩为每只一行；不得显示最近未选股票；不得使用“今日正式候选”“既有推荐复盘”作为替代格式。
6. 不得在正常股票报告后附加HEAD、工作区、提交、推送或临时文件清理情况。只有任务失败时才报告技术诊断。
7. 对既有推荐复盘，必须使用本次生成并记录的 monitor-report Markdown 内容，不得另写一份更短摘要。
8. 不修改程序、Skill或仓库文件，不提交，不推送。
```

自动任务中不得继续保留旧的详细业务规则副本。

如果 Codex 无权直接编辑 Automation：

- 将上面文字保存到诊断报告；
- 明确写“需要用户在Automation编辑面板替换”；
- 不得声称已经更新。

## Task 7：修复 `AGENTS.md` 的高优先级冲突

当前 `AGENTS.md` 的通用规则要求：

```text
最终简要汇报完成内容、验证证据……
```

这适用于开发任务，却容易让每日研究也被压缩成执行摘要。

在 `AGENTS.md` 的“任务执行纪律”增加一条最小例外：

```markdown
- 正式每日选股与复盘自动任务属于用户报告生产，不适用“最终简要汇报完成内容”的开发任务收尾格式。正常完成时，最终回复必须直接采用 `ops/forward-selection-prompt.md` 规定的完整股票报告；不得在报告后追加 HEAD、工作区、提交、推送、测试或临时文件说明。只有任务失败时才输出技术诊断。
```

不修改其他规则。

## Task 8：加强唯一报告来源

在 `ops/forward-selection-prompt.md` 的开头增加：

```markdown
## 最终回复唯一来源

本文件及其引用的 `ops/forward-monitor-prompt.md` 是每日股票报告的唯一格式来源。

正常完成时：
- 最终回复必须是完整股票报告；
- 不得在生成归档后另写执行摘要；
- 不得把逐股说明压缩为每只一行；
- 不得展示最近未选、比较股或内部候选；
- 不得追加Git、工作区、测试和文件清理汇报；
- 复盘部分直接采用本次已记录的正式复盘Markdown，不重新摘要。

只有执行失败时，才改为技术错误说明。
```

不要再增加一套荐股或复盘方法。

## Task 9：轻量测试

修改现有 Prompt 测试，优先：

```text
tests/test_v4_operational_prompts.py
tests/test_forward_monitor_prompt.py
```

只检查以下合同存在：

```text
正式每日选股与复盘自动任务属于用户报告生产
最终回复唯一来源
不得在生成归档后另写执行摘要
复盘部分直接采用本次已记录的正式复盘Markdown
不得追加Git、工作区、测试和文件清理汇报
```

不得对生成文字建立复杂正则评分器。

---

# 第三阶段：使用既有文件做一次不写入验证

## Task 10：生成链路验证样例

不得覆盖：

```text
local_archive/forward_monitor/monitor-report-2026-09-02.*
local_archive/forward_selection/research-trace-2026-09-02.json
```

使用这些既有文件创建：

```text
research/skill-optimization/daily-output-source-of-truth-20260903/
  expected-user-response-from-existing-archive.md
```

要求：

- 复盘部分使用现有正式归档Markdown中的完整逐股内容；
- 推荐部分按照当前 `forward-selection-prompt.md` 的详细格式，从已冻结 trace 重组；
- 不重新选股；
- 不使用2026-09-03盘中行情；
- 不列最近未选；
- 不附加HEAD和工作区；
- 明确展示这才是同一批归档的正确用户回复。

该文件只是验证输出链路，不修改历史归档。

## Task 11：人工对比

将以下两份逐项比较：

```text
用户实际收到的2026-09-03短摘要
expected-user-response-from-existing-archive.md
```

回答：

1. 哪些内容在最后摘要阶段被删除；
2. 哪些旧标题不是当前Prompt要求；
3. 哪些“最近未选”本不应对外出现；
4. 哪些复盘分析已经在归档中，却没有送达用户；
5. 是否证明问题在最后输出层。

---

# 第四阶段：验证、提交和部署

## Task 12：运行测试

```bash
./.venv/bin/python -m pytest -q \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_monitor_prompt.py

./.venv/bin/python -m pytest -q
git diff --check
```

确认没有修改：

```text
src/
tools/
任何Skill
数据库
schema
选股和复盘方法
```

本轮允许修改的生产文件只有：

```text
AGENTS.md
ops/forward-selection-prompt.md
```

以及相关测试、诊断和验证样例。

## Task 13：提交

```bash
git add \
  AGENTS.md \
  ops/forward-selection-prompt.md \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_monitor_prompt.py \
  docs/2026-09-03-daily-output-source-of-truth-fix-prompt.md \
  research/skill-optimization/daily-output-source-of-truth-20260903

git commit -m \
  "fix: return the full daily stock report instead of a task summary"
```

推送功能分支：

```bash
git push -u origin codex/daily-output-source-of-truth-fix-20260903
FEATURE_HEAD="$(git rev-parse HEAD)"
```

## Task 14：快进合并到main

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

## Task 15：Automation真实部署

确认 Automation 编辑面板中的 Instructions 已替换成 Task 6 的精简内容。

保存：

```text
任务名称
工作目录
下次运行时间
是否已替换Instructions
```

到 `root-cause-diagnosis.md`。

如果无法由Codex编辑，最终汇报必须明确：

```text
仓库修复已完成
Automation Instructions 尚未更新
用户仍需在Automation编辑面板粘贴哪段文字
```

不得把“Scheduled Task指向目录”误写成“Instructions也已更新”。

## Task 16：删除功能分支

仅在功能提交已进入main后：

```bash
git fetch origin --prune

git merge-base --is-ancestor \
  origin/codex/daily-output-source-of-truth-fix-20260903 \
  origin/main

git push origin --delete \
  codex/daily-output-source-of-truth-fix-20260903

git worktree remove \
  "$PROJECT_ROOT/.worktrees/daily-output-source-of-truth-fix-20260903"

git branch -d \
  codex/daily-output-source-of-truth-fix-20260903

git fetch origin --prune
```

不得强制删除。

保留：

```text
main
research/ai-liquid-cooling-2026h2
```

---

# 五、最终汇报格式

```markdown
已完成：每日股票任务最终输出链路诊断与修复

## 根因
- 实际TASK_ROOT：`<路径>`
- 实际HEAD：`<提交>`
- 归档JSON是否使用新复盘Skill：是/否
- 归档Markdown是否为当前四段格式：是/否
- 用户最终消息是否直接采用归档报告：是/否
- 根因位于：本地版本 / Skill调用 / Markdown生成 / Automation最终摘要
- 证据：<简述>

## 仓库
- 基线：`3ed239c3a5e27c1ff7261bd14150ee4982276373`
- main最终提交：`<HEAD>`
- 对比链接：<URL>
- 根因诊断：<URL>
- 正确输出验证：<URL>

## Automation
- Instructions是否已替换为精简入口：是/否
- 是否每次重新读取当前仓库Prompt：是/否
- 正常完成是否禁止执行摘要：是/否
- 是否禁止最近未选和Git状态进入用户报告：是/否
- 无法自动修改时用户需要做什么：<准确说明>

## 修改范围
- AGENTS.md：<修改>
- forward-selection-prompt.md：<修改>
- Skill修改：0
- Python修改：0
- schema修改：0
- 选股逻辑修改：0
- 复盘分析方法修改：0

## 验证
- 定向测试：<结果>
- 完整测试：<结果>
- `git diff --check`：<结果>
- main本地/远端一致：是/否
- 功能分支已删除：是/否
```

只有确认Automation自身的Instructions也已更新，才可以声称下一次每日任务会直接返回完整报告。
