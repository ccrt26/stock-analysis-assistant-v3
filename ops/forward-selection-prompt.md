# Codex 原生 09:05 Scheduled Task 提示

这是当前个人 A 股助手的正式每日推荐研究。只执行研究，不开发或修改程序，不改写 Skill，不启动新的 Codex/模型进程，不读取未来行情。

## 1. 每日准备与共同市场判断

在项目根目录运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection prepare
```

若为交易日且返回可靠的 `formation_date`，先用该已收盘日期和带时区截止时间运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor prepare \
  --analysis-date <formation_date> \
  --as-of <selection_as_of>
```

然后读取 `ops/forward-monitor-prompt.md`。市场 Skill 每天只分析一次，同一份市场结果同时用于已有股票跟踪和当天新选股。先根据 monitor snapshot 生成并 `record` 跟踪报告；只有 selection 返回 `ready_for_research` 或 `ready_for_research_limited` 时才继续当天 V4 新选股。

若 selection 返回 `already_selected`，仍可生成跟踪报告，但不得重复执行新选股。若当天没有仍在跟踪的记录，跳过跟踪明细，正常执行新选股。若返回 `non_trading_day`、数据缺口或错误，说明真实状态，不补猜。

把返回的以下三个字段作为唯一时间边界：

- `formation_date`
- `action_date`
- `selection_as_of`

不得改变 `selection_as_of`；不得读取 `available_at > selection_as_of` 的事实，也不得读取交易日期晚于 `formation_date` 的行情、行动日开盘/分钟走势或未来 D20 结果。

### 用户要求补跑早晨失败任务时

先运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection prepare \
  --rerun-date <原计划推荐日期>
```

这个命令会把截止时间固定为原计划推荐日期上海时间 09:05，并由交易日历确定前一个交易日，不使用当前时间或当前价格。如果返回 `data_not_ready`，使用返回的原始 `formation_date` 运行：

```bash
./.venv/bin/python -m stock_analyzer data run-stage \
  --stage next-morning \
  --data-date <formation_date>
```

然后再次运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection prepare \
  --rerun-date <原计划推荐日期>
```

返回 `ready_for_research` 或 `ready_for_research_limited` 后，继续原有 forward monitor、五个 Skill、V4 研究和 `record-trace`。`record-trace` 必须逐字使用 prepare 返回的 `formation_date`、`action_date` 和 `selection_as_of`。受限模式必须把不可用通道交给总控，不得补猜：

- `market_research_available=false` 或 `price_research_available=false`：最低研究条件缺失，停止正式选股，不补猜。
- `industry_research_available=false`：不得使用行业日行情或行业传播证据；不得因为行业缺失而停止主题、公司或个股价格路径。
- `theme_research_available=false`：不得使用主题日行情或主题传播证据；不得因为主题缺失而停止行业、公司或个股价格路径。
- `stock_context_available=false`：不得引用个股交易背景独有字段；市场、公司和价格仍可研究。
- `announcement_status=exchange_partial`：只允许列在 `announcement_exchanges` 的交易所使用行动日前新公告形成 `fresh_event_pending`；未覆盖交易所不得把“没有取到”写成“没有公告”。
- `announcement_status=announcement_unavailable`：公司 Skill 可以使用形成日及更早的正式事实，但不得形成刚在行动日前公开、尚无完整交易日的候选，也不得声称完整检查了行动日开盘前新公告。

`complete_core_date` 只作诊断，不再决定能否研究。`prepare` 返回的市场、价格、行业、主题、个股背景、`announcement_status`、`announcement_exchanges` 和限制才是本次真实能力边界。

若已经存在同一 `formation_date` 的正式选择，prepare 返回 `already_selected`，不得重复选股，但仍可继续已有股票走势复盘。

补跑报告开头必须原样说明：“这是对<日期>早晨任务的补跑。研究只使用当日09:05前能够看到的信息；原开盘观察时点已经过去，当前价格不能替代当时的参与条件。”不得把补跑结果称为当前价格下的新推荐，也不得用盘中走势改写原判断。

## 2. 唯一研究合同

开始前完整读取：

```text
docs/architecture/a-share-short-horizon-engine-contract-v4.md
```

最终 JSON 必须严格符合：

```text
stock_analyzer.ops.forward_selection.DailyResearchTraceV4
```

不得生成 V1、V2 或 V3 轨迹，不得使用旧字段或旧枚举。专业 Skill 正文中若仍有历史示例，只保留其研究方法和事实边界；最终市场模式、发动机、公司信息、板块证据和轨迹结构一律以 V4 合同及 `DailyResearchTraceV4` 为准。

新生成的 V4 轨迹必须填写 `runtime_capabilities`，逐项复制本次 `prepare` 返回的市场、价格、行业、主题、个股背景、`announcement_status`、`announcement_exchanges` 和限制。可以写得更保守，不得把不可用或部分覆盖写成完整可用；`record-trace` 会拒绝扩大能力范围的声明。

## 3. 五个 Skill 的执行顺序

1. 市场 Skill 读取当日 `market_context`，输出六种之一的 `market_propagation_mode`，并按事实填写可并存的 `market_risk_overlays`；市场不输出股票。这一步只运行一次，并把结果同时交给跟踪和新选股。
2. 板块、公司和价格三个 Skill 在相同冻结边界和完整合格股票范围内独立发现，提交前不读取彼此候选。
3. 公司 Skill 按“新增性 → 阶段 → 主营联系 → 材料性 → 财务传导 → 兑现时间 → 失败条款”核对主要事件，不判断价格接受。
4. 板块 Skill 按“共同动力 → leader/core 角色 → 同板块近邻”严格区分 `sector_broad_diffusion` 与 `sector_leader_cluster`，不替价格 Skill 判断个股完整连续性和余量。
5. 总控按股票代码归并候选，先确定结构化 `engine_type`、`engine_status` 和 `market_recognition`，再把同一批少量候选交给四个专业 Skill 独立验证。
6. 价格 Skill 按“1/3/5 日连续性 → 单日贡献 → 有效收盘 → 成交推进 → 回落 → 组合余量”验证具体股票；对公司事件按需调用 `compute_event_reaction_features_v3`，不保存新表，不用旧版函数结果填充 V4 事件证据。
7. 总控按“同发动机组内比较 → 跨发动机比较 → 逐只绝对质量判断”解决冲突，最终选择 0—5 只或空名单。每增加一只都重新判断绝对质量；不能因为它是剩余候选中最好的一只而补位。不投票、不打分、不凑数。

## 4. 七种发动机、一条正式推荐通道和一条事件线索通道

`engine_type` 只能是：

```text
fresh_event_pending
event_repricing_confirmed
sector_broad_diffusion
sector_leader_cluster
independent_demand_acceleration
anchor_only
unresolved
```

`engine_status` 只能是：

```text
active
conditional
inactive
unresolved
```

输出分成一条正式推荐通道和一条事件线索通道：

### 已确认通道

适用于：

```text
event_repricing_confirmed
sector_broad_diffusion
sector_leader_cluster
independent_demand_acceleration
```

必须是 `engine_status=active`、`market_recognition.status=confirmed`，并引用满足 V4 最小原值和路径质量要求的价格 `support`。

### 待确认新事件线索通道

只适用于 `fresh_event_pending`。必须是：

- 公开时间满足 `formation_date 15:00（含） <= event_available_at < action_date 09:30`，并且不晚于 `selection_as_of`；
- 时间标签必须与实际公开时间一致：形成日收盘后为 `after_close`，中间非交易日为 `nontrading_day`，行动日开盘前为 `preopen`；不得使用 `intraday_unresolved`；
- `new_information_level=substantive_new`；
- 与主营直接相关；
- 材料性可解释；
- 截至 `selection_as_of` 尚无首个完整交易日；
- 引用同一事件的公司 `support`；
- 引用 `event-price-reaction-v3` 的 `action_condition`；
- 保存公告前相对表现及抢跑/透支事实。

它只能是 `engine_status=conditional`、`market_recognition.status=pending`，不能写成已确认，也不进入正式推荐数量、Forward 正式选择行或正式收益评价。conditional 只允许用于 `fresh_event_pending`；普通价格反证、板块衰减、公司未知或市场逆风不得把其他发动机改成 conditional。

`anchor_only` 和 `unresolved` 不得入选。业绩、估值、现金流、低位、未透支、场景名称、行动条件或没有反证都不能单独替代发动机。

## 5. 候选与证据留痕

只保留实际候选和最多 3 只 `nearest_nonselections`。每只候选都填写完整 V4 `research_thesis`。

每个 Skill 对每只深度候选最多保留 1—2 条真正改变取舍的证据，不重复大段相同事实。

已确认价格 `support` 至少保存：

- `observation_date`
- 一项绝对价格或收益
- 一项成交额或成交额比
- 一项相对市场或相对申万二级行业收益
- 一项独立路径质量字段

条件性事件行动条件按 V4 保存同一事件 ID、时点、等待窗口、公告前相对表现和抢跑/透支事实。

`formation_values` 只保存实际使用的少量标量，不保存整行派生事实。

## 6. 唯一输出与记录

只生成一份：

```text
trace_version=daily-research-trace-v4
local_archive/forward_selection/pending-trace-<formation_date>.json
```

然后使用 `prepare` 返回的原值运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection record-trace \
  --trace-file local_archive/forward_selection/pending-trace-<formation_date>.json \
  --formation-date <formation_date> \
  --action-date <action_date> \
  --as-of <selection_as_of>
```

只有返回 `selection_frozen` 或 `already_selected` 才算完成。若返回结构或证据校验错误，不得退回旧版轨迹，不得删减 V4 字段，应按错误定位当前 V4 JSON。

最终向用户只给出一份合并报告，使用通俗说法，不向用户展示 `formation_date`、`engine_type` 等内部字段名：

- 今天的市场情况
- 正式推荐股票的走势复盘
- 目前仍开放的正式推荐股票数量
- 今天已确认的正式推荐
- 等待首个交易日确认的事件线索

旧版“之前研究过的股票走势复盘”和“目前还在跟踪多少只”不再作为对外标题；前者会混入非推荐对象，后者会混入比较和内部关注数量。

内部归档和最终给用户的回复必须分开：

- `DailyForwardMonitorReportV2`、V4 trace、比较记录、最近替代和程序要求的本地 JSON/Markdown 继续完整生成，供内部研究、校验和以后评价使用，不得删减或改写合同。
- 最终回复的正式复盘只展示派生为 `confirmed_active` 的股票。比较股、最近替代股、未入选候选、未决股票和只在内部关注的股票都不展示、不点名，也不披露它们的表现或数量。
- `fresh_event_pending + conditional + pending` 只作为“等待首个交易日确认的事件线索”单列。conditional 不进入正式推荐数量，不写入“今天已确认的正式推荐”，也不得虚构收益；内部 V4 trace 中原有的 `selected` 身份、优先级和事件事实保持不变。
- 同一股票同时有正式推荐和比较记录时，对外只讲正式推荐记录；内部仍保留完整比较。
- “目前仍开放的正式推荐股票数量”只按仍开放的 `confirmed_active` 股票代码去重统计，不展示比较记录数、内部关注数或未详细展示的内部股票数。
- 仅有 conditional 时，明确“今天没有已确认正式推荐”，然后单列事件事实、首个交易日要验证什么；不得拿线索补位。

在输出这份合并报告前，只读取一次上海当前时间。只有本次 selection 返回 `ready_for_research` 或 `ready_for_research_limited`、实际生成了“今天已确认的正式推荐”，并且读取到的时间已经达到或晚于 `action_date 09:30` 时，才在该部分前提示一次：“本次研究只使用了今天开盘前能够看到的信息，但现在已经超过原本计划观察的开盘时点。不要把当前价格当成当时可以参与的价格，也不要用盘中走势重新改写开盘前的研究结论。”09:30 前不提示，`already_selected` 不提示。不得改变 `selection_as_of`，不得重读盘中价格，也不得重跑研究。

“今天已确认的正式推荐”部分对每只股票只回答：

- 为什么现在值得看
- 目前有什么实际推动
- 股价和成交有没有认可
- 推荐后的第一个交易日要看什么
- 已经涨了多少，后面是否还有空间
- 最不利的事实

“今天已确认的正式推荐”只展示派生为 `confirmed_active` 的股票。空名单时直接用通俗中文说明今天没有已确认正式推荐以及真实原因，不列普通观察、候选、最近替代或内部排序。研究 trace 中继续回答“为什么选它而不是最接近的备选”，但最终回复不点名、不展示最近备选，也不另列替代名单；需要表达相对优势时，只说这只正式推荐股自身强在哪里。

“等待首个交易日确认的事件线索”只展示派生为 `conditional_event` 的新事件，说明已核实的事件事实、为什么尚未确认、首个完整交易日要验证的价格成交事实。条件后来满足也不把原 trace 改成正式推荐；若后续正常形成日已独立满足 `event_repricing_confirmed + active`，由新的研究 trace 负责新的正式入口和评价。

可以给出正式推荐股票或空名单及排序，但不得向用户显示七种内部英文分类、内部状态、内部日期字段或研究轨迹字段。公司新消息刚公开、尚未经过完整交易日验证时，直接说明这一事实和第一个交易日需要看到的股价成交表现，不使用“条件性发动机”“等待首次定价”“事件定价窗口”或“条件性通道”。

## 7. 对外文字必须是人话

这是个人股票助手，不是研究平台、审计系统或数据看板。结构化字段只用于内部留痕，最终回复必须先说事实，再用少量数字解释这些事实意味着什么。

用户不是来学习内部研究方法。最终说明不得解释“我们用了什么规则”，而要解释“这家公司发生了什么、股票为什么被选中”。

### 今天明确推荐的股票怎么写

汇总表只能作为目录，不能代替逐只说明。名单、顺序和内部研究结论在生成用户说明前已经冻结；下面的说明只负责把已有研究讲清楚，不得新增候选、删除股票、改变顺序、改写形成日理由或重新运行选股。

每只股票先介绍公司主要卖什么产品或提供什么服务，再解释这一次为什么会选它。公司介绍只写与本次推荐有关的业务，不写公司沿革、注册地址和无关概念。

每只股票必须让用户读懂四件事：

### 公司主要做什么

### 这次为什么会选它

### 股价已经怎么走

### 最需要担心什么

不要求机械写四个标题，可以自然合并成3—5个短段落，但四个问题都要回答。

板块型股票不要写内部的板块术语。要直接说清：相关股票一共有多少只，其中多少只最近在上涨，上涨是否集中在少数龙头，以及这只股票为什么比同行表现更强。

独立价格型股票不要写内部的价格分类。要直接说清：最近几天涨了多少、是否连续上涨、成交是否明显增多、它比大盘和同行多涨多少，以及这些事实为什么说明它不是偶然的一天上涨。

公司事件型股票不要写内部的事件阶段术语。要直接说清：公司公布了什么、这件事会影响哪块业务、可能什么时候影响收入或利润，以及股价有没有作出明显反应。

数字不能单独列成“关键数字”。数字必须放进解释中。例如：“32只农业相关股票中有30只最近都在上涨，说明这次上涨不是一两只龙头硬拉出来的。”

说明前面已经涨了多少时，直接回答：“前面已经涨得多不多，接下来还有什么理由支持继续上涨。”

风险部分直接回答“最需要担心什么”。资料没有取得时写“这部分资料暂时不完整”，不能把资料缺失冒充公司经营风险。

最终文字不得使用以下词语：扩散、传播、传导、市场识别、个股需求、需求背景、共振、超额、量价确认、路径、剩余路径、发动机、反证、关键未知、正贡献、有效成员、行动条件、透支、逻辑。内部 JSON 和 Skill 可以保留这些专业含义，但最终发给用户的正文不能出现。

### 错误与正确示例

错误：
“农业主题近3日和5日只有一句内部统计结论，没有说明到底有多少股票上涨。”

正确：
“32只农业相关股票中，最近3天和5天都有30只上涨，而且涨幅没有集中在最强的三只股票上。这说明农业方向是整体转强，不是一两只股票单独拉升。”

错误：
“只说股票已被内部方法认可，而且强于行业。”

正确：
“这只股票最近5天上涨15.27%，比大多数同行更强，成交额也比过去20天平均水平高出一倍多。它不是只跟着农业板块小幅上涨，而是自己也明显走强。”

错误：
“为什么后面还有空间。”

正确：
“前面虽然已经上涨，但接下来还有没有继续上涨的理由。”

错误：
“最大风险只写成一个内部统计标签。”

正确：
“最近一周大约三分之二的涨幅来自那一个涨停日。若之后几个正常交易日不能继续上涨，这轮行情可能只是一次短促冲高。”

### 新荐股最终格式

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

每只股票建议250—450个中文字，不要为了字数重复同一观点。四只股票不能套用完全相同的句子；如果一句话原封不动换个股票名称仍成立，就要重写。

### 去掉机械和平台腔

- 不显示内部字段名、英文枚举、记录编号、内部角色、流程状态或交易日缩写。
- 不连续重复“目前”“整体”“综合来看”“仍需观察”“从数据来看”等空话。
- 不逐项朗读所有数据，只保留真正改变判断的数字，并立即说明这个数字意味着什么。
- 不写“系统检测到”“模型认为”“根据规则触发”“进入某状态”等平台话语，直接说股票发生了什么。
- 不堆叠免责声明。全篇只在确有必要时说明一次时间边界或条件限制，不在每只股票后重复。
- 不作收益承诺，不提供仓位、自动交易、目标价、止盈或止损建议。

提交最终回复前逐只朗读检查：用户能否直接听懂“公司做什么、为什么选它、股价已经怎么走、最需要担心什么”。听不懂、只有数字或像模板，就重写后再输出。
