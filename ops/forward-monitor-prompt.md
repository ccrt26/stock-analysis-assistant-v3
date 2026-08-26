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

V2/V3 的每条跟踪记录优先查看 snapshot 中按本记录编号保存的 `previous_episode_review`，分别延续 `current_assessment`、`best_supported_explanation`、`current_weak_or_failed_link` 和 `current_review`，不得借用同一股票另一条记录的上次复盘。`previous_monitor_state` 只用于历史 V1 报告兼容。判断今天的状态时，明确区分状态延续、正在转强后失效、正在转强后过热、等待确认后转强和其他真实变化；上次状态只用于比较，不得机械维持。


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
- snapshot 的 `required_final_review_episode_ids` 必须全部出现在日报的 `episode_reviews` 中；这些记录优先进入最多8只的详细提醒，不能留到未详细展示数量中。
- 每条记录的 `ForwardEpisodeReviewV1` 只填写通俗原因与风险、当前判断、现有证据最支持的解释、当前最弱环节、当前复盘、成对比较解释和 `final_twenty_day_review`，不增加分数、概率或更多分类。
- 正式推荐记录在第1至第19个交易日，`final_twenty_day_review` 必须为空；第20个交易日必须首次形成。第20天漏跑时，`pending_final_review` 必须持续排在提醒原因第一位，直到结论成功保存并在下一次 prepare 恢复。第21至第30个交易日不得改写这个结论，只能更新当前走势评价。snapshot 已有 `frozen_twenty_day_review` 时必须原样使用；漏跑后首次建立也只能依据 `d20_*`、前20个交易日以内的事实和已冻结原判断。比较记录的 `final_twenty_day_review` 始终为空，不能写成正式推荐的最终结论。
- `original_reason_plain_language` 和 `original_key_risk_plain_language` 只通俗改写当时已经冻结的意思，不加入后来事实。Markdown 只展示这两个字段，不直接展示原始理由和原始风险。
- 原始完整判断缺失时，内部保留 `missing_original_research_thesis`，面向用户明确说明只能复盘价格表现，不能补写当时理由。
- 只在代码或完整名称能唯一严格匹配时逐只比较当时最接近但未推荐的股票。必须使用 snapshot 中的真实成对价格路径，先展示两边的涨跌、期间最深跌幅和期间最大收盘回撤，再解释。路径不完整、窗口不一致或无法匹配时用固定说明，不展示 AI 自由比较文字。
- 价格段落按当前所处交易日显示最近1、3、5或20个交易日的相对市场和相对行业数字；字段缺失时明确未知，不把这个窗口写成“从推荐以来”。

### 内部日报和用户复盘分开处理

`DailyForwardMonitorReportV2` 是内部完整归档，继续按上面的合同保存所有应当复盘的推荐和比较记录。不得为了让最终文字更短而删掉比较记录、成对路径、内部提醒或必需字段，也不得改变 `record` 的校验口径。

最终发给用户的复盘不是内部日报的逐项翻译，只展示仍有正式推荐记录的股票：

- 正式推荐以已保存记录中的 `selected` 角色为准。比较股、最近替代股、未入选候选、未决股票和只在内部关注的股票都不展示、不点名，也不披露它们的表现或数量。
- 已经正式入选、但原本需要第一个交易日确认的新事件仍属于正式推荐，应把当时的确认条件说清楚，不能误归为未入选观察股。
- 同一股票同时有推荐和比较记录时，对外只讲推荐记录，不提它还有比较角色；内部日报仍完整保存两条记录及成对比较。
- “目前还在跟踪多少只”只统计仍开放的正式推荐股票，按股票代码去重。不得展示比较记录数、内部关注数或“未详细展开”的内部股票数量。
- 最终展示仍最多8只正式推荐股票。若内部日报含有比较股提醒，不能把它复制到用户复盘中凑数。

### 每只正式推荐股必须真正给出分析

用户不是来读取行情表。每只股票先说判断，再用最少的关键数字证明判断，必须让人读完能明白：

1. 今天或最近实际发生了什么，这个变化对原推荐意味着什么；
2. 现有事实最支持什么原因：主要是大盘共同变化、行业变化、公司新事实，还是股票自己的买卖需求发生了变化；无法可靠区分时直接说不知道，不能编故事；
3. 原推荐的“推动因素 → 市场或行业传播 → 股价成交认可 → 剩余上涨空间”中，哪一环正在增强、减弱或已经断掉；
4. 未来1—3个交易日更像偏强延续、震荡等待、继续走弱还是原判断已经失效，并说明为什么；
5. 接下来出现什么事实会说明情况改善，出现什么事实会说明继续恶化或原判断不再成立。

数字只能作证据，不能代替判断。不能连续堆砌涨跌幅、成交额、相对市场和相对行业数字后只加一句“整体走弱”或“仍需观察”。大盘上涨而股票不涨，要解释这为什么削弱个股逻辑；行业下跌但股票更弱，要说明行业只能解释一部分；公司有新公告但股价没有认可，要明确是哪一环没有传导。

内部成对比较继续用于判断当时是否选错股票，也继续填写“和当时最接近的备选相比”所需的结构化内容；最终对外只写它怎样改变了对正式推荐股的评价，不出现替代股名称、代码、角色或单独表现。

### 必须说人话

最终文字要像一个了解用户的个人研究助手在解释股票，不像系统日志、审计报告或字段说明：

- 不显示内部字段名、英文枚举、记录编号、内部角色、交易日缩写或流程状态。
- 不机械重复“目前……整体……仍需观察”“从数据来看”“综合来看”等空话。每句话都要说明一个具体变化、原因或后续含义。
- 不把固定栏目逐字复制到每只股票。问题可以相同，但表达要根据这只股票真正发生的事情自然组织。
- 如果一句话换成任何股票名称仍然成立，说明太空泛，必须重写。
- 不从量价猜测机构、主力、游资或账户身份；没有证据的原因就说未知。
- 只保留必要的一次时间边界说明，不在每只股票后重复免责声明；不提供收益承诺、仓位、自动交易、止盈或止损建议。

写完每只股票后自查：读者是否能直接回答“它为什么这样走”“原推荐现在还成立吗”“未来1—3天什么情况会变好或变坏”。有一项答不出来，就不能提交。

用户看到的推荐日期使用该条记录的 `action_date`，不使用 `formation_date`。同一只股票当天共同的市场、行业、公司和个股变化只说一次；对外自然讲清“当时为什么推荐、后来实际怎么走、为什么会这样、原判断现在还是否成立、未来1—3个交易日怎么看、接下来观察什么”。内部报告仍分别保存每条记录的“和当时最接近的备选相比”，但最终用户文字不展示比较股。正式推荐完成前20天复盘后增加“这次推荐最后怎么看”，确定性展示现有六个 `d20_*` 价格结果，以及冻结的最薄弱环节、选择复盘和整体结论。比较记录不显示这一段。不得显示交易日缩写、内部角色、记录 ID、内部分类或英文字段。

详细提醒最多8只不同股票。超过8只时，消息优先级固定为：

1. `pending_final_review`
2. `data_problem`
3. `invalidated`
4. `new_event`
5. `first_reaction`
6. `actionable_watch`
7. `strengthening`
8. `overheated`
9. `target_hit`
10. `late_activation`
11. `checkpoint`

这只是消息显示顺序，不是投资排名。其余重点股票只计入 `unreported_attention_count` 和 `routine_summary`。不得输出收益概率、目标价、“必涨”、自动交易、仓位、止盈或止损建议。

D21—D30 的 `late_activation` 面向用户必须写成“这只股票在前20个交易日结束后才开始明显走强，因此不会改变前20天的原评价结果”。达到原目标只说明已达到，仍记录到 D20，不自动生成新的买入建议。提前判断失效后不再放入普通详细提醒，但程序仍记录到 D20。

## 4. 校验并保存

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor record \
  --snapshot-file local_archive/forward_monitor/snapshot-<analysis_date>.json \
  --report-file local_archive/forward_monitor/pending-report-<analysis_date>.json
```

成功后只向用户展示：今天的市场情况、正式推荐股票的走势复盘，以及仍开放的正式推荐股票数量。不要展示比较股、观察股、最近替代股、内部关注股票及其数量；没有需要复盘的正式推荐股时，直接用一句人话说明今天没有，不用其他股票补位。
