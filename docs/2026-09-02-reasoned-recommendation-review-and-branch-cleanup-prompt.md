# A股推荐理由、复盘分析、哈希减负与分支收口——Codex执行指令 V1.0

> **直接执行本文件，不要改写成泛化方案。**
>
> 本任务不是再次调整选股指标，也不是继续堆“说人话”的格式要求。真正目标是：
>
> 1. 让每只推荐股票都有一个完整的分析理由，而不是一串客观数据；
> 2. 让复盘说明“当初为什么推荐、后来事实为什么支持或否定了当初判断”；
> 3. 完成上一轮核查发现的少量一致性修复；
> 4. 将本轮改动合并到 `main`，清理已经进入 `main` 的旧远端分支；
> 5. 明确哈希只在真正有价值的地方保留，不再给普通文档和日常输出增加维护负担。
>
> 这是个人股票助手。禁止把任务扩大成评分平台、语言审计平台、复杂工作流或安全工程。

---

## 一、仓库与基线

### 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

### 唯一基线

```text
分支：main
提交：94955b91e1108948eef4df7b653c08c98e052b66
```

### 本轮功能分支

```text
codex/reasoned-recommendation-review-20260902
```

### 开始命令

在实际项目根目录执行：

```bash
git fetch origin --prune

test "$(git rev-parse origin/main)" = \
  "94955b91e1108948eef4df7b653c08c98e052b66"

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BASE_HEAD="$(git rev-parse origin/main)"

git worktree add \
  "$PROJECT_ROOT/.worktrees/reasoned-recommendation-review-20260902" \
  -b codex/reasoned-recommendation-review-20260902 \
  "$BASE_HEAD"

cd "$PROJECT_ROOT/.worktrees/reasoned-recommendation-review-20260902"

test "$(git rev-parse HEAD)" = "$BASE_HEAD"
test "$(git branch --show-current)" = \
  "codex/reasoned-recommendation-review-20260902"
test -z "$(git status --short)"
```

将本执行文件原样保存到：

```text
docs/2026-09-02-reasoned-recommendation-review-and-branch-cleanup-prompt.md
```

---

## 二、先理解最关键的问题

### 事实不等于推荐理由

以下内容都只是事实：

```text
近5日上涨15.27%
成交额是近20日平均值的2.24倍
最近5日67.37%的上涨来自一个涨停日
```

它们不能直接组成：

```text
所以推荐
```

推荐理由必须回答：

```text
这只股票接下来继续走强，需要什么事情成立？
这些事实为什么让这件事更可能发生？
这些事实中，哪些支持，哪些反对，哪些只是背景？
为什么在存在不利事实时仍然保留它？
为什么是这只股票，而不是同行里另一只？
```

### 对一拖股份三个数字的正确解释

#### 近5日上涨15.27%

这不是独立的推荐理由。

它最多说明：

```text
股票已经明显启动，市场已经在交易这个方向。
```

它既可能是好事，也可能意味着短期已经涨得较多。只有同时看到：

- 农业相关股票大多数都在上涨；
- 一拖股份不是只靠一天上涨；
- 它相对同行确实更强；
- 成交增加以后，收盘仍然向上；

才可以把这项事实用于支持“上涨可能延续”。

#### 成交额是近20日平均值的2.24倍

这也不是独立的推荐理由。

成交额放大只说明买卖明显比平时活跃。它可能是更多人买，也可能是更多人卖。只有当成交增加同时伴随：

- 股价持续上涨；
- 收盘位置较稳；
- 不只是盘中冲高后回落；
- 连续多个正常交易日都能维持；

才说明市场愿意在更高价格继续成交，才对推荐有支持作用。

#### 67.37%的涨幅来自一个涨停日

这不是支持证据，而是明确的不利事实。

它说明：

```text
最近上涨大部分集中在一天完成，
普通交易日的持续性还没有充分证明。
```

如果一拖股份仍被选择，完整理由必须是：

```text
农业相关股票普遍转强
+
公司核心业务就是农业机械
+
公司近期经营数据改善
+
股票本身已经出现成交增加和价格上涨
```

这些支持因素合在一起，暂时超过“涨幅集中在一个涨停日”的风险；但信心必须降低，并要求后续正常交易日继续上涨。若普通交易日不能继续收高，这次推荐所依赖的持续性判断就被削弱。

**不得再把67.37%和15.27%、2.24倍并排写成三项推荐依据。**

---

## 三、本轮唯一设计

### 推荐阶段

每只股票的理由必须形成一个完整论证：

```text
核心判断
→ 为什么这件事可能推动股票继续上涨
→ 哪些事实支持这个判断，以及为什么
→ 哪个事实最不利
→ 为什么最不利事实暂时没有推翻推荐
→ 什么情况出现后应承认判断变差
```

### 复盘阶段

每只股票的复盘必须检验当初的判断：

```text
当初期待看到什么
→ 推荐后实际发生了什么
→ 实际变化为什么支持或反对当初判断
→ 当初理由中哪一部分仍成立、哪一部分失败
→ 现在结论是什么
```

### 禁止退化成

```text
事实1
事实2
事实3
风险1
仍需观察
```

也禁止退化成：

```text
原判断部分支持
价格确认减弱
传播链仍在
```

这些都是结论标签，没有分析过程。

---

## 四、任务范围

### 允许修改

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

research/skill-optimization/plain-language-recommendation-review-20260902/
research/skill-optimization/reasoned-recommendation-review-20260902/

docs/2026-09-02-reasoned-recommendation-review-and-branch-cleanup-prompt.md
```

### 禁止修改

```text
src/stock_analyzer/ops/forward_selection.py
docs/architecture/a-share-short-horizon-engine-contract-v4.md

.agents/skills/interpreting-market-macro/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md

tools/
数据采集
数据库schema
七种发动机
四种状态
11个价格场景
D20定义
入口价格与收益计算
```

### 明确不做

- 不增加评分器、权重、概率或总分；
- 不新增“支持/反对/背景”结构化字段；
- 不新增自然语言质量模型；
- 不新增报告schema；
- 不重构选股流程；
- 不重新选择一拖股份或历史股票；
- 不使用未来行情改写形成日理由；
- 不批量重写历史文档；
- 不创建新的校验平台；
- 不为普通Markdown生成哈希文件；
- 不删除液冷产业研究的独立分支；
- 不使用 `reset --hard`、`push --force` 或 `git branch -D`。

---

## 五、执行纪律

本轮会调整正式推荐和正式复盘的文字合同，并会执行远端分支清理。

按当前 `AGENTS.md`，实施前只启动一次独立审查：

```text
模型：gpt-5.6-sol
推理：xhigh
职责：只审查本文件是否会改变选股计算、遗漏正式推荐边界、
      误删未合并分支、增加无必要哈希或出现过度工程化。
```

审查不实施、不启动其他子智能体。主智能体吸收一次审查意见后连续完成后续工作。除此之外不再启动子智能体。

---

# 第一阶段：基线、分支和哈希现状

## Task 1：读取当前实现

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
research/skill-optimization/plain-language-recommendation-review-20260902/one-tuo-recommendation.md
research/skill-optimization/plain-language-recommendation-review-20260902/formal-review-sample.md
research/skill-optimization/plain-language-recommendation-review-20260902/runtime-diagnosis.md
```

运行基线测试：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py

./.venv/bin/python -m pytest -q
```

记录实际结果，不沿用上一轮汇报数字。

## Task 2：形成分支现状记录

创建：

```text
research/skill-optimization/reasoned-recommendation-review-20260902/branch-audit.md
```

运行：

```bash
git fetch origin --prune

git for-each-ref \
  --format='%(refname:short) %(objectname)' \
  refs/remotes/origin \
  | sort
```

对每个远端分支判断：

```bash
if git merge-base --is-ancestor "origin/<branch>" origin/main; then
  echo "已进入main"
else
  echo "没有完整进入main"
fi
```

当前已知远端分支包括：

```text
chatgpt/final-engine-contract-v4
chatgpt/v4-operational-prompt-cleanup
codex/detailed-recommendation-explanation-20260901
codex/five-skill-selection-logic-optimization-20260901
codex/plain-language-recommendation-review-20260902
codex/skill-optimization-dataset-20260831
feat/industry-research-workflow-v2
fix/liquid-cooling-data-gap-v1
main
research/ai-liquid-cooling-2026h2
```

`branch-audit.md` 必须逐个记录：

```text
分支名
分支HEAD
是否已进入main
处理决定
```

当前设计原则：

- 已经进入 `main` 的旧开发分支：本轮完成并确认后删除远端引用；
- 本轮新功能分支：合并进 `main` 后删除；
- `research/ai-liquid-cooling-2026h2`：保留，不在本轮合并。

不得因为分支数量多，就把液冷研究分支强行合并。

## Task 3：审视哈希，不立即删除

运行：

```bash
git grep -n -E \
  'sha256|file_sha256|content_hash|payload_hash|business_key_hash|input_manifest_hash|checksums\.sha256' \
  -- \
  'src/**' \
  'tools/**' \
  'research/**' \
  'docs/**' \
  'AGENTS.md' \
  || true
```

只按以下三类判断：

### A. Git提交SHA

用途：

- 固定一次开发任务的准确基线；
- 确认本地、远端和实际运行目录是同一个版本；
- 在多分支和worktree下避免读错版本。

保留，但只在任务开始和结束使用。通过命令读取，不在多个文档反复手抄。

### B. 数据仓库内部哈希

包括：

```text
content_hash
file_sha256
business_key_hash
payload_hash
input_manifest_hash
```

它们用于：

- 判断数据是否变化；
- 去重；
- 保存历史修订；
- 检查文件与元数据是否一致；
- 中断后恢复；
- 保证派生数据对应正确输入。

本轮不得删除或改造。

### C. 冻结数据包校验和

例如：

```text
manifest.json
checksums.sha256
```

只在需要对外发布或冻结一组多文件研究样本时保留，用于确认交给ChatGPT复核的数据包没有被悄悄改动。

普通 Prompt、Skill、日报、复盘文字和本轮分支收口不需要新建这类文件。

---

# 第二阶段：推荐理由必须从事实走到结论

## Task 4：先写失败测试

修改：

```text
tests/test_v4_operational_prompts.py
```

增加：

```python
def test_selection_prompt_requires_reasoning_not_a_fact_list() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "事实本身不是推荐理由",
        "为什么这些事实让继续上涨更有可能",
        "哪些事实支持，哪些事实反对",
        "为什么最不利的事实暂时没有推翻推荐",
        "为什么是这只股票，而不是同行里另一只",
        "67.37%的涨幅来自一个涨停日不是支持证据",
    ):
        assert phrase in prompt

    assert "推荐理由必须是一个完整论证" in prompt
    assert "不得把涨幅、成交额和涨停贡献并排后直接得出推荐" in prompt
```

更新旧测试，删除对以下旧问题清单的强制要求：

```text
为什么现在值得看
目前有什么实际推动
股价和成交有没有认可
推荐后的第一个交易日要看什么
已经涨了多少，后面是否还有空间
最不利的事实
```

这些内容可以作为内部问题存在，但不得再成为第二套对外格式合同。

修改后、实现前，运行新测试并确认失败：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_v4_operational_prompts.py::test_selection_prompt_requires_reasoning_not_a_fact_list
```

## Task 5：重写新荐股的理由要求

修改：

```text
ops/forward-selection-prompt.md
```

### 5.1 删除第二套旧输出合同

找到仍然要求：

```text
“今天已确认的正式推荐”部分对每只股票只回答……
```

将整段替换为：

```markdown
“今天明确推荐的股票”只使用本节后面的唯一用户输出格式。
前面的内部研究问题用于形成判断，不再设置第二套对外问题清单。
```

### 5.2 加入核心原则

加入以下正文：

```markdown
### 推荐理由必须是一个完整论证

事实本身不是推荐理由。涨幅、成交额、行业上涨面、财务变化和价格位置只是证据。最终必须说明这些事实为什么让继续上涨更有可能，哪些事实支持，哪些事实反对，以及为什么最不利的事实暂时没有推翻推荐。

每只正式推荐股票必须回答：

1. **核心判断是什么**：未来约20个交易日可能继续上涨，主要依靠行业整体转强、公司新变化，还是股票自身持续走强。
2. **为什么这个判断可能成立**：说明行业、公司经营和股票表现之间怎样相互印证，不讲内部字段。
3. **为什么是这只股票**：同行普涨只证明方向值得关注；还要说明这家公司业务为什么真正相关、股票为什么比普通同行更强。
4. **事实为什么有意义**：每个数字都要说明它证明了哪一点。不能只写数字。
5. **最不利的事实是什么**：明确它怎样降低继续上涨的可能性。
6. **为什么仍然选择**：解释支持因素为何暂时超过不利事实；若无法解释，不得正式推荐。
7. **什么情况会证明选错**：用未来正常交易日可以观察到的事实说明。

不得把涨幅、成交额和涨停贡献并排后直接得出推荐。
```

### 5.3 加入事实的双向解释

加入：

```markdown
同一个数字可能支持，也可能反对推荐，不能机械解释：

- 5日涨幅较大：说明股票已经启动；但若主要来自一天，也说明持续性不足。
- 成交额放大：说明买卖活跃；只有价格持续上升、收盘稳固时才支持上涨，放量不涨反而是不利事实。
- 行业大多数股票上涨：说明整个方向受到关注；它不能单独证明具体股票值得选。
- 公司收入、利润、现金流改善：说明经营基础变好；它不能单独证明短期股价会继续上涨。
- 股价接近近期高点：可能说明强势，也可能说明已经涨得较多；要看能否站稳，而不是机械判定好坏。
- 67.37%的涨幅来自一个涨停日不是支持证据，而是持续性尚未证明的不利事实。
```

### 5.4 唯一用户格式

最终每只股票使用：

```markdown
### 股票名称（代码）

**公司主要做什么**

只介绍与本次推荐有关的产品、客户和应用。

**我为什么会选它**

先给完整结论，再说明行业、公司和股票自身如何共同支持。不能先罗列数字。

**这些情况为什么支持这个判断**

把3—5项真正重要的事实逐一解释：
- 它说明了什么；
- 为什么会提高或降低继续上涨的可能性；
- 它只支持行业方向、公司基础，还是具体股票。

**最需要担心什么**

说明最不利事实为何重要，以及为什么目前仍保留推荐。

**什么情况会证明判断变差**

说明后续正常交易日出现什么现象时，应承认推荐所依赖的判断被削弱。
```

每只约300—500字。不是为了字数重复，而是必须完成论证。

## Task 6：同步总控 Skill

修改：

```text
.agents/skills/orchestrating-stock-research/SKILL.md
```

在“名单冻结后的用户说明”中加入：

```markdown
内部选择理由和对外推荐说明都不能只是事实清单。

`research_result.selected_stocks[].selection_reason` 必须保存一段完整判断：
- 股票未来继续走强主要依靠什么；
- 哪些形成日前事实让这件事更可能；
- 为什么是它而不是同类；
- 最不利事实怎样削弱判断；
- 为什么仍然入选。

`strongest_counterevidence` 不只写风险名称，要说明它为何会降低继续上涨的可能性。
`nearest_comparison` 不只写谁强谁弱，要说明决定性差异为什么与未来表现有关。

如果总控只能说“它涨了多少、成交放大多少、财务改善多少”，却说不出这些事实为什么共同支持继续上涨，就不能形成正式推荐。
```

不增加字段，不改V4 schema。

## Task 7：同步公司 Skill

修改：

```text
.agents/skills/researching-company-events/SKILL.md
```

加入：

```markdown
公司事实在推荐理由中的作用必须说清：

- 主营直接相关，只证明行业或事件确实可能影响这家公司；
- 收入、利润、现金流改善，只证明经营基础有所改善；
- 它们不能自动证明短期股价会涨；
- 只有公司事实与行业变化、股票相对同行的表现及成交后的收盘结果相互印证，才可以支持正式推荐。

最终说明不能写“公司基本面提供支撑”后结束，必须说清具体是哪项经营变化，以及它为什么减少了纯题材炒作的可能性。
```

---

# 第三阶段：用一拖股份验证“理由”而不是“事实”

## Task 8：重写一拖股份样例

修改：

```text
research/skill-optimization/plain-language-recommendation-review-20260902/one-tuo-recommendation.md
```

必须保留原始事实，不重新选股，但核心段落改为完整论证。

样例至少达到以下内容水平：

```markdown
**我为什么会选它**

我选择一拖股份，不是因为它最近5天涨了15.27%本身。真正的理由是，农业方向大多数股票同时转强，一拖股份的核心业务又正是拖拉机等农业机械，公司一季度收入、利润和经营现金流也都比上年同期改善。行业变化、公司业务和经营情况指向同一个方向后，这次上涨就不只是一个与公司无关的热门概念。

股票本身也已经作出反应：成交额达到过去20天平均水平的2.24倍，同时价格明显上涨。这两项放在一起，说明买卖活跃后，价格仍然向上，而不是只有成交放大却涨不动。因此，一拖股份不是只具备农业机械身份，它已经成为这个方向中实际走强的股票之一。

**这些情况为什么支持这个判断**

32只农业相关股票中，最近3天和5天都有30只上涨，说明农业方向的上涨不是由一两只热门股单独造成。这只能证明农业方向值得看，不能单独证明必须选择一拖股份。

一拖股份主营农业机械，说明行业变化与它的核心业务直接相关；一季度经营改善，则降低了这轮上涨完全依靠题材的可能性。

近5日上涨15.27%说明股票已经启动，但不能据此直接推荐。成交额为近期平均水平的2.24倍，并且价格同时上涨，才说明这只股票不只是跟着行业轻微波动，而是出现了更活跃的买卖和更高的成交价格。

**最需要担心什么**

最近5日约67.37%的上涨来自一个涨停日。这是反对推荐的事实，不是支持推荐的理由。它说明大部分上涨集中在一天，普通交易日能否继续上涨还没有充分证明。

我仍然保留它，是因为农业方向整体转强、公司业务直接相关、经营数据改善和股票自身活跃四件事同时出现。但这项选择的把握不能说得过高。后续若离开涨停后仍能连续收高，推荐理由会更扎实；若成交很大却不再上涨，或者高开后持续回落，就说明此前上涨主要是一日冲高，原判断应当下调。
```

最终文字可以调整，但不得退回事实清单。

---

# 第四阶段：复盘必须检验当初为什么推荐

## Task 9：先写复盘失败测试

修改：

```text
tests/test_forward_monitor_prompt.py
```

增加：

```python
def test_review_prompt_explains_why_actual_results_support_or_refute_original_reason() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "当初期待看到什么",
        "实际发生的变化为什么支持或反对当初判断",
        "不能只写“部分支持”",
        "哪一项核心预期得到验证",
        "哪一项核心预期没有发生",
        "所以现在怎样评价这次推荐",
    ):
        assert phrase in text
```

运行并确认失败：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_forward_monitor_prompt.py::test_review_prompt_explains_why_actual_results_support_or_refute_original_reason
```

## Task 10：重写复盘分析要求

修改：

```text
ops/forward-monitor-prompt.md
```

在“正式推荐股票的走势复盘”加入：

```markdown
### 复盘不是行情播报

复盘必须先恢复当初推荐时真正期待发生的事情，再用推荐后的事实检验。

每只股票必须回答：

1. **当初期待看到什么**：例如，行业大多数股票继续上涨、该股继续强于同行、突破后能站稳、公司新消息得到股价响应。
2. **实际发生了什么**：只列与当初预期有关的价格、成交、行业和公司事实。
3. **为什么这些变化支持或反对当初判断**：说明事实与原预期的关系。
4. **哪一项核心预期得到验证**。
5. **哪一项核心预期没有发生或正在减弱**。
6. **所以现在怎样评价这次推荐**：继续成立、明显减弱、已经不成立，或者资料不足。
7. **接下来什么会改变结论**。

不能只写“部分支持”“价格表现较好”“仍需观察”。必须指出具体是哪一部分、为什么。

例如：

- 当初因为突破前高而推荐，后来跌回前高下方：这会削弱推荐，因为突破只有站稳才说明市场接受了更高价格。
- 当初因为行业普遍上涨而推荐，后来同行多数转弱但该股仍上涨：行业理由减弱，但股票自身可能仍强。
- 当初因为公司新合同而推荐，后来公告真实但股价和成交没有变化：公司事件仍然真实，但短期上涨预期没有被市场行为验证。
- 股票上涨并不自动证明原理由正确。若大盘和同行涨得更多，原先认为它更强的判断仍可能错误。
```

要求 `ForwardEpisodeReviewV1.current_review` 本身就是完整分析，至少包含：

```text
当初的核心预期
+
实际发生的关键变化
+
这些变化为什么支持或反对预期
+
当前结论
```

不增加模型字段。

## Task 11：调整用户复盘Markdown

修改：

```text
src/stock_analyzer/ops/forward_monitor.py
```

最终每只正式推荐股票使用：

```markdown
**当初为什么推荐**

**推荐后实际发生了什么**

**这些变化说明什么**

**现在结论**

**接下来关注什么**
```

其中：

- “推荐后实际发生了什么”只负责事实；
- “这些变化说明什么”必须使用 `review.current_review`，解释事实与原推荐理由的关系；
- 不再把事实和结论混成一句；
- 不打印内部 `current_assessment`、`best_supported_explanation`、`current_weak_or_failed_link` 标签；
- 不显示比较股；
- 不显示待确认事件。

不要创建新的渲染类或报告schema。

## Task 12：重写复盘样例

修改：

```text
research/skill-optimization/plain-language-recommendation-review-20260902/formal-review-sample.md
```

每只股票必须表现出“原预期—实际—含义—结论”。

例如金岭矿业应接近：

```markdown
当初推荐它，最重要的原因是股价突破近60天高点，而且连续几天比大盘更强。这个判断隐含的预期是：突破以后股价应当站在前高之上，并继续保持相对强势。

推荐后收盘累计仍上涨约1.22%，最近3天也比大盘多涨约1.90个百分点，这说明它没有立即转弱，相对大盘的优势还在。但股价已经回到此前高点下方约1.32%，这比小幅上涨更重要，因为当初推荐所依赖的“突破已经站稳”没有得到验证。

因此，这次推荐不是完全错误，但最核心的突破依据已经减弱。若后面重新站上前高并保持几个正常交易日，原判断会恢复；若继续在前高下方运行，即使仍小幅跑赢大盘，也不能再说突破理由成立。
```

华昌化工和中信银行也要使用同样的分析深度，但不能套用相同句子。

---

# 第五阶段：完成上一轮核查的最小收尾

## Task 13：统一正式推荐类别

当前正式推荐类别只有：

```python
PUBLIC_FORMAL_OUTPUT_CLASSES = frozenset(
    {"confirmed_active", "legacy_v1_not_rewritten"}
)
```

在 `src/stock_analyzer/ops/forward_monitor.py` 中，以下位置统一使用该集合：

1. `register_episodes()` 中的 `selected_registered`；
2. `required_final_review_episode_ids`；
3. `summary_payload["selected_count"]`；
4. `_attention_reasons()` 中的 `pending_final_review`；
5. `formal_return_started`；
6. `record_forward_monitor()` 的正式推荐判断；
7. Markdown正式推荐计数。

不得修改类别本身，也不得新增第五类状态。

增加测试：

```text
旧版明确正式推荐计入开放推荐数量
旧版明确正式推荐在第20天需要最终复盘
第20天漏跑后继续提醒补做
旧版正式推荐有可靠入口时可以形成正式收益
```

## Task 14：正式推荐不能被内部记录挤掉

内部日报仍最多8只，不改schema。

在 `record_forward_monitor()` 增加最小验证：

- 从 snapshot 的 `attention_stocks` 找出含正式推荐记录的股票；
- 如果正式推荐重点股票不超过8只，报告必须全部包含；
- 如果超过8只，报告中不得出现非正式记录挤占位置；
- 待确认事件和比较股只能使用正式推荐之后剩余的位置。

不改变内部JSON保留比较股和待确认事件的能力。

增加组合测试：

```text
8只待确认/比较记录
+
1只明确正式推荐
```

验证：

- 正式推荐必须进入report；
- 用户Markdown必须展示正式推荐；
- 非正式记录即使保存在内部，也不能把正式推荐挤掉。

## Task 15：恢复清楚的前20天固定结果

当前第21—30天页面可能只显示最新累计表现，再附一句前20天结论。

在用户Markdown中恢复一个简短段落：

```markdown
**前20个交易日最后结果**
```

只在存在冻结的 `final_twenty_day_review` 时显示：

```text
前20个交易日结束时的收盘涨跌
期间最高收盘涨幅
期间最深跌幅
冻结的最终结论
```

第21—30天最新走势继续单独展示，不得覆盖或混入前20天数据。

复用现有D20字段和现有函数，禁止增加第二套计算。

## Task 16：清理公开文档中的个人绝对路径

修改：

```text
research/skill-optimization/plain-language-recommendation-review-20260902/runtime-diagnosis.md
```

替换：

```text
<个人主目录>/股票分析助手
<个人主目录>/Documents/股票分析助手
```

为：

```text
$PROJECT_ROOT
$HOME/Documents/股票分析助手
```

运行：

```bash
PERSONAL_PATH_PREFIX="/Users/"'ccrt'
git grep -n "$PERSONAL_PATH_PREFIX" || true
```

只修复本轮及上一轮直接相关的公开运行记录，不批量重写所有历史材料。

---

# 第六阶段：明确哈希使用边界

## Task 17：在 `AGENTS.md` 增加简短政策

加入：

```markdown
## 哈希使用边界

- Git提交SHA只用于固定一次开发任务的准确基线、代码对比和确认本地/远端版本一致；优先由命令读取，不在多个文档重复手抄。
- 数据仓库中的 `content_hash`、`file_sha256`、`business_key_hash`、`payload_hash` 和 `input_manifest_hash` 用于去重、修订识别、输入对应和中断恢复，属于数据层核心能力，不因普通流程简化而删除。
- `manifest.json` 和 `checksums.sha256` 只用于需要冻结并交付的一组多文件研究或数据样本。
- 普通 Prompt、Skill、每日荐股、日常复盘、说明文档和分支合并，不新增校验和文件或输入哈希。
- 不为“看起来更严谨”重复计算 Git 已经提供的文件完整性能力。
```

不要新建独立哈希框架，不修改数据仓库代码和现有冻结样本。

---

# 第七阶段：测试与真实样例检查

## Task 18：定向测试

运行：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py
```

## Task 19：完整测试

```bash
./.venv/bin/python -m pytest -q
git diff --check
```

不得删除测试换取通过。

## Task 20：人工阅读检查

逐字阅读：

```text
one-tuo-recommendation.md
formal-review-sample.md
```

确认一拖股份回答了：

```text
为什么农业方向普遍上涨只支持“方向值得看”
为什么主营农业机械支持“这家公司确实相关”
为什么经营改善只提供经营基础
为什么15.27%本身不能直接推荐
为什么2.24倍成交额必须与上涨和收盘结合
为什么67.37%是反对推荐的事实
为什么在该风险下仍然选择
什么情况会证明选错
```

确认正式复盘回答了：

```text
当初具体期待什么
实际发生了什么
为什么实际事实支持或反对原预期
当前结论为什么成立
```

只做人工检查，不建立语言评分程序。

---

# 第八阶段：提交并快进合并到 main

## Task 21：提交功能分支

```bash
git add \
  AGENTS.md \
  docs/2026-09-02-reasoned-recommendation-review-and-branch-cleanup-prompt.md \
  ops/forward-selection-prompt.md \
  ops/forward-monitor-prompt.md \
  .agents/skills/orchestrating-stock-research/SKILL.md \
  .agents/skills/researching-company-events/SKILL.md \
  src/stock_analyzer/ops/forward_monitor.py \
  tests/test_v4_operational_prompts.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py \
  research/skill-optimization/plain-language-recommendation-review-20260902 \
  research/skill-optimization/reasoned-recommendation-review-20260902

git commit -m "fix: explain why evidence supports stock recommendations"
```

推送功能分支：

```bash
git push -u origin codex/reasoned-recommendation-review-20260902
```

记录：

```bash
FEATURE_HEAD="$(git rev-parse HEAD)"
```

## Task 22：合并到实际运行的 main

回到实际项目根目录：

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

验证：

```bash
MAIN_HEAD="$(git rev-parse main)"
REMOTE_MAIN_HEAD="$(git rev-parse origin/main)"

test "$MAIN_HEAD" = "$FEATURE_HEAD"
test "$REMOTE_MAIN_HEAD" = "$FEATURE_HEAD"
test -z "$(git status --short)"
```

Scheduled Task 已经运行在实际项目根目录的 `main`，因此只需再次核对其工作目录没有改变，不新建或复制定时任务。

---

# 第九阶段：清理已经进入 main 的旧分支

## Task 23：只删除已经合并的远端分支

候选列表：

```bash
MERGED_BRANCHES=(
  "chatgpt/final-engine-contract-v4"
  "chatgpt/v4-operational-prompt-cleanup"
  "codex/detailed-recommendation-explanation-20260901"
  "codex/five-skill-selection-logic-optimization-20260901"
  "codex/plain-language-recommendation-review-20260902"
  "codex/skill-optimization-dataset-20260831"
  "feat/industry-research-workflow-v2"
  "fix/liquid-cooling-data-gap-v1"
  "codex/reasoned-recommendation-review-20260902"
)
```

逐个执行：

```bash
git fetch origin --prune

for branch in "${MERGED_BRANCHES[@]}"; do
  if ! git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    echo "already absent: $branch"
    continue
  fi

  if git merge-base --is-ancestor "origin/$branch" origin/main; then
    git push origin --delete "$branch"
  else
    echo "KEEP: $branch is not fully merged into main"
  fi
done

git fetch origin --prune
```

禁止使用强制删除。

### 液冷研究分支必须保留

```text
research/ai-liquid-cooling-2026h2
```

当前该分支包含独立的液冷研究运行记录，并且与 `main` 已经分叉。它不是遗漏的股票助手功能分支。

本轮：

- 不合并它；
- 不删除它；
- 不改写它；
- 在 `branch-audit.md` 标记为“独立研究进行中，保留”。

后续继续液冷研究时，再在独立任务中先同步 `main`，不能在本轮顺便处理。

## Task 24：本地分支只做非强制清理

运行：

```bash
git worktree list --porcelain
git branch --merged main
```

对没有被任何worktree占用的已合并本地分支，只使用：

```bash
git branch -d <branch>
```

不得使用 `-D`，不得自动删除仍挂载的worktree，也不得删除worktree中的本地研究资料。

最终远端原则上只保留：

```text
main
research/ai-liquid-cooling-2026h2
```

如果某个候选分支没有通过祖先检查，保留并在报告中说明。

---

# 第十阶段：最终验证

## Task 25：版本和分支

```bash
git fetch origin --prune

git rev-parse main
git rev-parse origin/main

git for-each-ref \
  --format='%(refname:short) %(objectname)' \
  refs/remotes/origin \
  | sort

git status --short
```

## Task 26：改动范围

```bash
git diff --name-only \
  94955b91e1108948eef4df7b653c08c98e052b66...main

git diff --stat \
  94955b91e1108948eef4df7b653c08c98e052b66...main
```

核对：

- 没有修改选股计算；
- 没有修改V4合同；
- 没有修改价格场景；
- 没有修改数据仓库哈希；
- 没有新增校验和文件；
- 复盘只展示明确正式推荐；
- 一拖股份说明有完整分析；
- 旧版正式推荐的计数和D20处理一致；
- 正式推荐不会被内部待确认/比较记录挤掉；
- 前20天固定结果重新清楚展示；
- `main` 是实际运行版本；
- 液冷研究分支仍然存在。

---

# 十一、最终汇报格式

```markdown
已完成：A股推荐理由、复盘分析、哈希减负与分支收口

## GitHub
- 基线：`94955b91e1108948eef4df7b653c08c98e052b66`
- main最终提交：`<FINAL_HEAD>`
- 对比链接：<base...final>
- 一拖股份样例：<URL>
- 正式复盘样例：<URL>
- 分支审计：<URL>

## 推荐理由
- 事实清单是否已改成完整论证：是/否
- 15.27%为什么不能单独支持推荐：<一句话>
- 2.24倍成交额何时才支持推荐：<一句话>
- 67.37%涨停贡献属于支持还是风险：<一句话>
- 为什么在风险存在时仍选择一拖股份：<完整简述>

## 复盘
- 是否恢复“当初预期—实际变化—为何支持/反对—当前结论”：是/否
- 是否还会只写“部分支持”：是/否
- 是否只展示明确正式推荐：是/否
- 前20天固定结果是否清楚展示：是/否

## 一致性修复
- legacy正式推荐计数：<结果>
- legacy D20结案：<结果>
- 正式推荐优先进入8只内部提醒：<结果>
- 个人绝对路径：已清理/仍有何处

## 哈希
- Git SHA：仅用于基线和远端一致性
- 数据仓库哈希：保留，原因是去重、修订和恢复
- 冻结数据包checksums：仅冻结交付包保留
- 本轮是否新增普通文档哈希：否

## 分支收口
- 已删除的远端已合并分支：<列表>
- 保留的远端分支：<列表>
- `research/ai-liquid-cooling-2026h2`未合并原因：独立研究进行中
- main与实际每日任务版本一致：是/否

## 验证
- 基线定向测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- `git diff --check`：<结果>
- main本地/远端HEAD一致：是/否
- 工作区干净：是/否

## 明确未做
- 未重新选股
- 未修改五个Skill的选股计算
- 未修改七种发动机、四种状态和11个价格场景
- 未修改D20计算
- 未新增schema、数据库、评分器、数据源或语言平台
- 未删除或合并液冷研究分支
```

只有完整测试通过、功能提交快进进入 `main`、远端分支完成祖先检查后再清理，并且实际一拖股份及复盘样例达到“事实为什么支持结论”的要求，才可以声称完成。
