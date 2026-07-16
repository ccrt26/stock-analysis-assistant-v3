# V3 统一研究数据字段与收益口径审计修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` task by task and `superpowers:verification-before-completion` before the final commit. This task is explicitly authorized on the current local `main`; do not create a branch or worktree.
>
> **状态权威：** 本计划只记录实施过程，不代表当前生产能力；当前状态以 `docs/operations/production-capability-matrix.md` 为准。

**Goal:** 修复统一事实仓的股票日线字段契约与三类派生收益口径，保留财务多口径事实并提供确定性的可比查询，同时完成真实数据修复和审计。

**Architecture:** 在 `DatasetContract` 中登记供应商事实必需列和核心字段覆盖阈值，由写入和健康检查共同执行；事实字段仍保存 Tushare 原始口径。三类派生公式显式消费 `adj_factor`，只在本地生成 `close * adj_factor` 的可比价格，升级公式版本并按新版本重算已有派生日期。

**Tech Stack:** Python、pandas、DuckDB、PyArrow/Parquet、Pydantic、pytest、Tushare Pro。

## Global Constraints

- 直接使用当前本地 `main`，不创建分支或工作树。
- 不新增数据源，不开发选股框架，不生成、激活、发布或部署股票报告。
- 供应商 `pct_chg` 只作为 Tushare 日线事实；本地复权收益必须使用独立公式字段和公式版本。
- 保留业务唯一键、`available_at`、`payload_hash`、`revision_no` 和修订表语义。

---

### Task 1: 冻结事实契约和健康失败复现

**Files:**
- Modify: `src/stock_analyzer/data/research_contracts.py`
- Modify: `src/stock_analyzer/storage/research_warehouse.py`
- Modify: `src/stock_analyzer/ops/research_health.py`
- Test: `tests/test_research_contracts.py`
- Test: `tests/test_research_warehouse.py`
- Test: `tests/test_research_health.py`

- [x] 先写测试：缺少 `equity_daily.pre_close/change/pct_chg` 的新批次必须失败；已有缺列 Parquet 的健康结果必须报告 schema mismatch，且核心日期不完整。
- [x] 运行定点测试并确认因契约能力缺失而失败。
- [x] 最小实现必需列、字段覆盖审计和人可读健康输出。
- [x] 运行定点测试确认通过。

### Task 2: 固化财务业务键和可比查询

**Files:**
- Modify: `src/stock_analyzer/storage/research_query.py`
- Test: `tests/test_research_partition_query.py`
- Test: `tests/test_fundamental_backfill.py`

- [x] 先写测试：`financial_indicator` 不要求 `update_flag`，按 `(ts_code, report_period, report_type)` 及修订时间解析；财务报表强键保留 `statement_type` 变体。
- [x] 先写测试：可比现金流查询在 `as_of` 内优先报告期匹配的 `end_type`，再按 `update_flag`、合并报告优先级、`available_at` 和稳定键选择；早期只有未知 `end_type` 时仍可返回当时可见版本。
- [x] 运行定点测试确认失败，实现查询选择器后确认通过。

### Task 3: 三类派生公式改用复权价格

**Files:**
- Modify: `src/stock_analyzer/analysis/market_context_features.py`
- Modify: `src/stock_analyzer/analysis/hotspot_features.py`
- Modify: `src/stock_analyzer/analysis/stock_context_features.py`
- Modify: `src/stock_analyzer/ops/research_features.py`
- Test: `tests/test_market_context_features.py`
- Test: `tests/test_hotspot_features.py`
- Test: `tests/test_stock_context_features.py`
- Test: `tests/test_research_feature_job.py`

- [x] 分别增加除权日手算失败测试，证明原始 `close` 与 `close * adj_factor` 会给出不同收益。
- [x] 要求复权因子输入业务键唯一、正数且覆盖计算端点；缺失时对应收益留空并降低覆盖状态。
- [x] 市场、热点、个股公式升级到下一版本；收益、波动、方向和跨日价格位置使用本地复权价格，限价命中和供应商日线事实仍使用原始价格。
- [x] 作业输入清单加入相同日期的 `adj_factor`，确保上游因子修订触发重算。
- [x] 运行四组定点测试确认通过。

### Task 4: 修复真实 83 个股票日线分区

**Files/data:**
- Modify local facts and DuckDB metadata/revisions under `local_warehouse/` through the normal warehouse API.
- Create: `local_archive/audits/2026-07-16-v3-data-contract-return-audit.md`

- [x] 通过正式 Tushare `daily` 端点定向回填 2026-03-12 至 2026-07-13 的契约不完整交易日；不得用相邻原始收盘价伪造供应商字段。
- [x] 对每个日期核对修复前后行数、`(trade_date, ts_code)` 唯一性、OHLC、成交量/额、来源、文件哈希、内容哈希及核心字段覆盖。
- [x] 确认旧值进入修订记录，新值来源为 `tushare/daily`，`available_at` 与业务日期一致。

### Task 5: 重算新公式版本并量化影响

**Files/data:**
- Write new formula-version partitions under `local_warehouse/derived/`.
- Update: `local_archive/audits/2026-07-16-v3-data-contract-return-audit.md`

- [x] 为当前已有的 2026-07-13、2026-07-14、2026-07-15 三个分析日运行无网络派生重算。
- [x] 核对新旧市场、热点、个股字段差异；只把代码实际使用原始股票收盘价的正式派生字段列为受影响。
- [x] 保留旧公式分区作历史复现，新常量和健康检查只认可新公式版本。

### Task 6: 完整验证、审计和提交

**Files:**
- Update: `docs/operations/runbook.md`
- Create: `local_archive/audits/2026-07-16-v3-data-contract-return-audit.md`

- [x] 运行全部相关测试、全量测试、`git diff --check` 和静态范围检查。
- [x] 运行真实 `data health --full-history`，确认 83 日 schema mismatch 清零、事实唯一键与哈希通过、三类新公式派生可用。
- [x] 审计文档记录修复前后、正式键、查询选择规则、受影响字段和未解决限制。
- [x] 检查工作区只包含本任务改动，提交到当前本地 `main`。
