# A 股五 Skill 优化研究样本

本目录是从本地冻结研究产物和事实仓中导出的**公开安全、只读、可核对切片**，用于优化市场、板块、公司、价格和总控五个 Skill。它不是交易建议，也不包含仓位、自动交易、止盈止损或收益承诺。

## 边界与数量

- 正式行动日：`2026-08-20` 至 `2026-08-31`（含首尾）；
- 事后行情终点：`2026-08-31`；
- 正式入选事件：29 条；
- 不同股票：28 只；
- 行动日：8 个；
- 候选账记录：78 条；
- 决策证据记录：126 条；
- 已形成的逐 episode 跟踪复盘：26 条。

起点以用户提供的历史工作簿中最早 `action_date=2026-08-20` 为准。`action_date=2026-09-01` 的研究不在本样本内。形成日证据始终以各次 `selection_as_of` 冻结；`2026-08-31` 行情只进入 outcome/review 文件，不反向改写选择理由。

## 文件说明

- `data/formal_selections.csv`：所有正式入选事件及原始理由、最强反证、最近替代比较；
- `data/research_runs.jsonl`：8 次研究的完整冻结 trace 载荷，使用逻辑来源标识，不含本地路径；
- `data/candidate_ledger.jsonl`：所有明确进入候选账的股票；
- `data/decision_trace.jsonl`：研究 trace 中实际引用的结构化决策证据；
- `data/review_contracts.jsonl`：发动机、催化、传播、价格确认、剩余路径、反证、关键未知和行动条件引用；
- `data/monitor_episodes.jsonl`：截至 8 月 31 日收盘的正式 episode 快照；
- `data/monitor_alerts.jsonl` 与 `data/monitor_reviews.jsonl`：截至该交易日已生成的提醒和逐 episode 复盘；
- `data/daily_price_volume.csv`：每条正式入选事件从行动日起到 8 月 31 日的原始 OHLC、成交量、成交额和复权累计路径；
- `data/market_context.jsonl`：各形成日完整市场派生行；
- `data/sector_context.jsonl`：候选与决策证据实际引用行业，以及候选形成日主行业的派生行；
- `data/price_context.jsonl`：候选股票在各自形成日的价格派生行；
- `A股Skill优化样本_2026-08-20至2026-08-31.xlsx`：便于人工筛选和复盘的汇总工作簿；
- `manifest.json` 与 `checksums.sha256`：记录数、边界、文件哈希和已知限制。

## 口径

- `event_key` 以形成日、股票代码和角色区分事件，因此洛阳钼业两次入选分别保留；
- OHLC 为未复权原始价格，成交量单位为股，成交额单位为人民币元；
- 从行动日开盘计算的跨日累计收益使用 `raw_price × adj_factor`；
- 缺少可靠行情的交易日保留一行并标记 `missing_equity_daily`，不补猜；
- 8 月 31 日收盘跟踪报告在 9 月 1 日盘前形成，其 `report_as_of` 被完整保留，不能当作 8 月 31 日开盘前信息；
- 旧格式的 8 月 20 日研究没有 V4 `research_thesis` 和 `decision_trace`，对应字段保持空值并明确标记，绝不事后重建。

## 有意不包含

本目录不包含完整本地事实仓、公告正文/PDF、运行日志、环境变量、密钥、用户名或个人绝对路径。市场上下文为完整单行；板块和价格上下文仅保留本研究样本实际引用的审计切片，不代表整个 A 股发现宇宙。
