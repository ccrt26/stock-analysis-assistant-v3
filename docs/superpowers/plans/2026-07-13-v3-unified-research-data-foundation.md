# V3 统一研究数据底座实施计划

> **执行要求：** 本计划按测试先行执行。每个任务先写会失败的测试，确认失败原因正确，再写最小实现，最后运行相关回归。不得在实施过程中恢复旧 Phase 3 的评分、目标涨幅、仓位或报告发布能力。

**目标：** 把旧的多版本行情快照与分散的数据获取能力重构为唯一的、按业务事实去重、支持时间点查询、可自动补缺和可每日增量运行的研究数据底座；迁移现有历史并补齐截至 2026-07-13 的已确认缺失数据。

**总体方法：** 以 `ResearchWarehouse` 作为新的唯一研究入口。DuckDB 保存事实目录、运行、修订、缺口和质量状态，Parquet 保存宽表事实。旧 `FormalWarehouse` 只在迁移器中读取，不再作为生产写入目标；旧报告、Supabase 和发布流程保持停用。Tushare 与巨潮适配器只输出统一事实批次，任何批次都必须先暂存、校验，再原子提交。

**技术栈：** Python 3.11、Pydantic、pandas、PyArrow、DuckDB、Tushare Pro、httpx、Typer、pytest、launchd。

本计划记录执行方法，不单独作为当前运行状态证明；实际能力、真实回填和调度状态以 `docs/operations/production-capability-matrix.md` 的最新核验记录为准。

## 开始前的固定约束

- 工作目录固定为 `/Users/ccrt/股票分析助手` 的本地 `main`。
- 不创建分支或工作树。
- 不读取或继承已丢弃的 `codex/v3-report-readability` 工作树。
- 不打印 `.env.local`、Tushare token 或其他密钥。
- 网络获取只读外部数据；所有写入只发生在本地统一仓库。
- 不调用 Supabase、不生成报告、不激活报告、不部署 Cloudflare、不连接券商。
- 真实历史清理必须晚于逐键迁移核验和代码引用检查。
- 任何上游权限或数据缺口必须记录，不以 AKShare/BaoStock 静默补位。

## 任务 1：冻结新旧权威边界与运行状态

**修改：**

- `README.md`
- `docs/operations/runbook.md`
- `docs/operations/production-capability-matrix.md`
- `src/stock_analyzer/ops/job.py`
- `src/stock_analyzer/cli.py`

**新增测试：**

- `tests/test_research_data_authority.py`

### 1.1 先写失败测试

测试应证明：

- 当前权威文档明确说 Phase 3 分析暂停，数据底座重构进行中。
- 默认数据命令不会进入报告、Supabase、发布或激活路径。
- 旧 `run-daily-job` 不再被新版数据调度模板调用。
- CLI 中新的 `data` 命令组与旧报告命令清晰分离。

运行：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_data_authority.py -q
```

预期：首次因文档和新命令尚不存在而失败。

### 1.2 最小实现

- 把 README 与运维文档中过时的“报告仍在正式运行”改为用户确认的真实状态。
- 在 CLI 增加 `data` 子命令组占位，不调用旧分析管线。
- 在旧报告日任务入口增加明确的 legacy/dormant 说明；不删除历史代码，以免本轮引入无关大范围回归。

### 1.3 回归

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_data_authority.py tests/test_cli.py -q
```

## 任务 2：定义统一事实合同与数据集目录

**新增：**

- `src/stock_analyzer/data/research_contracts.py`
- `tests/test_research_contracts.py`

**修改：**

- `src/stock_analyzer/data/__init__.py`

### 2.1 先写失败测试

覆盖：

- 每个数据集都有稳定 ID、业务唯一键、分区字段、来源政策、必需/滞后属性和历史窗口。
- 首批目录包含：交易日历、证券主数据、股票日线、复权因子、每日估值、涨跌停、指数日线、行业目录/成分/行情、主题目录/成分/行情、公司资料、利润表、资产负债表、现金流、财务指标、主营构成、预告、快报、公告、增减持、解禁、回购、质押、停复牌、融资融券、分钟线。
- 合同禁止未知字段猜测；业务键字段不能为空。
- 来源优先级中不存在 AKShare/BaoStock 正式回退。
- `FactBatch` 必须携带来源、获取时间、可用时间策略和运行编号。

### 2.2 实现

使用 Pydantic/枚举定义：

- `ResearchDatasetId`
- `DatasetContract`
- `SourcePolicy`
- `FactBatch`
- `BatchQualityResult`
- `AvailabilityPrecision`
- `CompletenessStatus`

为每个数据集声明业务键，不在适配器内散落硬编码。

### 2.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_contracts.py -q
```

## 任务 3：建立统一 DuckDB 元数据与当前事实模型

**新增：**

- `src/stock_analyzer/storage/research_schema.py`
- `tests/test_research_schema.py`

**修改：**

- `src/stock_analyzer/storage/__init__.py`
- `src/stock_analyzer/config.py`

### 3.1 先写失败测试

必须验证以下表及约束：

- `research_dataset_catalog`
- `research_ingestion_runs`
- `research_run_datasets`
- `research_fact_partitions`
- `research_fact_revisions`
- `research_quality_checks`
- `research_data_gaps`
- `research_watermarks`
- `research_candidate_scopes`
- `research_analysis_snapshots`

测试模式：

- 同一数据集、分区和业务键不能有两个当前事实索引。
- 同一任务键重跑不会创建第二个进行中任务。
- 完整性状态只能取合同定义值。
- schema 版本可升级且重复初始化幂等。

### 3.2 实现

- 新数据库文件为 `local_warehouse/research.duckdb`。
- 旧 `warehouse.duckdb` 只读留给迁移器。
- 元数据表不保存密钥和大体积原始响应。
- `AppConfig` 暴露唯一的 `research_warehouse_path` 和事实目录。

### 3.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_schema.py tests/test_config_health.py -q
```

## 任务 4：实现原子、幂等、带修订的唯一事实仓库

**新增：**

- `src/stock_analyzer/storage/research_warehouse.py`
- `src/stock_analyzer/storage/research_parquet.py`
- `tests/test_research_warehouse.py`
- `tests/test_research_parquet.py`

**修改：**

- `src/stock_analyzer/storage/local_warehouse.py`

### 4.1 先写失败测试

测试场景：

1. 第一次提交一个股票日线分区，查询只有一份事实。
2. 完全相同批次重跑，行数、修订数和文件数不增加。
3. 同一业务键内容变化，当前值更新且旧值进入一条修订记录。
4. 批次含重复业务键时在 staging 阶段失败，不改变已提交事实。
5. 写 Parquet 后、提交前模拟异常，正式查询仍看到旧完整分区。
6. 多个交易日分区只替换目标分区。
7. `LocalWarehouse` 的正式写入委托给统一仓库，不再先删目录后裸写。
8. 外部代码无法通过仓库 API 请求无合同的 glob。

### 4.2 实现细节

- 标准化业务字段并生成 `payload_hash`。
- staging 目录使用运行 ID；提交使用同文件系统原子改名。
- 分区当前文件使用稳定路径，不含每次运行 `version_id`。
- 内容变化时只保存改变业务键的前值与变更字段。
- 提交事务登记分区文件哈希、行数、最小/最大日期、来源和质量结果。
- 失败清理 staging，但保留运行失败摘要。

### 4.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_warehouse.py tests/test_research_parquet.py tests/test_local_warehouse.py -q
```

## 任务 5：实现时间点查询、冻结导出与表达边界

**新增：**

- `src/stock_analyzer/storage/research_query.py`
- `src/stock_analyzer/storage/research_export.py`
- `src/stock_analyzer/knowledge/usage_policy.py`
- `tests/test_research_as_of.py`
- `tests/test_research_export.py`
- `tests/test_knowledge_usage_policy.py`

### 5.1 先写失败测试

- 7 月 10 日收盘时查询看不到 7 月 10 日晚间之后才发布的公告。
- T+1 才发布的融资融券记录不能出现在 T 日分析快照。
- 财报按公告/更新时间进入，而不是按报告期末进入。
- 历史行业成分按有效期返回。
- 冻结导出无重复业务键，附数据集、行数、哈希、缺口和事实截止时间。
- `src_cn_program_trading_rules_2025` 使“机构正在买入”“主力没有出货”等表述在无 Level 2 时被拒绝。
- 知识状态支持 `applied/limited/not_applicable/blocked_by_data/conflicted`。

### 5.2 实现

- 所有正式查询默认要求 `as_of`。
- 查询只读取质量通过、`available_at <= as_of` 的当前事实或所需历史修订。
- 分析快照保存事实键/分区清单，不复制事实文件。
- 导出写入 `local_archive/research_exports/`，仅作为临时、去重的外部分析输入。

### 5.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_as_of.py tests/test_research_export.py tests/test_knowledge_usage_policy.py -q
```

## 任务 6：重写旧 Parquet 重复迁移器

**新增：**

- `src/stock_analyzer/storage/research_migration.py`
- `src/stock_analyzer/ops/research_migration.py`
- `tests/test_research_migration.py`

**修改：**

- `src/stock_analyzer/cli.py`
- `src/stock_analyzer/storage/formal_migration.py`

### 6.1 先写失败测试

构造三个版本：

- 版本 A 包含日期 1、2；
- 版本 B 包含日期 1、2、3，前两日内容相同；
- 版本 C 修订日期 2 的一条事实。

验证：

- 迁移读取全部版本并集，不只读最后版本。
- 相同事实只保留一份。
- 冲突事实按确定性规则选择当前值并保存修订/冲突审计。
- 每日记录数与旧版本并集的唯一键一致。
- 重复迁移幂等。
- 审计未通过时不能生成可清理清单。

再增加真实目录只读测试，断言已知基线：

- 物理 3,450,498 行；
- 唯一 `(trade_date, ts_code)` 436,580；
- 重复 3,013,918；
- 8 个版本。

若实际源目录发生变化，测试应输出新的清单并要求人工确认，不自动改基线。

### 6.2 实现

- 新命令：`stock-analyzer data migrate-legacy-market`。
- 新命令：`stock-analyzer data audit-migration`。
- 新命令：`stock-analyzer data legacy-cleanup-manifest`。
- 迁移使用 DuckDB/Arrow 分块去重，避免把全部记录一次装进 Python 内存。
- 迁移清单记录每个旧文件哈希、每版本行数、每日期唯一数、冲突数、新分区哈希。
- `formal_migration.py` 标为 legacy，只供读取，不再创建新的正式版本树。

### 6.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_migration.py tests/test_formal_migration.py -q
```

## 任务 7：建立 Tushare 统一适配器与限速、断点机制

**新增：**

- `src/stock_analyzer/data/tushare_research_client.py`
- `src/stock_analyzer/data/research_sources.py`
- `src/stock_analyzer/data/research_rate_limit.py`
- `tests/test_tushare_research_client.py`
- `tests/test_research_rate_limit.py`

**修改：**

- `src/stock_analyzer/data/tushare_formal_client.py`
- `src/stock_analyzer/data/source_registry.py`
- `pyproject.toml`

### 7.1 先写失败测试

- 每个接口响应严格映射到对应事实合同。
- 日期、单位、空值和公告时间不被猜测。
- 分页完整，重复页被识别。
- 权限拒绝、频率限制、网络失败、尚未发布分别返回不同缺口原因。
- 重试从水位继续，不重新拉取已提交范围。
- 正式源注册表不含 AKShare/BaoStock 回退。

### 7.2 实现接口

首批封装并统一：

- `trade_cal`, `stock_basic`, `daily`, `adj_factor`, `daily_basic`, `stk_limit`；
- `index_basic`, `index_daily`, `index_classify`, `index_member`, `index_weight`；
- `stock_company`, `income`, `balancesheet`, `cashflow`, `fina_indicator`, `fina_mainbz`, `forecast`, `express`；
- `stk_holdertrade`, `share_float`, `repurchase`, `pledge_stat/pledge_detail`, `suspend_d`, `margin_detail`；
- Tushare `pro_bar` 分钟线。

旧 `TushareFormalEndpointClient` 可以委托新适配器读取，但不得继续写版本快照。

### 7.3 依赖调整

- `data` 可选依赖只保留 Tushare；移除 AKShare。
- 旧 AKShare 文件保留为历史代码直至引用测试通过，随后删除或明确隔离到 legacy。

### 7.4 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tushare_research_client.py tests/test_research_rate_limit.py tests/test_tushare_formal_client.py -q
```

## 任务 8：实现分层历史窗口的全市场价格、估值与指数回填

> **2026-07-14 执行修订：** 已接近完成的五年股票日线、复权、每日估值、涨跌停和宽基指数作为一次性紧凑底库保留；日常分析默认 82 日，市场状态最多 250 日。行业/主题行情限制为最近 250 个交易日，后续每日只增量获取。

**新增：**

- `src/stock_analyzer/data/research_backfill.py`
- `tests/test_research_market_backfill.py`

**修改：**

- `src/stock_analyzer/cli.py`

### 8.1 先写失败测试

- 一次性市场核心底库可为 2021-07-14 至 2026-07-13 的交易日生成应有分区。
- 行业和主题历史请求只覆盖截至日以前最近 250 个实际交易日。
- 已完成分区不重复请求。
- 日线、复权、估值、涨跌停中任一必需表失败时，该日期核心状态不完整。
- 停牌/退市股票导致的合理行数差异被声明，不简单要求所有表等行。
- 跨表代码和交易日一致。
- 断点后重启只补未完成日期。

### 8.2 实现

- 新命令：`stock-analyzer data backfill --through 2026-07-13 --scope market-core`。
- 日线类按交易日分批，指数历史可按代码/日期块获取。
- 默认选股查询只读 82 个交易日；市场状态查询最多读取 250 个交易日；五年读取必须由明确的估值或历史验证用途触发。
- 交易日预期证券数基于当日有效证券与交易状态计算。
- 生成每日核心数据健康状态。

### 8.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_market_backfill.py -q
```

## 任务 9：补齐申万行业与受控主题

**新增：**

- `src/stock_analyzer/data/classification_backfill.py`
- `tests/test_classification_backfill.py`

### 9.1 先写失败测试

- 申万 2021 一级、二级、三级目录和全市场成分进入同一有效期模型。
- 同一股票同层级有效期不得重叠。
- 没有历史生效日时不能默认为五年前已经属于当前行业。
- 正式受控主题只接收有稳定指数代码、名称、发布方、成分和行情的记录。
- 官方主题目录可以保留来源候选；正式受控主题由按时点查询动态取“目录、有效成分、已到达行情”的交集，禁止把后来核出的覆盖状态写回历史事实。
- 未知网页概念不会进入正式主题表。
- 行业/主题指数行情可与成分区间按日期连接。
- 板块历史只保留 A 股交易日历中的最近 250 个开市日；完整分区断点续跑不得再次请求指数行情。

### 9.2 实现

- 新命令范围：`--scope classifications`。
- 申万使用 `index_classify/index_member`；保存 L1/L2/L3 层级关系。
- 申万 L1 使用官方指数行情；L2/L3 热点特征由历史成分与唯一股票日线复算，不把接口未提供的二三级指数行情反复登记为上游故障。
- 主题目录从 CSI/SSE/SZSE 的可识别主题指数筛选，保存纳入依据。
- 成分历史优先使用带日期的权重/成员记录；无历史区间则登记缺口。

### 9.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_classification_backfill.py -q
```

## 任务 10：补齐公司资料、财务与主营业务

**新增：**

- `src/stock_analyzer/data/fundamental_backfill.py`
- `tests/test_fundamental_backfill.py`

### 10.1 先写失败测试

- 全市场公司资料而非 13/27 只候选。
- 每只股票计划最近 12 季和 5 个年度窗口。
- 利润表、资产负债表、现金流和财务指标分别保存，不压成一个最新摘要。
- 初次披露与修订按 `ann_date/f_ann_date/update_flag` 形成可用时间与修订。
- 主营构成保留产品/地区/行业分类和报告期。
- 无报告并不自动等于请求成功空集；结合上市时间和披露期判断。

### 10.2 实现

- 新命令范围：`--scope fundamentals`。
- 优先按公告期或时间块批量获取，必要时按股票断点获取。
- 为高频接口建立稳定分页与速率预算。
- 保存原始单位与标准化单位说明。

### 10.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_fundamental_backfill.py -q
```

## 任务 11：补齐公告、公司行动与风险事件

**新增：**

- `src/stock_analyzer/data/cninfo_research_client.py`
- `src/stock_analyzer/data/event_backfill.py`
- `src/stock_analyzer/data/event_classification.py`
- `tests/test_cninfo_research_client.py`
- `tests/test_event_backfill.py`

**修改：**

- `src/stock_analyzer/data/cninfo_disclosure_client.py`

### 11.1 先写失败测试

- 巨潮公告分页不重不漏，毫秒时间戳转为 Asia/Shanghai 的 `available_at`。
- 公告 ID 与原文链接稳定，重复拉取幂等。
- 关键词分类只产生“候选事件类别”，原始标题和来源链接始终保留。
- 结构化增减持、解禁、回购、质押、停复牌与公告元数据可关联。
- 立案、处罚、问询、风险警示、退市等高风险事件不因分类失败而消失，进入待复核队列。
- Tushare `anns_d` 权限拒绝不会触发 AKShare；使用已验证的巨潮直连。

### 11.2 实现

- 新命令范围：`--scope events`。
- 首次补齐近一年全市场公告元数据；增减持、回购和季度质押等真正稀疏的结构化公司行动保留五年；限售解禁只保留近一年历史，并保留分析日以前已公告的未来三年计划；停复牌按日数据只补近一年。
- 限售解禁日常更新按公告日增量抓取，不能每天重拉整个历史或未来窗口；未来计划必须以分析日已经公开为前提，禁止引入事后信息。
- `pledge_stat` 历史上既存在自然季度末快照，近期也常按周五形成统计快照。季度和分析日先查询自然目标日；若为空，再查询当日或之前最近周五，并最多逐周回退四次。旧版把自然日空返回当作完成的水位不再沿用。
- 候选股票需要全文时按公告 ID 单独获取，默认不下载全市场 PDF。
- 事件分类规则有版本号并与事实分离。

### 11.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_cninfo_research_client.py tests/test_event_backfill.py tests/test_cninfo_disclosure_client.py -q
```

## 任务 12：补齐融资融券与分钟线分层数据

> **2026-07-14 执行修订：** Tushare 官方历史分钟权限为每分钟 500 次、单次最多 8000 行；默认串行间隔采用 0.13 秒（约每分钟 461 次），不再沿用缺乏依据的 61 秒间隔。20 个交易日约 4800 根 1 分钟记录，可在单次上限内按一个代码提取。依据：<https://tushare.pro/document/1?doc_id=290>、<https://tushare.pro/document/1?doc_id=234>。

> **真实权限验收补充：** 当前本地凭证只有历史分钟试用额度（接口实测提示每天 2 次、每分钟 1 次），不能完成 50 只冻结候选加 8 个宽基指数的 20 日补齐。运行时改为直接调用分钟端点，让权限错误可见；首个权限、频率或接口失败后立即停止剩余代码并登记缺口，禁止重复轰击接口或把分钟覆盖标为完成。只有换成正式历史分钟权限后，0.13 秒正式权限限速才生效。

**新增：**

- `src/stock_analyzer/data/trading_structure_backfill.py`
- `tests/test_trading_structure_backfill.py`

### 12.1 先写失败测试

- 融资融券按实际上游可用时间进入，7 月 13 日未发布时状态为等待而非成功空表。
- 融资融券首次补齐只覆盖最近 250 个实际交易日。
- 交易所覆盖和缺失项被分项记录。
- 指数最近 20 个交易日分钟线完整。
- 宽候选池在获取前冻结，保存规则版本和股票代码。
- 最终候选缺少所需分钟线时不能宣称完成逐股交易结构分析。
- 分钟聚合 OHLC 与日线在配置容差内一致；超差批次隔离。
- 日线/分钟线输出不得标注机构身份。

### 12.2 实现

- 新命令范围：`--scope trading-structure`。
- 保存 1 分钟原始频率；其他频率由本地派生，不重复下载。
- 主要指数固定集合写入合同；候选集合写入 `research_candidate_scopes`。
- 融资融券次日 08:00 自动回补前一交易日。

### 12.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_trading_structure_backfill.py -q
```

## 任务 13：实现热点板块可复算特征

**新增：**

- `src/stock_analyzer/analysis/hotspot_features.py`
- `tests/test_hotspot_features.py`

### 13.1 先写失败测试

用人工构造的行业验证：

- 1/3/5/20 日相对收益正确；
- 上涨比例、等权/中位数收益不被单只大市值股替代；
- 成交占全市场比例按唯一事实计算，不受重复版本影响；
- 涨停、新高集中度和头部贡献正确；
- 行业内离散度能识别严重分化；
- 分钟路径能区分持续上涨、开盘拉升、尾盘拉升和冲高回落；
- 特征输出只描述可观察现象。

### 13.2 实现

- 输入只能来自 `ResearchQuery(as_of=...)`。
- 公式写入版本 `hotspot-v1`。
- 缺少历史成分或分钟线时返回 `limited` 与缺口，不补假值。
- 本轮只实现特征，不生成“必涨板块”或个股推荐。

### 13.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_hotspot_features.py -q
```

## 任务 14：实现缺口计划器、每日三阶段任务和数据健康摘要

**新增：**

- `src/stock_analyzer/ops/research_data_job.py`
- `src/stock_analyzer/ops/research_health.py`
- `ops/launchd/com.ccrt.stock-analysis-assistant.research-data.plist.example`
- `tests/test_research_data_job.py`
- `tests/test_research_data_launchd.py`

**修改：**

- `src/stock_analyzer/cli.py`
- `src/stock_analyzer/data/health.py`

### 14.1 先写失败测试

- `close` 阶段要求全市场核心行情、估值、涨跌停、指数与分类变更。
- `evening` 阶段要求财报、公告、事件、公司行动并冻结候选范围。
- `next-morning` 阶段补 T+1 融资融券和晚到修订。
- 非交易日不请求市场数据，但仍可获取公告/低频更新。
- 同一阶段重跑幂等，已完成数据不再请求。
- 一个必需数据集失败时总体状态不是成功，且已通过数据不被破坏。
- `waiting_upstream` 会进入下一次重试。
- `limited` 表示官方来源或当前账号明确不提供该能力；它必须长期显示在健康报告中并使相关分析降级，但不能让其他可用数据的每日更新误报失败。
- launchd 模板只调用数据命令，不调用报告、Supabase、部署或发布。
- 模板包含 18:30、21:30、次日 08:00，且日志独立。

### 14.2 实现

CLI：

```bash
stock-analyzer data run-stage --stage close --data-date YYYY-MM-DD
stock-analyzer data run-stage --stage evening --data-date YYYY-MM-DD
stock-analyzer data run-stage --stage next-morning --data-date YYYY-MM-DD
stock-analyzer data health --data-date YYYY-MM-DD
stock-analyzer data repair-gaps --through YYYY-MM-DD
```

健康摘要保存到：

```text
local_archive/data_health/YYYY-MM-DD.json
local_archive/data_health/YYYY-MM-DD.md
```

摘要使用人话列出：已补齐、等待上游、无法取得、校验失败、下次动作。

### 14.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_data_job.py tests/test_research_data_launchd.py -q
```

## 任务 15：移除正式 AKShare/BaoStock 与旧快照写入路径

**修改：**

- `src/stock_analyzer/ops/production_dependencies.py`
- `src/stock_analyzer/ops/formal_live.py`
- `src/stock_analyzer/data/formal_routes.py`
- `src/stock_analyzer/data/source_registry.py`
- `pyproject.toml`
- 相关旧测试

**删除或移入明确 legacy（确认无引用后）：**

- `src/stock_analyzer/data/akshare_formal_client.py`
- `tests/test_akshare_formal_client.py`

### 15.1 先写失败测试

- 默认依赖加载器没有 `akshare_module`。
- 新数据任务绝不实例化 `AkshareFormalEndpointClient`。
- `pyproject.toml` 的正式数据依赖不含 AKShare/BaoStock。
- 全仓生产源代码不存在新的 `save_group_version` 调用。
- 旧报告代码即使保留，也不能成为新数据任务依赖。

### 15.2 实现

- 把旧正式报告依赖工厂标记为 legacy report-only，或最小改为 Tushare/CNINFO 且不被数据任务引用。
- 删除 source registry 中的正式 AKShare backup_path。
- `FormalWarehouse.save_group_version` 只允许迁移兼容测试使用，生产入口停止调用。
- 调整过时测试：保留历史能力测试没有业务价值时删除；仍有通用合同价值时改测新适配器。

### 15.3 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_production_dependencies.py tests/test_formal_routes.py tests/test_research_data_job.py -q
rg -n "AkshareFormalEndpointClient|save_group_version\(" src/stock_analyzer
```

验收要求：任何剩余引用必须明确位于 legacy/migration 边界，不得位于新默认入口。

## 任务 16：真实迁移旧行情并验证重复修复

**只在任务 1–15 测试通过后执行。**

### 16.1 预迁移审计

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data inspect-legacy-market \
  --source-root local_warehouse/parquet/formal \
  --output local_archive/migrations/2026-07-13-pre-migration.json
```

核对已知基线和所有旧文件哈希。

### 16.2 执行幂等迁移

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data migrate-legacy-market \
  --source-root local_warehouse/parquet/formal \
  --migration-id unified-research-20260713
```

### 16.3 严格审计

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data audit-migration \
  --migration-id unified-research-20260713 \
  --strict-hashes
```

必须确认：

- 旧物理 3,450,498 行被解释为版本快照；
- 新股票日线只有 436,580 个迁移业务键（随后五年回填会增加历史日期）；
- 每个 `(trade_date, ts_code)` 当前事实唯一；
- 逐日 OHLC、成交量和成交额与旧版本并集的确定性当前值相同；
- 真实迁移重跑不增加事实或修订。

## 任务 17：真实自动回填截至 2026-07-13 的缺失数据

**前提：** 加载本地凭证但不输出；先执行接口权限探测和速率预算。

### 17.1 运行全范围回填

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data backfill \
  --through 2026-07-13 \
  --scope all \
  --resume
```

执行器按以下顺序推进并保存水位：

1. 交易日历、证券主数据；
2. 一次性五年股票/宽基指数日线、复权、估值、涨跌停底库；
3. 申万三级行业与受控主题，以及最近 250 个交易日板块行情；
4. 公司资料、12 季/5 年财务、主营、预告、快报；
5. 五年稀疏公司行动、近一年历史及未来三年已知解禁计划、近一年停复牌、公告元数据与风险事件；
6. 最近 250 个交易日融资融券；
7. 20 日指数和冻结候选分钟线。

遇到频率限制、网络中断或上游未发布时命令可安全退出，下一次 `--resume` 从水位继续。不得用“返回空表”冒充完成。

### 17.2 自动修复缺口

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data repair-gaps \
  --through 2026-07-13
```

允许多次运行，直到所有可获得范围完成；无法免费/无权限取得的内容转为 `complete_with_declared_gaps`，并写明：数据集、日期范围、来源接口、失败类别、对分析结论的限制。

### 17.3 生成数据健康摘要

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data health \
  --data-date 2026-07-13 \
  --full-history
```

## 任务 18：安装前验证每日任务，而不是直接声称已生效

### 18.1 离线调度验证

使用记录式源依次运行 close/evening/next-morning，验证：

- 三阶段应有范围完整；
- 中断恢复；
- 同阶段重跑幂等；
- 晚到融资融券只在正确时间进入；
- 失败不会留下半分区；
- 任务不触达报告、Supabase 和发布。

### 18.2 真实只读/本地写入试跑

对 2026-07-13 运行三阶段，真实来源只读，本地仓库写入：

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data run-stage --stage close --data-date 2026-07-13
PYTHONPATH=src .venv/bin/python -m stock_analyzer data run-stage --stage evening --data-date 2026-07-13
PYTHONPATH=src .venv/bin/python -m stock_analyzer data run-stage --stage next-morning --data-date 2026-07-13
```

### 18.3 launchd 配置

- 生成的数据专用 plist 不包含绝对个人路径或密钥。
- 本轮可以更新并验证模板。
- 只有确认用户机器当前旧任务状态和安装路径后，才替换已安装任务。
- 替换时必须先停止旧报告任务，安装新数据任务，执行 `launchctl print` 核对三个时点、main 路径、`RunAtLoad=false` 和数据命令。
- 不因模板测试通过就声称系统调度已经激活。

## 任务 19：全量回归、真实验收与旧版本清理

### 19.1 全量自动测试

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

### 19.2 静态边界检查

```bash
git diff --check
rg -n "AkshareFormalEndpointClient|baostock|version_id=\*|read_parquet\(.+formal" src tests ops
rg -n "Supabase|publish|Cloudflare|render_report" src/stock_analyzer/ops/research_* ops/launchd/com.ccrt.stock-analysis-assistant.research-data.plist.example
```

### 19.3 真实仓库验收

验收摘要至少打印：

- 各数据集日期范围、行数、唯一键数、重复数；
- 可获得范围的完成率；
- 等待/无法取得范围与业务影响；
- 旧行情迁移冲突数和修订数；
- 7 月 13 日各核心表覆盖；
- 行业 L1/L2/L3 目录和股票映射覆盖；
- 受控主题数量及成分有效期缺口；
- 财务/公告/公司行动覆盖；
- 分钟线与日线聚合校验；
- 每日三阶段试跑状态。

### 19.4 清理旧版本树

只有以下条件全部成立才清理：

1. 迁移严格审计通过；
2. 各数据集按修订后的分层窗口完成回填或缺口已声明；
3. 新仓库幂等重跑通过；
4. `rg` 证明生产代码不再读取旧版本树；
5. 清理清单中的路径全部位于旧 `local_warehouse/parquet/formal` 范围；
6. 删除前后新仓库查询哈希相同。

清理后保留的只有：迁移清单、逐日审计摘要和实际发生的修订记录，不保留八套重复行情副本。

### 19.5 最终提交前验证

```bash
git status --short
git diff --check
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m stock_analyzer data health --data-date 2026-07-13 --full-history
```

最终汇报必须用人话说明：

- 重复问题是否修好，数据是否还会被重复统计；
- 哪些缺失数据已经补齐；
- 哪些因免费来源或权限限制仍缺，以及会限制什么结论；
- 每日任务实际覆盖哪些数据、何时获取、失败后如何追补；
- launchd 是“模板已验证”还是“已实际安装并运行”；
- 明确本轮没有生成、激活或部署股票报告。

## 计划执行中的停止条件

以下情况不允许自行扩大范围，必须记录并采用安全降级：

- 需要购买 Level 2 或新增付费数据授权；
- 官方/Tushare 接口无权限且没有同口径正式免费来源；
- 巨潮或交易所接口发生无法确认语义的结构变化；
- 旧数据出现无法用来源时间、内容哈希和质量规则裁决的真实冲突；
- 清理清单包含旧版本树之外的文件；
- 任何步骤可能触发报告发布、Supabase 写入、Cloudflare 或券商操作。
