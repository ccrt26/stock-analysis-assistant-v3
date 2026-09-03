# 2026年8月20日以来正式推荐日评补录总结

## 覆盖结果

- 最早符合范围的正式推荐 `action_date` 为2026-08-21，最新可靠收盘交易日为2026-09-02。
- 覆盖22条正式 episode，只包含 `confirmed_active` 和已登记的 `legacy_v1_not_rewritten`；`conditional_event`、comparator、rejected 和 nearest nonselection 均未进入。
- 按各 episode 的 `action_date` 与交易所实际开市日逐日核对，应有112条，实际已保存112条，缺口0条。
- 其中30条来自同日旧 `monitor-report`，以 `copied_live_archive` 保存，旧记录已有的 `current_assessment`、`best_supported_explanation`、`current_weak_or_failed_link`、`current_review` 和最终结论字段逐字一致。
- 其中60条为 `backfill`，只使用同日 snapshot、原推荐 trace、当日 `as_of` 以前的事实和已完成的前一交易日日评。
- 最新2026-09-02另保存22条 `live` 日评，这些记录用于决定当前主动跟踪状态。

## 时点与历史保护

- 所有历史记录均使用 `tracking_decision=historical_not_applied`，没有追溯改写过去的主动跟踪状态。
- 各日 snapshot 的 `as_of` 固定在当日收盘之后、下一次正式研究之前；补录未读取后续交易日来解释当日。
- 2026-08-24至2026-09-01的历史 `monitor-report` 未改写，也没有事后重选旧8只详评。
- 2026-09-02按指令作为新制度首个 live 验收日重新保存标准 `monitor-report`；该日旧报告在重跑前已原样保留为 `monitor-report-2026-09-02.pre-daily-simple-eight-rerun-2026-09-03.*`。

## 最新 live 状态

- live前 active 为22条；当日全部完成简评。
- 3条停止主动跟踪：洛阳钼业和新产业因原判断被持续事实否定，华昌化工因始终没有可靠参与价格、原推荐无法执行。
- live后 active 为19条，`evaluation_only` 为3条，`completed` 为0条。三条已停止记录仍由程序保存确定性价格，并将在 D20 回到复盘队列形成最终结论。
- 当日详评恰好8只：3只今日停止和5只观点明显变化的股票全部优先；无 D20 成熟 episode，也无剩余普通轮换名额。
