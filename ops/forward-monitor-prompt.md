# 现有 09:05 每日任务中的股票跟踪步骤

这一步每天只运行一次，属于现有 09:05 任务，不创建新的 Scheduled Task。程序先记录全部股票，AI 只研究今天确实发生变化的股票。面向用户时说明“当时为什么看它、实际怎么走、原判断现在怎么看”，不展示内部字段名、英文值或交易日缩写。

## 1. 程序准备全部跟踪记录

当天收盘数据可靠后运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor prepare \
  --analysis-date <已收盘交易日> \
  --as-of <带时区截止时间>
```

程序处理全部跟踪记录，并生成 `local_archive/forward_monitor/snapshot-<analysis_date>.json`。不得把全部股票交给 AI，不得建立人工维护的第二套股票池，不得打分。

同一份市场 Skill 结果同时供选后跟踪和当天新选股使用，市场 Skill 每天只分析一次。

## 2. 只研究当天重点股票

价格 Skill 只解释 snapshot 中 `attention_reasons` 非空的不同股票，程序已经完成全部股票的价格计算。

板块 Skill 只在以下情况使用，并且只看重点股票真实涉及的板块：

- 原入选依据是 `sector_broad_diffusion` 或 `sector_leader_cluster`；
- 出现 `sector_state_changed`；
- 股票进入当天重点提醒。

公司 Skill 只在以下情况使用：

- 出现 `new_official_event`；
- 原入选依据是 `fresh_event_pending` 或 `event_repricing_confirmed`；
- 到达 D1、D3、D5、D10、D20 固定检查日；
- 公司事实可能推翻最初判断。

公告正文继续按 V4 规则按需读取，不批量下载。五个 Skill 使用各自的 `phase: review` 职责复盘冻结的原始完整判断，不重新推荐股票。公司事实是否仍成立，和股价成交是否实际支持该事实，必须分开写。不得改写原始完整判断、当时理由或前20个交易日的原评价结果。

每条跟踪记录都要查看 snapshot 中的 `previous_monitor_state`。判断今天的状态时，明确区分状态延续、正在转强后失效、正在转强后过热、等待确认后转强和其他真实变化；`previous_monitor_state` 只用于比较，不得机械维持上次状态。


## 3. 生成走势复盘日报

生成严格符合 `DailyForwardMonitorReportV2` 的新日报。一只股票仍只有一条提醒，但其 `episode_reviews` 必须为每条记录分别复盘，且每条使用一个 `ForwardEpisodeReviewV1`；前20个交易日的最终结论使用 `FrozenTwentyDayReviewV1`：

```text
local_archive/forward_monitor/pending-report-<analysis_date>.json
```

报告必须严格对应当天 snapshot：

- `market_propagation_mode` 只能是 `broad_sustained_participation`、`one_day_repair`、`sector_rotation`、`concentrated_speculation`、`weak_or_fragmented`、`unclear` 之一；
- `pool_summary` 和 `unreported_attention_count` 必须与 snapshot 完全一致；
- 每只提醒的 `episode_ids` 必须包含该股票全部 attention episode，不得只取子集；`roles`、交易日序号和原始完整判断必须从这些记录完整得出。
- `roles` 必须非空、去重且只允许 `selected`、`comparator`，固定按 `selected` 后 `comparator` 排列。同一股票同时有两种记录时仍只写一条提醒，向用户分别说明当时是推荐股还是比较对象。
- `episode_reviews` 中的 `episode_id` 必须与该股票全部 attention episode 完全一致，不得缺少、重复或多出；不得用该股票最大交易日序号替其他记录结案。
- 每条记录的 `ForwardEpisodeReviewV1` 只填写通俗原因与风险、当前判断、现有证据最支持的解释、当前最弱环节、当前复盘、成对比较解释和 `final_twenty_day_review`，不增加分数、概率或更多分类。
- 第1至第19个交易日，`final_twenty_day_review` 必须为空；第20个交易日必须首次形成。第21至第30个交易日不得改写这个结论，只能更新当前走势评价。snapshot 已有 `frozen_twenty_day_review` 时必须原样使用；第20天漏跑后首次建立，也只能依据 `d20_*` 和前20个交易日以内的事实。
- `original_reason_plain_language` 和 `original_key_risk_plain_language` 只通俗改写当时已经冻结的意思，不加入后来事实。Markdown 只展示这两个字段，不直接展示原始理由和原始风险。
- 原始完整判断缺失时，内部保留 `missing_original_research_thesis`，面向用户明确说明只能复盘价格表现，不能补写当时理由。
- 只在代码或完整名称能唯一严格匹配时逐只比较当时最接近但未推荐的股票。必须使用 snapshot 中的真实成对价格路径，先展示两边的涨跌、期间最深跌幅和期间最大收盘回撤，再解释。路径不完整、窗口不一致或无法匹配时用固定说明，不展示 AI 自由比较文字。
- 价格段落按当前所处交易日显示最近1、3、5或20个交易日的相对市场和相对行业数字；字段缺失时明确未知，不把这个窗口写成“从推荐以来”。

用户看到的每只股票使用自然短段落，最多显示“当时为什么看它、实际怎么走、为什么会这样、原判断现在怎么看、和当时最接近的备选相比、接下来观察什么”六个小标题。第20个交易日结束后再增加“这次选择最后怎么看”。不得显示交易日缩写、内部角色、记录 ID、内部分类或英文字段。

详细提醒最多8只不同股票。超过8只时，消息优先级固定为：

1. `data_problem`
2. `invalidated`
3. `new_event`
4. `first_reaction`
5. `actionable_watch`
6. `strengthening`
7. `overheated`
8. `target_hit`
9. `late_activation`
10. `checkpoint`

这只是消息显示顺序，不是投资排名。其余重点股票只计入 `unreported_attention_count` 和 `routine_summary`。不得输出收益概率、目标价、“必涨”、自动交易、仓位、止盈或止损建议。

D21—D30 的 `late_activation` 面向用户必须写成“这只股票在前20个交易日结束后才开始明显走强，因此不会改变前20天的原评价结果”。达到原目标只说明已达到，仍记录到 D20，不自动生成新的买入建议。提前判断失效后不再放入普通详细提醒，但程序仍记录到 D20。

## 4. 校验并保存

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor record \
  --snapshot-file local_archive/forward_monitor/snapshot-<analysis_date>.json \
  --report-file local_archive/forward_monitor/pending-report-<analysis_date>.json
```

成功后只向用户展示：今天的市场情况、之前研究过的股票走势复盘、目前还在跟踪多少只，以及没有详细展开的重点股票数量。不要展示全部跟踪股票。
