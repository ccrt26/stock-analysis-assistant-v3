# 每日荐股与正式推荐复盘“真正说人话”修复——Codex执行指令 V1.0

> **直接执行本文件。**
>
> 本任务解决两个已经复现的问题：
>
> 1. 新荐股虽然增加了篇幅，但仍在用“扩散、传播、市场识别、关键数字、路径”等内部研究术语向用户解释；
> 2. “正式推荐股票的走势复盘”仍会混入待确认事件、比较股或其他并未明确推荐的记录。
>
> 这是个人股票助手的输出修复，不是新一轮选股调优，不是审计工程，也不是报告平台建设。

---

## 一、仓库、基线与新分支

### 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

### 唯一代码基线

```text
分支：codex/detailed-recommendation-explanation-20260901
提交：36636cc9f80a1b568a6926d9395cf82f8ab58887
```

### 新分支

```text
codex/plain-language-recommendation-review-20260902
```

### 建议 worktree

```text
.worktrees/plain-language-recommendation-review-20260902
```

从仓库根目录执行：

```bash
git fetch origin

git worktree add \
  .worktrees/plain-language-recommendation-review-20260902 \
  -b codex/plain-language-recommendation-review-20260902 \
  36636cc9f80a1b568a6926d9395cf82f8ab58887

cd .worktrees/plain-language-recommendation-review-20260902

git rev-parse HEAD
git branch --show-current
git status --short
```

必须分别得到：

```text
36636cc9f80a1b568a6926d9395cf82f8ab58887
codex/plain-language-recommendation-review-20260902
空工作区
```

将本文件原样保存为：

```text
docs/2026-09-02-plain-language-recommendation-review-prompt.md
```

不得另写一份更宽泛的计划替代本文件。

---

## 二、已经确认的两个根因

### 根因一：昨天的“人话 Prompt”本身仍是程序语言

昨天新增的说明要求把以下内容作为固定栏目：

```text
为什么偏偏是现在
为什么不是普通跟涨
关键数字说明什么
为什么还可能有路径
```

样例中继续使用了：

```text
板块连续扩散
市场识别已形成
板块共振解释需求来源
个股超额
路径
个股需求
```

所以 Codex 并不是没有遵守 Prompt，而是在认真复述一套本身就不自然的 Prompt。

本轮不能继续通过“再增加一条要说人话”解决，必须把面向用户的词和组织方式整体改掉。

### 根因二：最新修改没有稳定进入每日任务，而且复盘 Markdown 仍在代码中输出非正式记录

GitHub 的详细说明修改位于：

```text
36636cc9f80a1b568a6926d9395cf82f8ab58887
```

但每日任务可能仍从其他项目目录、旧 worktree 或旧分支运行。

同时，当前 `forward_monitor.py` 的内部 JSON 虽然保留了不同记录身份，但 `_render_markdown()` 仍遍历全部 `report.alerts`，并分别输出：

```text
conditional_event
comparator
confirmed_active
```

这使得只靠 Prompt 要求“最终不要展示”并不稳定。

本轮必须同时解决：

```text
实际每日任务到底读哪个目录和提交
+
最终用户 Markdown 在代码层只展示明确正式推荐
```

---

## 三、从券商报告中学习什么，不照抄什么

本轮参考券商公司点评、业绩点评和首次覆盖报告的共同写法，但只学习结构，不复制券商腔。

### 学习的部分

券商报告通常先回答：

```text
公司发生了什么
→ 公司主要做什么
→ 这件事会影响哪块业务
→ 经营数据为什么变化
→ 为什么值得关注
→ 风险是什么
```

数字出现以后，会紧接着说明：

```text
增长来自哪块业务
利润为什么快于或慢于收入
行业变化如何影响公司
风险会在哪个环节出现
```

### 不照抄的部分

不得把下面这些券商或程序术语直接给个人用户：

```text
景气度
主线
催化
估值修复
预期差
扩散
传播
传导
市场识别
个股需求
量价确认
剩余路径
发动机
反证
关键未知
正贡献
有效成员
```

内部研究仍可使用原有字段和专业含义；这里只禁止最终给用户看的文字直接复述这些词。

### 面向用户的固定原则

每段都按：

```text
先说事实
→ 再解释这件事实意味着什么
→ 最后说明对这只股票的影响
```

不能按：

```text
先说内部结论
→ 再堆数字证明规则被触发
```

---

## 四、任务范围

### 允许修改

```text
docs/2026-09-02-plain-language-recommendation-review-prompt.md

ops/forward-selection-prompt.md
ops/forward-monitor-prompt.md

.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/researching-company-events/SKILL.md

src/stock_analyzer/ops/forward_monitor.py

tests/test_v4_operational_prompts.py
tests/test_forward_monitor_prompt.py
tests/test_forward_monitor.py

research/skill-optimization/plain-language-recommendation-review-20260902/
```

只在测试确实要求时，允许修改紧邻的既有测试辅助代码。

### 禁止修改

```text
src/stock_analyzer/ops/forward_selection.py
docs/architecture/a-share-short-horizon-engine-contract-v4.md

.agents/skills/interpreting-market-macro/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md

tools/
数据库
数据schema
数据采集
定时任务研究逻辑
D20定义
11个价格场景
```

不得：

- 重新选择今天的股票；
- 修改五个 Skill 的选股规则；
- 修改 active/conditional 分类；
- 修改入口价格或收益；
- 增加评分器、权重、语言评分模型；
- 增加新报告 schema；
- 增加新的 Markdown 类型或报告平台；
- 增加数据库表；
- 增加数据源；
- 联网补公司资料；
- 引入子智能体；
- 建立词语审计平台；
- 用大批正则检查自然语言；
- 为“安全”增加与目标无关的拦截和兜底。

内部 JSON 保持完整，最终用户 Markdown 做最小过滤。这个任务属于不改变研究结论的用户显示调整，不启动独立审查子智能体。

---

# 第一阶段：查清每日任务为什么没有读到昨天的修改

## Task 1：读取项目规则和当前实现

完整读取：

```text
AGENTS.md
ops/forward-selection-prompt.md
ops/forward-monitor-prompt.md
.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/researching-company-events/SKILL.md
src/stock_analyzer/ops/forward_monitor.py
tests/test_v4_operational_prompts.py
tests/test_forward_monitor_prompt.py
tests/test_forward_monitor.py
research/skill-optimization/detailed-recommendation-explanation-20260901/sample-report.md
```

运行基线：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py
```

记录真实结果。

## Task 2：定位每日任务实际工作目录

创建：

```text
research/skill-optimization/plain-language-recommendation-review-20260902/runtime-diagnosis.md
```

先运行：

```bash
git worktree list --porcelain
```

在用户目录中只做定向搜索，不全盘扫描：

```bash
grep -RIl \
  -e "stock-analysis-assistant-v3" \
  -e "stock_analyzer.ops.forward_selection" \
  -e "ops/forward-selection-prompt.md" \
  "$HOME/Library/LaunchAgents" \
  "$HOME/.codex" \
  "$HOME/Library/Application Support/Codex" \
  2>/dev/null || true
```

结合现有计划任务配置、当天任务日志或 Codex Scheduled Task 设置，找出每日任务实际使用的：

```text
TASK_ROOT
当前分支
当前HEAD
```

在实际目录运行：

```bash
git -C "$TASK_ROOT" rev-parse --show-toplevel
git -C "$TASK_ROOT" branch --show-current
git -C "$TASK_ROOT" rev-parse HEAD
git -C "$TASK_ROOT" status --short

git -C "$TASK_ROOT" merge-base --is-ancestor \
  36636cc9f80a1b568a6926d9395cf82f8ab58887 \
  HEAD
```

再检查实际读取的 Prompt 是否包含昨天的文字：

```bash
grep -F "名单冻结后的用户解释" \
  "$TASK_ROOT/.agents/skills/orchestrating-stock-research/SKILL.md" || true

grep -F "每只股票建议300—500个中文字" \
  "$TASK_ROOT/ops/forward-selection-prompt.md" || true
```

`runtime-diagnosis.md` 必须写清：

```text
每日任务实际工作目录
每日任务运行分支
每日任务运行HEAD
是否包含36636cc
是否读取到昨天修改后的Prompt
今天输出仍是旧格式的直接原因
```

不得只写“可能没有部署”。

---

# 第二阶段：把新荐股说明改成真正的人话

## Task 3：重写 `forward-selection-prompt.md` 的用户输出部分

修改：

```text
ops/forward-selection-prompt.md
```

保留内部选股、V4轨迹、active/conditional和记录流程。

删除或改写面向用户的以下固定标题和要求：

```text
为什么偏偏是现在
为什么不是普通跟涨
关键数字说明什么
为什么还可能有路径
```

最终推荐部分改为以下四个自然问题：

```markdown
### 公司主要做什么

### 这次为什么会选它

### 股价已经怎么走

### 最需要担心什么
```

不要求每只机械写四个标题。可以自然合并成3—5个短段落，但必须让用户读懂这四件事。

### 必须加入以下规则

```markdown
用户不是来学习内部研究方法。最终说明不得解释“我们用了什么规则”，而要解释“这家公司发生了什么、股票为什么被选中”。

每只股票先介绍公司主要卖什么产品或提供什么服务，再解释这一次为什么会选它。公司介绍只写与本次推荐有关的业务，不写公司沿革、注册地址和无关概念。

板块型股票不要写“板块扩散”。要直接说清：相关股票一共有多少只，其中多少只最近在上涨，上涨是否集中在少数龙头，以及这只股票为什么比同行表现更强。

独立价格型股票不要写“个股需求增强”或“市场识别形成”。要直接说清：最近几天涨了多少、是否连续上涨、成交是否明显增多、它比大盘和同行多涨多少，以及这些事实为什么说明它不是偶然的一天上涨。

公司事件型股票不要写“事件传导”或“市场尚未定价”。要直接说清：公司公布了什么、这件事会影响哪块业务、可能什么时候影响收入或利润，以及股价有没有作出明显反应。

数字不能单独列成“关键数字”。数字必须放进解释中。例如：“32只农业相关股票中有30只最近都在上涨，说明这次上涨不是一两只龙头硬拉出来的。”

说明前面已经涨了多少时，不使用“剩余路径”。直接回答：“前面已经涨得多不多，接下来还有什么理由支持继续上涨。”

风险部分直接回答“最需要担心什么”。资料没有取得时写“这部分资料暂时不完整”，不能把资料缺失冒充公司经营风险。

最终文字不得使用以下词语：
扩散、传播、传导、市场识别、个股需求、需求背景、共振、超额、量价确认、路径、剩余路径、发动机、反证、关键未知、正贡献、有效成员、行动条件、透支、逻辑。

内部 JSON 和 Skill 可以保留这些专业含义，但最终发给用户的正文不能出现。
```

### 必须加入错误与正确示例

```markdown
错误：
“农业主题近3日和5日形成广泛扩散，正贡献前三只占比较低。”

正确：
“32只农业相关股票中，最近3天和5天都有30只上涨，而且涨幅没有集中在最强的三只股票上。这说明农业方向是整体转强，不是一两只股票单独拉升。”

错误：
“市场识别已经形成，个股需求强于行业。”

正确：
“这只股票最近5天上涨15.27%，比大多数同行更强，成交额也比过去20天平均水平高出一倍多。它不是只跟着农业板块小幅上涨，而是自己也明显走强。”

错误：
“为什么还可能有路径。”

正确：
“前面虽然已经上涨，但接下来还有没有继续上涨的理由。”

错误：
“最强反证是涨停贡献较高。”

正确：
“最近一周大约三分之二的涨幅来自那一个涨停日。若之后几个正常交易日不能继续上涨，这轮行情可能只是一次短促冲高。”
```

### 新荐股最终格式

```markdown
## 今天明确推荐的股票

| 顺序 | 股票 | 为什么会选它 | 最需要担心什么 |
|---:|---|---|---|

### 1. 股票名称（代码）

**公司主要做什么**

一段自然介绍。

**这次为什么会选它**

把行业、公司和股票自己的事实连起来讲，不讲内部方法。

**股价已经怎么走**

把3—5个必要数字放入句子，并解释每个数字意味着什么。

**最需要担心什么**

已知风险、资料不足和接下来几天应观察的现象。
```

每只建议250—450个中文字。不要为了字数重复同一观点。

---

## Task 4：同步修改总控和公司 Skill 的用户表达要求

### 总控 Skill

修改：

```text
.agents/skills/orchestrating-stock-research/SKILL.md
```

保留内部因果链和选股方法，但将“名单冻结后的用户解释”改成：

```markdown
## 名单冻结后的用户说明

正式名单和顺序确定后，只把已有研究改写成用户能直接理解的说明。这个步骤不解释内部研究规则，不得重新选择股票。

最终说明只回答：

- 公司主要做什么；
- 这次为什么会选它；
- 它最近的股价和成交具体怎么变化；
- 它为什么不只是被大盘或行业带着上涨；
- 前面已经涨得多不多，接下来还有什么事实可能支持继续上涨；
- 最需要担心什么。

不要向用户使用“扩散、传播、传导、市场识别、个股需求、量价确认、路径、发动机、反证、关键未知”等内部词语。把统计字段换成实际数量和普通中文。

例如，不说“行业扩散成立”，要说“这个行业大多数股票都在上涨”；不说“个股超额明显”，要说“它比同行多涨了多少”；不说“剩余路径仍在”，要说“前面已经涨了多少，接下来还有什么继续上涨的理由”。

公司简介只帮助用户理解公司，不得反过来改变名单和排序。
```

### 公司 Skill

修改：

```text
.agents/skills/researching-company-events/SKILL.md
```

将最终公司介绍要求改成：

```markdown
最终给用户介绍公司时，只说：

1. 公司主要卖什么产品或提供什么服务；
2. 客户在什么场景使用；
3. 本次推荐所依据的行业变化或公司消息，和哪块业务直接相关。

不向用户写“主营联系、材料性、传导、事件阶段”等内部判断词。直接说事实，例如“公司主要生产大中型拖拉机，这次农业机械方向转强与它的核心业务直接相关”。

资料不全时只说哪份资料暂时没有取得。不要把“未取得中报三表”写成公司风险，也不要用“无关概念标签”这样的解释。
```

---

## Task 5：用一拖股份生成真实验收样例

创建：

```text
research/skill-optimization/plain-language-recommendation-review-20260902/one-tuo-recommendation.md
```

这是同一份已冻结选择的表达改写，不重新选股。

固定使用用户提供的事实：

```text
股票：一拖股份（601038.SH）
上证农业主题：32只有效股票
近3日上涨：30只
近5日上涨：30只
涨幅最强三只股票对主题上涨的贡献：27.76%
一拖股份近5日上涨：15.27%
成交额：约为近期平均水平2.24倍
一季度：收入、利润、经营现金流同比均改善
价格位置：接近近60日高位
最近5日上涨中约67.37%来自涨停日
```

公司介绍只读取本地 `company_profile` 和 `main_business`，不联网。

样例必须写成普通中文，至少讲清：

```text
一拖股份主要生产什么
为什么农业方向这次不是只有少数股票上涨
为什么在农业股票里会选到一拖股份
15.27%和2.24倍分别意味着什么
一季度经营改善提供什么支持
为什么涨停日贡献67.37%是当前最大风险
接下来几个正常交易日看什么
```

样例正文不得出现：

```text
扩散
传播
传导
市场识别
个股需求
需求背景
共振
超额
量价确认
路径
剩余路径
发动机
反证
关键未知
正贡献
有效成员
行动条件
透支
逻辑
```

推荐表达应接近：

```text
32只农业相关股票中，最近3天和5天都有30只上涨，而且最强的三只股票只贡献了不到三成涨幅。这说明这次不是几只热门股把整个农业方向拉起来，而是大多数农业股票都在转强。

一拖股份主要生产拖拉机等农业机械，业务与农业机械需求直接相关。它最近5天上涨15.27%，成交额约为过去20天平均水平的2.24倍，说明股票明显活跃起来。公司一季度收入、利润和经营现金流都比上年同期改善，也给这次上涨提供了一定经营基础。

最需要担心的是，最近一周大约三分之二的涨幅来自那一个涨停日，而且股价已经接近近60天高位。接下来若不靠涨停也能继续上涨，成交增加后收盘仍然稳，说明行情可能延续；若高开后快速回落，或者成交很大却不再上涨，就说明短期涨得过快。
```

不必逐字复制，但必须达到同等可读性。

---

# 第三阶段：正式推荐复盘只展示明确推荐过的股票

## Task 6：重写复盘 Prompt 的用户问题

修改：

```text
ops/forward-monitor-prompt.md
```

内部 `DailyForwardMonitorReportV2` 继续保存所有推荐、比较、待确认事件和内部提醒，不改 schema。

最终用户复盘只回答：

```text
当初为什么推荐
→ 推荐后实际怎么走
→ 最近发生了什么
→ 为什么今天要说它
→ 当初看中的原因现在还在不在
→ 接下来几天看什么
```

加入以下明确要求：

```markdown
“正式推荐股票的走势复盘”只能出现被明确正式推荐过的股票。

允许展示：
- `confirmed_active`
- 历史上明确正式推荐、但无法无损重建V4分类的 `legacy_v1_not_rewritten`

禁止展示：
- `conditional_event`
- comparator
- nearest_nonselection
- rejected
- unresolved
- 普通观察股
- 内部关注股

待确认事件可以保留在内部日报，但不得出现在“正式推荐股票的走势复盘”中，也不得单列给用户凑内容。

每只股票先说明当初为什么推荐，再说明从推荐日开始实际涨跌、期间最高和最深回落。随后说明最近发生的新公告、停牌、行业变化或股价变化，以及今天为什么需要重新说到它。

不要写“原逻辑得到部分支持”“传播链减弱”“价格确认不足”“进入某状态”。改成普通中文：
- “当初看中的上涨原因还在，但力度比刚推荐时弱了。”
- “股价已经跌回前期高点下方，说明上次突破没有站稳。”
- “公司有新公告，但股票停牌，没有新的价格可以判断。”
- “今天提到它，是因为公司发布了控制权变更公告。”
- “今天到了推荐后的第5个交易日，按原计划检查一次。”
```

面向用户不展示比较股名称，也不显示“还有多少内部股票未展开”。

---

## Task 7：最小修改 `forward_monitor.py` 的用户 Markdown

修改：

```text
src/stock_analyzer/ops/forward_monitor.py
```

### 不修改

- `DailyForwardMonitorReportV2`
- JSON保存内容
- snapshot内容
- attention计算
- comparator内部记录
- conditional内部记录
- D20冻结
- `RecordSummary`
- 数据schema

### 只修改 `_render_markdown()` 的用户显示

在常量区增加：

```python
PUBLIC_FORMAL_OUTPUT_CLASSES = frozenset(
    {"confirmed_active", "legacy_v1_not_rewritten"}
)
```

增加一个小函数：

```python
def _public_formal_episode_ids(
    alert: ForwardMonitorAlertV2,
    episodes: dict[str, dict[str, Any]],
) -> list[str]:
    return [
        episode_id
        for episode_id in alert.episode_ids
        if episode_id in episodes
        and _episode_selection_output_class(episodes[episode_id])
        in PUBLIC_FORMAL_OUTPUT_CLASSES
    ]
```

在 `_render_markdown()` 中先构造：

```python
public_alerts = [
    (alert, _public_formal_episode_ids(alert, episodes))
    for alert in report.alerts
]
public_alerts = [
    (alert, episode_ids)
    for alert, episode_ids in public_alerts
    if episode_ids
]
```

然后执行以下改动：

1. 只遍历 `public_alerts`；
2. 每只股票只遍历过滤后的正式推荐 `episode_ids`；
3. 不渲染 `conditional_event`；
4. 不渲染 comparator；
5. 不渲染“和当时最接近的备选相比”；
6. 不展示 conditional 数量；
7. 不展示 `unreported_attention_count`；
8. 不展示“今天没有详细展开的股票”；
9. 内部 JSON 仍完整保存上述内容；
10. Markdown标题改为：

```text
正式推荐股票的走势复盘
```

### 每只股票的 Markdown 固定为

```markdown
### 股票名称（代码）

**当初为什么推荐**

<原推荐原因和当时最需要担心的事，普通中文>

**推荐后怎么走**

<从推荐日开始的实际涨跌、最高上涨、最深下跌；只保留真正需要的数字>

**最近发生了什么，为什么今天提到它**

<先写 why_reported 的普通中文，再写与本次判断有关的公司、行业或股价变化；不要机械分成“市场方面、行业方面、公司方面、个股方面”>

**现在怎么看**

<用 current_review 为主；只保留一句普通判断，不逐项朗读内部分类>

**接下来关注什么**

<接下来几天看到什么说明改善，看到什么说明当初看中的原因已经明显减弱>
```

### 简化当前结论

不要在用户 Markdown 中依次拼接：

```text
current_assessment
current_weak_or_failed_link
best_supported_explanation
current_review
```

这些内部字段继续保存在 JSON。

用户 Markdown 只输出：

```python
current = review.current_review
```

如果确实需要一句前置结论，只使用下面的人话映射：

```python
assessment_labels = {
    "not_yet_tested": "推荐时间还短，现在下结论还早",
    "partly_supported": "当初看中的原因还有一部分成立",
    "supported": "后来的走势目前支持当初推荐",
    "weakening": "当初看中的原因正在减弱",
    "contradicted": "后来的走势已经不支持当初推荐",
    "insufficient_evidence": "现在掌握的资料还不足以判断",
}
```

不得把 `weak_labels` 和 `explanation_labels` 逐句打印给用户。

### 没有正式推荐需要复盘时

输出：

```text
今天没有被明确推荐过、同时又出现需要说明变化的股票。
```

不要用待确认事件、比较股或内部关注股填充。

---

## Task 8：复盘验收样例

创建：

```text
research/skill-optimization/plain-language-recommendation-review-20260902/formal-review-sample.md
```

使用用户提供的当天材料，但只展示明确正式推荐：

```text
应展示：
- 华昌化工
- 金岭矿业
- 中信银行

不得展示：
- 丽珠集团
```

原因：丽珠集团是待确认事件，不属于明确正式推荐的复盘范围。

样例每只股票按以下顺序自然说明：

```text
当初为什么推荐
推荐后怎么走
最近发生了什么
为什么今天提到它
现在怎么看
接下来关注什么
```

不得写：

```text
原逻辑
传播链
价格确认
部分支持
弱环节
状态
检查点
```

可以写：

```text
华昌化工今天需要说明，是因为公司出现控制权变更、股份转让和复牌安排。股票仍在停牌，没有新的成交价格，因此现在不能说当初推荐对了或错了。复牌后先看能否正常成交，以及收盘能否站稳。

金岭矿业从推荐日算起仍有小幅上涨，但股价已经回到此前高点下方，说明上次突破没有完全站稳。今天提到它，是因为最近相对大盘的优势还在，但力度变弱。接下来若重新站上前高并保持成交，情况会改善；若继续落后同行，当初看中的强势就会进一步减弱。
```

不必逐字复制，但必须达到同等可读性。

---

# 第四阶段：测试

## Task 9：更新 Prompt 测试

### `tests/test_v4_operational_prompts.py`

调整昨天新增的测试，使其要求新的自然栏目，而不是继续要求：

```text
为什么偏偏是现在
为什么不是普通跟涨
关键数字说明什么
为什么还可能有路径
```

增加断言：

```python
def test_recommendation_prompt_uses_fact_first_plain_language() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "公司主要做什么",
        "这次为什么会选它",
        "股价已经怎么走",
        "最需要担心什么",
        "32只农业相关股票中",
        "先说事实",
    ):
        assert phrase in prompt

    for old_heading in (
        "为什么偏偏是现在",
        "为什么不是普通跟涨",
        "关键数字说明什么",
        "为什么还可能有路径",
    ):
        assert old_heading not in prompt
```

不要扫描所有 Skill 中的内部专业词。只检查用户输出段。

### `tests/test_forward_monitor_prompt.py`

增加：

```python
def test_public_review_only_lists_explicit_formal_recommendations() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    assert "正式推荐股票的走势复盘" in text
    assert "confirmed_active" in text
    assert "legacy_v1_not_rewritten" in text
    assert "conditional_event" in text
    assert "不得出现在“正式推荐股票的走势复盘”中" in text
    assert "为什么今天要说它" in text
    assert "不得单列给用户凑内容" in text
```

---

## Task 10：更新 `forward_monitor.py` 测试

修改既有 Markdown 测试的旧预期：

```text
之前研究过的股票走势复盘
和当时最接近的备选相比
等待首个交易日确认的事件线索
用于比较的股票
今天没有详细展开的股票
```

这些都不应再出现在最终用户 Markdown。

至少增加以下测试。

### 1. conditional内部保留、用户Markdown隐藏

```python
def test_public_markdown_hides_conditional_event_but_keeps_internal_json(
    tmp_path: Path,
) -> None:
    # 沿用现有 conditional fixture 生成 snapshot/report。
    # JSON中仍有 conditional alert 和 episode review。
    # Markdown中不出现该股票名称，也不出现“等待首个交易日确认”。
    # Markdown明确说明今天没有需要复盘的正式推荐股票。
```

必须断言：

```python
assert saved["alerts"]
assert "丽珠集团" not in markdown
assert "等待首个交易日确认" not in markdown
assert "今天没有被明确推荐过" in markdown
```

测试可使用现有测试股票名称，不必强行使用丽珠集团；但语义必须一致。

### 2. comparator内部保留、用户Markdown隐藏

```python
def test_public_markdown_hides_comparator_episode(
    tmp_path: Path,
) -> None:
    # JSON保留 selected + comparator。
    # Markdown只展示正式推荐记录。
```

断言：

```python
assert saved["alerts"][0]["roles"] == ["selected", "comparator"]
assert "用于比较的股票" not in markdown
assert "和当时最接近的备选相比" not in markdown
assert "当时备选股" not in markdown
```

### 3. 只有比较股时不显示股票

```python
def test_public_markdown_does_not_use_internal_attention_to_fill_content(
    tmp_path: Path,
) -> None:
    # 构造只有 comparator 或 conditional 被提醒的报告。
    # Markdown不得出现股票名。
```

### 4. 正式推荐复盘使用新的自然顺序

断言包含：

```text
当初为什么推荐
推荐后怎么走
最近发生了什么，为什么今天提到它
现在怎么看
接下来关注什么
```

断言不包含：

```text
市场方面
行业方面
公司方面
个股方面
原判断仍有部分支持
原逻辑
传播链
价格确认
弱环节
状态
```

不要增加新的测试框架或语言评分器。

---

# 第五阶段：真实运行验证

## Task 11：定向测试

运行：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py
```

## Task 12：完整测试

```bash
./.venv/bin/python -m pytest -q
git diff --check
```

完整测试数不得少于基线，且不得删除测试来获得通过。

## Task 13：人工阅读两个样例

完整阅读：

```text
one-tuo-recommendation.md
formal-review-sample.md
```

确认：

- 一拖股份说明中没有内部研究术语；
- 能直接看懂32只中30只上涨意味着什么；
- 能直接看懂15.27%、2.24倍和67.37%分别意味着什么；
- 复盘中没有丽珠集团；
- 每只复盘都说明为什么今天会重新提到它；
- 复盘重点是股票发生了什么，而不是规则是否通过。

再运行简单结构检查：

```bash
./.venv/bin/python - <<'PY'
from pathlib import Path

root = Path(
    "research/skill-optimization/"
    "plain-language-recommendation-review-20260902"
)
recommendation = (root / "one-tuo-recommendation.md").read_text(encoding="utf-8")
review = (root / "formal-review-sample.md").read_text(encoding="utf-8")

forbidden_user_terms = (
    "扩散", "传播", "传导", "市场识别", "个股需求", "需求背景",
    "共振", "超额", "量价确认", "剩余路径", "发动机", "反证",
    "关键未知", "正贡献", "有效成员", "行动条件", "透支", "逻辑",
)
for term in forbidden_user_terms:
    assert term not in recommendation, (term, "one-tuo")
    assert term not in review, (term, "review")

for required in ("32只", "30只", "15.27%", "2.24", "67.37%"):
    assert required in recommendation, required

for name in ("华昌化工", "金岭矿业", "中信银行"):
    assert name in review, name
assert "丽珠集团" not in review

print("plain-language samples: PASS")
PY
```

这只检查两个人工样例，不对所有未来自然语言建立正则Gate。

---

# 第六阶段：提交、推送和实际每日任务部署

## Task 14：提交 feature branch

```bash
git add \
  docs/2026-09-02-plain-language-recommendation-review-prompt.md \
  ops/forward-selection-prompt.md \
  ops/forward-monitor-prompt.md \
  .agents/skills/orchestrating-stock-research/SKILL.md \
  .agents/skills/researching-company-events/SKILL.md \
  src/stock_analyzer/ops/forward_monitor.py \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py \
  research/skill-optimization/plain-language-recommendation-review-20260902

git commit -m "fix: make recommendation and review output user-readable"
```

检查：

```bash
git status --short
git log --oneline --decorate -3
```

推送：

```bash
git push -u origin codex/plain-language-recommendation-review-20260902
```

核对：

```bash
FEATURE_HEAD="$(git rev-parse HEAD)"
REMOTE_FEATURE_HEAD="$(
  git ls-remote \
    --heads origin \
    codex/plain-language-recommendation-review-20260902 \
  | awk '{print $1}'
)"

test "$FEATURE_HEAD" = "$REMOTE_FEATURE_HEAD"
```

---

## Task 15：让实际每日任务真正使用新版本

这一步不能再次省略。

回到第一阶段识别出的：

```text
TASK_ROOT
```

先检查：

```bash
git -C "$TASK_ROOT" status --short
git -C "$TASK_ROOT" branch --show-current
git -C "$TASK_ROOT" rev-parse HEAD
```

如果工作区干净，并且当前运行分支是 feature branch 的祖先：

```bash
git -C "$TASK_ROOT" merge-base --is-ancestor \
  HEAD \
  "$FEATURE_HEAD"
```

则在实际运行分支做**仅快进更新**：

```bash
RUNTIME_BRANCH="$(git -C "$TASK_ROOT" branch --show-current)"

git -C "$TASK_ROOT" fetch origin
git -C "$TASK_ROOT" merge --ff-only "$FEATURE_HEAD"
git -C "$TASK_ROOT" push origin "$RUNTIME_BRANCH"
```

不得 `reset --hard`，不得 force push。

如果每日任务本身固定绑定某个 worktree，应把任务工作目录改为这次已经通过测试的 worktree，而不是只在另一个目录提交后结束。

部署后必须验证：

```bash
git -C "$TASK_ROOT" rev-parse HEAD

grep -F "32只农业相关股票中" \
  "$TASK_ROOT/ops/forward-selection-prompt.md"

grep -F "不得出现在“正式推荐股票的走势复盘”中" \
  "$TASK_ROOT/ops/forward-monitor-prompt.md"

grep -F "PUBLIC_FORMAL_OUTPUT_CLASSES" \
  "$TASK_ROOT/src/stock_analyzer/ops/forward_monitor.py"
```

将实际部署后的：

```text
TASK_ROOT
运行分支
部署前HEAD
部署后HEAD
```

补入：

```text
runtime-diagnosis.md
```

再提交这份补充记录到 feature branch；如果实际运行分支与 feature branch相同，直接提交并推送即可。若不同，只在 feature branch保存一份报告副本，不制造重复功能提交。

如果实际每日任务目录有用户未提交改动，不覆盖。使用本次 feature worktree作为新的任务目录，并修改Scheduled Task的工作目录；如果当前Codex环境无法修改Scheduled Task设置，必须在最终汇报中明确给出需要用户操作的准确路径，不能声称已经部署。

---

# 第七阶段：最终检查

运行：

```bash
git diff --check
./.venv/bin/python -m pytest -q
git status --short

git diff --stat \
  36636cc9f80a1b568a6926d9395cf82f8ab58887...HEAD

git diff --name-only \
  36636cc9f80a1b568a6926d9395cf82f8ab58887...HEAD
```

允许出现的文件只能来自本文件“允许修改”清单。

确认：

- 没有修改选股规则；
- 没有修改 active/conditional；
- 没有修改 D20；
- 没有新增 schema；
- 内部 JSON仍保存 conditional和comparator；
- 用户 Markdown只显示正式推荐；
- 实际每日任务目录已经包含最终提交；
- 一拖股份样例是普通中文；
- 复盘样例不含丽珠集团。

---

# 八、最终汇报格式

```markdown
已完成：每日荐股与正式推荐复盘人话修复

## GitHub
- 基线：`36636cc9f80a1b568a6926d9395cf82f8ab58887`
- feature分支：`codex/plain-language-recommendation-review-20260902`
- feature最终提交：`<HEAD>`
- 分支链接：<URL>
- 对比链接：<URL>
- 一拖股份样例：<URL>
- 正式复盘样例：<URL>
- 运行目录诊断：<URL>

## 根因
- 今天荐股未使用昨天格式的原因：<实际目录、分支和HEAD>
- 丽珠集团混入正式复盘的原因：<说明Markdown此前遍历全部alert>

## 实际修改
- 新荐股说明：<如何从内部术语改成事实解释>
- 正式推荐复盘：<如何只显示明确推荐>
- 内部记录：<说明JSON仍完整>
- 代码：<说明只改Markdown渲染>
- 测试：<新增或调整哪些行为>

## 实际每日任务部署
- TASK_ROOT：`<路径>`
- 运行分支：`<分支>`
- 部署前HEAD：`<提交>`
- 部署后HEAD：`<提交>`
- 是否已包含feature最终提交：是/否
- Scheduled Task是否已指向该目录：是/否

## 样例检查
- 一拖股份是否出现“扩散、传播、路径、市场识别”等词：否
- 是否解释32只中30只上涨：是
- 是否解释15.27%、2.24倍和67.37%：是
- 正式复盘是否只含明确推荐：是
- 丽珠集团是否已从正式复盘消失：是
- 是否说明每只股票为什么今天被复盘：是

## 验证
- 基线定向测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- 样例检查：<结果>
- `git diff --check`：<结果>
- feature本地/远端HEAD一致：是/否
- 实际每日任务版本已更新：是/否
- 工作区干净：是/否

## 明确未做
- 未重新选股
- 未修改五个Skill的选股逻辑
- 未修改active/conditional
- 未修改D20和11个价格场景
- 未新增schema、数据库、数据源、评分器或平台
- 未用待确认事件和比较股填充正式复盘
```

只有以下条件全部满足，才可以声称完成：

```text
代码和Prompt修改通过完整测试
+
feature分支已经上传GitHub
+
一拖股份样例真正可读
+
正式复盘样例不含丽珠集团
+
实际每日任务工作目录已经使用最终版本
```
