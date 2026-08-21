# 手动 D20 研究复盘提示

这是人工发起的集中复盘，不是 Scheduled Task。只读取已经成熟 D20 的形成日，使用现有 Forward CSV、`local_archive/forward_selection/research-trace-*.json` 和当时可回放事实；未成熟日期不进入结论。

使用现有确定性函数，对每个成熟形成日的完整合格股票范围重算 11 个场景 case/control，不重新拟合阈值；对当时 trace 已引用的具体公司事件，按原 `as_of` 重算事件价格反应，不把后来事件补进形成日理由。分开评价：

1. 场景本身的历史关联；
2. 事件反应事实与当时所写发动机是否一致；
3. AI 在当日 trace 中如何使用场景、`raw_price`、催化、传播和价格确认。

只对 `daily-research-trace-v3` 使用结构化字段分层：先按 `engine_type`，再按 `engine_status=confirmed | fresh_event_pending | unconfirmed | invalidated` 汇总；旧版 trace 保持原样，只能按其实际字段单独描述，不倒填 v3 状态。`fresh_event_pending` 单独检查行动日以后是否出现预期的首个完整反应交易日，但不得把后来结果回写成形成日确认。

三者均分开比较可执行的收盘 20% 触达、最大收盘路径、MFE、MAE 和 D20 收盘，并检查：

- `provisional` 支持是否错误提升了候选；
- `provisional` 反证是否错杀了实际最近替代股；
- `supported_with_boundary` 和 `observation_only` 是否按权限使用；
- 当时实际引用的 `formation_values`、最强反证和同类比较是否与最终去向一致。
- `research_thesis` 是否把业绩、估值、现金流、低位或行动条件误当发动机；
- `decision_ids` 是否能还原哪条公司与价格证据实际支持、反证、比较或改变了选择。
- `confirmed` 是否真的留下观察日期、绝对价格或收益、成交额或成交额比、相对市场或行业收益；`fresh_event_pending` 是否确为形成日收盘后重大首次/增量事件并引用同一事件的等待窗口。
- `market_recognition` 是否引用当日 `market_propagation_environment`，`sector_diffusion` 是否留下形成日有效成员的 `sector_leader_cluster`，公司事件是否留下披露新颖性与新增信息等级。

对后来达标但未入选的股票，每只只归一个主要原因：`discovery_miss`、`decision_miss`、`data_capability_miss`、`future_catalyst`、`non_executable` 或 `no_point_in_time_case`。未来结果只用于确定倒查对象和评价取舍，不得制造形成日理由。

输出一份紧凑复盘：成熟日期与样本数、按发动机类型/状态的结果、场景结果、AI 使用结果、错失归因、可能需要人工调整的 Skill 条文和支持/反对证据。必须区分“发动机类型本身后续表现如何”和“AI 当时是否正确理解、引用并据此改变选择”。不自动修改 Skill，不创建数据库、模型、平台、新定时任务或统计 subsystem。成熟样本过少时只做描述，不宣告规则有效或无效。
