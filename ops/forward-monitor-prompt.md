# 现有 09:05 每日任务中的股票跟踪步骤

这一步每天只运行一次，属于现有 09:05 任务，不创建新的 Scheduled Task，也不新增定时任务。程序处理全部跟踪记录；每个 active 正式推荐 episode 在每个已收盘交易日都必须生成一条简短 AI 复盘，再从当日需复盘的正式推荐中选最多8只做详细复盘。面向用户时先展示全部主动推荐的今日结论，再按“今天发生了什么、相比上次判断、接下来1—3个交易日”展开重点股票，不展示内部字段名、英文值或交易日缩写。

## 1. 程序准备全部跟踪记录

当天收盘数据可靠后运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor prepare \
  --analysis-date <已收盘交易日> \
  --as-of <带时区截止时间>
```

程序处理全部跟踪记录，并生成 `local_archive/forward_monitor/snapshot-<analysis_date>.json`。snapshot 的 `daily_review_episode_ids` 是当天必须逐条简评的正式推荐记录，`evaluation_only_episode_ids` 是已停止普通日评但仍保留D20评价的记录，`detailed_review_candidate_codes` 是当天可进入详细复盘的股票。不得建立人工维护的第二套股票池，不得打分。

同一份市场 Skill 结果同时供选后跟踪和当天新选股使用，市场 Skill 每天只分析一次。

## 2. 先生成全部正式推荐的每日简评

只处理 snapshot 的 `daily_review_episode_ids`。每个 ID 恰好一条 `DailyFormalReviewV1`，总体写入 `DailyFormalReviewLedgerV1`，版本固定为 `daily-formal-reviews-v1`。conditional、比较股、落选股、未决股、evaluation_only 普通日期和 completed 记录不得进入。

每条简评先读取本 episode 的 `previous_daily_formal_review`；历史兼容时可读取 `previous_episode_review`，`previous_monitor_state` 只用于旧 V1 记录，不得借用同一股票另一 episode 的观点。普通无变化日仍要写短评，正文通常只用一两句说明今天最重要的变化及当前看法。观点变化单独写入 `view_change` 和 `view_change_reason`，未来1—3个交易日方向与原因写入展望字段，由外层展示。只有节点、重大变化或重要事项才加深。

`DailyFormalReviewV1.current_review` 是当天公开观点更新的唯一语义来源。需要重点展开的分析在保存每日账本前一次写好；生成详评时，`ForwardEpisodeReviewV1.current_review` 必须逐字复制对应日评正文，不允许第二次撰写。详评阶段也不得重新创作观点变化说明；公开内容直接读取当天日评的 `view_change` 和 `view_change_reason`。

先生成：

```text
local_archive/forward_monitor/pending-daily-formal-reviews-<analysis_date>.json
```

然后记录：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor \
  record-daily-formal-reviews \
  --snapshot-file local_archive/forward_monitor/snapshot-<analysis_date>.json \
  --review-file local_archive/forward_monitor/pending-daily-formal-reviews-<analysis_date>.json
```

成功后正式文件是 `local_archive/forward_monitor/daily-formal-reviews-<analysis_date>.json`。`live` 记录必须作出 `keep_active_tracking`、`stop_active_tracking` 或 `complete_observation`；`copied_live_archive` 和 `backfill` 只能使用 `historical_not_applied`。

只有两种情况允许 `stop_active_tracking`：原推荐最重要的判断被后续事实否定，且 `current_assessment=contradicted`；或者原推荐无法执行，`current_weak_or_failed_link=execution` 且 `entry_open` 为空。weakening 不能单独停止；单日下跌、横盘、数据暂缺、未达到20%、普通市场回落或短期展望偏下也不能单独停止。达到20%不提前结束，继续记录到D20。

停止主动跟踪后，次日起不再生成普通每日 AI 简评，也不占详细复盘名额；历史不删除，程序仍保存确定性价格到D20，D20重新进入日评并形成最终结论。新推荐必须建立新 episode，不能恢复或覆盖旧 episode。

D1、D3、D5、D10、D20 不决定是否生成每日简评，只决定当天加深什么：D1 评价第一天实际反应与可执行性；D3 评价早期持续性；D5 形成第一周小结；D10 形成中期小结；D20 形成最终复盘并默认 `complete_observation`。D25/D30只用于已经明确延长的记录，且不得改写D20；D30必须完成。

公告正文继续按 V4 规则按需读取，不批量下载。原五个 Skill 继续负责选股；复盘时，市场、板块、公司和价格四个专业 Skill 的 `phase: review` 只提供各自事实与解释，不重新推荐股票。`reviewing-stock-recommendations` 负责跨时间综合；总控只检查记录一致性。公司事实是否仍成立，和股价成交是否实际支持该事实，必须分开写。不得改写原始完整判断、当时理由或前20个交易日的冻结结论。

### 数据缺口只补一次

如果 snapshot 出现 `missing_price_path`、`missing_current_price_context`、`missing_market_context` 或 `missing_sector_context`，且对应交易日已经收盘，先按缺失类型使用现有流程定向补一次：

```bash
./.venv/bin/python -m stock_analyzer data run-stage \
  --stage close \
  --data-date <analysis_date>

./.venv/bin/python -m stock_analyzer data run-stage \
  --stage next-morning \
  --data-date <analysis_date>
```

只有价格或市场缺失时运行 `close`；只有行业、主题或公告缺失时运行 `next-morning`。补数后重新运行一次 monitor prepare，仍缺失就明确具体限制，不得循环重试。不得为一只股票执行全市场财务回填、增加数据源或增加任务。

若缺少的公司财务或公告正文会直接改变原推荐判断，公司 Skill 沿现有官方链接定向读取一次；无关月报、例行公告、单个公告标题或非核心细节不得主导整只股票的复盘。仍无法取得时只说明哪一项无法核对，继续分析其他已有事实。只有推荐参考价或整段行情确实不存在，才能说不能评价距离20%观察目标的进展。

相对行业表现与行业上涨面必须分开：`relative_industry_*` 表示股票相对形成日有效申万二级行业的表现，`sector_breadth_*` 表示 `original_group_code` 对应行业或主题的成员上涨面。前者存在而后者缺失时，只能说无法核对多数成员是否同步，不得说行业数据全部不可用；后者存在而前者缺失时也不得抹掉上涨面事实。


## 3. 生成走势复盘日报

完成全部每日简评并正式记录后，生成严格符合 `DailyForwardMonitorReportV2` 的重点详评日报。`detailed_review_stock_count` 等于当天需简评的不同正式推荐股票数与8之间的较小值；新日报必须恰好包含这个数量。不足8只时全部详细复盘，达到或超过8只时详细复盘恰好8只不同股票。一只股票在详细区只出现一次，同股多个正式 episode 的每条记录分别复盘；每条使用一个 `ForwardEpisodeReviewV1`，前20个交易日的最终结论使用 `FrozenTwentyDayReviewV1`：

```text
local_archive/forward_monitor/pending-report-<analysis_date>.json
```

报告必须严格对应当天 snapshot：

- `market_propagation_mode` 只能是 `broad_sustained_participation`、`one_day_repair`、`sector_rotation`、`concentrated_speculation`、`weak_or_fragmented`、`unclear` 之一；
- `pool_summary` 和 `unreported_attention_count` 必须与 snapshot 完全一致；
- 每只详评的 `episode_ids` 必须包含该股票当天全部正式简评 episode，不得混入 conditional、比较或落选记录；`roles`、交易日序号和原始完整判断必须从这些记录完整得出。
- `episode_reviews` 中的 `episode_id` 必须与该股票当天全部正式简评 episode 完全一致，不得缺少、重复或多出；不得用该股票最大交易日序号替其他记录结案。
- `alert_type=routine_detail` 表示当天没有重大异常，但按轮换进入详细复盘；它不是第二套关注池。
- 每条记录的 `ForwardEpisodeReviewV1` 只填写通俗原因与风险、当前判断、现有证据最支持的解释、当前最弱环节、逐字复制的当日复盘、成对比较解释和 `final_twenty_day_review`，不增加分数、概率或更多分类。
- 每只新提醒必须填写 `outlook_reason_plain_language`，用当前最重要的1—3项事实说明未来1—3个交易日为什么更可能向上、横盘、向下或暂时无法判断。先作出方向判断，不写“如果……就……”，不重复两个验证条件，也不照抄整段 `current_review`；它必须与 `outlook_1_3d`、`current_assessment` 和 `current_review` 一致。没有可交易价格或证据冲突时可以说明目前无法判断方向，并明确缺少什么。
- best_supported_explanation 等枚举继续在内部填写；current_review 才是公开分析核心，要写成连贯的观点更新短评，不向用户解释内部字段。why_reported 只说明今天为什么复盘，不参与涨跌归因，不直接展示。
- 具体推荐日期必须取该次正式推荐记录的 `action_date`，放在当前状态的简短前缀中；同股多个 episode 分别保留推荐日期和交易日序号，不能用复盘日期或当前日期代替。
- `confirmed_active` 和 `legacy_v1_not_rewritten` 两类正式推荐记录在第1至第19个交易日，`final_twenty_day_review` 必须为空；第20个交易日必须首次形成。第20天漏跑时，`pending_final_review` 必须持续排在提醒原因第一位，直到结论成功保存并在下一次 prepare 恢复。第21至第30个交易日不得改写这个结论，只能更新当前走势评价。snapshot 已有 `frozen_twenty_day_review` 时必须原样使用；漏跑后首次建立也只能依据 `d20_*`、前20个交易日以内的事实和已冻结原判断。
- 比较记录的 `final_twenty_day_review` 始终为空；`conditional_event` 也始终为空，二者都不能写成正式推荐的最终结论。
- `original_reason_plain_language` 和 `original_key_risk_plain_language` 只通俗改写当时已经冻结的意思，作为内部历史锚点，不加入后来事实；各自第一句写成简短的“当时主要看中……”和“主要担心……”。普通日不重复公开原理由和风险；D1 只取这两个字段的首句作简短背景，D20 的完整结案另用最终复盘字段。
- 原始完整判断缺失时，内部保留 `missing_original_research_thesis`，面向用户明确说明只能复盘价格表现，不能补写当时理由。
- 内部仍可使用真实成对价格路径帮助判断最初是否选对股票，但比较记录不进入本轮重点详评，不在用户报告展示替代股名称或表现。
- 当前状态只显示推荐后的交易日序号、当前收盘相对推荐参考价、期间最高收盘和最深下跌，缺失项不补猜。若 `current_review` 确需引用相对表现，按真实1、3、5或20个交易日窗口说明，不把这个窗口写成“从推荐以来”。
- D1—D4 的五日收益、连续性和最大上涨日字段可能跨越形成日前后，只能作为近期背景，不得冒充为完整的推荐后五日路径。

### 内部日报和用户复盘分开处理

snapshot、原始事实与 trace 是内部完整记录，继续保存全部推荐、比较、待确认事件、公告候选、成对价格和 attention 原因。`daily-formal-reviews-<analysis_date>.json` 保存当天全部正式简评；`DailyForwardMonitorReportV2` 只保存当天选出的重点详评，最多8只，不保存未进入正式推荐的事件线索或比较记录。它们仍留在 snapshot、原始事实与 trace 中，不等于删除。不得为了让最终文字更短而删掉内部事实或改变记录合同。

### 正式推荐股票的今日复盘

“正式推荐股票的今日复盘”只能出现被明确正式推荐过的股票。

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

待确认事件保留在 snapshot、原始事实与 trace，但不得写入 `daily-formal-reviews` 或 `monitor-report`，也不得出现在“正式推荐股票的今日复盘”中，并且不得单列给用户凑内容。面向用户不展示比较股名称，也不显示“还有多少内部股票未展开”。同一股票同时有正式推荐和比较记录时，对外只讲正式推荐 episode。

### 复盘不是行情播报

复盘在内部先恢复当初推荐时真正期待发生的事情，再用推荐后的事实检验；公开正文从今天的变化开始，不完整介绍公司或重新论证当初为何推荐。

内部仍要恢复当初期待看到什么，选择最有证据的主要解释，判断哪一项核心预期真正实现以及当前阶段，并给出未来1—3个交易日的判断。但 `current_review` 不展示这套推理步骤，而按以下原则形成观点更新稿：

1. **一个中心问题**：选择这只股票当天最重要的问题，其他信息只有能改变该判断时才使用。只有一项次要变化会影响下次复盘时，才在结尾用一句话提醒。
2. **一句话观点更新**：第一句直接给出最重要的变化和方向判断，并能独立作为标题。
3. **最少决定性事实**：使用回答中心问题所需的最少事实，最多4个、不设最低数量，不凑数。停牌且没有价格时，可以没有推荐后价格事实。
4. **与上一次复盘比较**：结合上一轮结构化字段与文字中心，填写当天 `view_change` 和 `view_change_reason`，由外层直接展示，不在详评重写一份；无上一轮时只与原推荐判断比较，不机械声明首次复盘。
5. **当前综合判断**：说清原推荐的关键一环是实现、减弱还是未知；后续基准判断由现有外层展望单独展示。

不平均复述市场、行业、公司和价格四路内容，不以“最有证据的解释是、当前阶段是、核心预期目前得到支持”作为固定句式。只有与中心问题直接相关时，才简要说明为什么这一解释比其他解释更有证据；`current_review` 不需要逐项证明其他解释全部错误。数据限制只有会改变结论时才写一句；例行公告不进入分析正文。

例如：

- 当初因为突破前高而推荐，后来跌回前高下方：这会削弱推荐，因为突破只有站稳才说明市场接受了更高价格。
- 当初因为行业普遍上涨而推荐，后来同行多数转弱但该股仍上涨：行业理由减弱，但股票自身可能仍强。
- 当初因为公司新合同而推荐，后来公告真实但股价和成交没有变化：公司事件仍然真实，但短期上涨预期没有被市场行为验证。
- 股票上涨并不自动证明原理由正确。若大盘和同行涨得更多，原先认为它更强的判断仍可能错误。

事实与观点分开。`current_review` 中每一项具体的日期、百分比、金额、股票数量、公告名称和财务变化，都必须能追溯到当前 snapshot 或 monitor report 的确定性字段、原推荐 trace，或当日按现有流程读取的正式公司材料中的明确字段和值。百分比和日期可以换算格式，但要保留来源字段和原始值。上一轮 `current_review`、旧日报中的 `company_change` 等 AI 自由文本只能作观点锚点，不能作新事实来源。相对表现、公司事件与价格反应、价格成交组合、原推荐检查点只支持目前更合理的解释，不证明唯一原因。现有证据不能区分原因时，直接说不知道并说明缺什么，不为完整感编故事。

`current_review` 可以用一句话说明“20%目标仍有现实可能”“需要重新加速才有可能”“目前已明显变得困难”“已经不再以完成目标为主要判断”或“无法计算”。这只是结合实际路径更新可实现性，不新增结构化字段，也不按每天1%线性推算。

### `current_review` 与现有渲染器的分工

current_review 只负责一句话观点更新、当天主要问题、必要的原因解释、原判断实现或减弱的部分、相较本记录上一轮的实质变化和当前看法。观点变化的完整说明交给 `view_change_reason`，不在正文再列一遍。

- 不再重复完整推荐日期；
- 不再重复当前、最高、最低的全套路径；
- 不再重复距离20%目标的固定进度句；
- 不再重复未来1—3个交易日的完整展望；
- 不再重复 `confirmation_condition` 和 `invalidation_condition`。

只有某个日期或数字直接决定中心判断时，才可在 `current_review` 中再引用一次。`original_reason_plain_language` 只通俗改写当时理由，不再自行加完整推荐日期；`original_key_risk_plain_language` 只改写当时风险。

### 日常复盘、事件复盘与 D20

- 日常复盘只写增量。观点未发生实质变化时约60—140个中文字，只补最重要的新支持或风险，以及是否需改变下一步判断。
- 观点实质改变时约150—320个中文字，说明从什么变成什么、哪个事实造成改变以及对原推荐的含义。
- 事件复盘约180—350个中文字，只写事件前的相关判断、事件改变了什么、价格是否已有对应反应和观点是否因此改变。例行公告不进入正文。
- D3、D5、D10 只是触发点，不自动决定字数。字符数只是 `current_review` 的写作参考，不建立自动校验。
- D20 最终复盘是唯一允许串起完整前20个交易日过程的复盘。`current_review` 当天仍只写增量；完整总结写入现有 `final_twenty_day_review.overall_review`，检验推荐理由、具体股票、时机、最大成功或错误和一条具体经验；D20 收盘、最高收盘和最深下跌仍由程序外层展示。
- 第21—30日必须原样保留已冻结的 `final_twenty_day_review`；`current_review` 只写 D20 之后新增表现，并说明它不改写前20日评价，不形成第二次 D20 结论。比较记录和待确认事件仍不形成正式推荐的 `final_twenty_day_review`。

最终 Markdown 每只正式推荐股票先以“当前状态：”一行显示推荐日期、推荐后的第几个交易日、当前收盘较推荐参考价涨跌、期间最高收盘和期间最深下跌；只显示真实取得的价格部分。随后只使用以下三个固定小标题：

**今天发生了什么**

直接展示当天 `DailyFormalReviewV1.current_review`。正文是一篇观点更新，不重讲完整推荐理由、公司介绍或整段价格过程。

**相比上次判断**

直接使用当天 `view_change` 与 `view_change_reason`，不让详评再次创作：`unchanged` 为判断没有实质变化，`strengthened` 为判断增强，`weakened` 为判断减弱，`invalidated` 为原判断已被事实否定，随后展示原样保存的原因。`first_review` 直接展示原因，只有确有必要时才在原因中说明这是第一次正式复盘。

**接下来1—3个交易日**

依次展示当前基准方向、`outlook_reason_plain_language`、进一步支持当前方向的表现、会让我改变当前判断的表现。理由必须在两个条件之前，不写两边都可能的空话。

原推荐背景只在以下情形出现：

- D1 在当前状态后增加一行“原推荐背景：当时主要看中……；主要担心……。”两项合计一到两句话，不恢复完整推荐模板。
- 普通 D3、D5、D10 和 `routine_detail` 不公开完整原理由和原风险。
- 当天 `view_change=invalidated` 且不说明原判断就无法理解时，`current_review` 可以用一句话提及原来期待什么。
- D20 在三段更新之后增加独立的 `**20个交易日最终复盘**`，展示 `FrozenTwentyDayReviewV1` 的通俗结论及前20日确定性价格事实；完整结论只出现一次，不再写入 `current_review`。D20 后继续观察时保留原最终结论，只更新此后的事实。
- 同一股票多个 episode 使用简短的“推荐日期（第几个交易日）：”前缀区分，三个标题每只股票只出现一次，不重复完整原推荐理由和风险。

没有 daily_ledger 的旧 V1/V2 报告继续可读，不回写、不迁移历史文件；旧 V2 新渲染采用同一三段模板，正文使用已有 `current_review`，缺少上次观点比较时如实说明未保存，不补写。

outlook_1_3d 保留现有七类，公开方向固定为：strengthening“未来1—3个交易日更可能继续向上”，continuation_possible“未来1—3个交易日更可能震荡偏上”，range_or_wait“未来1—3个交易日更可能横盘整理”，weakening“未来1—3个交易日更可能震荡偏下”，overheated“未来1—3个交易日更可能高位震荡，短线偏下”，invalidated“未来1—3个交易日更可能继续偏弱”，event_pending“目前没有足够的可交易事实判断方向”。确实无法判断方向时不得用横盘预测掩盖未知。

公开支持标签随方向分别为“会进一步支持向上判断的表现”“会进一步支持震荡偏上判断的表现”“会继续支持横盘判断的表现”“会进一步支持偏弱判断的表现”“会进一步支持高位震荡偏下判断的表现”“会继续维持暂时无法判断的事实”；改变条件统一为“会让我改变当前判断的表现”。

`confirmation_condition` 表示什么后续表现会进一步支持当前 outlook_1_3d，不是支持最初的看涨推荐；`invalidation_condition` 表示什么后续表现会使当前 outlook_1_3d 需要改变。各写一个完整中文句子，按当前方向填写：

| 当前方向 | confirmation_condition：支持当前方向 | invalidation_condition：改变当前方向 |
|---|---|---|
| `strengthening` / `continuation_possible` | 继续提高收盘、继续跑赢市场或行业、成交增加后仍能收稳。 | 连续收低、跌回关键区域、放量不涨、重新落后市场。 |
| `weakening` / `invalidated` | 继续降低收盘、继续跑输市场或行业、反弹不能收稳。 | 连续提高收盘、重新跑赢市场、收复关键区域并保持。 |
| `overheated` | 高位不能继续提高收盘、冲高回落增多、成交增加但收盘降低。 | 重新形成多个更高收盘并保持，且回落明显减轻。 |
| `range_or_wait` | 继续在原区间内波动，成交和收盘都没有形成明确方向。 | 连续突破区间上沿或下沿，并有多个收盘保持。 |
| `event_pending` | 仍缺少可靠可交易价格或关键事实仍未公开。 | 出现完整可交易价格和足以作出方向判断的新事实。 |

例如，当前判断为继续偏弱时，支持条件是“收盘继续降低，并继续落后市场”；改变条件是“连续几个交易日提高收盘，并重新跑赢市场”。不得把恢复上涨写成支持偏弱判断。条件只负责以后验证，不能取代当前方向和理由；这里只做生成前语义核对，不增加中文关键词识别器、评分器或自动 Gate。

四路 `market_change`、`sector_change`、`company_change`、`stock_change`、`why_reported`、成对比较和待确认记录继续保留在内部 JSON 和 snapshot，公开 Markdown 不直接拼接这些文字。不得为了缩短公开文字而删除内部事实或记录。

行动日停牌、没有可靠开盘价或无法按原条件参与时，阶段必须写“无法按计划执行”，不得当作普通资料缺失。若推荐后才停牌，先分析停牌前的可执行价格路径。

用户不是来读取行情表。每只股票在内部恢复当初期待，再用最少的关键事实说明今天的变化怎样更新判断。不要机械分成“市场方面、行业方面、公司方面、个股方面”，也不要依次朗读内部判断、薄弱项和解释分类。无法可靠区分原因时直接说不知道，不能编故事。

内部成对比较继续用于判断当时是否选错股票，也继续填写结构化内容；最终对外不出现替代股名称、代码、角色、单独表现或比较栏目。

### 必须说人话

- 不显示内部字段名、英文枚举、记录编号、内部角色、交易日缩写或流程状态。
- 不机械重复“目前……整体……仍需观察”“从数据来看”“综合来看”等空话。每句话都要说明一个具体变化、原因或后续含义。
- 不把固定栏目逐字复制成空模板；问题可以相同，但表达要根据这只股票真正发生的事情自然组织。
- 如果一句话换成任何股票名称仍然成立，说明太空泛，必须重写。
- 不从量价猜测机构、主力、游资或账户身份；没有证据的原因就说未知。
- 只保留必要的一次时间边界说明；不提供收益承诺、仓位、自动交易、止盈或止损建议。

8只详细复盘按以下顺序选择：

1. 今日停止主动跟踪；
2. D20最终复盘；
3. 观点明显变化；
4. 达到20%或出现显著回撤；
5. 重要公司事项；
6. D10；
7. D5；
8. D3；
9. D1；
10. 剩余名额按最长时间未详细复盘轮换补足。

这只是复盘资源顺序，不是投资排名。不得按股票代码、涨幅、推荐顺序、行业或发动机机械挑选，不建立分数或权重。同级高优先事项超过8只时，AI只选择对原推荐判断影响最大的8只，其他仍保留当天简评；任何股票都不能因为未进详细区而缺少每日简评。

D21—D30 的 `late_activation` 面向用户必须写成“这只股票在前20个交易日结束后才开始明显走强，因此不会改变前20天的原评价结果”。达到原目标只说明已达到，仍记录到 D20，不自动生成新的买入建议。提前判断失效后不再放入普通详细提醒，但程序仍记录到 D20。

## 4. 校验并保存

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor record \
  --snapshot-file local_archive/forward_monitor/snapshot-<analysis_date>.json \
  --report-file local_archive/forward_monitor/pending-report-<analysis_date>.json
```

成功后向用户展示：今天的市场情况；“所有主动推荐的今日结论”简表；“今天重点复盘的8只股票”（不足8只按实际数量改标题）；主动跟踪、仅保留评价和已完成三类数量；以及当天明确推荐的股票。不要展示待确认事件、比较股、普通观察股、最近替代股、内部关注股票及其数量。没有主动推荐时明确说明空表，不得用其他股票补位。
