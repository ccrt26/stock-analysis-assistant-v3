# 已正式推荐股票的每日状态跟踪（state-change-v1）

本 Prompt 仅用于 `run_policy.monitor_review_policy=state-change-v1` 的新任务。旧已开始任务由启动器只读 `ops/forward-monitor-legacy-prompt.md`，不得在同一任务并行采用两套写法。本步骤属于现有18:45晚间任务及正常手动入口，不创建新任务。managed 模式由现有独立复盘会话承担，不重新选股、不调用其他模型、不生成公司介绍或网页；外层继续负责正式合并日报与展示。

先读取 `.agents/skills/reviewing-stock-recommendations/SKILL.md`。其三态、结束原因、资料缺口、episode、节点和来源要求为本次活动业务合同。写法只读 prepare 输出 `input_file` 中所选的 `00_阅读指南.md`、`01_状态变化复盘_范文与注意事项.md`、`02_简单复盘_范文与注意事项.md` 全文，每任务各一次；文件内容内嵌于输入索引并带来源，不能只看到键名就声称已读。两篇分别为历史报告编辑和匿名虚构教学，均不是本股研究证据，示例数字不可成为实际规则。不读旧节点六项/普通详评四项范文。

## 1. 冻结输入与全覆盖

selection prepare 已确定 formation_date、action_date、带时区的 selection_as_of；沿用，不重新执行 selection prepare。使用同一日期和截止：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor prepare \
  --analysis-date <formation_date> \
  --as-of <selection_as_of> \
  --review-policy state-change-v1
```

读取返回的 `snapshot_file` 与 `input_file`，核对两者日期、as_of、策略一致。input-index 是紧凑供料，原 snapshot 是事实权威；当判断受重要公告影响时据索引读取正式原件或可靠摘录。市场资料只分析一次，行业和同股资料共用；每个 `daily_review_episode_ids` 均必须作出本日判断或明确无法可靠判断，不只看“提醒股”。完整旧条件和风险不得截断；价格路径用原确定性累计值与近期数据，不逐股读全部60日日线。需要时按原件索引定向查阅，不链接不可读位置。

原已结束 episode 的普通日不进入 AI 日评；`previous_tracking_stop` 仅证明同 episode 旧正式 live 已停止，不补造历史三态；`required_final_review_episode_ids` 中仅欠 D20 的早停记录用 `internal_only` 填简短结论，不重新激活。一次任务同版 snapshot/已存账本/报告直接复用，未完成只补缺，不重扫已完成股票。若缺关键事实，不能把未知改成“今日确认继续”；上次三态及判断日期如实保留。

## 2. 一份判断与正文

对每个应日评的 episode，先按原推荐身份、原条件、上次有效状态、本次增量和累计路径判断 `follow | wait | ended | null`。`ended` 同时填精确 `tracking_end_reason`。程序从前后态核对分类，不根据 `participation`、`view_change`、到达节点或文字长短分类。

`pending-daily-formal-reviews-<analysis_date>.json` 使用原 `DailyFormalReviewLedgerV1` 和每行 `DailyFormalReviewV1`，`ledger_version` 不变；账本和每行均填 `monitor_review_policy: "state-change-v1"`。既有 `current_assessment`、`current_path`、主要解释、最弱环节、`view_change`/原因、1—3日展望、`tracking_decision`/原因、`current_opportunity`、D20结案仍按原事实口径填写。`current_opportunity` 是当前参与意见，不能机械映射三态；同股共享当前意见。

- 状态未变、首次登记或今日资料不足：`review_kind=brief`。同股选最新仍跟踪 episode 的账本 `current_review` 写唯一短正文；其他 episode 的 `current_review=null`。重要新消息、风险或当前参与意见变化仍写清。缺资料时标上次判断日期，不能宣称今日已经确认不变。
- 任一 episode 真实从 `follow↔wait` 或 `follow/wait→ended`：变化股相关行 `review_kind=regular_detail`，其他未变 episode 仍为 `brief`；该股所有账本 `current_review=null`，唯一变化说明写在报告 alert 的 `stock_review`。正文必须区分不同推荐日期；真实变化超过8只也全部入报告。
- 已结束的 episode 只欠原 D20：`review_kind=internal_only`，`tracking_state=ended`，保留原结束原因，`current_review=null`、`current_opportunity=null`；`final_twenty_day_review` 和原价格结果留内部，不写公开文章。存在 `previous_tracking_stop` 时，原 `reason` 原样保留为 `tracking_decision_reason`，日期和明确的结束原因沿原记录；不得通过 brief 绕过。

初次没有有效三态不伪造变化。跟踪中出现数据缺口可设 `tracking_state=null`，但 `current_assessment=insufficient_evidence`，操作上继续检查，不把资料故障等同于稳定、等待或失败。`ended` 不能回到 `follow/wait`。正常 D20 默认 `ended + observation_complete + complete_observation`，简明说明结果；原目标提前达到不提前结束或抬目标，已明确批准的 D25/D30 延长沿用且 D20冻结。`thesis_invalidated` 要有原条件确认或足以否定原主要上涨依据的可信事实，不能单靠下跌/未达目标；`not_executable` 要有确认无法按原条件参与的证据。结束不等于卖出，也不宣称未来不会涨。

节点 D1/D3/D5/D10/D20/D25/D30 的事实、路径指标及本日简短判断在原 snapshot/账本/报告归档互相引用；节点到来不自动转态或写长文。D20 固定结案必填，早停也不能漏；晚补只用原 D20 窗口及当时可得解释事实，缺失保持 unknown。若 `final_review_delivery_only=true`，只原样复用输入的 `frozen_twenty_day_review` 并补缺失保存/装配，不重新研究其结论；缺失报告不等于缺失结案对象。避免在公开日报从 final 字段追加结案长文。

## 3. 保存与同股核对

完成全体判断和唯一正文后，同一执行者按输入指南通读实际公开正文，检查事实对判断的意义和下一观察点是否说清，不用登记/标签代替解释，不强制字数或段数。同时逐股核对时间、原风险与完整条件、关键数字来源、重要公告正文、前后态及结束原因；待核的事实只留下待核，不编买卖门槛、确认时长、价格或来源。然后保存：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor record-daily-formal-reviews \
  --snapshot-file local_archive/forward_monitor/snapshot-<analysis_date>.json \
  --review-file local_archive/forward_monitor/pending-daily-formal-reviews-<analysis_date>.json
```

`pending-report-<analysis_date>.json` 沿用 `DailyForwardMonitorReportV2`，填 `monitor_review_policy: "state-change-v1"`、市场/总体字段与 snapshot 一致；`alerts` 恰好包括每只有真实状态变化的股票，不截断、不补位。每股一条 `ForwardMonitorAlertV2`，`episode_ids` 覆盖该股当天全部应日评 episode，`stock_review` 为唯一公开正文，`episode_reviews.current_review=null`；原结构化事实与对应日评一致。没有状态变化时 `alerts=[]`，仍保存报告与简评账本。保存：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor record \
  --snapshot-file local_archive/forward_monitor/snapshot-<analysis_date>.json \
  --report-file local_archive/forward_monitor/pending-report-<analysis_date>.json
```

`record` 的 Markdown 是已存正文的确定性展示，不写投资结论。managed `same-day-current-opinion-v1` 先交两份 pending 文件与原 snapshot，不提前 record；原同股意见核对通过后由外层按同一 record 保存。修明确错误时只改本日未存、受影响股票；正式冲突不得覆盖旧文章或重跑全部模型。旧档案和旧任务只由 legacy 策略读取，不迁移。

面向用户的日报由现有装配器从报告和账本生成，只有“状态变化复盘”与“简单复盘”两组；同股正文显示一次，内部节点及 D20 结案不另附大篇。未完成股票或内部结案如实列出，不能声称已经全覆盖。
