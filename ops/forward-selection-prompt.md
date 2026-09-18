# 晚间正式研究运行提示

## 启动器分工与手动执行

`tools/stock_ai.py` 的 managed 新研究模式以外层说明为准（article-v1 分工）：选股研究会话只做选股研究，交付完整 pending trace、市场说明正文（含独立标题行 `## 今天的市场情况`）和 `selection-handoff.json`（市场正文与逐股研究取舍、证据引用、比较对象、改变条件及来源），暂不执行选股 record/record-trace、公司介绍或网页同步。正式复盘由外层另起的独立复盘会话按 `ops/forward-monitor-prompt.md` 执行，选股会话不做复盘；逐股最终推荐文章由作者会话按单股研究包与写作材料生成，选股会话不写四分区整篇日报、不写推荐正文。总控在少量候选验证时即可按代码/截止/类别调用 `recommendation_context`。作者或审稿发现需要改变研究的问题返回研究负责人，同步 pending 与交接后重建对应单股材料并回到作者。正文与研究一致后由外层保存采用稿并执行既有 record-trace，再原样装配正文、同步本地页面、补缺失公司介绍。阶段日志和采用稿留在本轮 ai_tasks 目录。

少量候选的通用事实入口（不需要先写 trace）：

```bash
./.venv/bin/python -m stock_analyzer.ops.recommendation_context \
  --code <ts_code> --formation-date <formation_date> --as-of <as_of> \
  --category financial --output <临时目录>/candidate-facts.json
```

可重复 `--code`/`--category`（financial/company/price/industry）；按需 `--period YYYY-MM-DD`、`--sector-date YYYY-MM-DD`。先核对各财务类别的本地可得期间，不把漏查写成未披露。行业上涨数、有效分母、比例、层级和窗口同包；动态变化需要同口径跨日资料，不能靠嵌套的3日/5日窗口直接推出趋势变化。上述是事实与口径核对，不替代总控的因果判断、比较和未知取舍。


手动完整执行仍按本文完成写稿、成稿核对、record-trace 和共同收尾；不得跳过冻结前反查。已有冻结结果的补交不进入新研究流程。程序或模型失败不等于合法空名单。

冻结前定向核对命令（只读事实仓，仅写指定临时材料；可追加 `--compare-code` 带入必要近邻）：

```bash
./.venv/bin/python -m stock_analyzer.ops.recommendation_context \
  --trace local_archive/forward_selection/pending-trace-<formation_date>.json \
  --output <本轮临时目录>/recommendation-context.json
```


这是当前个人 A 股助手的正式每日推荐研究。只执行研究，不开发或修改程序，不改写 Skill，不启动新的模型进程，不读取未来行情。本任务由本地启动器（launchd + `tools/stock_ai.py`）按时启动并在必要时接替模型；启动器只负责启动与结果识别，不参与研究判断。

## 最终回复唯一来源

本文件及其引用的 `ops/forward-monitor-prompt.md` 是每日股票报告的唯一格式来源。

正常完成时：
- 最终回复必须是完整股票报告；
- 不得在生成归档后另写执行摘要；
- 不得把逐股说明压缩为每只一行；
- 不得展示最近未选、比较股或内部候选；
- 不得追加Git、工作区、测试和文件清理汇报；
- 复盘部分直接采用本次已记录的正式复盘Markdown，不重新摘要。

只有研究或正式归档失败时，才改为技术错误说明。研究已归档但网页同步失败时，仍交付完整股票报告，仅在报告末尾附一行“研究已归档，网页同步失败：<具体错误>”。

## 1. 每日准备与共同市场判断

本任务通常由外层启动器调用：启动器已在调用模型前运行一次 prepare，并把其 JSON 摘要与 `formation_date`、`action_date`、`selection_as_of` 一并提供。有外层结果时直接使用，不得重复运行 prepare，不得改变这些时间边界。仅当人工单独运行本 Prompt 且没有外层结果时，才在项目根目录运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection prepare
```

正常研究在次日前一自然日18:45启动，固定使用当天18:30上海时间截止；核心数据最晚等到18:55。这里的次日就是 `action_date`，必须为交易日，不能自动跳过休息日提前推荐。若明天不是交易日（`non_trading_day`），正常说明无需生成报告并结束，不运行复盘或新选股；周末和长假统一在下个交易日前一自然日晚间运行。周日使用周五行情、周日18:30公告，为周一提供复盘和推荐。20:30只是交付目标，不新增守护服务。

若返回 `ready_for_research`、`ready_for_research_limited` 或 `already_selected`，用返回的可靠 `formation_date` 和原始 `selection_as_of` 运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor prepare \
  --analysis-date <formation_date> \
  --as-of <selection_as_of>
```

然后读取 `ops/forward-monitor-prompt.md`。市场 Skill 每天只分析一次，同一份市场结果同时用于已有股票跟踪和当天新选股。先为 monitor snapshot 的 `daily_review_episode_ids` 形成全部结构化判断草稿，再按 `checkpoint_review_episode_ids` 确定节点股、从非节点中选0—8只普通详评、其余归简评；各写唯一正文并核对一致性后，先调用 `record-daily-formal-reviews` 保存账本，再 `record` 全部节点详评和普通详评的 `monitor-report`。`checkpoint_review_stock_count` 是节点股数，`regular_detail_stock_limit` 是普通详评上限，不是必写篇数；账本只保存简评类正文。只有 selection 返回 `ready_for_research` 或 `ready_for_research_limited` 时才继续当天 V4 新选股。managed 模式下本段复盘步骤由外层的独立复盘会话执行，选股会话跳过本段；手动完整执行仍按本段顺序完成。

进入任何复盘写作前（正常任务、`already_selected` 当日仅复盘、补跑路径均同），必须按 `ops/forward-monitor-prompt.md` 的分类知识库入口实际读取对应类型的指南与范文，并按其当前机会合同为每条需复盘记录形成 `current_opportunity` 当前意见；具体读取范围、选择方法与失败降级仅由复盘 Skill／Prompt 维护，不依赖此前对话的记忆，也不把范文名单或知识库路径复制到本 Prompt。

若 selection 返回 `already_selected`，仍可生成跟踪报告，但不得重复执行新选股。若 snapshot 的 `daily_review_episode_ids` 为空，只跳过逐股写作，仍通过既有 `record-daily-formal-reviews`、`record` 保存 `reviews=[]` 的空账本和 `alerts=[]` 的空详评报告；报告汇总、未详评数量及市场内容使用真实 snapshot 和本次共同市场判断，不一律填零、不借用旧报告。正常继续新选股或共同收尾。若返回 `non_trading_day`、数据缺口或错误，说明真实状态，不补猜。

把返回的以下三个字段作为唯一时间边界：

- `formation_date`
- `action_date`
- `selection_as_of`

不得改变 `selection_as_of`；不得读取 `available_at > selection_as_of` 的事实，也不得读取交易日期晚于 `formation_date` 的行情、行动日开盘/分钟走势或未来 D20 结果。

内部继续保留 `formation_date`、`action_date` 和 `selection_as_of`。面向用户只用普通日期说明：

> 本报告使用截至<selection_as_of>（上海时间）能够取得的公开信息，
> 以及截至<formation_date>收盘的价格数据，供<action_date>交易日参考。
> 截止时间以后至开盘前的新公告不属于本次正式研究范围；
> 足以影响参与条件的变化由次晨安全提醒单独说明。

正常报告开头必须使用上面这段完整说明。21:30只补采事实，不重算或改写本次正式研究；次晨08:45只按 `ops/preopen-safety-prompt.md` 提醒，不重新选股。

复盘时在当前状态行用 `<action_date>` 对应的推荐日期作简短前缀，并保留推荐后的交易日序号。

### 用户要求补跑晚间失败任务时

补跑通常由外层启动器完成：`tools/stock_ai.py run nightly --rerun-date <原计划推荐日期>` 已按此规则运行 prepare 并提供结果，此时直接使用，不重复运行。仅当人工单独运行本 Prompt 且没有外层结果时，先运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection prepare \
  --rerun-date <原计划推荐日期>
```

这个命令会把截止时间固定为原计划推荐日期前一自然日上海时间18:30，并由交易日历确定前一个交易日，不使用当前时间或当前价格。如果返回 `data_not_ready`，使用返回的原始 `formation_date` 和 `selection_as_of` 定向补一次：

```bash
./.venv/bin/python -m stock_analyzer data run-stage \
  --stage pre-research \
  --data-date <formation_date> \
  --as-of <selection_as_of>
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
- `announcement_status=announcement_unavailable`：公司 Skill 可以使用形成日及更早的正式事实，但不得形成刚在行动日前公开、尚无完整交易日的候选，也不得声称完整检查了研究截止前新公告。

- `limitations` 包含“股东增减持结构化补采未完成”：不能把未取得写成没有发生，不声称完整检查了该类事件。
- `limitations` 包含“解禁结构化补采未完成”：不能把未取得写成没有安排，不声称完整检查了解禁安排。
- `limitations` 包含“回购结构化补采未完成”：不能把未取得写成没有发生，不声称完整检查了回购事件。

上述可选缺口不阻断已确认可用的市场、价格、行业或主题研究，公司 Skill 也可继续研究其他已取得事实；必须把 prepare 返回的全部 `limitations` 原样写入 V4 的 `runtime_capabilities.limitations`，不得删除其中一项或将未取得写成没有事件。

`complete_core_date` 只作诊断，不再决定能否研究。`prepare` 返回的市场、价格、行业、主题、个股背景、`announcement_status`、`announcement_exchanges` 和限制才是本次真实能力边界。

若已经存在同一 `formation_date` 的正式选择，prepare 返回 `already_selected`，不得重复选股，但仍可继续已有股票走势复盘。

补跑报告开头必须在固定报告开头后补充说明：“这是对<日期>交易日前晚任务的补跑。研究仍使用原计划交易日前一自然日18:30的固定截止；当前价格不能替代当时的参与条件。”不得把补跑结果称为当前价格下的新推荐，也不得用盘中走势改写原判断。

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
2. 板块、公司和价格三个 Skill 在相同冻结边界和完整合格股票范围内分别依据自己负责的事实发现线索，不把其他视角的候选或结论当作本视角来源。同一会话中的视角分工不等于独立上下文盲审。
3. 公司 Skill 按“新增性 → 阶段 → 主营联系 → 材料性 → 财务传导 → 兑现时间 → 失败条款”核对主要事件，不判断价格接受。
4. 板块 Skill 按“共同动力 → leader/core 角色 → 同板块近邻”严格区分 `sector_broad_diffusion` 与 `sector_leader_cluster`，不替价格 Skill 判断个股完整连续性和余量。
5. 总控按股票代码归并候选，先确定结构化 `engine_type`、`engine_status` 和 `market_recognition`，再把同一批少量候选交给四个专业 Skill 独立验证。
6. 先区分信息型早确认与纯价格机会，价格 Skill 按“1/3/5 日连续性 → 单日贡献 → 有效收盘 → 成交推进 → 回落 → 组合余量”验证具体股票；对公司事件按需调用 `compute_event_reaction_features_v3`，不保存新表，不用旧版函数结果填充 V4 事件证据。
7. 总控按“同发动机组内比较 → 跨发动机比较 → 逐只绝对质量判断”解决冲突，拟定 0—5 只或空名单。每增加一只都重新判断绝对质量；不能因为它是剩余候选中最好的一只而补位。不投票、不打分、不凑数。
8. managed 模式由总控交出 pending 和完整推荐草稿，外层只接续润色、忠实核对及保存；总控与手动完整执行均在 `record-trace` 之前，按本文件“推荐说明写作前的定向阅读”实读教学和适用范文，完成推荐说明草稿；由当前执行 AI 对照具体成稿核查第 7 节的完整论证、事实来源及与 thesis/条件的一致性。关键缺口按总控回到本轮验证并调整取舍，全部一致后再保存 trace（managed 模式由外层保存）。判断或总控草稿任一更新，旧写审结果不再沿用；返研改变名单时核对材料和适用范文随之更新。已有冻结结果的补写只忠实表达，冲突报错不暗改历史。

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

每个 Skill 对每只深度候选保留真正改变取舍的证据及必要出处，合并重复信息；不以固定条数删掉决定性支持或反证。 价格 decision 的保存载体数量仍沿现有合同每股 1—2 条，多项原值和出处可放在同条记录中；该格式不限制研究或补证的事实数量。

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

手动完整执行在写作与审稿完成后使用 `prepare` 返回的原值运行；managed 模式由外层执行此命令，研究模型在交付 pending 后停止本节保存步骤：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection record-trace \
  --trace-file local_archive/forward_selection/pending-trace-<formation_date>.json \
  --formation-date <formation_date> \
  --action-date <action_date> \
  --as-of <selection_as_of>
```

只有返回 `selection_frozen` 或 `already_selected` 才算完成。若返回结构或证据校验错误，不得退回旧版轨迹，不得删减 V4 字段，应按错误定位当前 V4 JSON。

### 方法版本辅助记录（仅新增研究，失败不撤销推荐）

`record-trace` 返回 `selection_frozen` 后保存以下辅助记录；managed 模式研究者在实际读取时即保存同样内容并标明 pending 身份，外层冻结后沿用，不能补造“已读”。保存位置：

```text
local_archive/forward_selection/research-run-context-<action_date>.json
```

全部字段使用真实读取值，不凭印象填写，不使用中文占位值：

```json
{
  "run_id": "与本次冻结研究对应的既有 run_id",
  "action_date": "从本次 trace 读取",
  "recorded_at": "实际读取方法文件时的带时区时间",
  "repo_commit": "实际 HEAD",
  "method_revision": "方法文件集合最后一次相关提交",
  "method_files": ["本次实际纳入版本核对的方法文件相对路径"],
  "method_files_changed_locally": [],
  "model_id": null,
  "version_status": "recorded_at_run",
  "source_trace": "原 trace 的仓库相对路径"
}
```

方法文件集合固定为：五个选股 Skill 的 `SKILL.md`、`ops/forward-selection-prompt.md`、`docs/architecture/a-share-short-horizon-engine-contract-v4.md`，以及本次实际读取的 `src/stock_analyzer/knowledge/` 方法条目。在仓库根目录用 `git rev-parse HEAD`、`git log -1 --format=%H -- <实际路径列表>`、`git diff --name-only HEAD -- <同一列表>` 取得；路径列表由本次已读文件确定。方法文件有未提交修改时，只记录事实并把 `version_status` 标为 `uncommitted_method_changes`，不阻断正式选股，也不新增哈希或快照。`model_id` 只有运行环境明确提供时才记录，否则留空。该记录是辅助说明，不写入正式 trace，不改变推荐保存成功条件；保存失败时说明失败即可，不撤销已保存的正式推荐，不重跑研究。历史运行不补造此记录。

### 研究归档后的网页同步（共同收尾）

正常新选股、selection prepare 返回 `already_selected` 后的复盘更新，以及人工补跑，都必须在正式归档成功后执行本步，再输出合并报告。`already_selected` 分支直接核对已有正式 trace，不重复选股或再写 trace。休市、不具备研究条件或正式归档失败时不调用网页同步。

managed 模式本节及公司介绍由外层执行，研究模型不重复操作。手动完整执行先确认日评账本与复盘报告的记录结果均为 `recorded` 或 `already_recorded`；本次执行了新选股时，`record-trace` 必须返回 `selection_frozen` 或 `already_selected`。`review_conflict`、`report_conflict`、`invalid_result`、结构校验错误或仅存在 pending 文件，都不算归档成功。没有需逐股复盘的记录也须完成前述合法空账本、空报告归档。

逐字使用 selection prepare 返回的三个时间字段，在项目根目录运行：

```bash
./.venv/bin/python tools/render_prism_web.py \
  --date <formation_date> \
  --action-date <action_date> \
  --as-of <selection_as_of>
```

不得省略参数后让脚本猜最新日期，也不得用当前日期或时间替代。程序只读取正式 trace、snapshot、日评账本、复盘报告及原有本地事实，校验归档与时点一致后更新本地 A2 主用页面 `style-preview/prism-a2.html` 和 `prism-a2-report-<formation_date>.html`；备用 `prism.html` 及旧 `prism-report-*` 停止同步，也不作为新版数据来源；不改写研究、Forward CSV、复盘或冻结结论。渲染器不是云端上传命令，只生成本地页面；公网发布只经 `tools/publish_prism_a2.sh` 人工执行。推送成功不等于公网已经更新，公网可见性以实际页面为准。

检查退出码及输出：退出码 0 且 `published=` 为文件路径或 `unchanged` 表示固定网页已就绪；`published=skipped_newer` 表示仅更新本次日期页，保留较新首页，不得称首页已切换到补跑日期。同步失败时保留已完成研究和上一版固定网页，交付完整合并报告并附前述一行具体错误；后续恢复只重新执行同一同步命令，不重跑研究。进程若在归档后、调用命令前中断，补跑恢复时仍须执行本步。

市场说明和推荐正文由当前模型撰写；复盘与跟踪数量由原记录装配。外层 `tools/stock_ai.py` 先保留模型响应为 `model-reply.md`，将已保存复盘的三个分区原样装配进 `final-reply.md`，跟踪数量采用同一正式统计函数；复盘 Markdown 必须与正式 JSON/日评账本对应，源冲突时不替换任何源记录。随后在严格归档、CSV 与合并报告核对通过后，将装配并验收的全文原样原子保存到 `local_archive/forward_selection/daily-research-<formation_date>.md`，再权威同步一次。模型不自行把草稿写入此已验收正文位置。重复同文不改写，已有不同文则报告展示衔接冲突并保留原文；失败 final-reply 或文件非空不构成通过，正文缺项时 WEB 单独标识历史摘要。人工独立执行先走同一装配命令，再经过 `verify_completed_run` 与正文衔接，不能用直接同步替代：

```bash
./.venv/bin/python tools/nightly_report.py \
  --draft <模型草稿路径> --output <本轮final-reply.md路径> \
  --formation-date <formation_date> --action-date <action_date> --as-of <selection_as_of>
```

自动入口会执行装配，无需让模型另跑一遍。模型草稿保留四个总标题；复盘和数量分区只需注明“由已保存正式记录装配”，不再让模型重抄、改引号或缩写已有复盘。最终交付使用装配后的完整报告，不能把占位草稿当作交付。

### 公司介绍补齐（同一共同收尾，介绍失败不撤销推荐）

首次同步之后（无论成功或失败），读取 `ops/company-introduction-prompt.md` 并按其执行公司介绍能力：以本次三个时间字段备料，只为缺失介绍的正式推荐股票逐只写作并保存；名单为空、只有条件事件或全部已有介绍时不写作。写作方法与来源边界按 `.agents/skills/writing-company-introductions/SKILL.md` 执行，正文由 AI 逐篇撰写，不由程序模板拼接。

全部股票处理完后按两个条件决定是否第二次同步：本轮新增保存了介绍，或首次同步失败。满足任一条件，就逐字用相同的三参数再执行一次上面的同步命令；两个条件都不满足则不再同步。第二次同步失败不循环重试，研究和已保存介绍都保留。

介绍生成失败不撤销推荐、不阻断已完成的网页同步：某只失败时其他股票照常保存，缺项股票在页面上显示简单缺项说明。不得把介绍写入正式推荐正文、V4 轨迹、Forward CSV 或复盘；介绍错误不得写成研究错误。最终合并报告仅在确有缺项时追加一行实际情况（如"网页已更新；甲公司的完整公司介绍暂缺：官方业务资料未能取得。"），介绍全部成功或全部复用时不追加任何开发说明。

最终向用户只给出一份合并报告，使用通俗说法，不向用户展示 `formation_date`、`engine_type` 等内部字段名：

- 今天的市场情况
- 正式推荐股票的今日复盘
- 目前仍开放的正式推荐股票数量
- 今天明确推荐的股票

旧版“之前研究过的股票走势复盘”和“目前还在跟踪多少只”不再作为对外标题；前者会混入非推荐对象，后者会混入比较和内部关注数量。

内部归档和最终给用户的回复必须分开：

- snapshot、V4 trace、比较记录、最近替代和程序要求的本地 JSON/Markdown 继续完整生成，供内部研究、校验和以后评价使用，不得删减或改写合同。`daily-formal-reviews-<analysis_date>.json` 保存全部结构化判断及仅简评类正文，`DailyForwardMonitorReportV2` 保存全部节点详评和最多8只普通详评的唯一正文；没有公开的事件候选仍完整保留在 snapshot、事实仓和 trace。
- 最终回复的正式复盘只展示派生为 `confirmed_active` 的股票。比较股、最近替代股、未入选候选、未决股票和只在内部关注的股票都不展示、不点名，也不披露它们的表现或数量。
- `fresh_event_pending + conditional + pending` 继续作为 `conditional_event` 保留在内部 V4 trace；原有的 `selected` 身份、优先级、事件公司证据和首个交易日观察条件保持不变。conditional 不进入正式推荐数量，不写入“今天明确推荐的股票”，也不得虚构收益或在用户报告中单列。
- 同一股票同时有正式推荐和比较记录时，对外只讲正式推荐记录；内部仍保留完整比较。
- “目前仍开放的正式推荐股票数量”只按仍开放的 `confirmed_active` 股票代码去重统计，不展示比较记录数、内部关注数或未详细展示的内部股票数。
- 仅有 conditional 时，明确“今天没有正式推荐”并说明真实原因；不得拿事件线索补位，也不展示 conditional 名称、数量或首个交易日条件。

在输出这份合并报告前，只读取一次上海当前时间。只有本次 selection 返回 `ready_for_research` 或 `ready_for_research_limited`、实际生成了“今天明确推荐的股票”，并且读取到的时间已经达到或晚于 `action_date 09:30` 时，才在该部分前提示一次：“本次研究只使用了今天开盘前能够看到的信息，但现在已经超过原本计划观察的开盘时点。不要把当前价格当成当时可以参与的价格，也不要用盘中走势重新改写开盘前的研究结论。”09:30 前不提示，`already_selected` 不提示。不得改变 `selection_as_of`，不得重读盘中价格，也不得重跑研究。

“今天明确推荐的股票”只使用本节后面的唯一用户输出格式。
前面的内部研究问题用于形成判断，不再设置第二套对外问题清单。

“今天明确推荐的股票”只展示派生为 `confirmed_active` 的股票。空名单时直接用通俗中文说明今天没有正式推荐以及真实原因，不列普通观察、事件线索、候选、最近替代或内部排序。研究 trace 中继续回答“为什么选它而不是最接近的备选”，但最终回复不点名、不展示最近备选，也不另列替代名单；需要表达相对优势时，只说这只正式推荐股自身强在哪里。

`conditional_event` 的条件后来满足，也不把原 trace 改成正式推荐；若后续正常形成日已独立满足 `event_repricing_confirmed + active`，由新的研究 trace 负责新的正式入口和评价。这个内部流程不在用户报告中展示。

可以给出正式推荐股票或空名单及排序，但不得向用户显示七种内部英文分类、内部状态、内部日期字段或研究轨迹字段。公司新消息刚公开、尚未经过完整交易日验证时，只保留在内部事实和 trace，不能出现在最终用户报告。

## 7. 对外文字必须是人话

这是个人股票助手，不是研究平台、审计系统或数据看板。结构化字段只用于内部留痕，最终回复必须先说事实，再用少量数字解释这些事实意味着什么。

用户不是来学习内部研究方法。最终说明不得解释“我们用了什么规则”，而要解释“这家公司发生了什么、股票为什么被选中”。

### 推荐理由必须是一个完整论证

事实本身不是推荐理由。涨幅、成交额、行业上涨面、财务变化和价格位置只是证据。最终必须说明为什么这些事实让继续上涨更有可能，哪些事实支持，哪些事实反对，以及为什么最不利的事实暂时没有推翻推荐。

每只正式推荐股票必须回答以下七项。它们是研究与写前自检问题，不是七段公开提纲：一个段落可以回答多个问题，不要求每项单列数字：

1. **核心判断是什么**：未来约20个交易日可能继续上涨，主要依靠行业整体转强、公司新变化，还是股票自身持续走强。
2. **为什么这个判断可能成立**：说明行业、公司经营和股票表现之间怎样相互印证，不讲内部字段。
3. **为什么是这只股票，而不是同行里另一只**：同行普涨只证明方向值得关注；还要说明这家公司业务为什么真正相关、股票为什么比普通同行更强。
4. **事实为什么有意义**：每个数字都要说明它证明了哪一点。不能只写数字。
5. **最不利的事实是什么**：明确它怎样降低继续上涨的可能性。
6. **为什么仍然选择**：解释支持因素为何暂时超过不利事实；若无法解释，不得正式推荐。
7. **什么情况会证明选错**：用未来正常交易日可以观察到的事实说明。

不得把涨幅、成交额和涨停贡献并排后直接得出推荐。

表达由本次已有主要依据决定：板块型说清共同变化与本股差异；价格型说清上涨延续的证据与已经付出的涨幅；公司事件型说清真实新增信息及经济意义。完整指标已用于研究，正文按解释价值选用，不强制逐项列出数量、两个相对收益、成交额、贡献占比及所有财务数字。冻结前的证据判断仍由原流程完成；冻结后发现事实冲突应报告具体问题，不静默删股重排。

数字不能单独列成“关键数字”。数字必须放进解释中。例如：“32只农业相关股票中有30只最近都在上涨，说明这次上涨不是一两只龙头硬拉出来的。”

说明前面已经涨了多少时，直接回答：“前面已经涨得多不多，接下来还有什么理由支持继续上涨。”

风险部分直接回答“最需要担心什么”。资料没有取得时写“这部分资料暂时不完整”，不能把资料缺失冒充公司经营风险。

研究判据由总控及对应专业 Skill 维护：价格连续性、单日贡献、成交推进、回落和余量见价格 Skill；公司经营与短期催化的区别见公司 Skill；行业广度与本股差异见板块 Skill。写作只解释本轮已形成的取舍，不在这里维护第二份选股门槛。具体成稿若不能解释为什么接受风险，返回总控验证，而不是加一句更好听的话。

具体写法按本节的首次推荐定向阅读入口，读取仓库教学与适用认可范文。用普通中文解释研究含义，不把内部术语、标签和流程直接搬到正文；不另维护一份逐词禁用表或重复例句。

### 唯一用户输出格式

汇总表只能作为目录，不能代替逐只说明。名单、顺序和内部研究结论在写作时已有明确拟定版本，成稿核对后一起冻结；写作步骤本身无权更改取舍；下面的说明只负责把已有研究讲清楚，不得新增候选、删除股票、改变顺序、改写当时理由或重新运行选股。

## 今天的市场情况

只使用当天已完成的市场分析，用通俗中文说明市场环境及其对正式推荐的含义。

## 正式推荐股票的今日复盘

复盘写作与逐篇复查按 `.agents/skills/reviewing-stock-recommendations/SKILL.md` 和复盘 Prompt 的已批准范文执行；本合并步骤由程序从正式结果原样装配，不重新改写分析或呈现。

程序装配与网页刷新后，逐只核对节点详评的阶段结论标题、普通详评的告知标题及各自分析正文与正式记录一致；不能因文件已存在而保留旧正文，也不能由合并步骤另拟标题或摘要。首篇检查过程留在本任务运行记录，最终回复仍只输出完整股票报告。

直接采用本次已记录的正式复盘 Markdown，只展示明确正式推荐过的股票，并依次包含：

以下复盘呈现规则描述程序装配后的成品，不要求模型在草稿中重复撰写已保存复盘。

合并报告的四个总标题固定使用二级标题（`##`）。复盘内“关键节点复盘”“今日深入复盘”“今日简评”各自使用独立标题行，每组只出现一次；建议使用三级标题（`###`），也允许保留独立复盘 Markdown 原有的二级标题。验收仅在“正式推荐股票的今日复盘”至“目前仍开放的正式推荐股票数量”之间识别这些分组，接受二至六级及其混排；仍须逐股核对分组、原正文和简评行，不因标题层级兼容而省略实质检查。不改写已记录的逐股分析标题或正文。

### 关键节点复盘、今日深入复盘 与 今日简评

依次包含三个分区（空分区写“今日无……”）：关键节点复盘与今日深入复盘为两类详评，每股采用状态行＋三段；今日简评为六列简表：

```markdown
| 股票 | 当前观察日 | 当前涨跌 | 今日简评 | 未来1—3日 | 主动跟踪 |
```

简表每只简评股一行；正文读取当日台账中 `brief` 类的 `DailyFormalReviewV1.current_review`，结构化结论读取台账。

### 关键节点复盘 与 今日深入复盘

到达 D1/D3/D5/D10/D20 检查节点的股票全部进入“关键节点复盘”，每只说明本次深入复盘原因（到达第几个交易日检查节点或补20日结案）；剔除节点后按优先级选最多8只进入“今日深入复盘”，每只说明当日入选原因，正文按 `.agents/skills/reviewing-stock-recommendations/SKILL.md` 的当前机会版普通详评四项写作，运行与范文入口见 `ops/forward-monitor-prompt.md`；这里直接采用已保存原文，不另写一套旧目标余程摘要；没有需要时写“今日无深入复盘。”。两类详评每只先写一行当前状态，显示推荐日期、交易日序号、收盘相对推荐参考价、期间最高收盘和最深下跌，只使用已取得的事实。然后采用以下三段：

**今天发生了什么**

展示独立展开的详评正文 `ForwardEpisodeReviewV1.current_review`：说明今天发生了什么、当前看法及重点日的阶段展开。详评与当天账本的结构化结论一致，账本不另写详评股的简评正文；观点变化说明仍读取当天日评的 `view_change` 与 `view_change_reason`。

**相比上次判断**

直接采用当天日评的 `view_change` 与 `view_change_reason`，说明判断维持、增强、减弱或被事实否定及其原因。

**接下来1—3个交易日**

依次显示当前方向、方向理由、支持当前方向的表现、改变当前方向的表现；偏弱判断的支持条件是继续偏弱，恢复上涨属于改变条件。

原推荐理由和风险作为内部历史锚点，普通日不重复公开；D1 可在当前状态后用一到两句话提示原推荐背景，D20 才允许独立完整结案，使用“20个交易日最终复盘”，不在当天正文重复。多个推荐记录只用推荐日期和交易日序号的简短前缀区分。

本节负责观点更新；下节“今天明确推荐的股票”负责首次完整论证，两部分不共享小标题，不互套模板。

## 目前仍开放的正式推荐股票数量

只使用正式推荐生命周期统计，不显示事件线索、比较记录或其他内部关注数量：

```text
主动跟踪：X只
仅保留评价：Y条
已完成：Z条
```

## 今天明确推荐的股票

| 顺序 | 股票 | 为什么会选它 | 最需要担心什么 |
|---:|---|---|---|

### 股票名称（代码）

**公司主要做什么**

用一两句说明与本次判断相关的主营产品、服务或客户。不复制完整公司介绍，不默认报业务占比；占比真正影响本次判断时才使用。

**为什么会选它**

开头直接给本次已有的判断：未来约20个交易日看好什么、最主要依据是什么。不用“较早确认、正常启动、已经偏晚”等阶段名称代替实际说明。

围绕这一个判断自然展开。解释最有用的支持证据、已经上涨带来的代价、最重要的不利因素及为何仍然选择；需要几段由内容决定，不强制四路各一段、正反分段或每段句数。主文中必须让读者看到重要风险，不能全部交给网页折叠区。

不再单设“行业或外部变化”“股票自身表现”“公司经营”“主要不利因素”“综合判断”作为必写栏目。公司经营仅提供基础时简述它的作用和限制；确有公司或行业新变化时围绕该变化组织，不套价格型范文。

数字按解释价值挑选，不逐项展示已经检查过的指标。关键原值继续留在既有研究记录。可将显示用收益等适当取整并写“约”，但观察价位、事件条款、日期、条件组合及百分比/百分点的含义必须准确。没有足够依据的精确指标可以省略，不以模糊结论冒充原数据。

第一段已给出的总判断，后文用证据支撑，不在末尾再写一段同义的“综合后仍推荐”。同一事实承担不同作用时可以解释，不做机械去重。删掉无新增含义的重复，不能删掉影响选择的反面事实。

**什么情况会让我改变看法**

用简明文字忠实说明原研究记录已有的削弱、推翻和无法参与条件。保留“同时/且/或”、盘中或收盘、连续或单次、信号确认时点的含义；不新增任意价位、涨幅上限、仓位、止盈或止损。

AI 检查的是事实与推论是否相称、是否回答选择问题；程序只核对身份、时点、完整性和正文对应，不以程序通过代替文章质量。

`selection_reason` 是索引摘要，不等于对用户交付的完整文章。成稿逐段检查：是否只是把摘要贴到“为什么会选它”下面，关键推论有无解释，是否把“前面跌过/目标低于前高”直接说成空间充足，是否把未读到资料写成公司没有披露。不以字数、段数或固定句型判定质量；冻结后的具体矛盾按后文如实报告，不能用润色加强原结论。

推荐正文的股票标题继续使用“### 股票名称（完整代码）”，内部小标题使用上述加粗格式，不改为#级别标题，以免影响现有原文提取。说清即停，不设文章字数、段数、句数或数字数量的验收门槛。

### 推荐说明写作前的定向阅读

拟定名单已有、尚未执行 `record-trace` 时，实际读取 `.agents/skills/orchestrating-stock-research/references/selection-writing-calibration.md`；冻结后的补写沿用此教学。同任务已读复用；零拟推荐跳过范文，不影响空名单说明。

按 `local_archive/knowledge-vault-path.txt` 定位本机子库，依次实际打开其 `AGENTS.md`、`10_方法与范文/00_已确认写作要点.md`、`10_方法与范文/推荐说明范文/00_阅读指南.md`，再按指南选读当前适用的推荐说明范文全文及批注。链接、嵌入、看到文件名或此前对话记忆不算读取。行业型、事件型和价格型都可学论证方法，不能复制范文中的事实、价位或结论。

打开具体范文全文前，按指南及文件 frontmatter 核对其事实截止与本次 `selection_as_of`；含本次截止后事实/未来结果的全文不读，只使用通用教学。历史原方法回放仍遵守当时版本，不能借文风学习引入后来方法。新候选稿、三类复盘、完整公司介绍不作为本类默认模板。路径、规则、指南或适用全文不存在/不可读时说明一次实际缺项，按仓库教学继续，不声称已读，不创建新库或借知识库缺项扩展研究。

范文只教论证与表达，研究结论来自本次事实。冻结前成稿发现实质缺口，按总控返回验证并同步理由与去留；冻结后发现冲突只报告具体问题，不修改股票身份、顺序、条件或原 trace。

### 去掉机械和平台腔

- 不显示内部字段名、英文枚举、记录编号、内部角色、流程状态或交易日缩写。
- 不连续重复“目前”“整体”“综合来看”“仍需观察”“从数据来看”等空话。
- 不逐项朗读所有数据，只保留真正改变判断的数字，并立即说明这个数字意味着什么。
- 不写“系统检测到”“模型认为”“根据规则触发”“进入某状态”等平台话语，直接说股票发生了什么。
- 不堆叠免责声明。全篇只在确有必要时说明一次时间边界或条件限制，不在每只股票后重复。
- 不作收益承诺，不提供仓位、自动交易、目标价、止盈或止损建议。

提交最终回复前逐只朗读检查：用户能否直接听懂“公司做什么、为什么选它、每项事实为什么支持或反对、为何仍然选择、什么情况会证明判断变差”。听不懂、只有数字或像模板，就重写后再输出。


### 信息型早确认运行补充

按 V4 合同第10节与五 Skill 执行可选 early_confirmation；只有真正新增信息且首个完整交易日响应已发生才可用。不得为满足字段猜来源、成员、时间或收益。推荐理由用普通话回答“发生什么新变化、已得到什么响应、为何不继续等、当前剩余路径和最强反证”。既有 formation_values 时间线缺失填 null，method_revision 指向实际使用版本。20日批量检验仍读 ops/selection-method-review-prompt.md；当前改变已获本次用户授权，未来改规则另需批准。
