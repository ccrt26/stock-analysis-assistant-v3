# 股票分析助手 V3 存储与执行治理设计

> **Lifecycle:** Historical storage design and still a normative boundary for local-wide/Supabase-narrow storage. It does not state current production readiness; see [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md).
>
> **2026-07-12 restoration:** [`2026-07-12-v3-formal-warehouse-restoration-design.md`](2026-07-12-v3-formal-warehouse-restoration-design.md) makes this boundary executable for formal-v2. `warehouse.duckdb` is the formal catalog and query entry; Parquet stores wide formal payload rows. The `formal_versions`, file inventory, canonical pointer, receipt, candidate, capability, and migration tables replace the contradictory wide formal payload JSON implementation.

## 1. 目标

第三版系统不能再把所有数据都堆进 Supabase，也不能退回第一版、第二版那种散乱本地文件。目标是建立一套可运行 6-12 个月、容量可控、可后评估、可复盘、可逐步优化的存储体系。

本设计遵循一个核心原则：

> Supabase 是云端决策账本和计算事实库；本地 DuckDB + Parquet 是全市场粗分析库；本地归档是完整报告和长文本冷存储。

Wide formal payload records are part of the local calculation warehouse. They must not be stored as standalone JSON group payloads or treated as a second source of truth.

系统必须保证：

- 全市场原始行情不直接进入 Supabase。
- 进入 Supabase 的数据必须能用于展示、后评估、规则优化或跨日期查询。
- 仅用于人类回看的完整报告、长篇文字、图表和原始大文件放在本地归档。
- 本地数据也必须被系统管理，不能散落成无人维护的文件堆。
- 任何真实生产写入前必须检查 Supabase 容量保护规则。

## 1.1 与既有设计和执行计划的关系

本设计不是一个独立补丁，而是对已经批准的 V3 总设计和 Tushare Ingestion V1 的正式修订。

它修订以下文件中的存储边界：

- `docs/superpowers/specs/2026-07-07-stock-analysis-assistant-v3-design.md` 的第 13、14、15、16、17、20 节。
- `docs/superpowers/specs/2026-07-08-tushare-ingestion-v1-design.md` 的数据写入、缓存、测试和验收边界。
- `docs/superpowers/plans/2026-07-08-tushare-ingestion-v1.md` 的 Task 5、Task 8、Task 9 继续执行方式。

它保留原有目标：

- 继续使用真实 Tushare 主源。
- 继续禁止样例数据进入生产报告或生产 Supabase。
- 继续生成最多 10 只正式推荐。
- 继续保留重点关注、结构化证据、后评估任务和静态网页报告。
- 继续使用 Subagent-Driven Development 执行关键实现和 review。

它改变原计划的一点：

- 原计划中“全市场行情、基础指标和全市场特征直接进入 Supabase”的执行方式停止。
- 下一步必须先实现本地 DuckDB + Parquet 分析库和 Supabase 选择性入库，再恢复生产 `run-daily`。
- 已经写出的 ingestion 代码和调试发现不废弃，但必须被合并进新的主线计划，而不是作为零散热修复继续推进。

## 2. Supabase Free 容量边界

Supabase 官方文档说明，Free Plan 项目数据库大小超过 500 MB 会进入 read-only 模式；这里指的是 Postgres 数据库实际数据大小，不是 1 GB disk size。数据库大小包括数据、索引、物化视图等，新项目自身也会占用约 40-60 MB。

参考：

- https://supabase.com/docs/guides/platform/database-size
- https://supabase.com/docs/guides/platform/cost-control

因此 V3 采用以下保护线：

- 350 MB：预警。系统报告必须提示 Supabase 容量接近上限。
- 400 MB：停止大写入。禁止写入行情窗口、批量候选、长文本、报告体等较大数据。
- 超过 400 MB 后，只允许写入很小的运行状态、错误记录或容量告警。
- 任何代码路径都不得把全市场历史行情直接写入 Supabase。

## 3. 三层存储架构

### 3.1 本地分析库：local_warehouse

位置：

```text
/Users/ccrt/股票分析助手/local_warehouse/
```

技术：

```text
DuckDB + Parquet
```

职责：

- 保存全市场原始行情、基础指标、粗筛特征、候选池和粗分析分数。
- 支持规则重算、回测、历史案例查询和后续知识库优化。
- 保留 180 天滚动数据。
- 不提交到 GitHub。
- 不直接展示给家庭成员。

建议目录：

```text
local_warehouse/
  warehouse.duckdb
  parquet/
    market_daily/
    daily_basic/
    features/
    candidates/
    source_runs/
```

说明：

- DuckDB 是本地查询入口。
- Parquet 是压缩数据仓库。
- 系统每天先把 Tushare/备用源数据落到本地分析库，再进行粗筛。
- 本地分析库可以保存全市场数据，因为它不受 Supabase Free 容量限制。

### 3.2 云端决策账本：Supabase

Supabase 只保存结构化、可计算、会被查询的数据。

进入 Supabase 的数据：

- 股票基础名单 `stock_master`。
- 每日最终推荐，最多 10 只。
- 后台对照组，每天 15 只，不在网页首页展示。
- 重点关注池，符合规则才进入，不凑数。
- 推荐、重点关注、对照组相关的结构化证据。
- 后评估任务和后评估结构化结果。
- 规则命中、规则版本、知识库版本。
- 报告索引、文件 hash、本地归档路径、发布状态。
- 数据源运行摘要和质量状态。
- 推荐股、重点关注股、后台对照组的有限行情窗口，最多最近 120 个交易日。

不进入 Supabase 的数据：

- 全市场历史行情。
- 全市场粗筛中间过程。
- 完整日报 HTML。
- 长篇证据原文。
- 长篇复盘文字。
- 图表图片。
- 大段日志。
- 可由本地 DuckDB 重算的临时中间结果。

活跃结构化数据保留策略：

- Supabase 中用于日常计算的结构化推荐、证据、后评估、报告索引保留 12 个月。
- 超过 12 个月的结构化数据可以导出到 `exports/` 后再清理，清理前必须有备份。

### 3.3 本地归档库：local_archive

位置：

```text
/Users/ccrt/股票分析助手/local_archive/
```

职责：

- 保存完整 HTML 报告。
- 保存长篇证据、分析、复盘文本。
- 保存文件清单、hash 和关联索引。
- 保存月度备份包。
- 由系统定期整理，不允许散乱写入。

建议目录：

```text
local_archive/
  reports/
  evidence_text/
  manifests/
  exports/
```

说明：

- `reports/` 保存完整日报 HTML，至少保留 24 个月，不自动删除。
- `evidence_text/` 保存长篇证据和复盘文本，保留 24 个月。
- `manifests/` 保存每日归档清单，记录文件路径、hash、大小、关联日期、股票代码、evidence_id、是否同步到 Supabase 索引。
- `exports/` 保存月度备份包，每月自动生成一个，保留最近 12 个。

`local_archive/raw_market/` 不作为独立重复仓库。全市场可计算数据的主体保存在 `local_warehouse/parquet/`。如需原始源响应审计，应通过 manifest 指向对应 warehouse 分区或月度 exports，避免一份数据存两遍。

## 4. 每日数据流

每日运行流程：

```text
Tushare / 备用免费 API
  ↓
local_warehouse：全市场原始数据与粗分析
  ↓
规则引擎：硬约束排除 + 稳健趋势评分 + 风险反证
  ↓
形成三类小集合：
  1. 最终推荐，最多 10 只
  2. 后台对照组，15 只
  3. 重点关注池，符合规则才进入
  ↓
容量检查：
  < 350 MB 正常写入
  350-400 MB 预警写入
  >= 400 MB 停止大写入
  ↓
Supabase：只写结构化决策事实、后评估任务、报告索引和有限行情窗口
  ↓
local_archive：写完整 HTML、长篇文本、manifest
  ↓
网页发布：只展示正式推荐和重点关注，不展示后台对照组
```

关键约束：

- 样例数据不得进入生产 Supabase。
- 缓存数据不得支撑当前交易日新推荐。
- 如果当前日 live 数据不足，不能发布正常股票分析报告。
- 如果 Supabase 容量超过 400 MB，不能执行大写入。
- 对照组用于系统学习，不展示给家庭成员。

## 5. 后评估数据边界

后评估分两类保存。

### 5.1 Supabase 保存结构化后评估

保存内容：

- 推荐日期。
- 股票代码。
- 推荐分数。
- 推荐类别：正式推荐、重点关注、后台对照。
- 命中规则和知识库版本。
- 5 日、20 日、40 日表现。
- 收益、回撤、波动、是否触发失效条件。
- 当初逻辑是否成立。
- 哪些规则有效，哪些规则误导。
- 可用于规则优化的标签。

这些数据参与统计、回测和规则优化，必须入库。

### 5.2 本地保存长篇后评估文本

保存内容：

- 当时为什么推荐。
- 复盘时对原因的长篇解释。
- 对行业、市场环境、公告、反证的自然语言分析。
- 给人阅读的完整说明。

这些主要用于人工回看，不直接参与日常计算，保存在 `local_archive/evidence_text/`。

## 6. 报告保存边界

Supabase 不保存完整 HTML 报告正文。

Supabase 保存报告索引：

- report_date
- report_type
- recommendation_count
- focus_count
- control_count
- local_report_path
- published_url
- sha256
- generated_at
- source_versions
- status

本地 `local_archive/reports/` 保存完整 HTML 报告。

这样系统可以通过 Supabase 查询“某天报告在哪里、结论是什么、是否发布”，但不会把完整 HTML 堆进数据库。

## 7. 本地保留和清理策略

保留策略：

- `local_warehouse` 全市场分析数据：180 天滚动。
- `local_archive/reports` 完整 HTML：至少 24 个月，不自动删除。
- `local_archive/evidence_text` 长篇证据和复盘文本：24 个月。
- `local_archive/manifests`：至少 24 个月。
- `local_archive/exports`：每月一个备份包，保留最近 12 个。
- Supabase 活跃结构化数据：12 个月。

清理策略：

- 清理前必须确保对应 manifest 存在。
- 清理 Supabase 结构化旧数据前必须先生成 exports。
- 清理本地报告和长文本前必须由用户确认。
- 原始行情和粗分析数据可以按 180 天自动滚动清理。

## 8. 已有 Supabase 状态

当前项目已经创建了 ingestion 表：

- `market_price_daily`
- `daily_basic_indicator`

新的设计不是删除这些表，而是改变写入策略：

- 禁止全市场历史行情写入。
- 只允许推荐股、重点关注股、后台对照组的有限 120 交易日窗口写入。
- 如果容量超过 400 MB，则这些有限行情窗口也停止写入。

当前已写入的 `stock_master` 约 5528 行属于基础名单，体积小，建议保留。行情表和每日基础指标表在停止前未写入有效大数据。

## 8.1 暂停前真实运行发现

暂停全量 Supabase 写入前，生产链路已经暴露出若干必须纳入主线设计的事实。这些不是独立补丁，后续计划必须吸收：

- Tushare `daily.amount` 的单位是千元，系统内部成交额阈值应统一换算成人民币元，否则会误判全市场成交额过低。
- 当前交易日少量股票可能没有当日 bar。系统可以允许极少量缺失，但必须设置覆盖率硬门槛；覆盖率不足时停止生成推荐。
- 历史行情里可能存在当前 `stock_basic` 不包含的股票代码。写入或计算前必须按可信股票基础名单过滤，避免外键失败和脏样本进入分析。
- 全市场行情直接批量 upsert Supabase 容易触发超时。新设计下不再全市场写 Supabase；对有限窗口写入仍要使用小批量、可重试、可审计的写入方式。
- `stock_master` 应以 Tushare `stock_basic` 为主更新，保留交易所、上市日期等字段，避免只根据推荐结果反推基础股票名单。

这些发现已经证明真实数据链路可推进，但也证明必须先完成本地 warehouse 与选择性入库，再继续真实生产运行。

## 9. 执行治理与模型分配

第三版后续实现继续采用 Subagent-Driven Development，但必须明确模型和边界，避免为了节省额度导致返工。

### 9.1 必须使用 GPT-5.5 xhigh 的环节

- 总体架构设计。
- 数据入库规则。
- Supabase schema、RLS、容量保护。
- Tushare 字段映射、单位处理和数据质量判断。
- DuckDB + Parquet 本地仓库设计。
- 选股规则、后评估规则、知识库规则。
- 生产 `run-daily` 链路。
- 任何真实数据源或真实数据库写入前的 review。
- 每个关键任务 reviewer。
- 最终 whole-branch review。

如果关键任务无法使用 GPT-5.5 xhigh，必须停止并询问用户，不得自动降级。

### 9.2 可以使用 GPT-5.4 high 的环节

- 文档整理。
- 简单测试补充。
- 小范围模板调整。
- 明确不涉及金融逻辑、数据库写入、数据源映射的小修。

### 9.3 不使用 mini 的环节

- 金融分析逻辑。
- 数据源映射。
- 数据库写入。
- 后评估。
- 规则优化。
- 容量保护。
- 真实生产链路。

### 9.4 子智能体报告要求

每个子智能体必须报告：

- 实际使用模型。
- 修改了哪些文件。
- 跑了哪些测试。
- 是否访问外网。
- 是否访问数据库。
- 是否触碰密钥。
- 是否产生真实写入。
- 发现了哪些风险。

### 9.5 人工确认门槛

以下操作必须先向用户确认：

- 真实 Supabase 写入。
- Supabase migration。
- 删除或清理任何本地归档。
- 删除或清理 Supabase 数据。
- 安装新依赖。
- 改变入库保留策略。
- 改变推荐数量、对照组数量或重点关注规则。

## 10. 下一步实施范围

本设计确认后，下一步实施计划应只做以下事情：

1. 引入 DuckDB + Parquet 本地分析库。
2. 把生产 pipeline 改成先写本地 warehouse，不再全市场写 Supabase。
3. Supabase 只写推荐、重点关注、后台对照、结构化证据、后评估和报告索引。
4. 对推荐/重点关注/对照组写有限 120 交易日行情窗口。
5. 实现 350 MB/400 MB 容量保护。
6. 建立 `local_archive`、manifest 和月度 exports。
7. 先用小规模测试验证，不直接执行全市场真实入库。

不在下一步范围：

- 大规模历史回测。
- 复杂交互式前端。
- 自动清理真实 Supabase 旧数据。
- 更换云数据库。
- 把本地 warehouse 同步到远端对象存储。
