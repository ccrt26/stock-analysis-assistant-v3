# 前20个交易日结束后的集中研究复盘

这是个人助手的人工集中复盘，不是 Scheduled Task。不得新增定时任务、数据库、模型、评分器或平台。

## 1. 数据边界

只读取已经完成20个交易日观察的选股日期：

- 现有 Forward CSV
- `local_archive/forward_selection/research-trace-*.json`
- `local_archive/forward_monitor/snapshot-*.json`
- `local_archive/forward_monitor/monitor-report-*.json`
- 当时原 `as_of` 可回放事实

未成熟日期不进入结论。未来结果只用于评价选择，不得回写当时的选择理由。

旧 V1、V2、V3 轨迹保持 legacy，只按其实际字段单独描述，不倒填 V4 类型。

## 2. V4 分组

对 `daily-research-trace-v4` 按以下七种最初入选依据分别汇总：

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

- 选股日期数
- 股票数
- 推荐后的第一个交易日，按原条件能够正常参与的比例
- 推荐后第1、3、5、10、20个交易日的涨跌
- 相对市场收益
- 相对行业收益
- 20 日内复权收盘达到 20% 的比例
- 最大收盘路径
- 期间最高涨幅
- 期间最深跌幅
- 第20个交易日收盘结果
- 推荐股与当时最接近但未推荐股票的比较

样本过少时只做描述，不宣告有效或无效。

## 4. 分开评价三件事

1. 最初入选依据本身的后续表现；
2. AI 当时是否正确识别短期推动因素和状态；
3. AI 是否正确使用场景、事件反应、公司披露链、板块传播和价格证据。

具体检查：

- `fresh_event_pending` 是否确为当时选股日收盘后首次 `substantive_new` 事件，首次定价是否满足原行动条件；
- `event_repricing_confirmed` 是否引用同一事件的公司支持和事件价格反应；
- `sector_broad_diffusion` 与 `sector_leader_cluster` 是否被正确区分；
- 领导集群成员数、成交份额、单股贡献和板块内百分位是否符合当时记录；
- `anchor_only` 是否被错误升级；
- 公司是否完整核对预告、修正、快报、正式报告和更正；
- 已确认价格支持是否同时保留绝对变化、成交、相对变化和路径质量；
- 市场传播模式及 `high_dispersion_risk` 是否按当时可见事实使用；
- 11 个既有价格场景的定义和权限是否保持原样。

对当时引用的事件，按原 `as_of` 重算 `compute_event_reaction_features_v3`，不把后来事件补进当时的选择理由。

## 5. 跟踪提醒是否及时、是否有用

只评价提醒出现的时点和内容，不得改变原20个交易日结果。逐项检查：

同一只股票有多次推荐或比较记录时，必须按每条记录分别复盘，不得用最大交易日序号代替其他记录的成熟状态。优先读取每条记录已冻结的前20个交易日最终结论；第21至第30个交易日的新变化只更新当前观察，不得改写已冻结结论。推荐股与当时最近备选股只在同次研究、同一观察窗口且两边价格路径完整时成对比较，数字以 snapshot 中的确定性结果为准。

1. 新事件等待首次价格反应的股票，是否等到首个完整可观察交易日才提醒；
2. “正在转强”或“接近重点观察条件”是否出现在后续1—3个交易日真实延续之前；
3. 失效提醒是否在原判断明显失效时及时出现；
4. 过热提醒是否在风险已经形成时出现，而不是事后补写；
5. 推荐后的前20个交易日内首次达到 20% 时是否及时提醒；
6. 第21至第30个交易日才首次达到 20% 时，是否始终说明“前20个交易日结束后才开始明显走强”，不得改变前20个交易日的原评价结果；
7. `data_problem` 是否只在问题新增、发生变化或固定检查日重复提醒；
8. `previous_monitor_state` 是否让前后状态可以连续复盘；
9. 是否存在重要变化已在 snapshot 中已出现但日报漏报；
10. 是否存在提醒很多但后续1—3个交易日没有对应事实支持的情况。

必须按当时 snapshot 和最终日报的时间顺序评价，禁止用未来结果倒填当天提醒理由。这里不新增定时任务，不增加自动评分，不新增模型、权重、Skill 或其他任务。

## 6. 当时为什么没有选中后来上涨的股票

后来达标但未入选的股票，每只只归一个主要原因：

```text
discovery_miss
decision_miss
data_capability_miss
future_catalyst
non_executable
no_point_in_time_case
```

必须区分短期推动因素事实无效、AI 使用错误和当时根本没有证据。

## 7. 输出

输出一份紧凑复盘：

- 成熟日期与成熟样本数
- 按当时短期上涨原因和状态汇总的结果
- 场景结果
- 事件结果
- AI 使用结果
- 推荐股与当时最接近但未推荐股票的比较
- 当时为什么没有选中后来上涨的股票
- 支持或反对修改 Skill 的重复证据
- 最小修改建议

面向用户的正文不得显示 D1、D20、MFE、MAE、selected、nearest_nonselection 等内部缩写或英文值；内部 JSON 或核对附录可以保留。本任务不自动修改 Skill，不得因为一两只股票改变规则。
