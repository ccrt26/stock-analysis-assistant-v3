# A股入选时机与专用复盘 Skill 优化——Codex 执行指令 V1.0

> **直接执行本文件，不要改写成另一份泛化方案。**
>
> 本任务解决两个实质问题：
>
> 1. 当前助手为了确认股票已经走强，容易等到股票短期明显上涨后才推荐；同一段上涨又被写成“确认”和“涨得过多”，却没有作出净判断。
> 2. 当前复盘仍偏向事实罗列、数据边界和规则检查，没有围绕“推荐日的判断是否正在实现、距离20%目标走到哪里、为什么”形成完整分析。
>
> 这是个人 A 股助手，不是系统平台。禁止新增评分平台、复杂状态机、数据库表、审批流程或第二套定时任务。

---

## 一、仓库、基线与分支

### 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

### 唯一基线

```text
分支：main
提交：b2c742c889dc380bd2fbce1c30db3b056364eb70
```

### 新功能分支

```text
codex/entry-timing-and-review-skill-20260902
```

### 创建 worktree

在实际项目根目录执行：

```bash
git fetch origin --prune

test "$(git rev-parse origin/main)" = \
  "b2c742c889dc380bd2fbce1c30db3b056364eb70"

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BASE_HEAD="$(git rev-parse origin/main)"
WORKTREE="$PROJECT_ROOT/.worktrees/entry-timing-and-review-skill-20260902"

git worktree add \
  "$WORKTREE" \
  -b codex/entry-timing-and-review-skill-20260902 \
  "$BASE_HEAD"

cd "$WORKTREE"

test "$(git rev-parse HEAD)" = "$BASE_HEAD"
test "$(git branch --show-current)" = \
  "codex/entry-timing-and-review-skill-20260902"
test -z "$(git status --short)"
```

将本文件原样保存为：

```text
docs/2026-09-02-entry-timing-and-review-skill-prompt.md
```

---

# 二、先接受本轮的科学结论

## 1. “已经上涨”既不是天然利好，也不是天然风险

为了避免推荐完全没有市场反应的股票，正式推荐需要一定的价格确认，因此推荐股通常不会停留在完全未启动状态。

但当前方法存在过度纠正：

```text
过去5日涨幅较大
相对行业涨幅较大
成交额放大
突破近期高点
```

这些现象可能都由同一个涨停日造成。若把它们分别当成四条支持证据，再把“涨幅主要来自一个涨停日”列为风险，就会出现表面平衡、实际重复计算的问题。

正确做法是：

```text
先判断上涨是不是分布在多个普通交易日
→ 再判断为了获得确认已经付出了多少涨幅
→ 最后作出“确认仍大于追高风险”或“追高风险已大于确认”的净结论
```

不能一边说最重要的价格依据还没有得到普通交易日验证，一边仍然正式推荐。

## 2. 近期高位本身不是淘汰理由

接近近期高点可能代表趋势仍强，也可能代表前期涨幅已经较多。

真正需要判断的是：

- 突破后能否站稳；
- 上涨是否主要集中在一个交易日；
- 除去最大上涨日后，其余交易日是否仍然向上；
- 最大上涨日之后是否继续上涨；
- 成交增加后，收盘是否继续提高；
- 是否仍存在新的公司或行业变化，而不是只剩价格惯性。

因此禁止把“接近60日高位”机械写成风险，也禁止把“突破60日高点”机械写成支持。

## 3. 不同入选原因需要不同程度的价格确认

### 行业或公司变化明确的股票

行业大多数股票共同转强，或者公司出现直接、重要的新变化时，价格只需出现**较早但真实的确认**：

- 连续几个普通交易日相对市场或同行更强；
- 收盘逐步提高；
- 成交增加没有变成放量不涨。

不得为了等待很大的5日涨幅，错过较早阶段。

### 只靠股票自身走势发现的股票

没有明确行业或公司原因时，必须要求更扎实的多日持续性：

- 不能只靠一个涨停或一个大阳线；
- 除去最大上涨日后仍应有正向表现；
- 最大上涨日之后不能马上回落；
- 成交增加后应继续形成较高收盘。

## 4. 复盘不能按每天1%线性判断

目标是推荐后约20个交易日观察能否上涨约20%，但股票不会每天均匀上涨。

复盘应说明：

```text
推荐日期
已观察多少个交易日
当前收盘较参考价上涨或下跌多少
期间最高到过哪里
期间最深下跌多少
离20%目标还差多少
推荐时期待发生的事情是否真的发生
```

不得用“第6天就应该上涨6%”之类的线性进度条判断好坏。

---

# 三、研究依据

将以下内容写入：

```text
research/skill-optimization/entry-timing-review-skill-20260902/scientific-rationale.md
```

只总结与本轮设计直接相关的结论，不扩建知识库。

## 顶级与A股研究

1. Jegadeesh 与 Titman，《Returns to Buying Winners and Selling Losers》，Journal of Finance，1993，DOI 10.1111/j.1540-6261.1993.tb04702.x  
   - 经典动量证据主要基于3—12个月持有期，不能直接推出“过去3—5天涨得多，未来20天就更容易继续涨”。

2. Lehmann，《Fads, Martingales, and Market Efficiency》，Quarterly Journal of Economics，1990，DOI 10.2307/2937816  
   - 一周赢家在下一周可能出现明显反转，说明极短期强势不能自动外推。

3. Lee 与 Swaminathan，《Price Momentum and Trading Volume》，Journal of Finance，2000，DOI 10.1111/0022-1082.00280  
   - 成交量会影响动量持续性，但高成交的赢家也可能更快反转；成交放大不是单向利好。

4. George 与 Hwang，《The 52-Week High and Momentum Investing》，Journal of Finance，2004，DOI 10.1111/j.1540-6261.2004.00695.x  
   - 接近长期高点并不天然意味着必须淘汰；高位要与突破质量和后续持续性一起判断。

5. Chui、Subrahmanyam 与 Titman，《Momentum, Reversals, and Investor Clientele》，NBER Working Paper 29453，2021  
   - 中国A股更明显地表现出短期反转特征，不能简单套用海外中期动量结论。

6. 张瑞琪、张兵，《Price Limit Dominates Daily Momentum Effect in the Chinese Stock Market》，中央财经大学学报，2025年第1期  
   - A股日频动量很大程度来自涨跌停后的延迟定价；剔除涨跌停股票后，日频动量不再显著。涨停贡献必须单独处理。

7. 《Does short-term momentum really exist in China? Evidence from “Siamese twin” stocks》，Applied Economics Letters，2025，DOI 10.1080/13504851.2025.2463623  
   - A股短期反转与流动性、个股波动有关，进一步说明极短期上涨不能作为通用继续上涨规则。

## 券商写法只学习结构

查看当前可取得的券商公司点评样例，学习以下写法：

```text
先给判断
→ 说明实际发生了什么
→ 拆出真正驱动收入、利润或股价变化的业务
→ 说明为什么可能继续
→ 说明哪个事实会改变判断
```

可参考：

- 华泰证券对中际旭创的点评：把业绩增长具体归因到高速光模块需求、产品放量和产品结构；
- 浙商证券对中科曙光的点评：把收入增长拆到IT设备和软件服务，而不是只报总收入；
- 东吴证券对招商证券的点评：把市场成交活跃与经纪业务收入增长连接起来。

不复制“景气度、催化、估值修复、预期差”等券商套话，不给目标价、仓位和收益承诺。

## 基本研究要求

参考 CFA Institute Standard V(A) 与 V(B)：

- 推荐必须有合理、充分的研究基础；
- 必须理解量化模型的假设和限制；
- 必须区分事实与判断；
- 必须说明真正重要的正面和负面因素；
- 不能只给结果而不让用户理解推荐依据。

---

# 四、任务范围

## 允许修改

```text
AGENTS.md

.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md
.agents/skills/reviewing-stock-recommendations/SKILL.md
.agents/skills/reviewing-stock-recommendations/agents/openai.yaml

ops/forward-selection-prompt.md
ops/forward-monitor-prompt.md

src/stock_analyzer/analysis/price_indicator_validation.py
src/stock_analyzer/ops/forward_monitor.py

tests/test_price_indicator_validation.py
tests/test_v4_operational_prompts.py
tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py
tests/test_forward_monitor.py

research/skill-optimization/entry-timing-review-skill-20260902/
docs/2026-09-02-entry-timing-and-review-skill-prompt.md
```

若现有测试把五个 Skill 名称写死，可对对应测试做最小调整。

## 禁止修改

```text
docs/architecture/a-share-short-horizon-engine-contract-v4.md
src/stock_analyzer/ops/forward_selection.py
src/stock_analyzer/analysis/price_scenario_validation.py
数据库 schema
数据采集来源
七种 engine_type
四种 engine_status
11个价格场景
D20目标定义
入口价格口径
自动任务数量
```

## 明确不做

- 不增加评分器、总分、权重或概率；
- 不新建“早期/中期/末期”数据库字段或状态机；
- 不增加第六个选股视角；
- 不建立复盘平台或第二套股票池；
- 不修改20%目标；
- 不用未来行情修改历史入选理由；
- 不因一个样例拟合大量阈值；
- 不增加新外部数据源；
- 不增加普通文档哈希或校验和；
- 不重构整个价格分析或跟踪模块；
- 不合并或删除 `research/ai-liquid-cooling-2026h2`。

---

# 五、执行纪律

本轮会修改正式选股判断和正式复盘合同。

按 `AGENTS.md`，实施前恰好进行一次独立审查：

```text
模型：gpt-5.6-sol
推理强度：xhigh
```

审查只回答：

1. 是否真正解决“确认太晚”和“风险已推翻推荐仍然入选”；
2. 是否误把涨幅大机械设为淘汰；
3. 新复盘 Skill 是否只是轻量综合，不是新平台；
4. 是否改变V4枚举、11个场景、D20或数据schema；
5. 是否存在过度工程化。

审查不实施、不调用其他子智能体。主智能体采用一次审查后的最小方案继续完成；此后不再启动子智能体。

---

# 第一阶段：基线与真实问题复现

## Task 1：读取当前实现

完整读取：

```text
AGENTS.md
docs/architecture/current-v3-architecture.md
docs/architecture/a-share-short-horizon-engine-contract-v4.md

.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/interpreting-market-macro/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/researching-company-events/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md

ops/forward-selection-prompt.md
ops/forward-monitor-prompt.md

src/stock_analyzer/analysis/price_indicator_validation.py
src/stock_analyzer/ops/forward_monitor.py

tests/test_price_indicator_validation.py
tests/test_v4_operational_prompts.py
tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py
tests/test_forward_monitor.py
```

运行：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_price_indicator_validation.py \
  tests/test_v4_operational_prompts.py \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py

./.venv/bin/python -m pytest -q
```

记录真实基线，不沿用历史汇报数字。

## Task 2：记录当前分支

运行：

```bash
git fetch origin --prune
git branch -r
```

当前远端原则上应只有：

```text
origin/main
origin/research/ai-liquid-cooling-2026h2
```

将结果写入：

```text
research/skill-optimization/entry-timing-review-skill-20260902/branch-status.md
```

不要合并液冷研究分支。它是独立研究运行，不是遗漏的选股功能。

---

# 第二阶段：补充“最大上涨日之外是否仍然强”的最小事实

## Task 3：先写价格字段失败测试

修改：

```text
tests/test_price_indicator_validation.py
```

为 `build_baseline_panel()` 增加以下测试。

### 情形A：最后一天单独大涨

构造最近5个交易日收益近似：

```text
0%、0%、0%、0%、10%
```

期望：

```python
largest_positive_day_contribution_5d == 1.0
sessions_since_largest_positive_day_5d == 0
return_ex_largest_positive_day_5d == 0.0
return_after_largest_positive_day_5d is NaN
relative_market_after_largest_positive_day_5d is NaN
```

### 情形B：较早上涨后继续上涨

构造最近5个交易日收益近似：

```text
6%、2%、1%、1%、1%
```

期望：

```python
largest_positive_day_contribution_5d == pytest.approx(6 / 11)
sessions_since_largest_positive_day_5d == 4
return_ex_largest_positive_day_5d > 0
return_after_largest_positive_day_5d > 0
relative_market_after_largest_positive_day_5d 可计算
```

### 情形C：没有正收益或窗口不完整

五个新增字段都应为 `NaN`，不得把“没有后续交易日”写成0收益。

先运行并确认失败：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_price_indicator_validation.py
```

## Task 4：增加五个原始观察字段

修改：

```text
src/stock_analyzer/analysis/price_indicator_validation.py
```

在 `build_baseline_panel()` 中增加：

```text
largest_positive_day_contribution_5d
sessions_since_largest_positive_day_5d
return_ex_largest_positive_day_5d
return_after_largest_positive_day_5d
relative_market_after_largest_positive_day_5d
```

### 精确定义

以形成日结束的最近5个有效交易日为窗口，使用复权收盘日收益：

1. `largest_positive_day_contribution_5d`  
   最大正收益 ÷ 五日所有正收益之和。

2. `sessions_since_largest_positive_day_5d`  
   最大正收益日之后已有多少个交易日，范围0—4。若最大值并列，选择更靠近形成日的那一天，避免虚构更多后续确认。

3. `return_ex_largest_positive_day_5d`  
   去掉最大正收益日后，其余四个交易日复合收益。

4. `return_after_largest_positive_day_5d`  
   最大正收益日之后至形成日的复合收益。最大正收益发生在形成日时，没有后续观察，写 `NaN`，不得写0。

5. `relative_market_after_largest_positive_day_5d`  
   同一后续窗口内，股票复合收益减去市场复合收益。没有后续观察时写 `NaN`。

只有五个股票日收益和对应市场日收益都完整时才计算。没有正收益时写 `NaN`。

### 版本要求

这是对现有 `price-analysis-context-v2` 增加向后兼容的原始观察字段：

- 不改变任何旧字段公式；
- 不修改11个场景；
- 不新增派生表；
- 本轮不做全库迁移；
- 不修改已有历史结果。

未来新交易日正常产生新增字段。历史影响分析直接从本地日行情临时计算，不覆盖历史冻结记录。

完成后运行：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_price_indicator_validation.py
```

---

# 第三阶段：修正正式入选时机

## Task 5：修改价格 Skill

修改：

```text
.agents/skills/analyzing-price-trading/SKILL.md
```

加入以下核心方法。

### 5.1 分开“获得的确认”和“已经付出的涨幅”

每只候选必须分别回答：

```text
获得的确认：
上涨是否分布在多个普通交易日；
是否持续强于市场和同行；
成交增加后收盘是否继续提高。

已经付出的涨幅：
最近5日、20日已经涨了多少；
最大上涨日贡献多少；
最大上涨日之后是否继续上涨；
当前是否只是刚突破，还是已在高位停滞。
```

最后必须明确写一个净结论：

```text
确认仍大于追高风险
追高风险已经大于确认
现有事实还无法判断
```

这是内部自然语言结论，不新增枚举或schema。

### 5.2 同一交易日造成的事实只能算一组证据

若最大上涨日同时造成：

- 5日涨幅较大；
- 相对市场或行业涨幅较大；
- 当日成交放大；
- 突破近期高点；

这些只能算一组“单日价格变化”，不能分别当成四条独立支持。

总控必须看到独立于该交易日的支持，例如：

- 其余四日仍上涨；
- 最大上涨日后继续上涨；
- 行业多数股票继续转强；
- 公司出现仍在兑现的新变化。

### 5.3 超过一半正收益来自单日时的处理

当：

```text
largest_positive_day_contribution_5d >= 0.50
```

或：

```text
limit_up_return_contribution_5d >= 0.50
```

必须进入“单日主导”判断：

- 最大上涨日就是形成日，尚无后续交易日时，不能仅凭该日形成正式推荐；
- 最大上涨日之后收益为负，或相对市场转弱时，不能写成持续性已经确认；
- 去掉最大上涨日后其余四天不涨时，5日涨幅、成交放大和突破不能继续重复充当支持；
- 若其余交易日仍上涨，且最大上涨日之后继续走强，才可以继续比较；
- 该判断不自动淘汰所有涨停股，也不改变 `fresh_event_pending` 的现有规则。

若最强不利事实已经推翻唯一价格支持，应淘汰或保持未决，不能正式推荐后再用长篇风险提示自我否定。

### 5.4 不同原因采用不同确认程度

#### 行业或公司变化明确

允许较早确认：

- 不要求先出现很大的5日涨幅；
- 连续普通交易日相对同行更强；
- 收盘逐步提高；
- 成交增加没有变成放量不涨；

即可交给总控综合比较。

#### 纯价格型

因为缺少外部原因，需要更强的多日证据：

- 去掉最大上涨日后仍强；
- 最大上涨日之后仍强；
- 多个收盘提高；
- 不能只依靠涨停或跳空。

## Task 6：修改总控 Skill

修改：

```text
.agents/skills/orchestrating-stock-research/SKILL.md
```

在同发动机比较和最终取舍中加入：

### 6.1 入选前必须作净判断

每只候选都必须回答：

```text
如果去掉最大上涨日带来的涨幅、相对收益、成交放大和突破，
还剩下哪些独立事实支持未来约20个交易日继续上涨？
```

如果剩下的只有：

```text
属于热门行业
公司基本面不错
最近涨得很多
```

不得形成正式推荐。

### 6.2 不再偏向“涨幅最大的候选”

同行比较优先看：

1. 行业或公司变化是否仍在继续；
2. 除去最大上涨日后是否仍然强；
3. 最大上涨日之后是否继续强；
4. 成交增加是否换来多个较高收盘；
5. 最近5日、20日已经付出多少涨幅；
6. 是否有同类股票在更早阶段已经出现真实确认。

在其他条件接近时，优先选择**确认已经出现但价格尚未主要靠一次大涨完成**的股票，不选涨幅最大者。

### 6.3 风险足以推翻时必须不选

正式推荐的“最需要担心什么”不能是已经成立、并且足以推翻核心推荐理由的事实。

例如：

```text
大部分涨幅来自形成日涨停
+
形成日后尚无普通交易日
+
其余交易日没有独立强势
```

这不是“推荐后需要提醒的风险”，而是“现在还不应正式推荐”的理由。

### 6.4 不把高位机械设为坏事

接近60日或250日高点时，判断重点是：

- 是否刚刚有效突破；
- 是否能在高点附近连续收稳；
- 是否有新变化继续推动；
- 是否出现放量不涨和冲高回落。

高位本身不自动支持或淘汰。

---

# 第四阶段：修改每日荐股 Prompt 和用户语言

## Task 7：修改 `forward-selection-prompt.md`

修改：

```text
ops/forward-selection-prompt.md
```

### 7.1 用户不再看到“冻结时点”

内部继续保留：

```text
formation_date
action_date
selection_as_of
```

面向用户统一改写为：

```text
我们在<action_date>开盘前选择这只股票，
使用的是截至<formation_date>收盘能够取得的信息。
```

复盘时统一写：

```text
这只股票在<action_date>开盘前被正式推荐。
```

用户正文禁止使用：

```text
冻结时点
冻结结论
形成日
行动日
正常双向成交
上涨覆盖
样本收窄
价格路径
反证
```

### 7.2 推荐理由必须先给净结论

每只正式推荐按以下顺序：

```markdown
**为什么在这个时间选择它**

先说明它处于：
- 较早确认阶段；
- 已有连续上涨但尚未明显过晚；
不得用内部标签，只用自然中文说明。

**支持选择的独立原因**

分别说明：
- 行业或公司为什么可能继续影响它；
- 除去最大上涨日后，股票本身为什么仍然强；
- 最大上涨日之后是否继续强；
- 为什么成交增加代表价格继续提高，而不是买卖激烈但涨不动。

**为什么不是追在短期高点之后**

明确说明最近5日和20日已经上涨多少；
最大上涨日贡献多少；
为什么这些涨幅还没有把主要机会消耗掉。
如果无法解释，不得正式推荐。

**最需要担心什么，以及为什么仍然选择**

只能保留一个最重要的不利事实。
必须说明它为什么尚未推翻推荐。
若无法说明，返回不推荐，不得用“后续观察”掩盖。

**什么情况会让我改变看法**

用普通中文说明：
- 若成交增加但股价不再上涨；
- 若最大上涨日后持续回落；
- 若原来多数同行上涨变成只剩少数股票上涨；
这些现象各自为什么会削弱原理由。
```

### 7.3 一拖股份不能再使用旧式结论

禁止再次写：

```text
5日上涨15.27%和成交2.24倍支持推荐，
67.37%来自涨停是风险，
后续观察。
```

必须先读取最大上涨日的真实日期和新增字段，再作以下二选一：

```text
A. 若最大上涨日就是选择前最后一个交易日，尚无后续确认：
   不形成正式推荐，说明要等一个普通交易日。

B. 若最大上涨日之后已经有交易日继续上涨，
   且去掉最大上涨日后其余四天仍为正：
   才能保留推荐，并清楚说明持续性证据。
```

不允许先假定一拖股份仍然入选。

---

# 第五阶段：形成日样本影响分析

## Task 8：用现有样本检查是否普遍追高

创建：

```text
research/skill-optimization/entry-timing-review-skill-20260902/entry-stage-impact.csv
research/skill-optimization/entry-timing-review-skill-20260902/entry-stage-findings.md
```

使用现有本地日行情，对 2026-08-20 至 2026-08-31 样本中的全部正式推荐，在各自选择时间点重新计算新增五个字段。

`entry-stage-impact.csv` 字段：

```text
event_key
formation_date
action_date
ts_code
name
engine_type
return_5d
return_20d
price_location_60d
limit_up_return_contribution_5d
largest_positive_day_contribution_5d
sessions_since_largest_positive_day_5d
return_ex_largest_positive_day_5d
return_after_largest_positive_day_5d
relative_market_after_largest_positive_day_5d
original_decision
revised_price_conclusion
revised_selection_effect
plain_reason
```

`revised_selection_effect` 只允许：

```text
keep
lower_priority
not_yet_formal
insufficient_data
legacy_not_rebuilt
```

规则：

- 只使用各自选择前已存在的行情；
- 不使用推荐后的收益决定改判；
- 旧V1记录可以标记 `legacy_not_rebuilt`；
- 不修改历史归档；
- 不拟合收益最优阈值；
- 汇总有多少股票属于单日主导、最大上涨日位于最后一天、去掉最大日后不再上涨。

## Task 9：重新判断一拖股份

创建：

```text
research/skill-optimization/entry-timing-review-skill-20260902/one-tuo-entry-reassessment.md
```

从本地读取一拖股份选择前真实5日行情，写清：

- 最大上涨日是哪一天；
- 是否为涨停日；
- 当天贡献多少；
- 去掉该日后其余四天复合涨跌；
- 最大上涨日之后还有几个交易日；
- 后续复合涨跌和相对市场表现；
- 按新方法是否仍能正式推荐。

不得为了保持旧结论而强行保留。

---

# 第六阶段：增加一个轻量专用复盘 Skill

## Task 10：创建复盘 Skill

创建：

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
.agents/skills/reviewing-stock-recommendations/agents/openai.yaml
```

### `SKILL.md` 的定位

```markdown
---
name: reviewing-stock-recommendations
description: Use only after a stock was explicitly recommended, to compare the dated original thesis with actual price, sector, company and market developments and explain progress toward the 20-trading-day 20% observation target.
---

# 正式推荐复盘

## 唯一职责

本 Skill 不发现候选、不选择股票、不改变历史推荐，也不是第六个选股视角。

它只接收：

- 明确正式推荐的记录；
- 推荐日期和当时完整理由；
- 推荐后的价格与成交事实；
- 市场、行业、公司和价格四个 Skill 的 review 结果；
- 已有 `ForwardEpisodeReviewV1` 字段。

它负责把这些事实合成一份用户能理解的复盘。

## 每次必须回答

1. 这只股票在具体哪一天开盘前被推荐；
2. 当时最重要的判断是什么；
3. 当时期待随后看到什么；
4. 到今天观察了多少个交易日；
5. 当前收盘涨跌、期间最高、期间最深下跌；
6. 距离20%观察目标还有多少个百分点；
7. 后来的事实为什么支持或反对当时判断；
8. 哪一项预期实现了，哪一项没有实现；
9. 现在应评价为继续成立、明显减弱、已经不成立或暂时无法判断；
10. 接下来哪件具体事情会改变结论。

## 分析原则

- 股票上涨不自动证明当初理由正确；必须比较市场、同行和原预期。
- 股票下跌也不自动证明公司事实错误；要指出失败发生在哪一层。
- 不按每天1%的线性速度评价。
- 停牌期间不虚构价格进展；先说停牌前走到哪里，再说新公告怎样改变公司背景，最后说明复牌后需要验证什么。
- 一条无关月报、公告标题或局部数据缺失不能决定整只股票的结论。
- 能用已有价格、行业和公司事实分析时，不得把整段结论写成“资料不足”。
- 不使用“冻结时点、冻结结论、原逻辑、传播链、正常双向成交”等用户难以理解的词。
- 必须使用具体推荐日期。

## 输出

继续填写现有 `ForwardEpisodeReviewV1`，不增加schema。

`original_reason_plain_language`：
写成“该股票在YYYY年M月D日开盘前被推荐，当时主要因为……”。

`current_review`：
必须包含“当时预期 → 实际变化 → 为什么支持或反对 → 当前结论”。

其他枚举只供内部记录，不直接显示给用户。
```

### `openai.yaml`

```yaml
interface:
  display_name: "正式推荐复盘"
  short_description: "把推荐日判断与后续走势、公司和行业变化进行对照，说明20日目标进展"
  default_prompt: "使用 $reviewing-stock-recommendations 复盘一只明确正式推荐过的股票，不重新选股。"
```

## Task 11：接入现有流程

修改：

```text
AGENTS.md
.agents/skills/orchestrating-stock-research/SKILL.md
ops/forward-monitor-prompt.md
```

明确：

- 原五个 Skill 继续负责选股；
- 市场、行业、公司和价格 Skill 的 review 阶段只提供各自事实与解释；
- 新复盘 Skill 负责跨时间综合和最终用户文字；
- 总控只检查记录一致性，不重复写一套复盘方法；
- 不新增定时任务；
- 不新增报告模型；
- 最终仍写入现有 `ForwardEpisodeReviewV1` 和 `DailyForwardMonitorReportV2`。

---

# 第七阶段：数据缺口先补一次，再说明限制

## Task 12：修改复盘数据处理说明

在：

```text
ops/forward-monitor-prompt.md
```

增加：

### 核心或行业日数据缺失

如果 snapshot 出现：

```text
missing_price_path
missing_current_price_context
missing_market_context
missing_sector_context
```

且对应交易日已经收盘，先按缺失类型补一次：

```bash
./.venv/bin/python -m stock_analyzer data run-stage \
  --stage close \
  --data-date <analysis_date>

./.venv/bin/python -m stock_analyzer data run-stage \
  --stage next-morning \
  --data-date <analysis_date>
```

只有价格/市场缺失时才补 `close`；只有行业、主题或公告缺失时只补 `next-morning`。然后重新运行一次 monitor prepare。

不得循环重试。

### 公司财务或公告正文缺失

- 若该材料会直接改变原推荐判断，由公司 Skill 沿现有官方链接定向读取一次；
- 若只是无关月报、例行公告或非核心细节，不得让它主导复盘；
- 不为一只股票启动全市场财务回填；
- 不增加新数据源；
- 仍缺失时，只说明哪一项无法核对，继续分析其他已有事实。

只有入口价格或整段行情确实不存在，才可以说无法评价目标进展。

---

# 第八阶段：复盘要显示20%目标进展并解释原因

## Task 13：修改 Markdown 渲染

修改：

```text
src/stock_analyzer/ops/forward_monitor.py
```

不改任何模型或数据库。

增加一个小函数：

```python
def _render_target_progress(episode: dict[str, Any]) -> str:
    ...
```

使用现有字段：

```text
action_date
day_number
current_close_return_since_entry
current_max_close_return_since_entry
current_max_high_return_since_entry
current_mae_since_entry
current_close_drawdown_from_peak
current_first_close_hit_20pct_date
current_first_high_hit_20pct_date
```

输出规则：

1. 先写具体日期：

```text
这只股票在2026年8月25日开盘前被正式推荐。
```

2. 当前收盘未到20%：

```text
到今天是推荐后的第6个交易日，收盘较参考价上涨2.68%，
离20%的观察目标还差17.32个百分点。
期间最高上涨4.66%，最深下跌1.63%。
```

3. 盘中到过20%、收盘没有站住：

```text
盘中曾达到20%，但收盘没有保持在该位置，说明目标曾被触及但没有站稳。
```

4. 收盘达到20%：

```text
收盘已经达到20%的观察目标，继续记录到第20个交易日，
判断达到后是否明显回吐。
```

5. 没有可靠入口价格：

```text
没有可靠的推荐参考价，因此不能计算距离20%目标的进展。
```

不要用线性每日速度评价。

### 用户复盘顺序

每只正式推荐股票只使用：

```markdown
**推荐日期和当时判断**

**到今天走到哪里**

**后来发生了什么**

**这些变化为什么支持或反对当时判断**

**现在怎么看**

**接下来关注什么**
```

其中：

- `_render_target_progress()` 只负责确定性数字；
- `review.current_review` 负责解释为什么；
- 不把数据限制写成主要结论；
- 不展示待确认事件、比较股或普通关注股；
- 不使用“当初看中它”，必须使用具体日期；
- 不使用“冻结结论”。

## Task 14：更新正式复盘样例

创建：

```text
research/skill-optimization/entry-timing-review-skill-20260902/review-sample.md
```

至少覆盖：

- 一只正常上涨但离20%仍远的正式推荐；
- 一只突破后跌回前高下方的正式推荐；
- 一只停牌的正式推荐。

每只都必须：

- 写具体推荐日期；
- 显示目标进展；
- 恢复推荐时的核心预期；
- 说明实际变化为什么支持或反对；
- 不能以“资料不足”结束全部分析；
- 停牌股说明停牌前进展、新公告影响和复牌后要验证的事情。

---

# 第九阶段：测试

## Task 15：Prompt 与 Skill 测试

修改：

```text
tests/test_v4_operational_prompts.py
tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py
```

至少断言：

```text
获得的确认
已经付出的涨幅
去掉最大上涨日
最大上涨日之后
不能一边说核心持续性没有验证一边正式推荐
具体推荐日期
距离20%观察目标
reviewing-stock-recommendations
不新增定时任务
```

用户输出段不得包含：

```text
冻结时点
冻结结论
正常双向成交
农业样本
```

不要对所有自然语言建立大规模禁词扫描，只检查固定 Prompt 和样例。

## Task 16：复盘代码测试

修改：

```text
tests/test_forward_monitor.py
```

至少覆盖：

1. 第6个交易日当前收益2.68%：

```text
离20%的观察目标还差17.32个百分点
```

2. 盘中达到20%、收盘低于20%：

```text
盘中曾达到20%
收盘没有保持
```

3. 收盘达到20%：

```text
收盘已经达到20%的观察目标
```

4. 无入口价格：

```text
不能计算距离20%目标的进展
```

5. 输出含具体推荐日期，不含“当初看中它”“冻结结论”。

6. conditional、comparator 仍保存在内部 JSON，但不出现在用户 Markdown。

7. 原D20冻结结果不变。

## Task 17：完整测试

```bash
./.venv/bin/python -m pytest -q \
  tests/test_price_indicator_validation.py \
  tests/test_v4_operational_prompts.py \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py

./.venv/bin/python -m pytest -q

git diff --check
```

不得删除旧测试换取通过。

---

# 第十阶段：提交、合并和分支收口

## Task 18：提交功能分支

```bash
git add \
  AGENTS.md \
  docs/2026-09-02-entry-timing-and-review-skill-prompt.md \
  .agents/skills/orchestrating-stock-research/SKILL.md \
  .agents/skills/analyzing-price-trading/SKILL.md \
  .agents/skills/reviewing-stock-recommendations/SKILL.md \
  .agents/skills/reviewing-stock-recommendations/agents/openai.yaml \
  ops/forward-selection-prompt.md \
  ops/forward-monitor-prompt.md \
  src/stock_analyzer/analysis/price_indicator_validation.py \
  src/stock_analyzer/ops/forward_monitor.py \
  tests/test_price_indicator_validation.py \
  tests/test_v4_operational_prompts.py \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py \
  research/skill-optimization/entry-timing-review-skill-20260902

git commit -m \
  "fix: distinguish early confirmation from late price chasing"
```

推送：

```bash
git push -u origin codex/entry-timing-and-review-skill-20260902
FEATURE_HEAD="$(git rev-parse HEAD)"
```

## Task 19：快进合并到实际运行的 main

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
MAIN_HEAD="$(git rev-parse main)"
REMOTE_MAIN_HEAD="$(git rev-parse origin/main)"

test "$MAIN_HEAD" = "$FEATURE_HEAD"
test "$REMOTE_MAIN_HEAD" = "$FEATURE_HEAD"
test -z "$(git status --short)"
```

每日 Scheduled Task 已使用实际项目根目录的 `main`，只核对现有设置，不创建第二个任务。

## Task 20：删除本轮已合并功能分支

先验证：

```bash
git fetch origin --prune

git merge-base --is-ancestor \
  origin/codex/entry-timing-and-review-skill-20260902 \
  origin/main
```

验证通过后：

```bash
git push origin --delete \
  codex/entry-timing-and-review-skill-20260902

git branch -d \
  codex/entry-timing-and-review-skill-20260902

git worktree remove \
  "$PROJECT_ROOT/.worktrees/entry-timing-and-review-skill-20260902"

git fetch origin --prune
```

不得使用强制删除。

最终远端应只保留：

```text
main
research/ai-liquid-cooling-2026h2
```

液冷研究分支不合并、不删除、不改写。

---

# 十一、最终验收

必须全部满足：

## 入选时机

- [ ] 不再把5日涨幅、相对涨幅、成交放大和突破当成四条独立支持；
- [ ] 能识别最大上涨日贡献；
- [ ] 能识别最大上涨日之后是否继续上涨；
- [ ] 最大上涨日为最后一天且无后续确认时，不形成普通正式推荐；
- [ ] 行业或公司原因明确的股票可以在较早确认阶段入选；
- [ ] 纯价格型股票要求更扎实的普通交易日持续性；
- [ ] 高位本身不自动支持或淘汰；
- [ ] 最强不利事实已经推翻核心依据时必须不选。

## 用户语言

- [ ] 使用具体日期；
- [ ] 不出现“冻结时点”“冻结结论”；
- [ ] 不出现“正常双向成交”“样本收窄”；
- [ ] 解释为什么支持、为什么反对、为什么最后仍选或不选。

## 复盘

- [ ] 新增专用复盘 Skill，但不参与选股；
- [ ] 不新增schema、数据库或定时任务；
- [ ] 显示当前、最高、最深下跌和距离20%目标；
- [ ] 不按每天1%线性评价；
- [ ] 说明后来事实为什么验证或否定推荐日判断；
- [ ] 数据缺失先用现有流程补一次；
- [ ] 一条无关公告不决定整只股票；
- [ ] 只复盘明确正式推荐。

## 工程范围

- [ ] 不修改七种发动机、四种状态、11个价格场景；
- [ ] 不修改D20和入口价格定义；
- [ ] 不增加评分器、权重、概率或语言平台；
- [ ] 不增加新数据源；
- [ ] 不增加普通文档哈希；
- [ ] 完整测试通过；
- [ ] main 本地与远端一致；
- [ ] 本轮功能分支已删除；
- [ ] 液冷研究分支仍保留。

---

# 十二、Codex 最终汇报格式

```markdown
已完成：A股入选时机与专用复盘 Skill 优化

## GitHub
- 基线：`b2c742c889dc380bd2fbce1c30db3b056364eb70`
- main最终提交：`<HEAD>`
- 对比链接：<URL>
- 科学依据：<scientific-rationale.md URL>
- 入选时机统计：<entry-stage-findings.md URL>
- 一拖股份重新判断：<one-tuo-entry-reassessment.md URL>
- 复盘样例：<review-sample.md URL>

## 入选时机
- 新增价格观察字段：<五项>
- 单日主导的正式推荐处理：<说明>
- 行业/公司型如何更早确认：<说明>
- 纯价格型如何避免单日冲高：<说明>
- 一拖股份按新方法：保留/降低优先级/暂不正式推荐
- 一拖股份的真实原因：<说明>

## 样本影响
- 可重建正式推荐数：<数量>
- 单日贡献超过一半：<数量>
- 最大上涨日为最后一天：<数量>
- 去掉最大日后不再上涨：<数量>
- 新方法保持：<数量>
- 降低优先级：<数量>
- 暂不正式推荐：<数量>

## 复盘 Skill
- 新 Skill：`reviewing-stock-recommendations`
- 是否参与选股：否
- 是否新增schema：否
- 是否新增定时任务：否
- 是否显示具体推荐日期：是
- 是否显示距离20%目标：是
- 是否解释实际变化为什么支持或反对：是

## 数据缺口
- 核心/行业数据补取方式：<说明>
- 公司正文补取方式：<说明>
- 是否增加新数据源：否
- 是否允许无关公告决定整只股票：否

## 验证
- 基线定向测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- `git diff --check`：<结果>
- main本地/远端一致：是/否
- 工作区干净：是/否

## 分支
- 远端保留：`main`、`research/ai-liquid-cooling-2026h2`
- 本轮功能分支是否已删除：是/否
- 液冷研究分支是否保持不变：是/否

## 明确未做
- 未增加评分器、权重、概率
- 未修改七种发动机、四种状态和11个价格场景
- 未修改D20和入口价格
- 未新增数据库、数据源或复盘平台
- 未用未来结果改写历史选择
```

只有完整测试通过、样本影响已实际计算、一拖股份基于真实五日顺序重新判断、新复盘 Skill 已接入现有日报、功能提交快进进入 `main` 并删除本轮功能分支后，才可以声称完成。
