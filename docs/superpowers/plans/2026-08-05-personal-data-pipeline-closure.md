# 个人股市数据链路收口实施计划

> **执行方式：** 主智能体在当前仓库内直接执行，不使用子智能体，不提交或推送 Git。

**Goal:** 只证明并修复收盘、晚间、次晨三项每日任务的 API 取数、确定性加工和 DuckDB + Parquet 存储链路。

**Architecture:** 保持现有三项任务、API 客户端和事实仓结构。只保留直接防止错取、错算、重复写入、文件/元数据不一致和虚假成功的机制。

**Tech Stack:** Python 3.12、pytest、Pandas、DuckDB、Parquet、macOS `fcntl`。

## Global Constraints

- 基线为 `625bd7f`，保留用户已有修复和无关未跟踪目录。
- 不恢复旧 V3，不开发选股、评分、Gate、报告、SKILL 或历史业务模拟。
- 每个行为修复先用可观察失败测试证明根因，再做最小修改。
- 外部数据源不可用时只报告阻塞，不伪造成功。

---

### Task 1: 撤回已确认的需求蔓延

**Files:**
- Modify: `src/stock_analyzer/ops/research_data_job.py`
- Modify: `tests/test_research_data_job.py`
- Delete: `src/stock_analyzer/ops/data_foundation_closure.py`
- Delete: `tests/test_data_foundation_closure.py`
- Delete: `docs/superpowers/plans/2026-08-05-data-foundation-closure-repair.md`

- [ ] 删除同阶段同日期的结果缓存和 `scope:*` 虚拟账本。
- [ ] 保留每次真实执行、单机互斥和一条简单运行记录。
- [ ] 运行任务记录定向测试。

### Task 2: 核对三项真实任务链

**Files:**
- Inspect/modify only as proven necessary under `src/stock_analyzer/data/`, `src/stock_analyzer/ops/research_data_job.py`, `src/stock_analyzer/cli.py`
- Test: existing `tests/test_*backfill.py`, `tests/test_research_data_job.py`, `tests/test_cli.py`

- [ ] 列出收盘、晚间、次晨的实际 API、日期、分页、证券范围和输出数据集。
- [ ] 用 fake client 连续运行两次，验证每次真实请求且事实收敛。
- [ ] 验证必要事实失败和健康不完整时 CLI 返回非零。

### Task 3: 仅修复实测仍存在的加工和存储故障

**Files:**
- Modify only files whose current behavior is proven wrong.

- [ ] 复核日期/时区、单位、业务键、修订收敛、主数据刷新、事件回看和 staging 范围。
- [ ] 复核 Parquet/manifest/SHA/行数及写入中断恢复。
- [ ] 对仍存在的故障逐一完成 RED→GREEN，不做无关重构。

### Task 4: 修复当前本地数据

**Files:**
- Reuse existing explicit repair scripts when they fit; otherwise extend one current repair script minimally.

- [ ] 先只读列出当前阻塞项和受影响行数。
- [ ] 仅对确认错误的 Parquet/DuckDB 建立备份并迁移。
- [ ] 验证第二次运行不再改变任何事实或修订。

### Task 5: 验证并立即停止

**Files:**
- No new production abstractions.

- [ ] 运行相关定向测试和完整 `python -m pytest -q`。
- [ ] 全量只读验证当前事实文件、manifest、SHA、行数、业务键和修订区间。
- [ ] 以明确日期运行三项任务并重复运行；外部阻塞如实记录。
- [ ] 只回答“可以继续每日运行”或“仍不可以”及直接证据，然后停止。
