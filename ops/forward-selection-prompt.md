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

然后读取 `ops/forward-monitor-prompt.md`。市场 Skill 每天只分析一次，同一份市场结果同时用于已有股票跟踪和当天新选股。先根据 monitor snapshot 生成并 `record` 跟踪报告；只有 selection 返回 `ready_for_research` 时才继续当天 V4 新选股。

若 selection 返回 `already_selected`，仍可生成跟踪报告，但不得重复执行新选股。若当天没有仍在跟踪的记录，跳过跟踪明细，正常执行新选股。若返回 `non_trading_day`、数据缺口或错误，说明真实状态，不补猜。

把返回的以下三个字段作为唯一时间边界：

- `formation_date`
- `action_date`
- `selection_as_of`

不得移动已经冻结的 `selection_as_of`；不得读取 `available_at > selection_as_of` 的事实，也不得读取交易日期晚于 `formation_date` 的行情、行动日开盘/分钟走势或未来 D20 结果。

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

## 3. 五个 Skill 的执行顺序

1. 市场 Skill 读取当日 `market_context`，输出六种之一的 `market_propagation_mode`，并按事实填写可并存的 `market_risk_overlays`；市场不输出股票。这一步只运行一次，并把结果同时交给跟踪和新选股。
2. 板块、公司和价格三个 Skill 在相同冻结边界和完整合格股票范围内独立发现，提交前不读取彼此候选。
3. 公司 Skill 对主要事件核对完整披露链：预告、预告修正、快报、正式报告和更正，并确定 `new_information_level`。
4. 板块 Skill 严格区分 `sector_broad_diffusion` 与 `sector_leader_cluster`，保存 V4 要求的成员和传播原值。
5. 总控按股票代码归并候选，先确定结构化 `engine_type`、`engine_status` 和 `market_recognition`，再把同一批少量候选交给四个专业 Skill 独立验证。
6. 对具体公司事件，价格 Skill 按需调用 `compute_event_reaction_features_v3`；不保存新表，不用旧版函数结果填充 V4 事件证据。
7. 总控解决冲突，最终选择 0—5 只或空名单。不投票、不打分、不凑数。

## 4. 七种发动机与两条入选通道

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

正式入选只有两条通道：

### 已确认通道

适用于：

```text
event_repricing_confirmed
sector_broad_diffusion
sector_leader_cluster
independent_demand_acceleration
```

必须是 `engine_status=active`、`market_recognition.status=confirmed`，并引用满足 V4 最小原值和路径质量要求的价格 `support`。

### 条件性新事件通道

只适用于 `fresh_event_pending`。必须是：

- 形成日 15:00 后首次公开；
- `new_information_level=substantive_new`；
- 与主营直接相关；
- 材料性可解释；
- 截至 `selection_as_of` 尚无首个完整交易日；
- 引用同一事件的公司 `support`；
- 引用 `event-price-reaction-v3` 的 `action_condition`；
- 保存公告前相对表现及抢跑/透支事实。

它只能是 `engine_status=conditional`、`market_recognition.status=pending`，不能写成已确认。

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

- 今日市场
- 已有股票重点提醒
- 跟踪数量概览
- 今日新选股

“今日新选股”部分给出：

- 正式推荐股票或空名单
- 排序
- 发动机类型和状态
- 为什么是现在
- 价格确认或条件性首次定价要求
- 剩余路径
- 最强反证
- 与最近替代股的比较
