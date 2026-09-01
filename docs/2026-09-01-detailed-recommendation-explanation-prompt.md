# 正式推荐股票详细说明优化——Codex执行指令 V1.0

> 本任务是一次**用户输出解释优化**。  
> 已完成的五个 Skill 选股逻辑、正式推荐与待确认事件的区分、D20口径均不得重做。  
> Codex必须直接执行本文件，不得将任务扩大成新的选股调优、schema改造、报告平台或安全工程。

---

## 一、仓库与分支

### 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

### 唯一基线分支

```text
codex/five-skill-selection-logic-optimization-20260901
```

### 唯一基线提交

```text
05e1788f8457f00eccbafd0b55a276a6acf18fc9
```

### 新分支

```text
codex/detailed-recommendation-explanation-20260901
```

### 建议 worktree

```text
.worktrees/detailed-recommendation-explanation-20260901
```

从仓库根目录执行：

```bash
git fetch origin
git worktree add \
  .worktrees/detailed-recommendation-explanation-20260901 \
  -b codex/detailed-recommendation-explanation-20260901 \
  05e1788f8457f00eccbafd0b55a276a6acf18fc9

cd .worktrees/detailed-recommendation-explanation-20260901

git rev-parse HEAD
git branch --show-current
git status --short
```

必须得到：

```text
05e1788f8457f00eccbafd0b55a276a6acf18fc9
codex/detailed-recommendation-explanation-20260901
空工作区
```

如基线不一致，停止，不得自行换成 `main` 或其他提交。

将本文件原样保存为：

```text
docs/2026-09-01-detailed-recommendation-explanation-prompt.md
```

---

## 二、唯一目标

保留现有选股名单、顺序、内部分类和形成日判断，只优化给用户看的正式推荐说明，使普通用户能够理解：

1. 这家公司主要做什么；
2. 为什么偏偏是现在进入推荐；
3. 这次上涨是市场普涨、板块共同上涨，还是股票自身更强；
4. 关键价格和成交数字分别说明什么；
5. 为什么认为后面仍可能有上涨路径；
6. 已知的不利事实是什么；
7. 哪些只是本地资料不足，不能冒充公司风险；
8. 下一个交易日看什么，能够增强或削弱原判断。

最终输出不能再只有一张“核心依据/最强反证”的简表。

---

## 三、任务边界

### 本轮允许修改

只在确有必要时修改：

```text
ops/forward-selection-prompt.md
.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/researching-company-events/SKILL.md
tests/test_v4_operational_prompts.py
docs/2026-09-01-detailed-recommendation-explanation-prompt.md
research/skill-optimization/detailed-recommendation-explanation-20260901/
```

### 本轮禁止修改

不得修改：

```text
src/stock_analyzer/ops/forward_selection.py
src/stock_analyzer/ops/forward_monitor.py
docs/architecture/a-share-short-horizon-engine-contract-v4.md
.agents/skills/interpreting-market-macro/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md
tools/
数据库、数据schema、数据采集、定时任务
```

也不得：

- 改变现有4只股票及其顺序；
- 重跑或重新设计选股逻辑；
- 增加字段、Pydantic模型、数据库表或持久化状态；
- 增加评分器、字数评分、人话评分模型；
- 增加新数据源；
- 联网补公司介绍；
- 修改七种发动机、四种状态、11个价格场景；
- 修改 active/conditional 的现有语义；
- 修改D20、入口价格、跟踪或收益口径；
- 增加第六个 Skill；
- 启动子智能体。

这属于纯文档、措辞和测试补充，不改变正式研究结论，不需要独立审查子智能体。

---

## 四、开始前读取

完整读取：

```text
AGENTS.md
ops/forward-selection-prompt.md
.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/researching-company-events/SKILL.md
tests/test_v4_operational_prompts.py
```

同时确认本地已有公司资料能力：

```text
company_profile
main_business
income_statement
cash_flow
financial_indicator
```

公司介绍只使用现有本地资料，不新增来源。

运行基线测试：

```bash
./.venv/bin/python -m pytest -q tests/test_v4_operational_prompts.py
```

记录真实结果。

---

# 五、具体修改

## Task 1：修改每日推荐 Prompt

文件：

```text
ops/forward-selection-prompt.md
```

找到当前“今天已确认的正式推荐怎么写”及其附近对外输出要求，保留现有 active/conditional 分流规则，但将正式推荐部分改成下面的完整要求。

### 必须加入的正文

```markdown
### 今天已确认的正式推荐怎么写

汇总表只能作为目录，不能代替逐只说明。只要当天存在已确认正式推荐，必须先给一张简明汇总表，再按优先顺序逐只写完整说明；不得只输出股票名称、核心依据和最强反证。

名单、顺序和内部研究结论在生成用户说明前已经冻结。下面的解释步骤只负责把已有研究讲清楚，不得新增候选、删除股票、改变顺序、改写形成日理由或重新运行选股。

对每只正式推荐股票，使用自然中文讲清以下内容：

1. **公司是做什么的**：用80—150字说明核心产品或服务、主要应用场景，以及本次研究关注的板块或变化对应公司哪块真实业务。公司成立年份、注册地址、管理层履历和无关概念标签不写。
2. **为什么偏偏是现在**：说明近期真正出现了什么新增变化或需求，为什么不是长期不变的公司介绍，也不是因为“业绩不错、位置较低”就推荐。
3. **为什么不是普通跟涨**：区分大盘共同变化、所属行业共同变化和股票自身增量。板块型股票要说明板块为什么是真扩散以及该股为何强于普通成员；独立价格型股票要说明多日连续性为何不是单日脉冲；公司事件型股票要说明事件如何传导并且价格是否已经认可。
4. **关键数字说明什么**：每只只保留3—5个真正改变判断的数字。每出现一个涨幅、相对收益、成交额比、现金流或位置数字，必须紧接着解释这个数字意味着什么，不能用一串数字代替结论。
5. **为什么还可能有路径**：综合近期3日、5日、20日涨幅，最大单日贡献，成交是否持续推动收盘，行业动力是否仍在以及公司经营支撑来说明。不得只用“低位”“没有涨停”“距离目标还有若干ATR”证明空间。
6. **最大风险和下一步观察**：分开写“已知的不利事实”和“资料限制”。公司现金流恶化、利润下降、上涨过度集中等属于不利事实；本地没有取得中报三表、公告正文不完整属于资料限制，不能冒充公司本身的风险。最后用人话说明下一个交易日看到什么会增强原判断，看到什么会说明正在变差。

每只股票建议300—500个中文字。可以使用清楚的小标题，但不能把内部字段和值逐项翻译成模板。四只股票不能套用完全相同的句子；如果一句话原封不动换个股票名称仍成立，就要重写。

最终报告不得出现 `engine_type`、`engine_status`、`market_recognition`、`decision_trace`、`formation_date`、`action_date` 等内部字段名，也不得写“系统检测到”“模型触发”“根据规则进入某状态”。

推荐说明可以解释“为什么这只股票自身更强”，但最终对外不必点名全部落选股。公司介绍只是帮助用户认识公司，不能反过来成为新的入选理由。
```

### 汇总表固定格式

正式推荐存在时，汇总表使用：

```markdown
| 顺序 | 股票 | 这次主要看中的原因 | 最大已知风险或资料限制 |
|---:|---|---|---|
```

“已知风险”和“资料限制”在详细说明中必须分开；汇总表可合并成一列，但文字要标明是哪一类。

---

## Task 2：修改总控 Skill

文件：

```text
.agents/skills/orchestrating-stock-research/SKILL.md
```

在“作出最终取舍”之后、“Review阶段”之前加入以下小节。

```markdown
## 名单冻结后的用户解释

正式名单和顺序确定后，再进行一次只读的用户解释整理。这个步骤不属于候选发现或重新取舍，不得新增、删除、替换、重新排序股票，也不得修改冻结 trace。

只对最终派生为 `confirmed_active` 的0—5只股票整理说明。使用已冻结的：

- `catalyst` 和 `short_term_engine` 解释为什么是现在；
- `propagation` 和板块证据解释推动怎样传到股票；
- `price_confirmation` 解释价格和成交是否认可；
- `remaining_path` 解释此前消耗和后续路径；
- `fundamental_anchor` 解释经营支撑；
- `company_risk` 解释已知公司风险；
- `critical_unknown` 和原行动条件解释下一步看什么；
- `nearest_comparison` 只用于提炼这只股票自身胜在哪里，对外不必点名全部落选股。

公司基本介绍使用现有 `company_profile` 和 `main_business`。必要时让公司 Skill 对最终名单做一次只读补充，只回答“公司做什么”和“本次逻辑对应哪块业务”，不得重新扫描市场、产生新候选或改变已有结论。

最终对外输出先给简明汇总表，再逐只说明。每只必须讲清公司业务、为什么是现在、为什么不只是普通跟涨、关键数字的含义、剩余路径、已知风险、资料限制和下一步观察。汇总表不能代替逐只说明。
```

同时将文件中原来的：

```text
每日给用户的合并报告必须使用通俗中文。新推荐股票只回答……
```

调整为：

```text
每日给用户的合并报告必须使用通俗中文，并按照“名单冻结后的用户解释”生成。汇总表只能作为目录，不能代替逐只说明。
```

不要删除原有选股因果链、同发动机比较、停止补位和 active/conditional 规则。

---

## Task 3：修改公司 Skill

文件：

```text
.agents/skills/researching-company-events/SKILL.md
```

在“验证阶段”之后、“Review阶段”之前加入：

```markdown
## 最终名单的公司介绍补充

当总控已经冻结正式名单并只要求对外解释时，本 Skill 可以对最终入选股票补充一段简明公司介绍。这个动作只服务于用户理解，不属于再次发现或验证，不得改变候选、排序、发动机、价格判断或形成日结论。

只使用现有本地 `company_profile`、`main_business` 和形成日已经使用的公司事实，回答两件事：

1. 公司主要卖什么产品或提供什么服务，客户或应用场景是什么；
2. 本次推荐所依赖的板块、事件或价格需求，对应公司哪一块真实业务。

介绍控制在80—150个中文字，不写公司沿革、注册地址、管理层履历和无关概念标签。没有新公司事件的价格型候选，要明确说“本次入选不依赖新的公司公告，公司业务和财务只作为经营背景”。

资料缺失和公司风险必须分开。没有取得中报三表、公告正文或主营细分，只能写“暂时无法完整核实”，不能写成公司经营一定恶化；利润下降、现金流恶化、合同兑现周期长等已知事实才属于公司风险。

公司介绍不能被总控当成新的入选理由，也不能因为某家公司介绍更完整就提高优先级。
```

不要新增输出字段或修改V4 schema。

---

## Task 4：增加轻量测试

文件：

```text
tests/test_v4_operational_prompts.py
```

在文件末尾增加以下测试：

```python
def test_detailed_recommendation_explanation_is_required_after_selection_freeze() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    orchestrator = Path(
        ".agents/skills/orchestrating-stock-research/SKILL.md"
    ).read_text(encoding="utf-8")
    company = Path(
        ".agents/skills/researching-company-events/SKILL.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "汇总表只能作为目录",
        "公司是做什么的",
        "为什么偏偏是现在",
        "为什么不是普通跟涨",
        "关键数字说明什么",
        "为什么还可能有路径",
        "已知的不利事实",
        "资料限制",
        "下一个交易日",
        "每只股票建议300—500个中文字",
    ):
        assert phrase in prompt

    for phrase in (
        "名单冻结后的用户解释",
        "不得新增、删除、替换、重新排序股票",
        "company_profile",
        "main_business",
        "汇总表不能代替逐只说明",
    ):
        assert phrase in orchestrator

    for phrase in (
        "最终名单的公司介绍补充",
        "只服务于用户理解",
        "公司主要卖什么产品或提供什么服务",
        "资料缺失和公司风险必须分开",
        "不能被总控当成新的入选理由",
    ):
        assert phrase in company
```

不得增加自然语言评分器、正则字数Gate或新的测试框架。

先运行该测试并确认修改前失败；完成三处文档修改后再次运行并确认通过：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_v4_operational_prompts.py
```

---

# 六、用现有四只股票生成真实示例报告

创建目录：

```text
research/skill-optimization/detailed-recommendation-explanation-20260901/
```

创建：

```text
research/skill-optimization/detailed-recommendation-explanation-20260901/sample-report.md
```

这不是新一轮选股，不重新判断名单。固定使用以下结果和顺序：

| 顺序 | 股票 | 已冻结的主要证据 | 已知问题 |
|---:|---|---|---|
| 1 | 瑞丰新材 300910.SZ | 化学制品连续扩散；5日+15.68%；相对行业+11.40%；5日均上涨；成交额比1.44；无涨停脉冲 | 本地未取得2026年中报三表，这是资料限制，不是公司风险 |
| 2 | 鸣志电器 603728.SH | 电机行业持续扩散；5日+11.28%；相对行业+8.13%；5日均上涨；成交额比1.48；20日-0.60% | 最新中报财务覆盖不足，这是资料限制 |
| 3 | 汉得信息 300170.SZ | 3日/5日+12.91%/+12.98%；相对IT服务+9.08%/+7.43%；价格和成交确认仍有效 | 半年经营现金流降至-2.00亿元，这是已知公司风险 |
| 4 | 三一重工 600031.SH | 3日/5日+6.10%/+7.52%；相对工程机械+4.56%/+4.67%；成交额比2.30；半年收入和利润同比增长 | 形成日单日上涨占近期路径较高，这是价格路径风险 |

### 示例报告要求

`sample-report.md` 必须包括：

```markdown
# 最新正式推荐说明展示样例

## 简明汇总
<一张4行表格>

## 1. 瑞丰新材（300910.SZ）
### 公司是做什么的
### 为什么这次选它
### 关键数字说明什么
### 为什么还可能有路径
### 最大风险、资料限制和下一步观察

## 2. 鸣志电器（603728.SH）
...

## 3. 汉得信息（300170.SZ）
...

## 4. 三一重工（600031.SH）
...
```

公司介绍必须读取本地已有 `company_profile` 和 `main_business`。不得联网。

报告必须满足：

- 名单和顺序与上表完全一致；
- 每只约300—500个中文字；
- 每只只选3—5个关键数字；
- 每个数字后紧接人话解释；
- “数据缺失”不冒充“公司风险”；
- 不显示内部字段、英文状态或研究编号；
- 不写目标价、仓位、止盈止损；
- 不承诺收益；
- 不把公司简介写成新的推荐理由；
- 四只股票不能套用同一段模板。

报告开头写明：

```text
本页只展示同一份已冻结名单在新说明格式下的表达效果，不重新选择股票，也不使用后续行情改变原判断。
```

---

# 七、人工检查命令

生成报告后运行：

```bash
./.venv/bin/python - <<'PY'
from pathlib import Path

path = Path(
    "research/skill-optimization/"
    "detailed-recommendation-explanation-20260901/"
    "sample-report.md"
)
text = path.read_text(encoding="utf-8")

stocks = [
    "瑞丰新材（300910.SZ）",
    "鸣志电器（603728.SH）",
    "汉得信息（300170.SZ）",
    "三一重工（600031.SH）",
]
positions = [text.index(stock) for stock in stocks]
assert positions == sorted(positions), positions

required = [
    "公司是做什么的",
    "为什么这次选它",
    "关键数字说明什么",
    "为什么还可能有路径",
    "最大风险、资料限制和下一步观察",
]
for phrase in required:
    assert text.count(phrase) == 4, (phrase, text.count(phrase))

for forbidden in [
    "engine_type",
    "engine_status",
    "market_recognition",
    "decision_trace",
    "formation_date",
    "action_date",
    "系统检测到",
    "模型触发",
]:
    assert forbidden not in text, forbidden

print("sample report structure: PASS")
PY
```

该命令只检查结构，不评价文字好坏。之后必须人工完整阅读四只股票，确认：

- 能看懂公司做什么；
- 能看懂为什么是现在；
- 能看懂数字的意义；
- 能看懂已知风险与资料限制的区别；
- 能看懂下一交易日该观察什么。

如果仍然只是数字换行，必须重写样例，不要增加程序。

---

# 八、验证

运行定向测试：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_v4_operational_prompts.py \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py
```

运行完整测试：

```bash
./.venv/bin/python -m pytest -q
```

运行差异检查：

```bash
git diff --check
git status --short
git diff --stat 05e1788f8457f00eccbafd0b55a276a6acf18fc9...HEAD
git diff 05e1788f8457f00eccbafd0b55a276a6acf18fc9...HEAD -- \
  ops/forward-selection-prompt.md \
  .agents/skills/orchestrating-stock-research/SKILL.md \
  .agents/skills/researching-company-events/SKILL.md \
  tests/test_v4_operational_prompts.py \
  docs/2026-09-01-detailed-recommendation-explanation-prompt.md \
  research/skill-optimization/detailed-recommendation-explanation-20260901
```

核对没有任何 `src/`、`tools/`、数据库或其他 Skill 改动：

```bash
git diff --name-only 05e1788f8457f00eccbafd0b55a276a6acf18fc9...HEAD
```

允许出现的文件只有本文件和“任务边界”中列出的文件。

---

# 九、提交与推送

建议一个提交完成，不拆成大量小提交：

```bash
git add \
  docs/2026-09-01-detailed-recommendation-explanation-prompt.md \
  ops/forward-selection-prompt.md \
  .agents/skills/orchestrating-stock-research/SKILL.md \
  .agents/skills/researching-company-events/SKILL.md \
  tests/test_v4_operational_prompts.py \
  research/skill-optimization/detailed-recommendation-explanation-20260901/sample-report.md

git commit -m "docs: expand plain-language recommendation explanations"
```

再次验证：

```bash
git status --short
git rev-parse HEAD
./.venv/bin/python -m pytest -q
git diff --check
```

推送：

```bash
git push -u origin codex/detailed-recommendation-explanation-20260901
```

核对远端：

```bash
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(
  git ls-remote \
    --heads origin \
    codex/detailed-recommendation-explanation-20260901 \
  | awk '{print $1}'
)"

printf 'local : %s\nremote: %s\n' "$LOCAL_HEAD" "$REMOTE_HEAD"
test "$LOCAL_HEAD" = "$REMOTE_HEAD"
test -z "$(git status --short)"
```

不得合并 `main`。

---

# 十、最终汇报格式

```markdown
已完成：正式推荐股票详细说明优化

## GitHub
- 基线提交：`05e1788f8457f00eccbafd0b55a276a6acf18fc9`
- 分支：`codex/detailed-recommendation-explanation-20260901`
- 最终提交：`<HEAD>`
- 分支链接：<URL>
- 对比链接：<URL>
- 示例报告：<URL>

## 修改
- 每日推荐 Prompt：<具体变化>
- 总控 Skill：<具体变化>
- 公司 Skill：<具体变化>
- 测试：<具体变化>

## 示例结果
- 名单与顺序是否保持：是/否
- 瑞丰新材说明字数：<数字>
- 鸣志电器说明字数：<数字>
- 汉得信息说明字数：<数字>
- 三一重工说明字数：<数字>
- 已知风险与资料限制是否分开：是/否
- 是否仍只输出简表：是/否

## 验证
- 修改前定向测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- 样例结构检查：<结果>
- `git diff --check`：<结果>
- 工作区干净：是/否
- 本地/远端HEAD一致：是/否

## 明确未做
- 未改变4只股票或顺序
- 未修改选股逻辑和V4合同
- 未修改底层Python代码
- 未增加schema、数据源、评分器或平台
- 未修改11个价格场景
- 未修改active/conditional与D20口径
```

只有完整测试通过、样例报告已经人工读通、GitHub推送成功且远端HEAD一致，才可以声称完成。
