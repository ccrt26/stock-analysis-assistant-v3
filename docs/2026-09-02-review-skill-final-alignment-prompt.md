# 正式推荐复盘 Skill 最终一致性收尾——Codex执行指令 V1.0

> **直接执行本文件，不要改写成更宽泛的复盘平台方案。**
>
> 当前复盘已经从“数据检查表”进步到“观点更新”，但仓库实际内容仍存在四类问题：
>
> 1. 新方法又形成了新的固定模板；
> 2. 具体数字、日期和公告缺少明确的字段追溯纪律；
> 3. `current_review` 与现有 Python 外层“目标进展、未来展望”职责重复；
> 4. 日常复盘、事件复盘和 D20 最终复盘仍未完全分开。
>
> 本轮只修改复盘 Skill、调用 Prompt、入口说明、测试和样例。
>
> **严禁修改任何 Python 文件、schema、数据库、选股逻辑、定时任务和现有报告模型。**

---

## 一、仓库、基线和分支

### 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

### 唯一基线

```text
分支：main
提交：219c43fa8b22797f03dce0d0b49a6c735f392c4d
```

### 新功能分支

```text
codex/review-skill-final-alignment-20260902
```

### 创建 worktree

在实际项目根目录执行：

```bash
git fetch origin --prune

test "$(git rev-parse origin/main)" = \
  "219c43fa8b22797f03dce0d0b49a6c735f392c4d"

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BASE_HEAD="$(git rev-parse origin/main)"
WORKTREE="$PROJECT_ROOT/.worktrees/review-skill-final-alignment-20260902"

git worktree add \
  "$WORKTREE" \
  -b codex/review-skill-final-alignment-20260902 \
  "$BASE_HEAD"

cd "$WORKTREE"

test "$(git rev-parse HEAD)" = "$BASE_HEAD"
test "$(git branch --show-current)" = \
  "codex/review-skill-final-alignment-20260902"
test -z "$(git status --short)"
```

将本文件原样保存为：

```text
docs/2026-09-02-review-skill-final-alignment-prompt.md
```

---

# 二、这次要解决什么

## 1. 保留 GLM 正确的意见

本轮必须落实：

- 每只股票有一个主要问题；
- 与上一次复盘的观点进行真实比较；
- 所有具体数字、日期和公告都可追溯到本次 snapshot 或原推荐记录；
- 不知道是合法结论，不为完整感编造涨跌原因；
- 观点是否变化决定篇幅，D3/D5/D10 只负责触发，不机械决定字数；
- D20 是唯一允许串起完整20日过程的复盘；
- 第21—30日不得改写冻结的 D20 结论；
- 不通过程序正则给自然语言打分。

## 2. 修正 GLM 过于机械的意见

### 事实不是要求“逐字相同”

snapshot 中可能保存：

```text
0.0240
```

用户文字会写：

```text
2.40个百分点
```

因此要求是：

> 每项具体事实能够追溯到明确字段和值。

不是要求用户文字与 JSON 字符串逐字一致。

### 不把“原因”限制成三条唯一通道

复盘允许使用四类证据联系：

1. 市场/行业共同变化与相对表现；
2. 公司事件和事件前后相对价格反应；
3. 价格、成交、收盘、上影和回撤的组合；
4. 原推荐判断中的具体检查点，例如突破是否站稳、是否有可靠入口、经营变化是否仍成立。

这四类只支持“目前更合理的解释”，不能证明唯一真实原因。

### 上次观点不能只看枚举

上一轮的：

```text
current_assessment
best_supported_explanation
current_weak_or_failed_link
```

作为明确锚点；上一轮 `current_review` 的第一句和中心问题用于保留语义。

不能只看枚举，因为同一个 `supported` 内部也可能从“快速上涨”变成“高位整理”；也不能只重读散文凭印象总结，因为容易虚构观点变化。

---

# 三、允许和禁止范围

## 允许修改

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
.agents/skills/reviewing-stock-recommendations/agents/openai.yaml

ops/forward-monitor-prompt.md

tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py

docs/2026-09-02-review-skill-final-alignment-prompt.md

research/skill-optimization/review-skill-final-alignment-20260902/
```

## 禁止修改

```text
src/
tools/
AGENTS.md
ops/forward-selection-prompt.md

.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/interpreting-market-macro/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/researching-company-events/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md

数据库
schema
七种发动机
四种状态
11个价格场景
20%目标
D20计算
入口价格
定时任务
```

不得：

- 修改 `forward_monitor.py`；
- 新增 Review V3、Pydantic 字段或报告模型；
- 新增评分、权重、概率；
- 新增事实表或复盘数据库；
- 新增语言审计程序；
- 新增正则生成文本 Gate；
- 新增外部数据源；
- 重新选股；
- 改写历史正式复盘；
- 为普通文档增加哈希；
- 处理液冷研究分支。

---

# 四、执行纪律

本轮修改正式复盘合同。

按 `AGENTS.md`：

- 实施前恰好启动一次 `gpt-5.6-sol`、`xhigh` 独立审查；
- 只审查：是否解决新模板、字段追溯、职责重复和 D20 区分；是否误改程序或扩大工程范围；
- 审查不实施、不启动其他子智能体；
- 主智能体采用一次审查意见后连续完成；
- 此后不再启动其他子智能体。

---

# 五、开始前完整读取

```text
AGENTS.md

.agents/skills/reviewing-stock-recommendations/SKILL.md
.agents/skills/reviewing-stock-recommendations/agents/openai.yaml

ops/forward-monitor-prompt.md

src/stock_analyzer/ops/forward_monitor.py

tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py

research/skill-optimization/analyst-style-review-skill-20260902/
  current-review-writing-diagnosis.md
  review-sample-v3.md

local_archive/forward_monitor/
  最新 snapshot JSON
  最新 monitor-report JSON
  最新 monitor-report Markdown
```

读取 Python 只为确认当前外层渲染职责，禁止修改。

运行基线：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py

./.venv/bin/python -m pytest -q
```

记录真实结果，不复述上一轮数字。

---

# 六、Task 1：形成 GLM 意见核对表

创建：

```text
research/skill-optimization/review-skill-final-alignment-20260902/
glm-feedback-verification.md
```

逐项写：

```text
GLM意见
仓库当前是否已经落实
证据文件与原句
仍存在的问题
本轮处理
```

至少核对：

1. 新模板化风险；
2. 与上一次复盘的锚点；
3. 数字和公告事实追溯；
4. 不知道是否合法；
5. 决定性事实是否会被凑数；
6. 字数和触发日关系；
7. 一个主要问题是否过于僵硬；
8. D20 是否允许完整叙事；
9. 第21—30日是否保留冻结结论；
10. 本轮是否确实无需改 Python；
11. V3 样例是否与实际 Python 输出结构一致；
12. V3 样例是否仍出现“个股增量、行业扩散、核心预期”等内部用语。

结论不能只写“GLM正确”，必须分成：

```text
正确且已落实
正确但只落实一部分
需要修正后采用
不适合本项目
```

---

# 七、Task 2：消除现有 Skill 与 Python 外层职责重复

当前 Python 已固定输出：

```text
推荐日期和当时判断
到今天走到哪里
我的分析
接下来更可能怎样
```

其中：

- 推荐日期和原理由由程序单独渲染；
- 当前、最高、最低和距离20%由程序单独渲染；
- 未来1—3日方向及增强/改变条件由程序单独渲染；
- `current_review` 只出现在“我的分析”。

因此修改：

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
ops/forward-monitor-prompt.md
```

明确：

## `current_review` 只负责

- 一句话观点更新；
- 今天唯一的中心问题；
- 为什么这样涨、跌或横盘；
- 原推荐判断哪一部分实现、哪一部分减弱；
- 与上一轮相比观点是否改变；
- 当前综合判断。

## `current_review` 不再重复

- 完整推荐日期；
- 当前涨跌、最高、最低的全套清单；
- 距离20%目标的固定进度句；
- “未来1—3个交易日更可能……”的完整展望；
- `confirmation_condition`；
- `invalidation_condition`。

只有某个数字直接决定中心判断时，才可在 `current_review` 中再次引用一次。

### 示例

允许：

```text
仍有小幅盈利，但收盘已经跌回原突破位下方，
因此推荐时最重要的“突破后站稳”没有实现。
```

不允许：

```text
当前上涨1.22%，最高2.44%，最低-1.90%，
离20%还差18.78个百分点……
```

因为完整进度已经由外层“到今天走到哪里”展示。

---

# 八、Task 3：修正“新模板化”

修改：

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
```

## 1. 一个主要问题，而不是绝对只准一个变化

每只股票确定一个主要问题。

允许在结尾用一句话指出一个次要变化，但只有它会影响下一次复盘时才写。例如：

```text
另外，公司新订单刚公布，是否改变经营判断留到下一次有价格反应后再看。
```

不得并列展开两个中心。

## 2. 决定性事实最多4个，不设最低数量

将：

```text
只使用2—4个决定性事实
```

改成：

```text
使用回答中心问题所需的最少事实，最多4个，不设最低数量。
一个事实已经足够时立即停止，不得为了满足数量凑事实。
停牌且没有价格时，可以没有推荐后价格事实。
```

## 3. 不强制每天同样的段落形状

删除：

```text
current_review 写成2—3个自然段
```

改成：

```text
current_review 可以是一段，也可以是两三段；
开头、段落和结尾服务于这只股票当天真正发生的事情，
不追求每天同构。
```

一句话没有实质变化时可以合法成立。

## 4. 不强制每次公开写“首次复盘”

没有 `previous_episode_review` 时：

- 内部只与原推荐判断比较；
- 不得伪造上次观点；
- 最终用户文字通常不必写“这是首次复盘”；
- 只有“没有上一轮观点”本身会影响理解时才说明。

## 5. 避免内部研究词

最终 `current_review` 不使用以下词作为固定标签或核心表达：

```text
行业扩散
个股增量
核心预期
当前阶段
最有证据的解释
价格支持
观点验证
```

替换为具体事实：

```text
行业里多数股票上涨
比同行多涨多少
推荐时最看重的判断
现在更像……
后来是否真的发生
```

“突破、回撤、上影”等必要价格词第一次出现时用普通中文解释，例如：

```text
上影较多，即盘中多次冲高后又收回来。
```

---

# 九、Task 4：增加事实追溯纪律，不增加程序 Gate

在 Skill 和 Prompt 中加入：

## 1. 具体事实白名单

`current_review` 中每一项具体：

- 日期；
- 百分比；
- 金额；
- 股票数量；
- 公告名称；
- 财务变化；

必须能够追溯到：

```text
当前 snapshot
当前 monitor report 的确定性字段
原推荐 trace
当日按现有流程读取的正式公司材料
```

不能来自模型常识、上一次散文记忆或外部未记录信息。

百分比格式换算允许：

```text
0.024 → 2.40个百分点
```

但必须记录来源字段。

## 2. 推断范围

只允许基于以下联系形成观点：

1. 股票相对市场和行业的差异；
2. 正式公司事件与事件前后相对表现的对应；
3. 价格、成交、收盘、盘中冲高回落和回撤的组合；
4. 原推荐判断中的具体检查点。

这些联系支持“目前更合理的解释”，不证明唯一原因。

## 3. 枚举一致性

正文不能与：

```text
best_supported_explanation
current_assessment
current_weak_or_failed_link
outlook_1_3d
```

明显矛盾。

若正文判断主要来自行业，`best_supported_explanation` 不能写股票自身；确实为混合时使用 `mixed`。

不增加代码校验；由生成前自检和样例人工核对完成。

## 4. 合法的不知道

现有事实不能区分原因时，允许写：

```text
目前无法判断这次下跌主要来自行业还是股票自身，
因为缺少……
```

不得为了输出一个原因而编故事。

---

# 十、Task 5：使用上一轮观点作为真实锚点

在 Skill 和 Prompt 中规定：

先读取本记录自己的：

```text
previous_episode_review.current_assessment
previous_episode_review.best_supported_explanation
previous_episode_review.current_weak_or_failed_link
previous_episode_review.current_review
```

判断观点是否改变时：

1. 先比较前三个结构化字段；
2. 再读取上一轮 `current_review` 第一句和中心问题；
3. 只有以下情况才公开写“观点改变”：
   - 结构化判断发生变化；
   - 主要解释发生变化；
   - 原推荐的关键一环发生变化；
   - 新决定性事实使同一粗枚举下的具体观点发生实质变化。

仅仅换了一种措辞，不叫观点改变。

没有上次记录时，只与原推荐判断比较，不在用户文字中机械宣布“首次复盘”。

---

# 十一、Task 6：按观点变化控制篇幅

删除当前：

```text
D3、D5固定180—350字
D10固定250—450字
```

改为：

## 日常复盘，观点未变

```text
约60—140个中文字。
```

只写：

- 观点未变；
- 最新一项最重要的支持或风险；
- 是否需要改变下一步判断。

## 观点发生实质变化

```text
约150—320个中文字。
```

说明：

- 从什么判断变成什么判断；
- 哪个决定性事实造成变化；
- 这对原推荐意味着什么。

## 新事件影响原推荐

```text
约180—350个中文字。
```

只讨论：

- 事件改变了什么；
- 没改变什么；
- 价格是否已有相应反应。

## D3/D5/D10

只是触发点，不自动决定字数。

D10 无变化时可以一段短评；D3 出现重大变化时可以写完整分析。

字符数仅为参考，不增加自动校验。

---

# 十二、Task 7：把 D20 与日常复盘真正分开

在 Skill 和 Prompt 中新增独立小节：

## 日常复盘

只写增量：

```text
与上一次相比什么变了
观点维持还是改变
下一步基准判断
```

不得重述完整历史。

## 事件复盘

只写：

```text
事件前的相关判断
事件本身改变了什么
价格是否出现与之对应的变化
当前观点是否因此改变
```

例行公告不进正文。

## D20 最终复盘

D20 是唯一允许串起完整过程的复盘。

不按固定五问逐项作答，要写成一篇完整但紧凑的总结，包含：

- 推荐时最重要的判断；
- D1—D20最关键的2—4次观点变化；
- 是否达到20%；
- 推荐理由最终是否成立；
- 具体股票和推荐时机是否合适；
- 最大成功或错误；
- 一条可供以后改进的具体经验。

使用已有：

```text
final_twenty_day_review
decision_review
weak_or_failed_link
D20确定性指标
历史 previous_episode_review
```

不新增字段。

第21—30日：

- 原样保留冻结D20结论；
- 只说明D20之后新增表现；
- 不得把后来的上涨或下跌重写成第二次D20结论。

---

# 十三、Task 8：更新 Skill 入口说明

修改：

```text
.agents/skills/reviewing-stock-recommendations/agents/openai.yaml
```

默认提示改为明确表达：

```text
围绕当天唯一主要问题形成观点更新；
使用最少且可追溯的决定性事实；
不重复程序已展示的目标进度和展望条件；
观点未变时简短更新；
D20才串起完整过程。
```

不增加工具或字段。

---

# 十四、Task 9：形成与实际生产结构一致的 V4 样例

创建：

```text
research/skill-optimization/review-skill-final-alignment-20260902/
  review-sample-v4.md
  review-sample-v4-fact-trace.md
```

## `review-sample-v4.md`

必须模拟当前 Python 的真实四段输出：

```text
推荐日期和当时判断
到今天走到哪里
我的分析
接下来更可能怎样
```

不得再用脱离实际渲染器的自由格式冒充生产效果。

至少覆盖：

1. 观点明显下调：金岭矿业；
2. 观点由快速上涨改为高位整理：德尔股份；
3. 观点未变：四川九洲或海油工程；
4. 无法执行：华昌化工；
5. 公司事件触发：从本地正式记录选一个真实案例；
6. D20最终复盘：从本地成熟正式推荐中选一个真实案例。

如果当前没有成熟 D20 正式记录：

- 明确写“当前没有成熟D20案例”；
- 不虚构数据；
- 只在文末提供无数字的写作结构示例。

## 样例要求

“我的分析”中：

- 不重复完整推荐日期；
- 不重复全套当前/最高/最低/目标距离；
- 不重复“未来1—3个交易日更可能”；
- 最多4项具体事实；
- 观点未变的股票明显更短；
- 不机械写“这是首次复盘”；
- 不出现“行业扩散、个股增量、核心预期、当前阶段、最有证据的解释”。

## `review-sample-v4-fact-trace.md`

只用于人工核对样例，不属于生产schema。

表格字段：

```text
股票
样例中的具体事实
来源文件
来源字段
原始值
展示值
```

逐项列出样例中的：

- 日期；
- 百分比；
- 公告；
- 股票数量；
- 财务数据。

不为无具体数字的观点句建立“哈希”或程序校验。

---

# 十五、Task 10：轻量测试

## 修改

```text
tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py
```

## 增加测试

```python
def test_review_skill_avoids_new_template_and_uses_traceable_minimum_facts() -> None:
    review = Path(
        ".agents/skills/reviewing-stock-recommendations/SKILL.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "最多4个，不设最低数量",
        "不得为了满足数量凑事实",
        "可以是一段，也可以是两三段",
        "通常不必写“这是首次复盘”",
        "每一项具体",
        "能够追溯到",
        "previous_episode_review.current_assessment",
        "previous_episode_review.best_supported_explanation",
        "仅仅换了一种措辞，不叫观点改变",
        "D20 是唯一允许串起完整过程的复盘",
        "第21—30日",
    ):
        assert phrase in review

    for old in (
        "只使用2—4个决定性事实",
        "D10：250—450个中文字",
        "写成2—3个自然段",
    ):
        assert old not in review
```

```python
def test_review_prompt_aligns_current_review_with_existing_renderer() -> None:
    prompt = Path(
        "ops/forward-monitor-prompt.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "current_review 只负责",
        "不再重复完整推荐日期",
        "不再重复距离20%目标的固定进度句",
        "不再重复未来1—3个交易日的完整展望",
        "日常复盘只写增量",
        "事件复盘",
        "D20 最终复盘",
        "字段和值",
    ):
        assert phrase in prompt
```

测试只验证合同存在，不对未来生成文字做正则质量评分。

---

# 十六、Task 11：验证范围

运行：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py

./.venv/bin/python -m pytest -q

git diff --check
```

确认没有修改 Python：

```bash
test -z "$(
  git diff --name-only \
    219c43fa8b22797f03dce0d0b49a6c735f392c4d...HEAD \
  | grep -E '^(src|tools)/' || true
)"
```

确认没有修改五个选股 Skill：

```bash
test -z "$(
  git diff --name-only \
    219c43fa8b22797f03dce0d0b49a6c735f392c4d...HEAD \
  | grep -E '^\.agents/skills/(orchestrating-stock-research|interpreting-market-macro|researching-sectors-industries|researching-company-events|analyzing-price-trading)/' \
  || true
)"
```

人工完整阅读 V4 样例，回答：

- 是否仍有八只股票同一开头；
- 是否仍反复写“按现在的表现”；
- 是否仍机械声明首次复盘；
- 是否每个具体数字都能在事实追溯表找到；
- 是否观点未变的股票明显更短；
- D20 是否串起过程但没有重写冻结结论；
- 是否与当前 Python 四段输出一致。

---

# 十七、Task 12：提交、合并和分支清理

## 提交

```bash
git add \
  docs/2026-09-02-review-skill-final-alignment-prompt.md \
  .agents/skills/reviewing-stock-recommendations/SKILL.md \
  .agents/skills/reviewing-stock-recommendations/agents/openai.yaml \
  ops/forward-monitor-prompt.md \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py \
  research/skill-optimization/review-skill-final-alignment-20260902

git commit -m \
  "docs: align review skill with evidence and production output"
```

推送功能分支：

```bash
git push -u origin codex/review-skill-final-alignment-20260902
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
  origin/codex/review-skill-final-alignment-20260902 \
  origin/main

git push origin --delete \
  codex/review-skill-final-alignment-20260902

git worktree remove \
  "$PROJECT_ROOT/.worktrees/review-skill-final-alignment-20260902"

git branch -d \
  codex/review-skill-final-alignment-20260902

git fetch origin --prune
```

不得强制删除。

远端继续保留：

```text
main
research/ai-liquid-cooling-2026h2
```

液冷研究分支不合并、不删除、不修改。

---

# 十八、最终验收标准

## GLM意见

- [ ] 对每一条意见作出“已落实/部分落实/修正采用/不采用”判断；
- [ ] 不把GLM意见全部机械照搬；
- [ ] 数字追溯按字段和值，不要求字符串逐字相同；
- [ ] 原因解释不声称证明唯一因果；
- [ ] 上次观点使用结构化字段和上一轮文字共同锚定。

## Skill

- [ ] 一个主要问题，可附带一句次要变化；
- [ ] 决定性事实最多4个、不设最低数量；
- [ ] 不凑数；
- [ ] 不强制同样段落结构；
- [ ] 不机械公开“首次复盘”；
- [ ] 观点未变时短写；
- [ ] 观点改变时写明改变原因；
- [ ] 不知道可以成为正式结论；
- [ ] D20允许完整叙事；
- [ ] D21—D30不改写D20。

## 与实际程序一致

- [ ] `current_review` 不重复程序单独展示的推荐日期；
- [ ] 不重复完整目标进度；
- [ ] 不重复完整未来展望和两个条件；
- [ ] V4样例使用当前Python真实四段结构；
- [ ] 不修改任何Python文件。

## 工程范围

- [ ] 不修改五个选股Skill；
- [ ] 不修改选股逻辑；
- [ ] 不新增schema、数据库、字段、数据源或任务；
- [ ] 不新增自然语言评分程序；
- [ ] 完整测试通过；
- [ ] main本地与远端一致；
- [ ] 本轮功能分支删除；
- [ ] 液冷研究分支保持不变。

---

# 十九、Codex最终汇报格式

```markdown
已完成：正式推荐复盘Skill最终一致性收尾

## GitHub
- 基线：`219c43fa8b22797f03dce0d0b49a6c735f392c4d`
- main最终提交：`<HEAD>`
- 对比链接：<URL>
- GLM意见核对：<URL>
- V4生产格式样例：<URL>
- 样例事实追溯：<URL>

## GLM意见
- 正确且已落实：<列表>
- 正确但此前只落实一部分：<列表>
- 修正后采用：<列表>
- 不采用：<列表>

## 关键修改
- 新模板化：<如何消除>
- 上次观点锚点：<如何处理>
- 事实追溯：<如何处理>
- current_review职责：<如何与Python外层分开>
- 日常/事件/D20：<如何区分>
- D21—D30：<如何保持冻结结论>

## 样例
- 观点未变是否明显更短：是/否
- 是否仍机械写首次复盘：是/否
- 是否仍出现内部研究词：是/否
- 所有具体数字能否追溯：是/否
- 是否与生产四段渲染一致：是/否
- 是否存在真实D20样例：是/否；若否说明原因

## 工程范围
- Python修改：0
- 五个选股Skill修改：0
- schema修改：0
- 数据库修改：0
- 新任务：0
- 自然语言程序Gate：0

## 验证
- 基线定向测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- `git diff --check`：<结果>
- main本地/远端一致：是/否
- 功能分支已删除：是/否
- 工作区干净：是/否
```
