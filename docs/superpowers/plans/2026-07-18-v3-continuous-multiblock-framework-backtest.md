# V3 连续多时间块完整框架回测实验实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在严格历史时点和 Mac 数据仓零写入条件下，连续运行 174 个运营日，评价前 144 个成熟形成日上的六入口发现、十只压缩、重点/候补、挑战者替换和 1—6 周项目机制，并诚实识别当前框架不能执行或不能验证的部分。

**Architecture:** 本实验使用逐日运营时钟和最终评价时钟。逐日阶段从 2025-10-30 运行到 2026-07-17，每天只读取截至当天可得的事实，先更新旧项目、再运行同一六入口发现流和三套名单政策，然后将状态和哈希原子写入 U 盘；全部 174 日冻结后，评价阶段才计算前 144 个成熟形成日的未来 10/20/30 日路径。批量读取和滚动复算只能在三个真实日期和时点边界合成样例与现有严格单日路径逐值一致后启用。

**Tech Stack:** Python 3.12、pandas、DuckDB、PyArrow、Pydantic 2、现有 `ResearchWarehouse`/`ResearchQuery`/三类治理派生公式、Codex CLI 隔离结构化判断、pytest、Parquet、JSON、YAML、SHA-256 和 Markdown。

## Global Constraints

- 直接使用当前本地 `main`，不创建分支或工作树。
- 框架权威固定为 `docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`；实验设计权威固定为 `docs/superpowers/specs/2026-07-18-v3-continuous-multiblock-framework-backtest-design.md`。
- 不读取或继承旧 Phase 3 的评分、固定权重、推荐结论或报告表达。
- 不修改数据底座、数据源、生产派生公式、生产清单、正式报告、生产调度或部署状态。
- Mac 本地 `local_warehouse/facts/`、`local_warehouse/derived/` 和 `local_warehouse/research.duckdb` 只能直接只读，禁止克隆、链接后改写或在其父目录创建实验临时文件。
- 所有实际回测产物、缓存、临时文件、日志、DuckDB 临时目录和排序溢写只能位于 `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-18-v3-continuous-multiblock/`。
- 单元测试源码和实验工具源码可写入仓库；测试运行时设置 `TMPDIR` 和 `V3_BACKTEST_ROOT` 到 U 盘，避免在 Mac 生成大型测试数据。
- 形成日截止固定为北京时间 `23:59:59`；事实要求 `available_at <= cutoff`，关系要求形成日处于有效区间，派生观察要求 `analysis_date == formation_date`。
- 只调用 `research_registry.yaml` 中 27 项 `current` 知识；`historical_only`、暂缓、退出或 `discard` 不可调用。
- 每个候选只允许一个主要机会来源；热点和价格只是发现入口或辅助因素，不是价值来源。
- 六入口不投票、不计分；十只和五只是不凑数上限；无法区分的容量竞争整组回内部研究池。
- 成交、放量、上涨和收盘位置只描述交易结果，禁止推断机构、主力、吸筹或出货。
- 本实验不建立买卖、仓位、交易费用、净值或夏普率；目标是形成日收盘后 10—30 个交易日盘中触及约 20%，中心窗口 20 日。
- 回测完成后只报告结果和漏洞；不自动修改框架、不编写正式 V3 实施计划、不激活、不部署。

## 冻结样本和输出根

```yaml
experiment_id: 2026-07-18-v3-continuous-multiblock
operational_start: 2025-10-30
operational_end: 2026-07-17
mature_formation_end: 2026-06-04
operational_sessions: 174
mature_formation_sessions: 144
maintenance_tail_sessions: 30
target_return: 0.20
horizons: [10, 20, 30]
drawdown_sensitivities: [0.05, 0.10]
stationary_bootstrap_mean_blocks: [10, 20, 30]
primary_bootstrap_mean_block: 20
output_root: /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-18-v3-continuous-multiblock
experiment_scope: null
full_v3_status: null
```

成熟样本报告块固定为：A `2025-10-30..2025-12-10` 30 日；B `2025-12-11..2026-01-23` 30 日；C `2026-01-26..2026-03-16` 30 日；D `2026-03-17..2026-04-28` 30 日；E `2026-04-29..2026-06-04` 24 日。块边界不重置滚动项目。

## 文件职责

- Modify `src/stock_analyzer/evaluation/v3_backtest/calendar.py`：唯一冻结 174/144/30 日和 A—E 块。
- Modify `src/stock_analyzer/evaluation/v3_backtest/contracts.py`：结构化影响、证据卡状态、比较、验证和转换合同。
- Create `src/stock_analyzer/evaluation/v3_backtest/capability.py`：六入口能力矩阵和 `full/partial` 先行否决门。
- Create `src/stock_analyzer/evaluation/v3_backtest/batch_snapshots.py`：Mac 仓只读、多日期一次读取、滚动复算、逐值一致门。
- Modify `src/stock_analyzer/evaluation/v3_backtest/judge.py` 和 prompt：固定新合同、缓存上下文和一致性回执。
- Create `src/stock_analyzer/evaluation/v3_backtest/decision.py`：无分数三阶段支配图、共同暴露和零至十/零至五压缩。
- Create `src/stock_analyzer/evaluation/v3_backtest/lifecycle.py`：双时钟、三政策、5/10/20/30 日检查和维护尾段。
- Create `src/stock_analyzer/evaluation/v3_backtest/baselines.py`：形成期透明基线和匹配对照成员冻结。
- Reuse/modify only as required `src/stock_analyzer/evaluation/v3_backtest/freeze.py`：U 盘原子写、哈希树、174 日完整性和未来字段隔离。
- Modify `src/stock_analyzer/evaluation/v3_backtest/outcomes.py`：冻结后揭示成熟项目、策略暴露和替换反事实。
- Modify `src/stock_analyzer/evaluation/v3_backtest/statistics.py`：真实决策日聚类、A—E 分块、三政策合法估计单位。
- Create `src/stock_analyzer/evaluation/v3_backtest/runner.py`：`preflight/equivalence/form/freeze/reveal/report` 六阶段总执行器。
- Create `src/stock_analyzer/evaluation/v3_backtest/report.py`：模块判定、能力缺口、失败审计和普通语言报告。
- Tests mirror each created/modified module under `tests/evaluation/v3_backtest/`.

---

### Task 1: 冻结 174 日运营日历、144 日成熟样本和机器配置

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_backtest/calendar.py`
- Modify: `tests/evaluation/v3_backtest/test_calendar.py`
- Create: `docs/superpowers/specs/2026-07-18-v3-continuous-multiblock-backtest-config.yaml`

**Interfaces:**
- Produces: `BacktestCalendar(operational, mature, maintenance_tail, blocks, maturity_end)`。
- Invariant: `operational == mature + maintenance_tail`，且 `mature[-1]` 后恰有 30 个市场交易日到 `maturity_end`。

- [ ] **Step 1: 写新的失败测试**

```python
def test_calendar_has_174_operational_and_144_mature_sessions(open_sessions):
    cal = build_frozen_calendar(open_sessions, data_end=date(2026, 7, 17))
    assert cal.operational[0] == date(2025, 10, 30)
    assert cal.operational[-1] == date(2026, 7, 17)
    assert cal.mature[-1] == date(2026, 6, 4)
    assert len(cal.operational) == 174
    assert len(cal.mature) == 144
    assert len(cal.maintenance_tail) == 30
    assert tuple(map(len, cal.blocks)) == (30, 30, 30, 30, 24)
```

- [ ] **Step 2: 运行 RED**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_calendar.py -q`  
Expected: FAIL，因为现有合同仍是 143 日、三块和 2026-07-16。

- [ ] **Step 3: 实现唯一日期合同**

```python
@dataclass(frozen=True)
class BacktestCalendar:
    operational: tuple[date, ...]
    mature: tuple[date, ...]
    maintenance_tail: tuple[date, ...]
    blocks: tuple[tuple[date, ...], ...]
    maturity_end: date

    @property
    def primary(self) -> tuple[date, ...]:
        return self.mature
```

保留 `primary` 只作为现有模块的兼容只读别名，不保留旧 extension。构造器只接收交易日和截止日，不接收收益、热点或结果。

- [ ] **Step 4: 写并校验 YAML**

将本计划“冻结样本和输出根”的 YAML 原样写入配置，并增加 A—E 精确边界、`cutoff_time: 23:59:59+08:00`、`knowledge_status: current`、`candidate_cap: 10`、`focus_cap: 5`、`experiment_scope: null`、`full_v3_status: null`。

- [ ] **Step 5: 运行 GREEN 和提交**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_calendar.py -q`  
Expected: PASS。  
Commit exact files: `test: freeze continuous V3 backtest calendar`。

### Task 2: 建立 U 盘工作区、生产仓零写入证据和能力矩阵

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/capability.py`
- Create: `tests/evaluation/v3_backtest/test_capability.py`
- Create at run time only: `$V3_BACKTEST_ROOT/preflight/capability-matrix.json`
- Create at run time only: `$V3_BACKTEST_ROOT/preflight/mac-warehouse-fingerprint-before.json`

**Interfaces:**
- Produces: `CapabilityMatrix.freeze() -> CapabilityReceipt`，字段含 `experiment_scope`、`full_v3_status` 和六个 `RouteCapability`。
- `RouteCapability` 必须含 `can_enumerate_all`、`can_form_ready_card`、`can_enter_ten`、`missing_fields`、`coverage_start/end`、`evidence_hashes`。

- [ ] **Step 1: 写 fail-closed 测试**

```python
def test_any_structurally_missing_required_route_forces_partial():
    receipt = freeze_capability_matrix(matrix_with_industry_cycle_not_executable())
    assert receipt.experiment_scope == "partial"
    assert receipt.full_v3_status == "not_executable"
    assert receipt.routes["industry_cycle"].can_enter_ten is False
```

再测试“能枚举但无 ready 卡”不能进入十只，以及缺少证据哈希不能冻结。

- [ ] **Step 2: 建立 U 盘目录并固定运行环境**

建立 `preflight/ formation/{snapshots,routes,evidence,judgments,projects,manifests} outcomes/ statistics/ reports/ logs/ cache/ tmp/ duckdb-tmp/`。每次运行导出：

```bash
export V3_BACKTEST_ROOT=/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-18-v3-continuous-multiblock
export TMPDIR="$V3_BACKTEST_ROOT/tmp"
export DUCKDB_TMPDIR="$V3_BACKTEST_ROOT/duckdb-tmp"
```

- [ ] **Step 3: 生成只读能力证据**

对六入口逐一检查实际 `scan_routes` 实现和本地字段。不得把 `ResearchHypothesis.internal_only=True` 当 ready。公告只有标题/URL而缺正文、金额、主体、执行条件时，事件入口必须 `can_form_ready_card=false`。产业/周期和困境没有任何可生成 lead 的实现时必须明确 `not_executable_with_local_data`。

- [ ] **Step 4: 冻结 Mac 仓指纹**

分别记录 `facts`、`derived` 树指纹和 `research.duckdb` 文件 SHA-256、大小、mtime_ns。指纹函数不能在仓内写 marker。运行后每个阶段重新比较；任何变化故障关闭。

- [ ] **Step 5: 运行测试和提交**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_capability.py tests/evaluation/v3_backtest/test_routes.py -q`  
Expected: PASS；能力矩阵在本地实际缺口下冻结为 `partial/not_executable` 时，实验继续评价可执行模块而不是停止。  
Commit: `test: audit executable V3 backtest capability`。

### Task 3: 用批量只读快照替代 174 次仓库克隆，并通过严格同值门

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/batch_snapshots.py`
- Create: `tests/evaluation/v3_backtest/test_batch_snapshots.py`
- Modify only if required: `src/stock_analyzer/evaluation/v3_backtest/snapshots.py`

**Interfaces:**
- Produces: `BatchSnapshotStore.prepare(operational_dates, root) -> BatchSnapshotReceipt`。
- Produces: `BatchSnapshotStore.snapshot(origin) -> FormationSnapshot`，与 `materialize_formation_snapshot` 对外合同一致。
- Produces: `compare_snapshot_exact(reference, candidate) -> ExactParityReceipt`。

- [ ] **Step 1: 写越界与时点边界失败测试**

合成两版同业务键事实：一版 `available_at == cutoff` 必须可见，一版晚一微秒必须不可见；关系 `valid_from` 当日可见、次日才开始不可提前出现。测试批量缓存不得因后一天已读取到内存而污染前一天快照。

- [ ] **Step 2: 写三日期逐值一致测试**

日期固定 `2025-10-30`、`2026-02-11`、`2026-06-04`。逐表比较 schema、列顺序、规范化 dtype、业务键、行数、空值位置、每个值、输入分区哈希、三类公式版本、market/sector/stock 行数、六入口 manifest 输入。浮点不得使用容差；统一 `NaN/NaT` 表示后比较 Arrow IPC 内容哈希。

- [ ] **Step 3: 实现一次读取和滚动复算**

只读扫描所需事实分区到进程内 Arrow/Pandas 表；每个 origin 使用 `available_at`、业务日期和有效区间过滤。市场、热点、价格观察使用原生产公式函数逐形成日复算，但复用已读取表，不创建隔离仓、不复制 DuckDB。静态事实缓存键为 `origin/cutoff/fact_manifest_hash/formula_versions`。

- [ ] **Step 4: 实现内容寻址落盘**

快照写 `$V3_BACKTEST_ROOT/cache/snapshots/<sha256>/`；先同卷 `.partial-<uuid>`，校验行数和业务键后改名。每文件不超过 3.5GB；相同内容只保存一次，日期 manifest 引用内容哈希。

- [ ] **Step 5: 运行同值门**

先运行合成边界测试，再在三个真实日期分别执行现有严格单日路径和新批量路径。任何差异都写入 `preflight/equivalence-diff/` 并禁止主实验。只有三日 `exact_equal=true` 才写 `preflight/equivalence-receipt.json`。

- [ ] **Step 6: 运行测试和提交**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_snapshots.py tests/evaluation/v3_backtest/test_batch_snapshots.py -q`  
Expected: PASS。  
Commit: `perf: add exact multi-origin V3 snapshots`。

### Task 4: 扩展结构化判断合同，不允许市场和热点只作标签

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_backtest/contracts.py`
- Modify: `src/stock_analyzer/evaluation/v3_backtest/judge.py`
- Modify: `src/stock_analyzer/evaluation/v3_backtest/prompts/v3_backtest_judge_v1.txt`
- Modify: `tests/evaluation/v3_backtest/test_contracts.py`
- Modify: `tests/evaluation/v3_backtest/test_judge.py`

**Interfaces:**
- Adds: `EvidenceCardStatus(ready, insufficient_as_of_cutoff, not_executable_with_local_data)`。
- Adds: `ContextEffect(supports_current_opportunity, raises_company_evidence_bar, limits_focus, accelerates_invalidation_check, not_applicable, opposes_causal_chain)`。
- Adds: `ValidationDisposition(satisfied, unmet, negated, not_observable_as_of_date)`。
- Adds: `ComparisonStage(same_hotspot_opportunity_role, same_opportunity_cross_context, cross_opportunity)`。
- Produces a candidate judgment with cited `market_effect`, `hotspot_effect`, `card_status`, `price_role`, `next_validation_state`, decisive edges and reversal facts。

- [ ] **Step 1: 写合同 RED**

拒绝：缺市场影响、缺热点影响、`card_status != ready` 却建议进入十只、比较边引用组外股票、无反转事实、数值无证据、出现 score/probability/机构身份。

- [ ] **Step 2: 扩展 Pydantic schema 和 prompt**

prompt 固定三阶段比较顺序和 `capacity_tie_abstention`；要求每个判断逐条引用 evidence id。模型不得在缺少产业事实时把价格异常改称产业趋势，也不得用热点或业绩质量替代主要机会来源。

- [ ] **Step 3: 修正缓存承诺**

判断缓存键必须包含：

```python
@dataclass(frozen=True)
class JudgmentCacheKey:
    origin: date
    cutoff: str
    fact_manifest_hash: str
    formula_version: str
    knowledge_version: str
    prompt_version: str
    project_state_hash: str
    checkpoint: str
    comparator_cohort_hash: str
    portfolio_exposure_hash: str
    previous_judgment_hash: str
```

不得遗漏任一字段；5/10/20/30 检查点强制重判。

- [ ] **Step 4: 一致性门**

在三真实日期对相同输入重复两次；候选集合、主要机会、层级、支配边、无法区分组不一致即停止。最多一次结构纠错，不能从两次结果中挑有利版本。

- [ ] **Step 5: 运行和提交**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_contracts.py tests/evaluation/v3_backtest/test_judge.py -q`  
Expected: PASS。  
Commit: `test: freeze contextual V3 judgment contract`。

### Task 5: 实现无总分三阶段压缩和重点/候补分层

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/decision.py`
- Create: `tests/evaluation/v3_backtest/test_decision.py`

**Interfaces:**
- Consumes: 当日 verified judgment batch、有效 incumbent 状态、能力矩阵。
- Produces: `compress_research_pool(...) -> DecisionReceipt`；含 `DailyDecision`、内部研究池、比较图、淘汰原因、tie abstention、共同暴露和最强未入选挑战者。

- [ ] **Step 1: 写固定顺序和不凑数测试**

断言事件卡不 ready 在硬边界阶段退出；只有 7 只有效时输出 7；只有 2 只具备行动价值时 focus 为 2；无法区分组面对 1 个空席时整组不入选。

- [ ] **Step 2: 写三阶段支配图测试**

同热点同机会同价格角色先比较；幸存者进入同机会跨热点/角色；非支配者进入跨机会组合竞争。循环边、断证据边或矛盾边使该组 `indistinguishable`，不得按输入顺序或代码排序选一只。

- [ ] **Step 3: 写共同暴露测试**

相同业务驱动和相同热点风险、没有独立公司事实的重复表达不得同时占位；不同角色且具有独立驱动可以并存。共同暴露检查不能为了行业均衡纳入证据更弱对象。

- [ ] **Step 4: 实现分层和审计回执**

`focus` 要求新增驱动、当前行动资格、价格未完全消耗、路径风险、下一验证和失效均 ready；`early_validation` 要明确缺失确认；`high_elasticity_tracking` 要明确为什么可能冲高但今天不适合重点。不得将文字流畅度转为隐含分数。

- [ ] **Step 5: 运行和提交**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_decision.py -q`  
Expected: PASS。  
Commit: `test: compress V3 pool with dominance graphs`。

### Task 6: 实现三套名单政策和 174 日连续生命周期

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/lifecycle.py`
- Create: `tests/evaluation/v3_backtest/test_lifecycle.py`

**Interfaces:**
- Produces: `FixedInitialPolicy`, `DailyResetPolicy`, `RollingCompetitionPolicy`。
- Consumes the same `DailyDiscoveryFrame`; only lifecycle behavior differs。
- Produces `DailyLifecycleReceipt` with projects, daily exposures, transitions and replacement pairs。

- [ ] **Step 1: 写项目身份和双时钟测试**

同股票+同主要机会+同首次形成日只是一项项目；截至 t 已发生的目标/失效可更新旧项目；t+1 行情不得进入 t 决策。维护尾部新项目标为 `maintenance_tail_immature`，但可以替换成熟样本旧项目。

- [ ] **Step 2: 写固定检查点状态测试**

第 5 日执行周一验证；第 10 日 `unmet` 且无新增正式事实降候补、`negated` 退出、`not_observable` 保留并提前复检；第 20 日后只有因果链仍成立且有允许的第二波确认才能继续；第 30 日强制结束。价格反弹本身不能成为第二波确认。

- [ ] **Step 3: 写替换配对测试**

替换必须同日冻结 challenger/replaced、两者收盘、剩余期限、决定性事实、共同风险和不替换反事实 id。单日涨幅、成交放大、旧项目未涨或“名单需要变化”不能单独触发替换。

- [ ] **Step 4: 写三政策估计单位测试**

定期首批固定只在 A—E 块首日播种，块内目标/硬失效/到期退出且不补普通挑战者；每日重置只有同日 attention-set 暴露，不产生项目占位；滚动竞争完整更新。三者引用相同发现 frame hash。

- [ ] **Step 5: 实现并运行**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_lifecycle.py -q`  
Expected: PASS。  
Commit: `test: add continuous V3 lifecycle policies`。

### Task 7: 在形成期冻结透明基线和匹配对照

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/baselines.py`
- Create: `tests/evaluation/v3_backtest/test_baselines.py`

**Interfaces:**
- Produces: `freeze_daily_controls(frame, route_batch) -> ControlMembershipReceipt`。
- Cohorts: `all_market`, `matched_market`, `hotspot_baseline`, `earnings_baseline`, `price_baseline`。

- [ ] **Step 1: 冻结价格角色和流动性分组**

价格角色只用形成日变量：过去 20 日复权收益处于同日合格证券 80%及以上为 `strong_leader`；20%—80%且过去 5 日收益为正为 `balanced_start`; 其余为 `other_tradable`。过去 20 日成交额按同日上市板块内五分位分组；缺完整 20 日历史记匹配不足，不猜组。

- [ ] **Step 2: 冻结不放回匹配顺序**

每候选最多 5 个对照：同形成日+上市板块+一级行业+价格角色+成交额五分位精确匹配；少于 3 个时依次放宽相邻成交额组、相邻价格角色；仍不足记录 `insufficient_matches`，不跨行业。

- [ ] **Step 3: 冻结三个透明基线**

- Hotspot: 仅用热点入口可用成员；按 `relative_return_20d desc`、`breadth_20d desc`、`median_return_20d desc`、`turnover_share_average_20d desc`、`security_id asc`，最多十只。
- Earnings: 仅用业绩入口可用成员；按 `available_at desc`、`operating_change_magnitude desc`、`security_id asc`。`operating_change_magnitude` 只从同一份当时可见 `financial_indicator` 记录的 `tr_yoy/netprofit_yoy/dt_netprofit_yoy/ocf_yoy` 非空绝对值取最大值；四项全缺时排在有值之后，不以缺值补足。
- Price: 仅用全市场可交易且特征完整成员；按 `relative_return_20d desc`、`current_amount_ratio_20d desc`、`security_id asc`；负相对收益不入基线。

三个基线不足十只不补齐；平局只用代码升序稳定，不解释为更优。排序字段在形成表中保存，结果字段在形成期禁止存在。

- [ ] **Step 4: 运行和提交**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_baselines.py -q`  
Expected: PASS，包括未来结果字段注入、跨行业补造和不放回违规测试。  
Commit: `test: freeze transparent V3 control cohorts`。

### Task 8: 完成 U 盘冻结、揭示和时间相关统计合同

**Files:**
- Reuse/modify: `src/stock_analyzer/evaluation/v3_backtest/freeze.py`
- Reuse/modify: `tests/evaluation/v3_backtest/test_freeze.py`
- Modify: `src/stock_analyzer/evaluation/v3_backtest/outcomes.py`
- Modify: `src/stock_analyzer/evaluation/v3_backtest/statistics.py`
- Modify: `tests/evaluation/v3_backtest/test_outcomes.py`
- Modify: `tests/evaluation/v3_backtest/test_statistics.py`

**Interfaces:**
- Produces: `freeze_formation_run(...)->FormationFreezeReceipt`，`evaluate_frozen_projects(...)`，`compare_layers(...)`，`compare_replacements(...)`，`summarize_occupancy(...)`，`stationary_block_interval(...)`。

- [ ] **Step 1: 更新冻结完整性测试**

要求 174 个每日状态、144 个 mature origin、30 个 maintenance tail；每天六条 route manifest、三政策同一发现 hash；每个候选/判断/替换/退出可追溯。形成目录出现 future/outcome/target_touched/terminal_return/形成日后价格字段立即失败。

- [ ] **Step 2: 适配 FAT 同卷原子冻结**

不得依赖 chmod。每个表先写 `.partial-uuid`，校验 schema、行数、业务键、父清单哈希和 SHA-256 后同目录改名。总清单写完再次逐文件验证。单文件超过 3.5GB 拒绝并按形成月切分。

- [ ] **Step 3: 扩展结果揭示**

评价 discovery/action/replacement/trade 四种真实基准；只对 mature origins 计算完整 10/20/30 日主指标。维护尾部新项目不进成熟命中率，但其替换和席位影响进入运营指标。

- [ ] **Step 4: 修正聚类和政策比较**

发现按 `discovery_date`，重点按 `action_date`，替换按 `replacement_date`，日级 attention-set 按 `trade_date` 做连续时间块重采样。滚动/固定可比较 episode、项目和日席位；滚动/每日重置只比较同日路径、保留率和换名单成本，不比较无效占位。

- [ ] **Step 5: 运行和提交**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_freeze.py tests/evaluation/v3_backtest/test_outcomes.py tests/evaluation/v3_backtest/test_statistics.py -q`  
Expected: PASS。  
Commit only exact reviewed files: `test: evaluate frozen continuous V3 mechanisms`。

### Task 9: 建立六阶段执行器和可恢复日志

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/runner.py`
- Create: `tests/evaluation/v3_backtest/test_runner.py`
- Modify: `src/stock_analyzer/evaluation/v3_backtest/__init__.py`

**Interfaces:**
- CLI: `python -m stock_analyzer.evaluation.v3_backtest.runner {preflight,equivalence,form,freeze,reveal,report}`。
- `form` 顺序：载入 <=t 事实 → 更新旧项目 → 当日六入口/证据/判断 → 决策压缩 → 三政策推进 → 原子冻结 t → 下一个交易日。

- [ ] **Step 1: 写阶段隔离测试**

`form` 不得导入 outcomes 或读取 `$ROOT/outcomes`；`reveal` 没有有效总 freeze receipt 必须拒绝；形成文件改一字节必须拒绝；前一日状态 hash 缺失时后一天不能运行。

- [ ] **Step 2: 写恢复测试**

中断后只能从最后一个完整且哈希正确的交易日继续；`.partial-*` 不可当成功；已冻结日期重复运行必须内容相同，否则标记 nondeterministic 并停止。

- [ ] **Step 3: 实现性能和磁盘遥测**

每阶段记录墙钟、CPU、峰值 RSS、缓存命中、模型调用/纠错数、读取分区、写入字节和 U 盘剩余空间。超过 15GB 软上限停止新增缓存并报告，不删除 U 盘其他文件。

- [ ] **Step 4: 运行执行器测试**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest/test_runner.py -q`  
Expected: PASS。  
Commit: `test: orchestrate continuous V3 backtest stages`。

### Task 10: 三连续日端到端预检、耗时外推和全测试门

**Files:**
- Runtime only: `$V3_BACKTEST_ROOT/preflight/three-day/`
- Runtime only: `$V3_BACKTEST_ROOT/preflight/runtime-estimate.json`

**Interfaces:**
- Consumes Tasks 1—9。
- Produces可信的 174 日耗时/空间估计和主运行允许回执。

- [ ] **Step 1: 运行完整测试集**

Run: `TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest tests/test_historical_framework_validation.py tests/test_research_historical_availability.py -q`  
Expected: 全部通过；工作区既有无关改动保持不变。

- [ ] **Step 2: 运行三个连续运营日**

日期固定为 `2025-10-30, 2025-10-31, 2025-11-03`，从空状态依次运行完整 `form`，包括六入口 manifest、证据包、判断、压缩和三政策；不揭示未来结果。

- [ ] **Step 3: 核验主运行门**

必须同时满足：严格同值回执 true；未来字段扫描为零；Mac 仓三指纹未变；三日状态链闭合；相同输入判断一致；U 盘写入正常；能力矩阵已冻结；任何 `partial` 都明确传播到报告标题。

- [ ] **Step 4: 计算有证据的外推**

将首次日、增量日、缓存命中、模型调用量分别外推到 174 日，不用简单三日平均掩盖冷启动。若超过一小时，先只优化重复读取、内容缓存和无状态安全并发，再重跑三日；不得减少日期、证据、政策或判断。

- [ ] **Step 5: 记录决定并提交代码状态**

运行前记录 `git rev-parse HEAD`、配置/设计/代码哈希和测试摘要到 U 盘。代码若有改动，精确暂存并提交 `test: preflight continuous V3 backtest`；不得提交运行数据。

### Task 11: 连续运行 174 个运营日并冻结形成产物

**Files:**
- Runtime only under `$V3_BACKTEST_ROOT/formation/`, `cache/`, `logs/`, `preflight/`。

**Interfaces:**
- Produces exactly 174 chained daily receipts and one formation freeze receipt。

- [ ] **Step 1: 顺序运行形成阶段**

批量快照/入口枚举可安全并发，但每个日期的旧项目更新、最终判断、压缩、三政策和状态冻结严格按交易日顺序。形成期不得运行 `reveal`、导入未来结果或计算未来收益。

- [ ] **Step 2: 每 10 日自动检查**

核验累计日期连续、六 manifest/日、三政策发现 hash 相同、状态父 hash、未来字段扫描、Mac 仓指纹、U 盘空间、模型失败和入口覆盖。失败立即停止并保留证据；不得静默跳日。

- [ ] **Step 3: 完成 144 日成熟形成和 30 日维护尾段**

维护尾段仍扫描、竞争和更新，不能简化成只看旧项目；尾部新项目标记 immature。主形成日 2026-06-04 项目必须运行到 2026-07-17。

- [ ] **Step 4: 原子冻结总形成清单**

验证 174 日文件、144 mature、30 tail、A—E 边界、项目链、策略链、基线成员和全部输入/提示/模型/知识哈希。写总 SHA-256 树并重新校验后，才生成 `formation-freeze-receipt.json`。

### Task 12: 冻结后揭示、统计、遗漏审计和普通语言报告

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/report.py`
- Create: `tests/evaluation/v3_backtest/test_report.py`
- Runtime only: `$V3_BACKTEST_ROOT/outcomes/`, `statistics/`, `reports/`。

**Interfaces:**
- Produces: `$V3_BACKTEST_ROOT/reports/v3-continuous-multiblock-backtest-results.md` 和机器可复算表。

- [ ] **Step 1: 写报告合同测试**

报告必须先写 `experiment_scope` 和 `full_v3_status`；若 partial，标题和总结必须含“部分覆盖回放”，完整 V3 结论只能 `not_executable`。每模块只取 `support_continue/failed/insufficient_evidence/not_testable`，不得合成总分。

- [ ] **Step 2: 揭示未来路径和对照**

重新验证形成哈希后，计算成熟样本 discovery/action/replacement/trade 的 10/20/30 日触及、首次触及、目标前最大不利、先目标/先回撤、期末、相对市场/行业，以及全市场、匹配、热点、业绩和价格基线。

- [ ] **Step 3: 评价五个问题**

逐项报告十只压缩、重点与两类候补、替换、生命周期、完整机制。A—E 分块、全区间、冷启动含/不含、行业/主题集中和 10/20/30 块长敏感性必须并列展示；不能只展示最好版本。

- [ ] **Step 4: 做代表性遗漏和失败审计**

只审计当日热点同类、内部最强挑战者、被容量/替换淘汰者，以及后来触及且当时有真实因果证据的代表股票。分类为入口漏扫、时点不可得、公司传导、机会误判、价格消耗、风险反证、支配比较、共同暴露、容量或模型错误；后来上涨不能倒造当时理由。

- [ ] **Step 5: 输出普通语言结论**

先回答“哪些能执行、哪些不能”；再回答五个机制问题；最后列漏洞、影响和建议验证方向。不得将盘中触及称为可实现收益或准确率，不修改临时框架。

- [ ] **Step 6: 最终复算和零写入验收**

从 Parquet/JSON 独立重算报告关键表；校验所有哈希；比较 Mac 仓 before/after 指纹；记录 U 盘最终空间。运行：

```bash
TMPDIR="$V3_BACKTEST_ROOT/tmp" .venv/bin/pytest tests/evaluation/v3_backtest -q
git diff --check
```

Expected: 测试通过、Mac 仓三指纹完全一致、报告数字可由机器表复算。

## 故障关闭条件

以下任一情况立即停止主运行并保留证据，不继续拼出漂亮结果：

- 相对形成日读取了未来 `available_at`、未来关系、未来价格、结果标签或替换反事实；
- 批量快照在三个真实日期或合成时点边界与严格单日路径任何值不一致；
- 运营日不是 174、成熟形成日不是 144、维护尾段不是 30，或 6 月 4 日没有完整未来 30 日；
- 任一日期缺六入口 manifest 却生成候选；
- 不 ready 的机会卡、无正文经济事实的公告或 internal-only 价格/热点线索进入十只；
- 同输入的候选集合、主要机会、层级或决定性比较不稳定；
- 三政策使用了不同发现流，或生命周期为并发而乱序；
- Mac 数据仓任一指纹变化，或实际回测数据写到 U 盘之外；
- 形成文件/总清单哈希不一致，或 freeze 前出现 future/outcome 字段；
- `experiment_scope=partial` 却输出完整 V3 支持结论。

结构性入口不可执行本身不停止局部回放：它必须强制 `partial/not_executable`，继续评价实际可执行模块并把不能验证的模块记为 `not_testable`。

## 并行和所有权

- 主执行者独占日历、合同集成、判断协议、逐日压缩、生命周期、总执行器和最终结论。
- 可把互不共享状态的“批量快照/同值门”和“结果/统计/报告测试”交给不同子智能体；各自只改明确文件，主执行者复核后合并。
- 不允许按日期把主观判断分给多个智能体；这会混入不同口径。
- 不允许两个执行者同时修改 `contracts.py`、`decision.py`、`lifecycle.py` 或 `runner.py`。
- 所有并行产物必须通过相同配置哈希、代码哈希和输入哈希合并；最终状态推进永远单线程按日期。

## 计划自检

- **设计覆盖：** Tasks 1—3 覆盖样本、USB、能力和同值效率；Tasks 4—7 覆盖结构判断、三阶段压缩、生命周期和基线；Tasks 8—9 覆盖冻结、评价合同和执行器；Tasks 10—12 覆盖预检、174 日形成、揭示、统计和报告。
- **边界覆盖：** 双时钟、144/30 分离、partial 先行否决、三政策不同估计单位、真实决策日聚类、FAT 哈希冻结和 Mac 零克隆均有测试与停止门。
- **无占位内容：** 所有日期、路径、枚举、排序、放宽次序、命令和预期状态已冻结；没有结果揭示后再选规则的接口。
- **类型一致：** `BacktestCalendar`、`CapabilityReceipt`、`FormationSnapshot`、`DecisionReceipt`、`DailyLifecycleReceipt`、`ControlMembershipReceipt` 和 `FormationFreezeReceipt` 在首次产生任务定义，后续只消费不改名。
- **执行方式已选定：** 用户已授权直接执行，并允许在不影响结果时使用子智能体；因此本计划完成后采用“主执行者顺序控制 + 独立模块子智能体”的方式执行，不再请求执行选择。
