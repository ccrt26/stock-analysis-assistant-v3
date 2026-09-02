# V4 样例事实追溯表

## 口径

本表只用于人工核对 `review-sample-v4.md`，不属于生产 schema，也不建立哈希或自然语言程序 Gate。来源文件是被 Git 忽略的本地冻结事实，不把它们描述成 GitHub 已提交数据。百分比按“原始小数 × 100”并四舍五入到两位；“目标还差”按 `20% - 当前收盘涨幅` 计算。观点句和条件句不是客观事实，不为它们伪造事实来源。

| 股票 | 样例中的具体事实 | 来源文件 | 来源字段 | 原始值 | 展示值 |
|---|---|---|---|---|---|
| 全局 | 冻结报告日期与观察边界 | `local_archive/forward_monitor/snapshot-2026-09-01.json` | `analysis_date`; `as_of` | `2026-09-01`; `2026-09-02T09:05:00+08:00` | `snapshot-2026-09-01.json`; `2026-09-02T09:05:00+08:00` |
| 全局 | 20%观察目标 | `src/stock_analyzer/ops/forward_monitor.py` | `_render_target_progress` 的既有固定目标 | `0.20` | `20%` |
| 全局 | 未来观察窗口 | `src/stock_analyzer/ops/forward_monitor.py` | `_render_public_outlook` 的既有公开句式 | `outlook_1_3d` | `未来1—3个交易日` |
| 金岭矿业 | 正式推荐日期 | `snapshot-2026-09-01.json` | `episodes[episode_id=formal:2026-08-27:000655.SZ:selected].action_date` | `2026-08-28` | `2026年8月28日` |
| 金岭矿业 | 不依赖涨停、突破60日高点、形成日成交1.61倍且成交增加对应收盘上涨 | 同上 | `original_referenced_decisions[decision_id=px-000655].formation_values.{limit_up_return_contribution_5d,breakout_vs_prior60,amount_ratio_last_20d,volume_price_efficiency_5d}` | `0.0`; `0.006849`; `1.607715`; `1.0` | `不依赖涨停就突破60日高点`; `约1.61倍`; `成交增加后收盘持续抬升` |
| 金岭矿业 | 一季度归母净利润同比下降28.46% | 同上 | `original_referenced_decisions[decision_id=co-000655].formation_values.q1_net_profit_yoy_pct` | `-28.4575` | `下降28.46%` |
| 金岭矿业 | 推荐后第3个交易日、当前上涨及目标差距 | 同上 | `day_number`; `current_close_return_since_entry`；目标差为固定目标减该字段 | `3`; `0.012211668928086894`; `0.1877883310719131` | `第3个交易日`; `上涨1.22%`; `还差18.78个百分点` |
| 金岭矿业 | 推荐后最高收盘、盘中最高、最深下跌及当前离最高收盘的回落 | 同上 | `current_max_close_return_since_entry`; `current_max_high_return_since_entry`; `current_mae_since_entry`; `current_close_drawdown_from_peak` | `0.024423337856173788`; `0.02578018995929443`; `-0.01899592944369044`; `-0.01192052980132452` | `2.44%`; `2.58%`; `1.90%`; `1.19%` |
| 金岭矿业 | 当前低于形成日前60日高点1.32%、成交1.16倍、收盘上涨1.22% | 同上 | `breakout_vs_prior60`; `amount_ratio_last_20d`; `current_close_return_since_entry` | `-0.013227513227513144`; `1.1596198634574277`; `0.012211668928086894` | `下方1.32%`; `1.16倍`; `1.22%` |
| 德尔股份 | 正式推荐日期 | `snapshot-2026-09-01.json` | `episodes[episode_id=formal:2026-08-25:300473.SZ:selected].action_date` | `2026-08-26` | `2026年8月26日` |
| 德尔股份 | 形成日成交2.95倍、成交增加对应多个收盘上涨、离长期高点较远 | 同上 | `original_referenced_decisions[decision_id=px-300473].formation_values.{amount_ratio_last_20d,volume_price_efficiency_5d,breakout_vs_prior60}` | `2.945`; `0.8302`; `-0.3376` | `约2.95倍`; `推动多个收盘上涨`; `离长期高点较远` |
| 德尔股份 | 一季度利润和经营现金流改善 | 同上 | `original_referenced_decisions[decision_id=co-300473].formation_values.{net_profit_yoy_pct,operating_cash_flow_cny}` | `105.8`; `112200000.0` | `一季度利润和经营现金流改善` |
| 德尔股份 | 推荐前涨幅集中在最近3天 | 同上 | `original_research_thesis.market_recognition.basis`; `original_referenced_decisions[decision_id=px-300473].formation_values.return_3d` | `3日上涨13.0575%`; `0.130575` | `主要集中在最近3天` |
| 德尔股份 | 推荐后第5个交易日、当前上涨及目标差距 | 同上 | `day_number`; `current_close_return_since_entry`；目标差为固定目标减该字段 | `5`; `0.10441116956697694`; `0.09558883043302306` | `第5个交易日`; `上涨10.44%`; `还差9.56个百分点` |
| 德尔股份 | 推荐后最高收盘、盘中最高、最深下跌及当前离最高收盘的回落 | 同上 | `current_max_close_return_since_entry`; `current_max_high_return_since_entry`; `current_mae_since_entry`; `current_close_drawdown_from_peak` | `0.12140833670578721`; `0.18292189397005254`; `-0.022258195062727637`; `-0.015156983038614347` | `12.14%`; `18.29%`; `2.23%`; `1.52%` |
| 德尔股份 | 最新一日跑输市场和同行 | 同上 | `relative_market_1d`; `relative_industry_1d` | `-0.012206378572042542`; `-0.022253219121698163` | `跑输市场1.22个百分点`; `跑输同行2.23个百分点` |
| 海油工程 | 正式推荐日期 | `snapshot-2026-09-01.json` | `episodes[episode_id=formal:2026-08-21:600583.SH:selected].action_date` | `2026-08-24` | `2026年8月24日` |
| 海油工程 | 四只油服工程股票同步走强且该股形成时最强 | 同上 | `original_referenced_decisions[decision_id=sec-600583].formation_values.{qualifying_leader_count,candidate_industry_percentile_5d}` | `4`; `1.0` | `四只`; `其中最强的一只` |
| 海油工程 | 半年收入和现金流改善、利润几乎没有增长 | 同上 | `original_referenced_decisions[decision_id=co-600583].formation_values.{revenue_yoy,n_cashflow_act,net_profit_yoy}` | `0.09418`; `1560681000.0`; `-0.00637` | `半年收入和现金流改善`; `半年利润几乎没有增长` |
| 海油工程 | 形成时接近60日高点 | 同上 | `original_referenced_decisions[decision_id=px-600583].formation_values.price_location_60d` | `0.984496` | `接近60日高点` |
| 海油工程 | 推荐后第7个交易日、当前上涨及目标差距 | 同上 | `day_number`; `current_close_return_since_entry`；目标差为固定目标减该字段 | `7`; `0.046666666666666634`; `0.15333333333333338` | `第7个交易日`; `上涨4.67%`; `还差15.33个百分点` |
| 海油工程 | 推荐后最高收盘、盘中最高和最深下跌 | 同上 | `current_max_close_return_since_entry`; `current_max_high_return_since_entry`; `current_mae_since_entry` | `0.046666666666666634`; `0.06333333333333324`; `-0.018333333333333424` | `4.67%`; `6.33%`; `1.83%` |
| 海油工程 | 当前收盘仍为推荐后最高、最近5日85.71%的行业成员上涨、同期跑赢同行0.89个百分点 | 同上 | `current_close_return_since_entry == current_max_close_return_since_entry`; `sector_breadth_5d`; `relative_industry_5d` | `0.046666666666666634 == 0.046666666666666634`; `0.8571428571428571`; `0.008929395217711196` | `仍是推荐后的最高收盘`; `85.71%`; `多涨0.89个百分点` |
| 华昌化工 | 正式推荐日期 | `snapshot-2026-09-01.json` | `episodes[episode_id=formal:2026-08-25:002274.SZ:selected].action_date` | `2026-08-26` | `2026年8月26日` |
| 华昌化工 | 形成日成交3.53倍并突破近期高点 | 同上 | `original_referenced_decisions[decision_id=px-002274].formation_values.{amount_ratio_last_20d,breakout_vs_prior60}` | `3.5255`; `0.050325` | `约3.53倍`; `突破近期高点` |
| 华昌化工 | 半年利润和经营现金流改善 | 同上 | `original_referenced_decisions[decision_id=co-002274].formation_values.{net_profit_yoy_pct,operating_cash_flow_cny}` | `1026.9`; `197200000.0` | `半年利润和经营现金流改善` |
| 华昌化工 | 半年业绩增量已在7月预告披露 | 同上 | `original_research_thesis.company_information.disclosure_chain.prior_forecast` | `2026年7月业绩预告已预计半年归母净利润同比大幅增长。` | `半年业绩增量在7月预告中已经披露` |
| 华昌化工 | 没有可靠推荐参考价，不能计算目标进展 | 同上 | `entry_open`; `current_close_return_since_entry`; `data_limitations` | `null`; `null`; `["missing_price_path","missing_current_price_context"]` | `没有可靠的推荐参考价，因此不能计算距离20%目标的进展` |
| 华昌化工 | 9月1日披露控制权变更进展暨复牌公告 | 同上 | `new_announcements[announcement_id=1225542847].{available_at,title}` | `2026-09-01T16:00:00+00:00`; `关于筹划公司控制权变更事项的进展暨复牌公告` | `9月1日`; `《关于筹划公司控制权变更事项的进展暨复牌公告》` |

## 上一轮观点锚点说明

这四条对应 episode 的 `previous_episode_review` 均为 `null`，所以样例只与各自冻结的原推荐判断比较，没有借用同股票其他记录或旧日报自由文本，也没有机械写“这是首次复盘”。若未来存在上一轮记录，结构化三字段与上一轮 `current_review` 第一句只作为观点锚点；其中的自由文本不得在没有其他字段佐证时转写为新的价格、公告或财务事实。

## D20 核对说明

对本地 `local_archive/forward_monitor/monitor-report-*.json` 完整解析后，没有发现非空的 `final_twenty_day_review`。因此 V4 只提供字段分工的无历史数据结构示例，不列收益数字，也没有可追溯成真实股票结果的内容。
