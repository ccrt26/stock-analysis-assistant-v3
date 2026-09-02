# 现有 09:05 每日任务中的股票跟踪步骤

这一步每天只运行一次，属于现有 09:05 任务，不创建新的 Scheduled Task，也不新增定时任务。程序先记录全部股票，AI 只研究今天确实发生变化的股票。面向用户时按“推荐日期和当时判断、到今天走到哪里、我的分析、接下来更可能怎样”说明，不展示内部字段名、英文值或交易日缩写。

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

公告正文继续按 V4 规则按需读取，不批量下载。原五个 Skill 继续负责选股；复盘时，市场、板块、公司和价格四个专业 Skill 的 `phase: review` 只提供各自事实与解释，不重新推荐股票。`reviewing-stock-recommendations` 接收具体推荐日期、当时完整理由、四路 review 结果和已有 `ForwardEpisodeReviewV1`，负责跨时间综合和最终用户文字；总控只检查记录一致性，不重复形成第二套复盘方法。公司事实是否仍成立，和股价成交是否实际支持该事实，必须分开写。不得改写原始完整判断、当时理由或前20个交易日的原评价结果。

V2/V3 的每条跟踪记录优先查看 snapshot 中按本记录编号保存的 `previous_episode_review`，分别延续 `current_assessment`、`best_supported_explanation`、`current_weak_or_failed_link` 和 `current_review`，不得借用同一股票另一条记录的上次复盘。`previous_monitor_state` 只用于历史 V1 报告兼容。判断今天的状态时，明确区分状态延续、正在转强后失效、正在转强后过热、等待确认后转强和其他真实变化；上次状态只用于比较，不得机械维持。

### 数据缺口只补一次

如果 snapshot 出现 `missing_price_path`、`missing_current_price_context`、`missing_market_context` 或 `missing_sector_context`，且对应交易日已经收盘，先按缺失类型使用现有流程定向补一次：

```bash
./.venv/bin/python -m stock_analyzer data run-stage \
  --stage close \
  --data-date <analysis_date>

./.venv/bin/python -m stock_analyzer data run-stage \
  --stage next-morning \
  --data-date <analysis_date>
```

只有价格或市场缺失时运行 `close`；只有行业、主题或公告缺失时运行 `next-morning`。补数后重新运行一次 monitor prepare，仍缺失就明确具体限制，不得循环重试。不得为一只股票执行全市场财务回填、增加数据源或增加任务。

若缺少的公司财务或公告正文会直接改变原推荐判断，公司 Skill 沿现有官方链接定向读取一次；无关月报、例行公告、单个公告标题或非核心细节不得主导整只股票的复盘。仍无法取得时只说明哪一项无法核对，继续分析其他已有事实。只有推荐参考价或整段行情确实不存在，才能说不能评价距离20%观察目标的进展。

相对行业表现与行业上涨面必须分开：`relative_industry_*` 表示股票相对形成日有效申万二级行业的表现，`sector_breadth_*` 表示 `original_group_code` 对应行业或主题的成员上涨面。前者存在而后者缺失时，只能说无法核对多数成员是否同步，不得说行业数据全部不可用；后者存在而前者缺失时也不得抹掉上涨面事实。


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
- best_supported_explanation 保存最有证据的主要解释；current_review 才是公开分析核心，必须完成原因比较、预期检验、阶段和未来判断。why_reported 只说明今天为什么复盘，不参与涨跌归因，不直接展示。
- 具体推荐日期必须取该次正式推荐记录的 `action_date`，写成“这只股票在YYYY年M月D日开盘前被正式推荐”，不能用复盘日期或当前日期代替。
- `confirmed_active` 和 `legacy_v1_not_rewritten` 两类正式推荐记录在第1至第19个交易日，`final_twenty_day_review` 必须为空；第20个交易日必须首次形成。第20天漏跑时，`pending_final_review` 必须持续排在提醒原因第一位，直到结论成功保存并在下一次 prepare 恢复。第21至第30个交易日不得改写这个结论，只能更新当前走势评价。snapshot 已有 `frozen_twenty_day_review` 时必须原样使用；漏跑后首次建立也只能依据 `d20_*`、前20个交易日以内的事实和已冻结原判断。
- 比较记录的 `final_twenty_day_review` 始终为空；`conditional_event` 也始终为空，二者都不能写成正式推荐的最终结论。
- `original_reason_plain_language` 和 `original_key_risk_plain_language` 只通俗改写当时已经冻结的意思，不加入后来事实。Markdown 只展示这两个字段，不直接展示原始理由和原始风险。
- 原始完整判断缺失时，内部保留 `missing_original_research_thesis`，面向用户明确说明只能复盘价格表现，不能补写当时理由。
- 只在代码或完整名称能唯一严格匹配时逐只比较当时最接近但未推荐的股票。必须使用 snapshot 中的真实成对价格路径，先展示两边的涨跌、期间最深跌幅和期间最大收盘回撤，再解释。路径不完整、窗口不一致或无法匹配时用固定说明，不展示 AI 自由比较文字。
- 价格段落按当前所处交易日显示最近1、3、5或20个交易日的相对市场和相对行业数字；字段缺失时明确未知，不把这个窗口写成“从推荐以来”。
- D1—D4 的五日收益、连续性和最大上涨日字段可能跨越形成日前后，只能作为近期背景，不得冒充为完整的推荐后五日路径。

### 内部日报和用户复盘分开处理

`DailyForwardMonitorReportV2` 是内部完整归档，继续按上面的合同保存所有应当复盘的推荐、比较、待确认事件和内部提醒。不得为了让最终文字更短而删掉比较记录、成对价格、内部提醒或必需字段，也不得改变 `record` 的校验口径。

### 正式推荐股票的走势复盘

“正式推荐股票的走势复盘”只能出现被明确正式推荐过的股票。

允许展示：

- `confirmed_active`
- 历史上明确正式推荐、但无法无损重建V4分类的 `legacy_v1_not_rewritten`

禁止展示：

- `conditional_event`
- comparator
- nearest_nonselection
- rejected
- unresolved
- 普通观察股
- 内部关注股

待确认事件可以保留在内部日报，但不得出现在“正式推荐股票的走势复盘”中，也不得单列给用户凑内容。面向用户不展示比较股名称，也不显示“还有多少内部股票未展开”。同一股票同时有正式推荐和比较记录时，对外只讲正式推荐记录；内部日报仍完整保存全部记录。

### 复盘不是行情播报

复盘必须先恢复当初推荐时真正期待发生的事情，再用推荐后的事实检验。

每只股票必须按以下推理顺序回答：

1. **当初期待看到什么**：推荐日只选一项最重要、可检验的预期。
2. **结果**：从实际涨跌、期间高低点和20%观察目标开始，不按经过天数线性外推。
3. **最有证据的主要解释**：在市场、行业、公司变化、股票自身或混合/未知中选当前最合理的一种。
4. **为什么这一解释比其他解释更有证据**：必须与市场、相对行业、行业上涨面、新公司事实和收盘路径中相关的替代解释比较，不声称证明唯一因果。
5. **哪一项核心预期真正实现**：说明已实现、没实现或无法检验及其依据。
6. **当前阶段**：选择继续走强、上涨后整理、开始失速、明显减弱、已经失败或无法执行，并给出依据。
7. **未来1—3个交易日**：给出基准判断和原因，再写什么事实会增强或改变判断。

不能只写“部分支持”“价格表现较好”“仍需观察”或“资料不足”。必须指出主要解释、替代解释、核心预期、阶段和未来判断。

例如：

- 当初因为突破前高而推荐，后来跌回前高下方：这会削弱推荐，因为突破只有站稳才说明市场接受了更高价格。
- 当初因为行业普遍上涨而推荐，后来同行多数转弱但该股仍上涨：行业理由减弱，但股票自身可能仍强。
- 当初因为公司新合同而推荐，后来公告真实但股价和成交没有变化：公司事件仍然真实，但短期上涨预期没有被市场行为验证。
- 股票上涨并不自动证明原理由正确。若大盘和同行涨得更多，原先认为它更强的判断仍可能错误。

`ForwardEpisodeReviewV1.current_review` 本身必须是完整分析，至少包含：主要解释、与替代解释的比较、推荐日核心预期是否实现、当前阶段、未来1—3个交易日的基准判断和原因。

最终 Markdown 每只正式推荐股票严格只使用以下四段：

**推荐日期和当时判断**

**到今天走到哪里**

必须按实际收益说明当前收盘、期间最高、期间最深下跌和距离20%观察目标还差多少；不按每天1%的线性速度评价。

**我的分析**

**接下来更可能怎样**

“我的分析”只展示 `review.current_review`；前20个交易日的冻结结论以“前20个交易日最后结果：”并入这一段，不新增第五个标题。不打印内部 `current_assessment`、`best_supported_explanation`、`current_weak_or_failed_link` 标签。

outlook_1_3d 使用现有七类：strengthening 对应更可能继续走强，continuation_possible 对应更可能震荡偏强，range_or_wait 对应更可能横盘整理或等待新变化，weakening 对应更可能继续回落或弱势震荡，overheated 对应更可能高位剧烈波动并出现回吐，invalidated 表示原判断已不成立，event_pending 表示等待事件或复牌后的实际交易反应。确实无法判断方向时，current_review 和公开展望必须写“未来1—3个交易日方向暂时无法判断”，不得把未知包装成横盘预测。

四路 `market_change`、`sector_change`、`company_change`、`stock_change`、`why_reported`、成对比较和待确认记录继续保留在内部 JSON 和 snapshot，公开 Markdown 不直接拼接这些文字。不得为了缩短公开文字而删除内部事实或记录。

行动日停牌、没有可靠开盘价或无法按原条件参与时，阶段必须写“无法按计划执行”，不得当作普通资料缺失。若推荐后才停牌，先分析停牌前的可执行价格路径。

用户不是来读取行情表。每只股票先恢复当初期待，再用最少的关键事实说明它被验证还是被削弱。不要机械分成“市场方面、行业方面、公司方面、个股方面”，也不要依次朗读内部判断、薄弱项和解释分类。无法可靠区分原因时直接说不知道，不能编故事。

内部成对比较继续用于判断当时是否选错股票，也继续填写结构化内容；最终对外不出现替代股名称、代码、角色、单独表现或比较栏目。

### 必须说人话

- 不显示内部字段名、英文枚举、记录编号、内部角色、交易日缩写或流程状态。
- 不机械重复“目前……整体……仍需观察”“从数据来看”“综合来看”等空话。每句话都要说明一个具体变化、原因或后续含义。
- 不把固定栏目逐字复制成空模板；问题可以相同，但表达要根据这只股票真正发生的事情自然组织。
- 如果一句话换成任何股票名称仍然成立，说明太空泛，必须重写。
- 不从量价猜测机构、主力、游资或账户身份；没有证据的原因就说未知。
- 只保留必要的一次时间边界说明；不提供收益承诺、仓位、自动交易、止盈或止损建议。

详细提醒最多8只不同股票。超过8只时，消息优先级固定为：
正式推荐重点股票不超过8只时必须全部进入详细提醒，不得由待确认事件或比较记录挤占。正式推荐重点股票超过8只时，8个位置也只能由正式推荐使用；待确认事件和比较记录只能使用正式推荐之后剩余的位置。


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

这只是内部提醒顺序，不是投资排名。其余重点股票只留在 `unreported_attention_count` 和 `routine_summary`，不得展示给用户。

D21—D30 的 `late_activation` 面向用户必须写成“这只股票在前20个交易日结束后才开始明显走强，因此不会改变前20天的原评价结果”。达到原目标只说明已达到，仍记录到 D20，不自动生成新的买入建议。提前判断失效后不再放入普通详细提醒，但程序仍记录到 D20。

## 4. 校验并保存

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor record \
  --snapshot-file local_archive/forward_monitor/snapshot-<analysis_date>.json \
  --report-file local_archive/forward_monitor/pending-report-<analysis_date>.json
```

成功后只向用户展示：今天的市场情况、正式推荐股票的走势复盘和仍开放的正式推荐股票数量。不要展示待确认事件、比较股、普通观察股、最近替代股、内部关注股票及其数量；没有正式推荐需要复盘时，直接说明“今天没有被明确推荐过、同时又出现需要说明变化的股票”，不得用其他股票补位。
