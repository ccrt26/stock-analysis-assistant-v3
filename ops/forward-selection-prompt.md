# Codex 原生 09:05 Scheduled Task 提示

这是当前个人 A 股助手的正式每日推荐研究。直接使用 `$orchestrating-stock-research`；不要开发或修改程序，不要改写 Skill，不要启动新的 Codex/模型进程，也不要调用未来行情评价。

先在当前项目根目录运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection prepare
```

该命令只做确定性准备：确认交易日、等待现有 09:00 次晨数据任务就绪、冻结 `formation_date`、`action_date` 和带时区的 `selection_as_of`、检查四类派生结果并结算到期 D20；它不运行 AI。只有返回 `status=ready_for_research` 才继续。若返回 `already_selected`、`non_trading_day`、数据缺口或错误，说明具体状态后停止，不补猜。

把 prepare 返回的三个冻结字段作为本次唯一时间边界：

- `formation_date`：所有行情和形成日观察的最晚交易日期；
- `action_date`：计划参与日；
- `selection_as_of`：事实可见性的截止时点，必须早于行动日 09:30。

研究运行超过 18 分钟或在 09:30 以后完成都不使结果失效。完成时间不得移动已冻结的 `selection_as_of`；不得读取 `available_at > selection_as_of` 的事实，也不得读取交易日期晚于 `formation_date` 的行情、行动日开盘/分钟走势或未来 20 日结果。

在同一个顶层研究会话中按总控 Skill 的当前合同实际使用四个专业 Skill：

1. `interpreting-market-macro` 直接读取当日 `market_context` 一行，冻结唯一结构化 `market_propagation_environment` 和搜索含义，不输出股票；
2. `researching-sectors-industries` 先在 DuckDB 投影、过滤 `sector_hotspot`，再对少量板块查形成日有效成员；`sector_diffusion` 股票线索必须形成包含候选自身的 `sector_leader_cluster`；
3. `researching-company-events` 第一轮只查形成日新增的结构化财务、业绩、回购、减持、解禁和公告元数据，并按截至 `selection_as_of` 的历史披露结构化判断首次披露、实质增量、重复披露或历史不足及新增信息等级；原文只在少量候选验证中按需读取；
4. `analyzing-price-trading` 先用 SQL 读取程序已生成的场景身份、相对市场/申万二级行业、量价推进、突破、涨停贡献、ATR 目标距离和流动性，缩小范围后再深度比较；公司 Skill 已识别形成日可见的具体事件时，可按需使用 `compute_event_reaction_features` 计算事件前 5 日和事件后 1/3/5 个完整交易日的相对市场、相对行业和成交额反应，以 `event_price_reaction` 记录实际使用，不另存新表。

市场先输出搜索环境，板块、公司和价格独立发现；总控归并候选并冻结命题后，四个 Skill 独立验证同一批少量候选，提交前不读取彼此结论。总控解决冲突并最终选 0—5 只，不按专业 Skill 投票、证据数量、场景数量、固定分数或 Gate 排序。

所有正式入选统一按这条链解释：

```text
新信息或新需求
→ 是否形成板块传播或股票需求
→ 相对市场和行业的价格成交是否确认
→ 上涨路径是否仍未耗尽
→ 基本面锚和公司风险是否支持
```

公司催化、基本面锚、传播和价格确认不得混写。业绩、估值、现金流、低位、材料完整度、没有透支或行动日条件都不能单独替代短期上涨发动机。形成日收盘后、`available_at <= selection_as_of` 且由公司 Skill 判为首次披露或实质增量的重大新信息，可以在没有首个完整反应交易日时用 `engine_status=fresh_event_pending` 条件性入选；它必须引用同一事件的 `awaiting_first_session` 行动条件，不能写成 `confirmed`。重复披露、一般财报、有限增量或无新增信息不适用。

股票范围为上海主板、深圳主板和创业板；排除科创板、北交所、场内基金、ST/\*ST、退市整理、停牌、无可靠报价及行动日明确无法正常参与的股票。最终允许 0—5 只或空名单，不补位、不凑数，不区分 forward 与 reconstructed。

只保留实际候选和最多 3 只最近未入选股。每个 Skill 对每只深度候选最多保留 1—2 条真正改变取舍的证据，不重复大段相同事实。每只候选必须结构化填写 `engine_type / engine_status / market_recognition` 和公司披露新颖性；每只入选还须分开说明公司催化、短期上涨发动机、传播、价格确认、剩余路径、基本面锚、公司风险、关键未知和为什么优于最接近替代股。入选股和实际 `nearest_nonselection` 每只保留 1—2 条价格证据；没有合适场景时使用 `raw_price`。`confirmed` 的价格 `support` 必须至少记录 `observation_date`、一项收盘价或绝对收益、一项成交额或成交额比，以及一项相对市场或申万二级行业收益；标签、布尔值、位置、ATR、行动条件不能替代。

完成研究后，只生成一份 `trace_version=daily-research-trace-v3`、符合 `stock_analyzer.ops.forward_selection.DailyResearchTrace` 的 JSON。每条 `decision_trace` 使用唯一 `decision_id`；每只候选填写结构化 `research_thesis` 并以 `decision_ids` 引用本股票证据。`confirmed` 入选引用公司证据和合格价格 `support`；`fresh_event_pending` 引用公司重大新事件及同一事件的价格 `action_condition`；`sector_diffusion` 另引用板块证据并填写龙头簇。`research_result` 仍符合现有 `ResearchResult`，`skills_used` 必须是实际使用的五个 Skill；若 0 只，`selected_stocks=[]` 并填写真实 `empty_reason`；若研究或事实查询失败，按现有失败合同填写，不伪装成空名单。`formation_values` 只保存当时实际使用的少量数字、布尔值或简短状态，不保存整行派生数据。程序只检查结构、时点、引用角色和最小数值，不替 AI 判断事件语义、材料性或发动机是否成立。

把这份唯一 JSON 保存为：

```text
local_archive/forward_selection/pending-trace-<formation_date>.json
```

然后使用 prepare 返回的原值运行（不要重新生成时间）：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection record-trace \
  --trace-file local_archive/forward_selection/pending-trace-<formation_date>.json \
  --formation-date <formation_date> \
  --action-date <action_date> \
  --as-of <selection_as_of>
```

只有 `record-trace` 返回 `selection_frozen` 或 `already_selected` 才算完成。程序会从完整 trace 抽取现有 ResearchResult 行写入原 Forward CSV，并把完整轨迹原子移动为 `research-trace-<formation_date>.json`；不再另外生成 pending ResearchResult JSON。最终向用户直接给出正式推荐股票（或空名单）、排序和详细理由。
