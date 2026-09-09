# 当前机会复盘与单次结案 V1（current-opportunity-v1）

本文是三类日常复盘改为"当前机会判断"后的核心合同简明说明；详细执行要求以 `ops/forward-monitor-prompt.md` 与复盘 Skill 为准。

## 1. 三类复盘各自回答什么

| 类型 | 核心问题 | 内容合同 |
|---|---|---|
| 关键节点复盘（checkpoint_detail） | 经过这个阶段，目前机会变好、变差还是换了依据？从现在看怎么办？ | 新六项：当前方向与参与意见及阶段结论；原关键期待与关键路径；改变当前机会的证据；倾向与反证；当前价格下的机会与代价；改变意见的事实。第20日另按固定结案输出 |
| 深度复盘（regular_detail） | 今天哪项变化足以影响后续走势或参与价值？现在的首选意见是什么？ | 新四项：为什么值得详写与意见调整/维持；变化与反证如何影响意见；当前价格与时间要求下是否值得参与；下一步关键条件与重新判断时点 |
| 简单复盘（brief） | 今天有没有足以改变前次方向或参与意见的增量？ | 只写最重要增量及其影响；600字符上限不变；外层显示本日当前意见与1—3日方向 |

## 2. 当前机会对象（账本唯一权威存储）

`DailyFormalReviewV1.current_opportunity: CurrentOpportunityV1 | None`：

- `reference_close/reference_date`：只取本 episode `review_context.price_levels.current_close` 与 snapshot.analysis_date；本日无可信收盘时两者为空。成对出现；`consider` 必须有参照。
- `outlook_5_10d`：up/sideways/down/unclear，面向分析日之后的实际交易日，不重启原推荐周期、不设盈利目标；unclear 不写成横盘。
- `outlook_1_3d` 及其七枚举不变；两个窗口可不同，理由说清差异。
- `participation`：consider（当前条件下可考虑参与，禁止无条件买入表述）/wait（等待所述条件）/avoid（当前暂不参与，可与原推荐有效并存）/insufficient（关键资料不足）。
- `change_condition`：最有价值的改变事实或已知重评时点，不发明数值/日期/线性涨幅。
- 同股同日相同事实截止时对象保持一致；record 拒绝不一致的待保存稿。
- 旧账本无该字段可原样读取（显示"历史未记录"或不显示该区域），不回写、不从旧评价反推。

## 3. 与原推荐结案的关系

- 原 `current_assessment`、`current_weak_or_failed_link`、`tracking_decision`、`FrozenTwentyDayReviewV1` 全部沿用，只评价原推荐；不是买卖信号。
- 第20日：固定结案五件事（原期待与担心；前20日触达/期末/过程风险；原判断支持/削弱/未知；差异归因；一个可批量检查的问题）只写 `overall_review` 公开一次；当天正文写当前更新，`current_opportunity` 写当前窗口。
- 晚补结案数字仅取原前20日；原因资料用原第20日事实截止；路径缺失保持 missing/unknown。
- 当前 `avoid` 不自动停止跟踪；`consider` 不新增正式推荐、不让条件事件晋升、不重开已结案记录；5—10日窗口超出原生命周期不授权新日常任务。

## 4. 展示

- Markdown 与两个网页从已保存账本读取该对象，在当日观点区域先显示"当前机会"块（方向、参与意见、改变条件、参照日/价）；详评正文围绕依据展开，不逐句复述该区域。
- 状态行与目标标注"原推荐参考价/原20%观察目标"；`view_change` 仍显示"相比上次复盘"，不改义。
- 载荷侧（`tools/web_display_contract.py`）预算中文文案，前端只渲染；缺失显示"历史未记录"，不借用另一日期补齐。

## 5. 与批量研究的连接

- 已结束记录的旧详评/结案按本批原始身份导出（`build_monitor_records` 接收 `valid_episode_ids`），不以最新快照 membership 为唯一集合。
- 方法版本辅助文件接入 `research_runs.jsonl`（`research_run_context/version_status/version_missing_reason`）；无文件或不匹配记 unknown，run_id 为 null 按 dirty/unknown 处理。
- 事后重读的派生行 `context_origin=retrospective_reconstruction`；公式版本字符串命中不再视为当时输入。
- 固定20日新增市场基准字段：`fixed_d20_market_return/excess_market_return/market_basis/market_missing_reason`，仅在 complete 且第20日同窗基准可靠时填写（基准 000300.SH，action 开盘到第20日收盘）。
- manifest 声明 `current_opportunity_contract: current-opportunity-v1` 仅当包内账本实际含新对象；校验器核对一致性。
- 人工批量研究入口：`ops/selection-method-review-prompt.md`（默认 diagnose；规则修改须用户批准具体提案后实施）。
