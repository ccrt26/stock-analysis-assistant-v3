# 手动 D20 研究复盘提示

这是人工发起的集中复盘，不是 Scheduled Task。只读取已经成熟 D20 的形成日，使用现有 Forward CSV、`local_archive/forward_selection/research-trace-*.json` 和当时可回放事实；未成熟日期不进入结论。

使用现有确定性函数，对每个成熟形成日的完整合格股票范围重算 11 个场景 case/control，不重新拟合阈值。分开评价：

1. 场景本身的历史关联；
2. AI 在当日 trace 中如何使用该场景或 `raw_price`。

两者均分开比较可执行的收盘 20% 触达、最大收盘路径、MFE、MAE 和 D20 收盘，并检查：

- `provisional` 支持是否错误提升了候选；
- `provisional` 反证是否错杀了实际最近替代股；
- `supported_with_boundary` 和 `observation_only` 是否按权限使用；
- 当时实际引用的 `formation_values`、最强反证和同类比较是否与最终去向一致。

对后来达标但未入选的股票，每只只归一个主要原因：`discovery_miss`、`decision_miss`、`data_capability_miss`、`future_catalyst`、`non_executable` 或 `no_point_in_time_case`。未来结果只用于确定倒查对象和评价取舍，不得制造形成日理由。

输出一份紧凑复盘：成熟日期与样本数、场景结果、AI 使用结果、错失归因、可能需要人工调整的 Skill 条文和支持/反对证据。不自动修改 Skill，不创建数据库、模型、平台、新定时任务或统计 subsystem。成熟样本过少时只做描述，不宣告规则有效或无效。
