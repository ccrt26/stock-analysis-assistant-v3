# Data Foundation Fault Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复申万行业目录重复有效期和公告公开时间倒序，并以可恢复、幂等迁移修复现有 DuckDB + Parquet 数据。

**Architecture:** 行业源头在缺少 `list_date` 时复用同一实体的首次观察日期，真实属性变化才关闭旧区间。公告事实仓把一秒纯时间摆动规范为较晚时间且不创建修订，实质内容修订一律从本地接收时刻生效。现有坏数据通过独立修复模块先备份、再原子替换受影响分区和修订元数据，并写入迁移收据。

**Tech Stack:** Python 3.12、pytest、Pandas、DuckDB、PyArrow/Parquet。

## Global Constraints

- 以 `625bd7f` 后的新架构为边界，不恢复旧 V3。
- 不开发选股、评分、Gate、关注池、报告或新 SKILL。
- 保留 `sector_hotspot` 的重复有效目录拒绝保护。
- 不删除整个事实仓或整月公告重新开始。
- 不提交、不推送；每个任务后只检查 `git diff`。
- 每项生产行为先写失败测试并观察预期失败。

---

### Task 1: 稳定申万行业目录有效期

**Files:**
- Modify: `src/stock_analyzer/data/classification_backfill.py`
- Test: `tests/test_classification_backfill.py`

**Interfaces:**
- Consumes: `ResearchWarehouse.read_current(ResearchDatasetId.INDUSTRY_CATALOG)`。
- Produces: `_sw_catalog_and_members(through)` 返回复用首次观察日期的目录行，并在属性变化时返回旧行闭合记录与新行。

- [ ] **Step 1: 写缺少 `list_date` 的跨月重复刷新失败测试**

  使用真实 `ClassificationBackfillService` 和临时 `ResearchWarehouse`，连续以 `2026-07-13`、`2026-08-03` 刷新同一缺日期的 L3 行，断言最终只有一个有效实体且 `valid_from=2026-07-13`。

- [ ] **Step 2: 运行测试并确认因生成两条开放记录失败**

  Run: `.venv/bin/python -m pytest tests/test_classification_backfill.py::test_missing_sw_list_date_reuses_first_observed_effective_date -q`

- [ ] **Step 3: 最小实现首次观察日期复用**

  在 `_sw_catalog_and_members()` 中按 `(industry_system, level, industry_code)` 读取现有历史；缺少上游日期且当前属性相同时复用最早开放记录的 `valid_from`。

- [ ] **Step 4: 写属性变化区间失败测试并观察失败**

  第二次刷新改变 `industry_name`，断言旧行 `valid_to=2026-08-02`，新行 `valid_from=2026-08-03`，且没有重叠。

- [ ] **Step 5: 最小实现属性变化闭合**

  同日变化使用原业务键形成事实修订；跨日变化返回去除治理字段的旧行闭合记录，再生成首次观察于 `through` 的新行。

- [ ] **Step 6: 运行分类定向测试**

  Run: `.venv/bin/python -m pytest tests/test_classification_backfill.py -q`

---

### Task 2: 在健康检查中暴露有效区间重叠

**Files:**
- Modify: `src/stock_analyzer/ops/research_health.py`
- Test: `tests/test_research_health.py`

**Interfaces:**
- Produces: `DatasetHealth.effective_interval_overlaps: int` 与 `effective_interval_issues: tuple[str, ...]`。
- Produces: 行业目录重叠使 `complete_core_date=False`，Markdown 输出冲突实体及两个区间。

- [ ] **Step 1: 写行业目录重叠健康失败测试**

  构造两个业务键不同但在同一天同时有效的 `850401.SI` 行，断言重叠数为 1、问题文本包含 `SW2021/L3/850401.SI`，核心健康为假。

- [ ] **Step 2: 运行测试并确认字段或行为缺失**

  Run: `.venv/bin/python -m pytest tests/test_research_health.py::test_health_reports_overlapping_industry_catalog_intervals -q`

- [ ] **Step 3: 实现小表语义审计**

  只对 `industry_catalog` 的实际 Parquet 路径按 `(industry_system, level, industry_code)` 排序区间；区间端点按包含关系判断，输出确定性问题文本。

- [ ] **Step 4: 更新健康 Markdown 并运行健康测试**

  Run: `.venv/bin/python -m pytest tests/test_research_health.py -q`

---

### Task 3: 规范公告时间抖动并保护实质修订时点

**Files:**
- Modify: `src/stock_analyzer/storage/research_warehouse.py`
- Modify: `src/stock_analyzer/data/research_time.py`
- Test: `tests/test_research_warehouse.py`
- Test: `tests/test_research_as_of.py`
- Test: `tests/test_research_time.py`

**Interfaces:**
- Produces: 公告相同业务内容、公开时间相差不超过一秒时，以较晚时间规范化且不写 `research_fact_revisions`。
- Produces: 公告实质内容修订的 `available_at=max(old_available_at, batch_ingested_at)`，精度为 `ingestion_cutoff`。
- 保持: 其他 `SOURCE_PUBLISHED` 数据集原有严格规则。

- [ ] **Step 1: 写一秒倒退和往返抖动失败测试**

  依次提交 `:29`、`:28`、`:29` 的同一公告，断言当前时间固定为 `:29`、修订数为 0、重复提交内容哈希不再变化。

- [ ] **Step 2: 运行测试并确认当前抛出倒序异常**

  Run: `.venv/bin/python -m pytest tests/test_research_warehouse.py::test_announcement_time_jitter_converges_without_revision -q`

- [ ] **Step 3: 最小实现公告时间抖动规范化**

  在 `_merge()` 比较 payload 前，仅当公告除 `announcement_time` 外的业务字段完全相同且时间差不超过一秒时选择较晚行；保留原 `revision_no`，不生成修订。

- [ ] **Step 4: 写实质内容倒序修订与 as-of 失败测试**

  首次公告时间为 `T1`；本地在 `T3` 收到标题变化但源时间为 `T0<T1`，断言新版本 `available_at=T3`，`T1..T3` 查询返回旧标题，`T3` 后返回新标题。

- [ ] **Step 5: 最小实现公告修订接收时点策略**

  `resolve_revision_availability()` 仅对 `ANNOUNCEMENT` 的实质修订返回接收时点；其他来源公开型数据仍在倒序时拒绝。

- [ ] **Step 6: 运行公告、时间和 as-of 定向测试**

  Run: `.venv/bin/python -m pytest tests/test_research_warehouse.py tests/test_research_time.py tests/test_research_as_of.py -q`

---

### Task 4: 建立可恢复且幂等的现有数据修复程序

**Files:**
- Create: `src/stock_analyzer/ops/research_data_repair.py`
- Create: `tests/test_research_data_repair.py`

**Interfaces:**
- Produces: `repair_known_data_faults(warehouse_root: Path, archive_root: Path) -> dict[str, Any]`。
- CLI: `.venv/bin/python -m stock_analyzer.ops.research_data_repair --warehouse local_warehouse --archive local_archive/repairs`。
- Writes: 固定迁移 ID 的备份清单、DuckDB/Parquet 备份、JSON 收据及 `research_migrations` 记录。

- [ ] **Step 1: 写纯变换失败测试**

  断言相同的行业重叠行保留最早记录；公告纯时间链选择最大公开时间、当前 `revision_no` 归一并列出需要删除的纯时间修订哈希；冲突内容必须拒绝自动修复。

- [ ] **Step 2: 写临时仓库集成失败测试**

  构造旧式行业重叠和倒置公告修订，运行修复两次；断言第一次产生备份和收据，第二次不再修改，Parquet 哈希与 DuckDB 元数据一致。

- [ ] **Step 3: 运行测试并确认模块缺失**

  Run: `.venv/bin/python -m pytest tests/test_research_data_repair.py -q`

- [ ] **Step 4: 实现备份、原子分区替换和元数据事务**

  先复制 `research.duckdb` 与受影响 Parquet；所有新 Parquet 先写 `.staging`，文件提升失败或 DuckDB 事务失败时恢复旧文件；更新分区哈希、行数和全局键索引，并只删除已证明为纯时间变化的公告修订。

- [ ] **Step 5: 写收据与幂等迁移记录**

  收据记录修复前后数量、受影响 ID/哈希、备份 SHA-256、文件 SHA-256 和验证结果；已完成迁移再次运行只重新验证。

- [ ] **Step 6: 运行迁移测试**

  Run: `.venv/bin/python -m pytest tests/test_research_data_repair.py -q`

---

### Task 5: 修复本地现有数据并重算观察

**Files:**
- Data: `local_warehouse/research.duckdb`
- Data: `local_warehouse/facts/industry_catalog/classification_version=SW2021/data.parquet`
- Data: affected `local_warehouse/facts/announcement/*/data.parquet`
- Create: `local_archive/repairs/2026-08-04-known-data-faults/*`
- Update: `local_archive/data_health/2026-08-03.{json,md}`

- [ ] **Step 1: 执行迁移程序**

  Run: `.venv/bin/python -m stock_analyzer.ops.research_data_repair --warehouse local_warehouse --archive local_archive/repairs`

- [ ] **Step 2: 只读查询验证数据不变量**

  验证行业业务键唯一、行业有效期无重叠、公告无倒置/重叠修订、纯时间链已折叠。

- [ ] **Step 3: 重算 2026-08-03 三类观察**

  Run: `.venv/bin/python -m stock_analyzer data derive --data-date 2026-08-03`

- [ ] **Step 4: 重写健康报告并核对三类输入**

  Run: `.venv/bin/python -m stock_analyzer data health --data-date 2026-08-03 --full-history`

---

### Task 6: 完整验证和任务试跑

**Files:**
- Verify only: all modified code, facts, receipts and health reports.

- [ ] **Step 1: 运行全部定向测试**

  Run: `.venv/bin/python -m pytest tests/test_classification_backfill.py tests/test_research_health.py tests/test_research_warehouse.py tests/test_research_time.py tests/test_research_as_of.py tests/test_research_data_repair.py tests/test_research_feature_job.py -q`

- [ ] **Step 2: 运行全量测试**

  Run: `.venv/bin/python -m pytest -q`

- [ ] **Step 3: 以明确日期试跑晚间与次晨任务**

  Run: `.venv/bin/python -m stock_analyzer data run-stage --stage evening --data-date 2026-08-03`

  Run: `.venv/bin/python -m stock_analyzer data run-stage --stage next-morning --data-date 2026-08-03`

  两条命令各重复一次验证幂等；外部源或凭据不可用时记录真实阻塞。

- [ ] **Step 4: 最终证据检查**

  检查测试退出码、健康报告、派生行数、任务退出码、迁移收据、`git diff --check`、`git status --short`，并确认无旧 V3 或选股业务改动。
