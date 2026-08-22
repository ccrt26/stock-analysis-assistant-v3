# 手动 D20 研究复盘提示

这是个人助手的人工集中复盘，不是 Scheduled Task。不得新增定时任务、数据库、模型、评分器或平台。

## 1. 数据边界

只读取已经成熟 D20 的形成日：

- 现有 Forward CSV
- `local_archive/forward_selection/research-trace-*.json`
- 当时原 `as_of` 可回放事实

未成熟日期不进入结论。未来结果只用于评价选择，不得回写形成日理由。

旧 V1、V2、V3 轨迹保持 legacy，只按其实际字段单独描述，不倒填 V4 类型。

## 2. V4 分组

对 `daily-research-trace-v4` 按以下七种发动机分别汇总：

```text
fresh_event_pending
event_repricing_confirmed
sector_broad_diffusion
sector_leader_cluster
independent_demand_acceleration
anchor_only
unresolved
```

同时按四种状态区分：

```text
active
conditional
inactive
unresolved
```

## 3. 每组至少报告

- 形成日数
- 股票数
- 行动日可执行率
- D1、D3、D5、D10、D20 收益
- 相对市场收益
- 相对行业收益
- 20 日内复权收盘达到 20% 的比例
- 最大收盘路径
- MFE
- MAE
- D20 收盘
- selected 与 nearest_nonselection 的同日成对结果

样本过少时只做描述，不宣告有效或无效。

## 4. 分开评价三件事

1. 发动机类型本身的后续表现；
2. AI 当时是否正确识别发动机和状态；
3. AI 是否正确使用场景、事件反应、公司披露链、板块传播和价格证据。

具体检查：

- `fresh_event_pending` 是否确为形成日收盘后首次 `substantive_new` 事件，首次定价是否满足原行动条件；
- `event_repricing_confirmed` 是否引用同一事件的公司支持和事件价格反应；
- `sector_broad_diffusion` 与 `sector_leader_cluster` 是否被正确区分；
- 领导集群成员数、成交份额、单股贡献和板块内百分位是否符合形成日记录；
- `anchor_only` 是否被错误升级；
- 公司是否完整核对预告、修正、快报、正式报告和更正；
- 已确认价格支持是否同时保留绝对变化、成交、相对变化和路径质量；
- 市场传播模式及 `high_dispersion_risk` 是否按形成日事实使用；
- 11 个既有价格场景的定义和权限是否保持原样。

对当时引用的事件，按原 `as_of` 重算 `compute_event_reaction_features_v3`，不把后来事件补进形成日理由。

## 5. 错失归因

后来达标但未入选的股票，每只只归一个主要原因：

```text
discovery_miss
decision_miss
data_capability_miss
future_catalyst
non_executable
no_point_in_time_case
```

必须区分发动机事实无效、AI使用错误和形成日根本无证据。

## 6. 输出

输出一份紧凑复盘：

- 成熟日期与样本数
- 按发动机类型/状态的结果
- 场景结果
- 事件结果
- AI 使用结果
- selected/nearest 成对比较
- 错失归因
- 支持或反对修改 Skill 的重复证据
- 最小修改建议

不得自动修改 Skill，不得因为一两只股票改变规则。
