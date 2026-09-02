# A股正式推荐复盘因果分析优化——Codex执行指令 V1.0

> **直接执行本文件。不要把它改写成“增加更多复盘栏目”“增加数据检查”或“搭建复盘平台”。**
>
> 当前荐股说明已经基本可读。本轮只解决正式推荐股票的复盘：
>
> - 不再把客观数据分栏重复一遍；
> - 必须判断股票推荐后为什么这样涨、跌或横盘；
> - 必须说明这一变化与推荐时的判断有什么关系；
> - 必须给出下一阶段更可能怎样发展的有条件判断；
> - 仍然只复盘明确正式推荐过的股票。
>
> 这是个人股票助手。不得过度工程化，不得过度防御，不得增加评分器、复杂状态机、数据库表、第二套任务或新的研究平台。

---

# 一、仓库、基线与分支

## 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

## 唯一基线

```text
分支：main
提交：04b0fde12372ffd3ed7255663d2f017390d75ae4
```

## 新功能分支

```text
codex/causal-recommendation-review-20260902
```

## 创建独立 worktree

在实际项目根目录执行：

```bash
git fetch origin --prune

test "$(git rev-parse origin/main)" = \
  "04b0fde12372ffd3ed7255663d2f017390d75ae4"

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BASE_HEAD="$(git rev-parse origin/main)"
WORKTREE="$PROJECT_ROOT/.worktrees/causal-recommendation-review-20260902"

git worktree add \
  "$WORKTREE" \
  -b codex/causal-recommendation-review-20260902 \
  "$BASE_HEAD"

cd "$WORKTREE"

test "$(git rev-parse HEAD)" = "$BASE_HEAD"
test "$(git branch --show-current)" = \
  "codex/causal-recommendation-review-20260902"
test -z "$(git status --short)"
```

将本文件原样保存为：

```text
docs/2026-09-02-causal-recommendation-review-prompt.md
```

---

# 二、当前复盘为什么仍然失败

必须先读取本地实际产物：

```text
local_archive/forward_monitor/monitor-report-2026-09-01.md
local_archive/forward_monitor/monitor-report-2026-09-01.json
local_archive/forward_monitor/snapshot-2026-09-01.json
```

如果文件日期不同，以用户刚刚重跑得到的同一份正式复盘日期为准。

当前输出的问题不是数据太少，而是方法和展示同时有问题。

## 1. 同一批事实被重复三次

目前每只股票依次输出：

```text
到今天走到哪里
后来发生了什么
这些变化为什么支持或反对
现在怎么看
接下来关注什么
```

“后来发生了什么”先输出相对市场、相对行业，再把公司、行业、股票和市场变化全部拼接；“这些变化为什么……”又复述一遍；“现在怎么看”最后只输出“得到支持”或“部分支持”。

这会造成：

```text
事实很多
+
判断只有一句标签
+
用户仍不知道为什么这样涨跌
```

## 2. 专用复盘 Skill 仍是检查清单，不是分析方法

当前 `reviewing-stock-recommendations` 要求回答十项内容，但没有规定：

- 如何判断上涨主要来自市场、行业、公司消息还是股票自身；
- 如何判断成交放大是继续上涨的支持，还是高位换手和卖压；
- 如何判断上涨后的回落属于正常整理，还是原判断开始失败；
- 如何从当前状态推演未来1—3个交易日和剩余观察期。

因此 Codex 会逐项填满事实，却不会形成完整判断。

## 3. 代码强制输出一个没有信息量的结论

当前 `_render_markdown()` 会把：

```text
current_assessment=supported
```

自动翻译成：

```text
当初的核心预期目前得到支持。
```

这类句子没有回答“为什么”，还会与前面的 `current_review` 重复。

## 4. 代码把内部变化字段直接拼给用户

当前会把：

```text
company_change
sector_change
stock_change
market_change
why_reported
```

全部拼进“后来发生了什么”。

这些字段适合内部归档和生成分析，不适合直接给用户阅读。它们容易带出：

- 数据是否存在；
- 哪个检查点触发；
- 哪个内部场景变化；
- 一条与推荐判断无关的例行公告。

## 5. 后续判断只是条件清单，不是发展判断

当前“接下来关注什么”只是把确认条件和失效条件机械拼接，甚至出现：

```text
。。如果若……。，说明……
```

用户得到的是两个检查条件，却不知道：

```text
按照目前证据，最可能先继续上涨、横盘消化，还是回落？
为什么？
```

---

# 三、科学的复盘方法

本轮采用一个简单的五步方法，不增加评分，不增加新模型。

```text
结果
→ 主要驱动
→ 推荐理由验证
→ 当前所处阶段
→ 后续更可能怎样
```

## 第一步：先说结果，不急着解释

使用现有确定性数据说明：

- 具体推荐日期；
- 已观察多少个交易日；
- 当前收盘相对推荐参考价涨跌；
- 期间最高；
- 期间最深下跌；
- 从期间最高回落多少；
- 距离20%观察目标还有多少。

这一段只负责事实，不在这里得出原因。

## 第二步：判断这段涨跌最可能由什么驱动

使用现有 `best_supported_explanation`，但最终给用户时不用英文枚举。

只允许五类主要解释：

### A. 市场共同上涨或下跌

特征：

- 股票与全市场涨跌接近；
- 没有明显跑赢市场；
- 同时没有重要公司新消息。

结论应类似：

```text
这段上涨主要跟随市场，并不能证明推荐时认为它会独立走强的判断已经实现。
```

### B. 行业共同变化

特征：

- 行业大多数股票同步上涨或下跌；
- 股票相对行业没有明显领先；
- 公司没有足以单独解释股价的新变化。

结论应类似：

```text
这段上涨主要来自整个行业，说明方向判断可能正确，但还不能证明具体股票选得最好。
```

### C. 公司新变化

特征：

- 推荐后出现与主营直接相关、可能影响经营的新公告或经营事实；
- 新变化前后，股票相对市场和行业出现明显不同表现；
- 例行月报、会议通知、公告标题不能算主要解释。

结论应类似：

```text
公司新订单公布后，股票开始明显跑赢同行，这使公司消息成为目前最有证据的解释。
```

不能只因为公告存在，就把涨跌归因于公告。

### D. 股票自身表现

特征：

- 股票明显跑赢市场和行业；
- 没有足以解释的公司新消息；
- 成交增加后多个收盘继续提高，而不是只在盘中冲高。

结论应类似：

```text
这段上涨不能由市场或行业解释，当前更像是股票自身延续了推荐前的强势。
```

不得写成“主力流入”“机构抢筹”或臆测交易主体。

### E. 混合或暂时无法判断

市场、行业、公司和股票自身同时有影响，或关键事实互相冲突时，明确写：

```text
目前更像是行业上涨和股票自身走强共同作用，无法把全部涨幅归给一个原因。
```

不知道时可以说不知道，不编故事。

## 第三步：检验推荐时的核心判断

每次推荐都有一个最重要的预期，例如：

- 突破前高后能够站稳；
- 行业多数股票继续转强；
- 该股继续强于同行；
- 公司新变化开始得到股价响应；
- 成交增加后收盘继续提高。

复盘必须明确回答：

```text
这个核心预期实现了吗？
为什么？
```

不能只写“部分支持”。

## 第四步：判断当前所处阶段

不新增内部枚举，但分析文字必须从以下自然判断中选择最贴近的一种：

- **仍在继续走强**：当前收盘接近推荐后最高，仍跑赢市场或行业，成交增加仍推动收盘。
- **上涨后整理**：仍高于推荐参考价，回落有限，相对优势没有明显消失，但短期不再继续创新高。
- **上涨开始失速**：成交仍大，收盘却不再提高；上影和回落增加；相对优势缩小。
- **原判断明显减弱**：跌回原突破位置下方、开始跑输同行，或公司/行业原依据已经消失。
- **原判断已经失败**：后来的事实与推荐时最核心预期相反。
- **无法执行而不是资料不足**：推荐日停牌或没有可靠可参与价格，不能评价20%目标，应说明这是无法按计划参与，不是普通数据缺失。

## 第五步：给出有条件的后续判断

不承诺未来，也不能只给观察条件。

必须先给一个基准判断：

```text
按照现在的走势，未来1—3个交易日更可能：
继续走强
震荡偏强
高位整理
横盘等待
继续回落
无法判断
```

然后说明为什么，再说什么情况会改变这个判断。

例如：

```text
目前更可能在高位整理，而不是立即连续上涨。原因是股价仍接近推荐后的最高收盘，但盘中高点回落较多，说明上涨时已经出现明显卖压。若后续成交没有继续放大、收盘重新接近前高，才可能恢复上行；若成交放大却连续收低，回落可能继续。
```

不得给数值概率，不建立情景评分表。

---

# 四、研究依据

创建：

```text
research/skill-optimization/causal-recommendation-review-20260902/scientific-basis.md
```

只写与本轮复盘方法有关的简要依据。

## 1. 事件研究

A. Craig MacKinlay，《Event Studies in Economics and Finance》，Journal of Economic Literature，1997。

采用的结论：

- 评价公司事件不能只看股票原始涨跌；
- 应当扣除市场和行业共同变化，观察异常表现；
- 事件重叠、同期市场变化会使归因复杂；
- 所以复盘使用“最有证据的解释”，不声称已经证明唯一真实原因。

## 2. 成交与价格

Charles M. C. Lee、Bhaskaran Swaminathan，《Price Momentum and Trading Volume》，Journal of Finance，2000，DOI 10.1111/0022-1082.00280。

采用的结论：

- 成交活跃程度会影响趋势延续和反转；
- 高成交本身不是单向利好；
- 成交放大必须结合价格方向、收盘位置、回落和持续时间解释。

## 3. 研究与沟通

CFA Institute Standard V(A) 与 V(B)。

采用的结论：

- 推荐和复盘要有合理、充分的研究基础；
- 要理解模型和量化工具的假设与限制；
- 要区分事实与判断；
- 对用户只保留真正重要的正面、负面因素和过程变化；
- 不能只输出模型结论或事实清单。

## 4. 券商点评写法

参考当前券商公司点评常见结构：

```text
先给结论
→ 拆解主要原因
→ 指出哪项业务或市场变化产生影响
→ 判断这种变化能否持续
→ 给出风险
```

只学习结构，不复制“景气度、催化、估值修复、预期差”等套话，也不给目标价和仓位。

---

# 五、修改范围

## 允许修改

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md

ops/forward-monitor-prompt.md

src/stock_analyzer/ops/forward_monitor.py

tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py
tests/test_forward_monitor.py

research/skill-optimization/causal-recommendation-review-20260902/
docs/2026-09-02-causal-recommendation-review-prompt.md
```

如果当前测试文件对用户标题写死，可只做紧邻的最小修改。

## 禁止修改

```text
AGENTS.md
ops/forward-selection-prompt.md

.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/interpreting-market-macro/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/researching-company-events/SKILL.md

src/stock_analyzer/ops/forward_selection.py
src/stock_analyzer/analysis/price_indicator_validation.py
src/stock_analyzer/analysis/price_scenario_validation.py

数据库schema
数据采集来源
七种engine_type
四种engine_status
11个价格场景
20%目标定义
入口价格定义
自动任务
```

## 明确不做

- 不新增 Review V3、报告模型或Pydantic字段；
- 不增加评分、权重、概率；
- 不增加第二个复盘 Skill；
- 不增加数据库表；
- 不增加定时任务；
- 不新增外部数据源；
- 不逐股搜索新闻网站解释涨跌；
- 不猜“主力”“机构”“游资”；
- 不修改历史正式推荐和历史20天结论；
- 不覆盖用户已经生成的 `local_archive` 正式报告；
- 不为自然语言建立复杂自动评分器；
- 不为普通文档增加哈希；
- 不处理液冷研究分支。

---

# 六、执行纪律

本轮修改正式复盘合同，因此按 `AGENTS.md`：

- 实施前恰好启动一次 `gpt-5.6-sol`、`xhigh` 的独立审查；
- 审查只检查本文件是否能形成真正分析、是否误改选股、是否增加无必要schema或平台；
- 审查不实施、不调用其他子智能体；
- 主智能体采用一次审查后的最小修订；
- 此后不再启动其他子智能体。

---

# 第一阶段：建立基线诊断

## Task 1：读取当前代码与实际报告

完整读取：

```text
AGENTS.md
.agents/skills/reviewing-stock-recommendations/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md
ops/forward-monitor-prompt.md
src/stock_analyzer/ops/forward_monitor.py

tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py
tests/test_forward_monitor.py

local_archive/forward_monitor/monitor-report-2026-09-01.md
local_archive/forward_monitor/monitor-report-2026-09-01.json
local_archive/forward_monitor/snapshot-2026-09-01.json
```

如果本地报告日期不同，使用用户最新重跑的实际日期。

运行：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py

./.venv/bin/python -m pytest -q
```

记录真实基线。

## Task 2：写根因诊断

创建：

```text
research/skill-optimization/causal-recommendation-review-20260902/current-output-diagnosis.md
```

必须用最新实际报告中的至少四只股票说明：

- 哪些事实被重复；
- 哪个结论只是标签；
- 为什么没有形成主要原因判断；
- 为什么没有形成后续基准判断；
- 哪些数据缺失表述与已存在数据互相矛盾；
- 哪些句子是代码机械拼接造成的。

至少覆盖：

```text
华昌化工
中信银行
金岭矿业
德尔股份
```

---

# 第二阶段：补足复盘真正需要的已有价格信息

## Task 3：先写失败测试

修改：

```text
tests/test_forward_monitor.py
```

在 snapshot 复制测试中增加以下字段：

```text
return_1d
return_3d
return_5d
up_days_5d
relative_continuity_5d
largest_positive_day_contribution_5d
sessions_since_largest_positive_day_5d
return_ex_largest_positive_day_5d
return_after_largest_positive_day_5d
relative_market_after_largest_positive_day_5d
price_location_60d
```

这些字段已经存在于当前 `price_analysis_context`，本轮只把它们复制进 monitor snapshot。

先运行相关测试，确认修改前失败。

## Task 4：扩充 `_price_fields()`

修改：

```text
src/stock_analyzer/ops/forward_monitor.py
```

仅扩充 `_price_fields()` 的 mapping，将上述已有字段复制到 snapshot。

要求：

- 不新增计算公式；
- 不修改 `price-analysis-context-v2`；
- 不新增表；
- 字段缺失时保持 `None`；
- 不影响历史已保存报告；
- 不改变任何提醒触发规则。

这些信息用于复盘判断：

- 最近上涨是否连续；
- 是否主要由一个交易日造成；
- 最大上涨日后是否继续上涨；
- 当前成交是否真正推动收盘。

---

# 第三阶段：重写专用复盘 Skill 的分析方法

## Task 5：重写 `reviewing-stock-recommendations/SKILL.md`

保留“不参与选股、不改变历史推荐、不增加schema”的定位。

将当前十项检查清单改为以下方法。

## 必须先确定一个主要解释

使用现有：

```text
best_supported_explanation
```

但不能只填枚举。`current_review` 必须说明：

```text
主要解释是什么
为什么市场、行业、公司或股票自身中这一项证据最强
哪个替代解释不能解释全部走势
```

### 市场共同变化

若股票没有明显跑赢市场，不得把上涨说成股票自身强势。

### 行业共同变化

若股票与行业接近，只能说明行业判断可能成立，不能证明具体股票选择优秀。

### 公司变化

只有与主营直接相关的新事实，并且股票在消息前后相对市场或行业出现不同表现时，才可把公司变化作为主要解释。

### 股票自身变化

只有明显跑赢市场和行业、且成交增加后多个收盘继续提高时，才可这样判断；不得推断交易主体。

### 混合或未知

证据不足时明确混合或未知。

## 必须解释成交的含义

价格 Skill提供成交事实后，复盘 Skill按以下条件解释：

```text
上涨 + 成交增加 + 收盘接近高位
= 上涨仍有持续买盘支持的证据

上涨 + 成交增加 + 上影/回落增加
= 买卖激烈，但卖压同时增大

横盘或下跌 + 成交增加
= 成交活跃不能支持继续上涨，可能是获利兑现或分歧加大

成交下降 + 价格仍稳
= 可能是上涨后整理，不自动判弱

成交下降 + 价格下跌 + 相对表现转弱
= 原有强势更可能正在消退
```

不把成交额本身当成原因。

## 必须判断价格所处阶段

`current_review` 必须自然说明是：

```text
继续走强
上涨后整理
上涨开始失速
原判断明显减弱
原判断已失败
无法执行
```

不新增枚举。

## 必须给出后续基准判断

`current_review` 或最终展望必须说明：

```text
未来1—3个交易日更可能怎样
为什么
什么事实会改变这个判断
```

不得只写“继续观察”。

## `current_review` 固定内容

每条 `current_review` 必须包含四部分，但写成一段自然分析：

```text
1. 这段涨跌最可能由什么驱动；
2. 推荐时最重要的预期是否实现；
3. 当前属于继续上涨、整理、失速还是失败；
4. 未来1—3个交易日更可能怎样以及原因。
```

建议150—300个中文字，不自动检查字数。

## 不能出现的退化写法

```text
当前得到支持。
部分预期已经发生。
仍需观察。
资料不足。
成交放大，价格上涨。
```

单独出现都不构成完整分析。

---

# 第四阶段：加强价格 Skill 的 review 输入

## Task 6：只修改价格 Skill 的 Review 阶段

修改：

```text
.agents/skills/analyzing-price-trading/SKILL.md
```

不改 discovery 和 validation。

Review 阶段必须向专用复盘 Skill说明：

1. 推荐后价格是连续上升、先涨后回落、横盘还是持续下跌；
2. 当前收盘是否接近推荐后最高；
3. 最近1、3、5日绝对涨跌；
4. 最近是否仍跑赢市场和行业；
5. 成交增加时，收盘是否提高；
6. 最大上涨日贡献多少；
7. 最大上涨日之后是否继续上涨；
8. 上影和冲高回落是否增加；
9. 原突破位置是否站稳；
10. 最符合哪种价格阶段。

不得只返回数字；必须解释数字为什么支持“继续、整理、失速或失败”。

---

# 第五阶段：重写复盘 Prompt 的字段职责

## Task 7：修改 `ops/forward-monitor-prompt.md`

### 7.1 明确各字段用途

加入：

```markdown
### 内部事实与最终分析分开

- `market_change`、`sector_change`、`company_change`、`stock_change`：只保存内部事实，不直接拼给用户。
- `best_supported_explanation`：选择当前最有证据的主要解释。
- `current_assessment`：内部状态，不直接翻译成一句空结论。
- `current_weak_or_failed_link`：内部记录哪一部分正在减弱，不单独展示。
- `current_review`：专用复盘 Skill 生成的完整分析，是用户复盘的核心。
- `outlook_1_3d`：下一阶段基准方向。
- `confirmation_condition`、`invalidation_condition`：各写成一整句普通中文，分别说明什么会增强和改变基准判断。
```

### 7.2 `why_reported` 只解释为什么今天复盘

只能写：

```text
到了固定复盘日
出现与原判断相关的新公告
价格表现明显转强或转弱
突破位置发生变化
第一次达到20%目标
```

不得在 `why_reported` 中塞入分析结论和所有数据。

### 7.3 主要原因判断

要求：

```markdown
复盘不能声称已经知道唯一真实原因。应使用“目前最有证据的解释”“更可能”“主要由……解释”等说法。

先比较股票与市场，再比较股票与行业，最后看公司新变化及股票自身的收盘和成交。只有后来的表现无法被市场和行业解释时，才把股票自身变化作为主要解释。
```

### 7.4 行业数据不要笼统说缺失

明确：

```markdown
- `relative_industry_*` 存在时，可以判断股票是否跑赢行业；
- `sector_breadth_*` 或行业成员统计缺失时，只能说“无法核对行业多数股票是否仍同步变化”；
- 不得一边写“比行业强多少”，一边又写“行业数据全部不可用”；
- 行业广度缺失不能抹掉已经存在的个股相对行业结果；
- 只有原推荐主要依赖行业共同变化时，行业广度缺失才是重要限制。
```

### 7.5 停牌不是普通资料不足

```markdown
推荐日没有可参与价格或随后停牌时，直接说明这次推荐无法按计划执行。不能把它写成普通“资料不足”，也不能假装继续计算20%目标。

停牌前有价格时，先分析停牌前走势；停牌后新公告只说明可能改变复牌后的关注点，不预测一定上涨或下跌。
```

### 7.6 未来发展判断

`outlook_1_3d` 与文字对应：

```text
strengthening           → 更可能继续走强
continuation_possible   → 更可能震荡偏强
range_or_wait           → 更可能横盘整理或等待新变化
weakening               → 更可能继续回落或弱势震荡
overheated              → 更可能高位剧烈波动并出现回吐
invalidated             → 原推荐判断已不成立
event_pending           → 等待事件后的实际交易反应
```

最终不能只给枚举或映射句，还要在 `current_review` 说明为什么。

---

# 第六阶段：简化最终 Markdown，避免事实堆叠

## Task 8：先修改渲染测试

修改：

```text
tests/test_forward_monitor.py
```

新用户结构只保留：

```text
推荐日期和当时判断
到今天走到哪里
我的分析
接下来更可能怎样
```

存在D20冻结结论时另加：

```text
前20个交易日最后结果
```

以下标题不得再出现：

```text
后来发生了什么
这些变化为什么支持或反对当时判断
现在怎么看
接下来关注什么
```

测试还必须断言：

- `market_change` 等内部原文不直接出现在Markdown；
- `_render_current_assessment()` 的通用句不再出现；
- 没有重复句号；
- 不出现“如果若”；
- conditional和comparator仍只保存在内部JSON，不出现在用户Markdown。

## Task 9：重写 `_render_markdown()`

修改：

```text
src/stock_analyzer/ops/forward_monitor.py
```

### 每只股票最终只展示

```markdown
### 股票名称（代码）

**推荐日期和当时判断**

<具体日期、当时最重要的理由和主要风险>

**到今天走到哪里**

<确定性目标进展>

**我的分析**

<review.current_review>

**接下来更可能怎样**

<由outlook_1_3d生成的自然基准句>
<alert.confirmation_condition完整句>
<alert.invalidation_condition完整句>

**前20个交易日最后结果**

<仅在存在冻结D20结论时展示>
```

### 删除公开拼接

用户Markdown不得直接拼接：

```text
alert.company_change
alert.sector_change
alert.stock_change
alert.market_change
alert.why_reported
```

这些继续保存在JSON，交给专用复盘 Skill生成 `current_review`。

### 删除通用状态句

不再公开调用：

```python
_render_current_assessment()
```

可以删除该函数；若内部仍有用途则保留但不渲染。

### 增加简短展望函数

允许增加一个小函数：

```python
def _render_public_outlook(alert: ForwardMonitorAlertV2) -> str:
    ...
```

要求：

- 用上述 `outlook_1_3d` 人话映射；
- `confirmation_condition` 和 `invalidation_condition` 原样作为完整句；
- 只清理结尾标点；
- 不自动添加“如果”或“若”，避免“如果若”；
- 不推断新事实；
- 不增加新字段。

---

# 第七阶段：核查行业数据缺失的真实原因

## Task 10：写一次性数据诊断

创建：

```text
research/skill-optimization/causal-recommendation-review-20260902/review-data-diagnosis.md
```

对最新 snapshot 中公开复盘的股票逐只记录：

```text
ts_code
original_group_code
relative_industry_3d/5d 是否存在
sector_breadth_3d/5d 是否存在
missing_sector_context 是否存在
sector_hotspot 当日是否有对应 group_code
```

判断属于哪一种：

1. 相对行业可用，只有行业广度不可用；
2. 当日 `sector_hotspot` 分区未生成；
3. group_code映射错误；
4. 原推荐依赖主题，而当前只取得行业；
5. 真实无可用数据。

## Task 11：只在确认代码错误时修复

- 若只是相对行业与行业广度层次不同，不改数据代码，只修正复盘文字；
- 若现有 `sector_hotspot` 已有对应行但 `forward_monitor` 没有匹配到，只在 `forward_monitor.py` 做最小映射修复；
- 若分区未生成，使用现有 `data run-stage`/`derive` 补一次并记录结果；
- 不增加新数据源；
- 不循环重试；
- 不把一条无关公告或行业广度缺失写成整只股票无法分析。

---

# 第八阶段：形成真正可读的验收样例

## Task 12：创建新样例

创建：

```text
research/skill-optimization/causal-recommendation-review-20260902/review-sample-v2.md
```

使用最新实际报告的冻结事实，不修改历史推荐，至少重写：

```text
华昌化工
中信银行
金岭矿业
德尔股份
海油工程
```

每只只使用四个栏目：

```text
推荐日期和当时判断
到今天走到哪里
我的分析
接下来更可能怎样
```

### 华昌化工必须说明

- 推荐日是否存在可靠可参与价格；
- 若不存在，应评价为无法执行，不是普通资料不足；
- 停牌前能分析什么；
- 控制权变更只改变公司背景，不能直接推出复牌方向；
- 复牌后最可能先出现高波动，方向需要实际成交确认。

### 中信银行必须说明

- 当前上涨有多少不能由市场和行业解释；
- 当前收盘是否接近推荐后最高；
- 目前更像持续走强还是缓慢上涨后的整理；
- 离20%较远时，不按线性速度判断，但要说明按当前强度更可能缓慢推进，而不是快速完成目标。

### 金岭矿业必须说明

- 相对市场为正、相对行业接近零各自意味着什么；
- 跌回原突破位下方为什么比小幅盈利更重要；
- 当前更像突破失败前的整理，还是已经明显减弱；
- 后面最可能怎样。

### 德尔股份必须说明

- 当前上涨10.44%、最高收盘12.14%、盘中最高18.29%之间的关系；
- 为什么这说明股票自身很强，同时也说明高位卖压增加；
- 当前更可能高位整理，而不是机械判断继续直线上涨；
- 哪种收盘和成交变化会恢复继续上涨判断。

### 海油工程必须说明

- 当前收盘为推荐后最高，意味着上涨仍在推进；
- 相对市场和行业的表现分别说明什么；
- 上影增多意味着什么；
- 当前更可能震荡偏强还是开始失速，并说明原因。

---

# 第九阶段：测试

## Task 13：Skill与Prompt测试

修改：

```text
tests/test_engine_contract_knowledge_v4.py
tests/test_forward_monitor_prompt.py
```

至少断言专用复盘 Skill 和 Prompt 包含：

```text
主要解释
市场共同变化
行业共同变化
公司变化
股票自身变化
混合或暂时无法判断
成交增加但收盘不再提高
上涨后整理
上涨开始失速
未来1—3个交易日更可能
相对行业存在时不能说行业数据全部不可用
停牌是无法执行而不是普通资料不足
```

不对全部自然语言做正则评分。

## Task 14：代码测试

修改：

```text
tests/test_forward_monitor.py
```

至少覆盖：

1. 新四段标题顺序；
2. 原五段旧标题不再出现；
3. `market_change`、`sector_change`、`stock_change`、`company_change` 原文不直接进入Markdown；
4. `current_review` 完整进入“我的分析”；
5. `outlook_1_3d` 映射正确；
6. 确认条件和失效条件不会形成双重“如果若”；
7. 不出现连续两个句号；
8. D20最终结论仍显示且不改变；
9. conditional和comparator仍保留内部JSON、对外隐藏；
10. 新增价格字段从price context复制到snapshot；
11. 缺少某个新增字段时保持None，不导致日报失败。

## Task 15：运行验证

```bash
./.venv/bin/python -m pytest -q \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py

./.venv/bin/python -m pytest -q

git diff --check
```

测试总数不得低于基线，不得删除旧测试换取通过。

---

# 第十阶段：实际效果复核

## Task 16：人工逐只检查样例

完整阅读：

```text
review-sample-v2.md
```

每只必须能直接回答：

```text
这段涨跌主要由什么解释？
为什么不是另外一种解释？
推荐时最重要的预期实现了吗？
当前是继续、整理、失速还是失败？
未来1—3个交易日更可能怎样？
为什么？
什么事实会改变判断？
```

如果任何一只仍然只是：

```text
涨了多少
成交多少
跑赢多少
部分支持
继续观察
```

就重写文字，不增加代码或字段。

## Task 17：不得覆盖历史正式报告

不修改：

```text
local_archive/forward_monitor/monitor-report-2026-09-01.*
```

新样例只放在研究目录。

未来下一次每日任务自动使用新Prompt和新渲染。

---

# 第十一阶段：提交、合并和分支收口

## Task 18：提交功能分支

```bash
git add \
  docs/2026-09-02-causal-recommendation-review-prompt.md \
  .agents/skills/reviewing-stock-recommendations/SKILL.md \
  .agents/skills/analyzing-price-trading/SKILL.md \
  ops/forward-monitor-prompt.md \
  src/stock_analyzer/ops/forward_monitor.py \
  tests/test_engine_contract_knowledge_v4.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_forward_monitor.py \
  research/skill-optimization/causal-recommendation-review-20260902

git commit -m \
  "fix: turn recommendation reviews into causal analysis"
```

推送：

```bash
git push -u origin codex/causal-recommendation-review-20260902
FEATURE_HEAD="$(git rev-parse HEAD)"
```

## Task 19：快进合并到实际运行的main

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

现有Scheduled Task继续使用实际项目根目录的`main`，不新建任务。

## Task 20：删除本轮功能分支

确认已完整进入main：

```bash
git fetch origin --prune

git merge-base --is-ancestor \
  origin/codex/causal-recommendation-review-20260902 \
  origin/main
```

确认通过后：

```bash
git push origin --delete \
  codex/causal-recommendation-review-20260902

git worktree remove \
  "$PROJECT_ROOT/.worktrees/causal-recommendation-review-20260902"

git branch -d \
  codex/causal-recommendation-review-20260902

git fetch origin --prune
```

不得使用强制删除。

最终远端继续只保留：

```text
main
research/ai-liquid-cooling-2026h2
```

液冷研究分支不合并、不删除、不修改。

---

# 十二、最终验收标准

## 复盘方法

- [ ] 先判断主要驱动，不再直接堆市场、行业、公司和价格事实；
- [ ] 能区分市场共同、行业共同、公司变化、股票自身、混合或未知；
- [ ] 不声称从量价知道主力或机构行为；
- [ ] 成交额必须结合价格、收盘、上影和回落解释；
- [ ] 明确推荐时最重要的预期是否实现；
- [ ] 明确当前属于继续走强、上涨后整理、失速、减弱、失败或无法执行；
- [ ] 给出未来1—3个交易日的基准判断和理由；
- [ ] 不用“仍需观察”替代判断。

## 用户输出

- [ ] 每只只保留“推荐日期和当时判断、到今天走到哪里、我的分析、接下来更可能怎样”；
- [ ] 不再显示内部四路变化字段的原始拼接；
- [ ] 不再显示“部分预期已经发生”一类通用状态句；
- [ ] 不出现重复句号和“如果若”；
- [ ] 不以例行公告或局部数据缺失主导整只股票；
- [ ] 停牌导致无可参与价格时写“无法执行”，不是普通“资料不足”。

## 数据与工程

- [ ] 只复制已有价格字段，不新增计算模型；
- [ ] 不新增Pydantic字段、schema、数据库、数据源或定时任务；
- [ ] 不修改选股逻辑；
- [ ] 不修改20%目标、D20、入口价格和11个价格场景；
- [ ] 完整测试通过；
- [ ] main本地与远端一致；
- [ ] 本轮功能分支已删除；
- [ ] 液冷研究分支保持不变。

---

# 十三、Codex最终汇报格式

```markdown
已完成：A股正式推荐复盘因果分析优化

## GitHub
- 基线：`04b0fde12372ffd3ed7255663d2f017390d75ae4`
- main最终提交：`<HEAD>`
- 对比链接：<URL>
- 根因诊断：<current-output-diagnosis.md URL>
- 科学依据：<scientific-basis.md URL>
- 数据诊断：<review-data-diagnosis.md URL>
- 新复盘样例：<review-sample-v2.md URL>

## 方法变化
- 主要驱动判断：<说明>
- 推荐理由验证：<说明>
- 当前阶段判断：<说明>
- 未来1—3日判断：<说明>
- 成交量解释：<说明>

## 实际样例
- 华昌化工：<一句真正结论>
- 中信银行：<一句真正结论>
- 金岭矿业：<一句真正结论>
- 德尔股份：<一句真正结论>
- 海油工程：<一句真正结论>

## 行业数据问题
- relative_industry是否可用：<结果>
- sector breadth是否可用：<结果>
- 原因：<真实原因>
- 是否修改数据代码：是/否及理由
- 是否增加新数据源：否

## 代码
- 是否新增schema：否
- 是否新增计算模型：否
- 是否只复制已有价格字段：是
- 是否删除公开事实拼接和通用状态句：是
- conditional/comparator内部记录是否保留：是
- 对外是否隐藏：是

## 验证
- 基线定向测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- `git diff --check`：<结果>
- main本地/远端一致：是/否
- 工作区干净：是/否

## 分支
- 远端保留：`main`、`research/ai-liquid-cooling-2026h2`
- 本轮功能分支是否删除：是/否

## 明确未做
- 未修改选股逻辑
- 未修改七种发动机、四种状态、11个价格场景
- 未修改20%目标、D20和入口价格
- 未新增评分、概率、schema、数据库、数据源或定时任务
- 未覆盖历史正式复盘
```

只有新样例已经真正回答“为什么这么涨跌、原判断是否实现、后面更可能怎样”，完整测试通过，功能提交进入main且功能分支删除后，才可以声称完成。
