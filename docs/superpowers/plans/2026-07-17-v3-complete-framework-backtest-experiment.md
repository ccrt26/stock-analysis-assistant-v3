# V3 完整候选机制历史回测实验实施计划

> **当前状态权威：** 本计划只定义一次隔离、可审计的验证实验，不证明当前生产能力；当前生产状态只以 `docs/operations/production-capability-matrix.md` 为准。
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改数据底座、不激活报告、不继承旧 Phase 3 评分的前提下，对 V3 的六入口发现、最终十只压缩、重点/候补分层、每日挑战者替换和 1—6 周项目生命周期做一次覆盖 191 个逐日形成日的严格历史实验。

**Architecture:** 实验分成“形成期”和“结果期”两个物理阶段。形成期只读取每个交易日收盘前已经可得的事实，依次生成六入口扫描清单、研究池、证据包、最多十只有效候选、最多五只重点、项目状态和三套名单政策；形成产物连同文件哈希提交后，结果期才允许读取未来 10/20/30 个交易日行情。主样本为 2025-10-30 至 2026-06-03 的 143 个可比形成日，2025-08-15 至 2025-10-29 的 48 个有限覆盖形成日单独报告，不与主样本合并命中率。

**Tech Stack:** Python 3.12、pandas、DuckDB、PyArrow、Pydantic、现有 `ResearchWarehouse`/`ResearchQuery`/治理后派生公式、Codex CLI 的隔离结构化输出、pytest、Parquet、JSON 和 Markdown。

## Global Constraints

- 直接使用当前本地 `main`，不创建分支或工作树。
- 本计划是独立验证实验，不修改 `docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`，除非实验结束后用户明确要求把已确认结论回写框架。
- 不修改 `local_warehouse/facts`、`local_warehouse/derived`、`research.duckdb` 或生产清单；所有派生回放写入 `/tmp/v3-complete-backtest-*`，长期实验产物写入 `local_archive/experiments/2026-07-17-v3-complete-backtest/`。
- 不增加数据源，不重建数据底座，不生成正式日报，不激活、不部署、不调用发布链。
- 每个形成日的截止时间固定为北京时间 `23:59:59`；所有事实必须通过严格 `available_at <= cutoff`，分类关系还必须满足当日有效区间。
- 当前快照型 `security_master`、`company_profile` 和无历史发布时间的 `pledge` 在历史形成日不可见时必须 fail closed；不得用今天的信息倒填。
- 历史分钟数据缺失、部分主题无公开成分、公告正文无法自动取得时必须记录限制；不得用标题、成交结果或模型常识补造事实。
- 只允许调用 `research_registry.yaml` 中状态为 `current` 的 27 项知识，并按候选场景选择；`historical_only`、暂缓和退出知识不可调用。
- 六入口只负责召回，不投票、不加分；每个候选只允许一个主要机会来源和最多一个辅助因素。
- 最多十只、最多五只都是注意力上限，不是必须填满的配额；无法形成决定性比较时减少名单。
- 成交、放量、上涨和收盘位置只描述交易结果；禁止推断机构、主力、吸筹或出货。
- 当前实验验证候选机制，不定义买入价、卖出价、仓位、交易成本、策略净值或夏普比率。
- 历史时期已经参与设计，结果只能称为设计样本/历史初证；无论结果多好，都不能替代规则冻结后的连续真实日报。

## 实验问题与预先冻结的判定顺序

实验分别回答五个问题，不合成总分：

1. 最终十只是否相对同日全市场、同日期同上市板块匹配样本、热点优先、业绩优先和简单价格基线提高目标发现与提前量；
2. 重点层是否在目标触及、目标前回撤、期末表现和不同时间块上优于 `early_validation` 与 `high_elasticity_tracking`；
3. 滚动竞争是否相对首批固定和每日重置减少遗漏或无效占位，并且挑战者相对被替代者产生配对增量；
4. 项目状态机是否能在第 1—2 周清理证据失败项目、目标触及时释放名额、第 30 个交易日强制结束，而不过度抖动；
5. 完整机制的结果是否不依赖单一月份、行业或少数极端股票，并在 10/20/30 日、先回撤 5%/10% 和连续时间块不确定性下方向一致。

固定执行顺序为：数据时点 → 六入口扫描 → 合并去重 → 硬边界 → 唯一主要机会 → 分类型证据卡 → 选择命题 → 同类支配比较 → 共同暴露 → 十只上限 → 重点/候补 → 旧项目与挑战者竞争 → 状态冻结。任何执行器不得改换顺序。

## 样本、时间块和统计单位

- **主样本：** 2025-10-30 至 2026-06-03，共 143 个连续交易日。起点是 2025-07-31 主题成分历史后的第 60 个交易日，使热点公式的 20/60 日参与面具有可比基础；终点保证当天新项目到 2026-07-16 仍有完整 30 个未来交易日。
- **主样本块 A：** 2025-10-30 至 2026-01-07，48 个形成日。
- **主样本块 B：** 2026-01-08 至 2026-03-24，48 个形成日。
- **主样本块 C：** 2026-03-25 至 2026-06-03，47 个形成日。
- **有限覆盖扩展：** 2025-08-15 至 2025-10-29，48 个形成日。主题成分历史不足 60 个交易日的观察必须标记 `limited_theme_history`，结果单列。
- **评价单位：** 主要单位是不可倒改的候选项目，不是“股票×每日”；每日状态行只评价管理过程，不能当作独立预测增加样本量。
- **发现基准：** 项目首次进入有效十只当天的复权收盘。
- **行动基准：** 项目首次升为重点当天的复权收盘。
- **替换基准：** 挑战者与被替代者共同使用替换日复权收盘，并在相同剩余期限比较。

## 文件结构

### 新建实验代码

- `src/stock_analyzer/evaluation/v3_backtest/contracts.py`：实验枚举、Pydantic 合同、项目与状态记录。
- `src/stock_analyzer/evaluation/v3_backtest/calendar.py`：形成日、时间块、成熟日和窗口验证。
- `src/stock_analyzer/evaluation/v3_backtest/snapshots.py`：严格 as-of 快照和隔离派生缓存。
- `src/stock_analyzer/evaluation/v3_backtest/routes.py`：六入口枚举、去重和 `route_scan_manifest`。
- `src/stock_analyzer/evaluation/v3_backtest/evidence.py`：候选事实包、知识路由、事实/观察/判断分层。
- `src/stock_analyzer/evaluation/v3_backtest/judge.py`：冻结提示、结构化 Codex 调用、模式校验和重试审计。
- `src/stock_analyzer/evaluation/v3_backtest/decision.py`：硬边界、选择命题、支配比较、共同暴露和分层。
- `src/stock_analyzer/evaluation/v3_backtest/lifecycle.py`：首批固定、每日重置和滚动竞争三套状态机。
- `src/stock_analyzer/evaluation/v3_backtest/freeze.py`：形成产物写入、哈希、无未来字段审计和提交清单。
- `src/stock_analyzer/evaluation/v3_backtest/outcomes.py`：复用并扩展现有未来路径计算。
- `src/stock_analyzer/evaluation/v3_backtest/statistics.py`：基础率、匹配对照、配对替换、时间块区间和遗漏复盘。
- `src/stock_analyzer/evaluation/v3_backtest/runner.py`：`preflight`、`form`、`freeze`、`reveal`、`report` 五个显式阶段。

### 新建测试

- `tests/evaluation/v3_backtest/test_contracts.py`
- `tests/evaluation/v3_backtest/test_calendar.py`
- `tests/evaluation/v3_backtest/test_snapshots.py`
- `tests/evaluation/v3_backtest/test_routes.py`
- `tests/evaluation/v3_backtest/test_evidence.py`
- `tests/evaluation/v3_backtest/test_judge.py`
- `tests/evaluation/v3_backtest/test_decision.py`
- `tests/evaluation/v3_backtest/test_lifecycle.py`
- `tests/evaluation/v3_backtest/test_freeze.py`
- `tests/evaluation/v3_backtest/test_outcomes.py`
- `tests/evaluation/v3_backtest/test_statistics.py`
- `tests/evaluation/v3_backtest/test_runner.py`

### 实验配置与产物

- `docs/superpowers/specs/2026-07-17-v3-complete-backtest-freeze.md`：人类可读的预登记和限制。
- `docs/superpowers/specs/2026-07-17-v3-complete-backtest-config.yaml`：机器可读的日期、窗口、模型和提示哈希。
- `local_archive/experiments/2026-07-17-v3-complete-backtest/formation/*.parquet`：只含形成信息的全量产物。
- `local_archive/experiments/2026-07-17-v3-complete-backtest/outcomes/*.parquet`：冻结后揭示的未来路径。
- `local_archive/experiments/2026-07-17-v3-complete-backtest/manifests/*.json`：输入、输出、提示、模型、知识和文件哈希。
- `docs/superpowers/specs/2026-07-17-v3-complete-backtest-results.md`：完整结果、失败和结论。

---

### Task 1: 预登记实验配置和不可混用的样本边界

**Files:**
- Create: `docs/superpowers/specs/2026-07-17-v3-complete-backtest-freeze.md`
- Create: `docs/superpowers/specs/2026-07-17-v3-complete-backtest-config.yaml`
- Test: `tests/evaluation/v3_backtest/test_calendar.py`

**Interfaces:**
- Consumes: `trade_calendar`、`equity_daily` 的实际截止日和本计划冻结日期。
- Produces: `BacktestCalendar(primary, extension, blocks, maturity_end)`，后续任务不得自行选择日期。

- [ ] **Step 1: 写日期生成的失败测试**

```python
def test_frozen_calendar_has_143_primary_and_48_extension_origins(open_sessions):
    calendar = build_frozen_calendar(open_sessions, data_end=date(2026, 7, 16))
    assert calendar.primary[0] == date(2025, 10, 30)
    assert calendar.primary[-1] == date(2026, 6, 3)
    assert tuple(map(len, calendar.blocks)) == (48, 48, 47)
    assert len(calendar.extension) == 48
    assert calendar.maturity_end == date(2026, 7, 16)
```

- [ ] **Step 2: 运行 RED**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_calendar.py -v`  
Expected: FAIL，原因是 `build_frozen_calendar` 尚不存在。

- [ ] **Step 3: 写机器配置**

配置必须明确 `target_return: 0.20`、`horizons: [10, 20, 30]`、`drawdown_sensitivities: [0.05, 0.10]`、主样本和扩展样本日期、三个固定时间块、`facts_as_of: strict_available_at`、允许知识状态 `current`、候选上限 10、重点上限 5。不得写命中率通过线。

- [ ] **Step 4: 实现并验证日期生成**

实现只允许根据交易日历验证配置，不允许扫描收益或热点后调整日期。运行同一测试，Expected: PASS。

- [ ] **Step 5: 提交预登记**

Run: `git diff --check`，然后提交 `docs: freeze complete V3 backtest experiment`。该提交发生在任何主样本未来结果查询之前。

### Task 2: 建立实验合同，禁止把事实、观察和判断混写

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/__init__.py`
- Create: `src/stock_analyzer/evaluation/v3_backtest/contracts.py`
- Test: `tests/evaluation/v3_backtest/test_contracts.py`

**Interfaces:**
- Produces: `DiscoveryRoute`、`OpportunityType`、`CandidateLayer`、`ProjectState`、`EvidenceRef`、`SelectionProposition`、`CandidateProject`、`DailyDecision`、`RouteScanManifest`。

- [ ] **Step 1: 写合同失败测试**

测试以下违规均被 Pydantic 拒绝：六入口之外的 route；主要机会来源为“热点”或“价格异常”；候选没有形成日或失效条件；重点候选没有行动基准；一只项目有两个主要机会来源；观察项占用十只名额；判断文本引用不存在的 `evidence_id`。

- [ ] **Step 2: 实现枚举和最小合同**

```python
class DiscoveryRoute(StrEnum):
    HOTSPOT = "hotspot"
    EARNINGS = "earnings"
    COMPANY_EVENT = "company_event"
    INDUSTRY_CYCLE = "industry_cycle"
    DISTRESS_REPAIR = "distress_repair"
    PRICE_ANOMALY = "price_anomaly"

class CandidateLayer(StrEnum):
    INTERNAL = "internal"
    EARLY_VALIDATION = "early_validation"
    HIGH_ELASTICITY = "high_elasticity_tracking"
    FOCUS = "focus"
```

`EvidenceRef` 必须含 `evidence_id`、`kind`（`api_fact/local_observation/model_judgment`）、`dataset`、`business_time`、`available_at`、`input_hash`。用户语言不得存入此合同。

- [ ] **Step 3: 运行合同测试**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_contracts.py -v`  
Expected: 所有合法/非法样例通过。

- [ ] **Step 4: 提交**

Commit: `test: define complete V3 backtest contracts`。

### Task 3: 构建严格 as-of 快照和隔离派生缓存

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/snapshots.py`
- Test: `tests/evaluation/v3_backtest/test_snapshots.py`
- Use unchanged: `src/stock_analyzer/ops/research_features.py`
- Use unchanged: `src/stock_analyzer/storage/research_query.py`

**Interfaces:**
- Produces: `materialize_formation_snapshot(warehouse, origin, temp_root) -> FormationSnapshot`。
- `FormationSnapshot` 只包含 `available_at <= origin 23:59:59 Asia/Shanghai` 的事实和由这些事实复算的三类观察。

- [ ] **Step 1: 写未来事实和修订泄漏失败测试**

用同一业务键的两版财务事实证明：形成日只能看到当时版本；未来 `valid_from` 关系不可见；未来才知道的 `valid_to` 不提前泄漏；`company_profile` 和 `pledge` 在 ingestion cutoff 前为空。

- [ ] **Step 2: 写生产仓零写入测试**

运行单日回放前后递归计算 `local_warehouse/facts`、`local_warehouse/derived` 和 `research.duckdb` 指纹，断言完全相同；所有新文件只能位于传入的 `temp_root`。

- [ ] **Step 3: 实现隔离快照**

复用 `ResearchQuery` 和 `run_research_features`，将 DuckDB 元数据复制到独立临时根并只读链接事实分区；派生结果写入临时根。缓存键固定为 `origin + as_of + fact_manifest_hash + formula_versions`，旧公式缓存不得命中。

- [ ] **Step 4: 做三日严格烟雾测试**

固定日期 `2025-10-30`、`2026-01-08`、`2026-06-03`。每一天必须产生 market、sector 和 stock 三类结果；允许已知分钟和主题成分缺口，但任何核心数据失败立即停止。

- [ ] **Step 5: 运行并提交**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_snapshots.py tests/test_research_historical_availability.py -v`  
Commit: `test: add strict isolated formation snapshots`。

### Task 4: 对六入口做全量扫描，而不是代表案例抽查

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/routes.py`
- Test: `tests/evaluation/v3_backtest/test_routes.py`

**Interfaces:**
- Produces: `scan_routes(snapshot, window_policy) -> tuple[RouteScanManifest, ...]` 和去重后的 `ResearchHypothesis`。

- [ ] **Step 1: 写六入口完整性测试**

每个形成日必须恰好有六条 manifest；每条记录截止时间、请求和实际分区、应扫与实扫记录数、触发数、去重数、缺失、排除和人工边界。热点必须先枚举全部有效行业和受控主题；业绩必须扫描声明报告期内全部可得预告/快报/定期报告；事件必须枚举声明窗口内全部正式公告；价格必须从全市场可交易证券开始。

- [ ] **Step 2: 写“不准投票”测试**

同一股票由三入口发现时只生成一个研究假设；保留三个 route 和证据，但没有 `route_score`、`vote_count` 或额外优先级。

- [ ] **Step 3: 实现入口枚举和高召回触发**

触发条件只能来自框架第 6.2 节的最少输入与准入：热点要求可复算共同变化和可追溯关系；业绩要求当时可见的新增经营信息；事件要求正式公开且直接相关；周期要求产业事实和公司敏感度线索；修复要求风险缓解与多表改善线索；价格要求相对市场/行业的异常并触发原因调查。没有完整周期事实的项目仍可进入内部核查，但不得预标为周期拐点。

- [ ] **Step 4: 固定公告深读边界**

公告标题只用于召回。缺少正文、金额、主体或执行条件时生成 `needs_deep_read`，不允许模型把标题解释成经济重要性。每个形成日记录待深读数量和实际完成数量；未完成的候选不能进入十只。

- [ ] **Step 5: 运行并提交**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_routes.py -v`  
Commit: `test: enumerate all six historical discovery routes`。

### Task 5: 生成候选证据包并按场景调用正式知识

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/evidence.py`
- Test: `tests/evaluation/v3_backtest/test_evidence.py`
- Use unchanged: `src/stock_analyzer/knowledge/research_registry.yaml`

**Interfaces:**
- Produces: `build_candidate_packet(snapshot, hypothesis, registry) -> CandidateEvidencePacket`。

- [ ] **Step 1: 写知识治理测试**

断言只读取 `current` 知识；每个候选记录实际调用和不适用的知识；不能机械附加全部 27 项；任何 `historical_only` 引用使形成日失败。

- [ ] **Step 2: 写证据分层测试**

API 原始事实、本地公式观察和模型判断分别存储；模型输出不能覆盖事实字段；用户表达不进入实验输入。所有数字必须引用 `evidence_id`。

- [ ] **Step 3: 实现统一证据包**

证据包包含市场约束、热点全景、业务传导、五类机会所需事实、财务质量、估值语境、公司事件、价格/成交/流动性、最近事实后的价格反应、当前价格到目标所需条件、反证、未知和下一项验证事实。缺失字段显式写 `not_available_as_of`，不自动补齐。

- [ ] **Step 4: 运行并提交**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_evidence.py -v`  
Commit: `test: build governed candidate evidence packets`。

### Task 6: 冻结一个一致的结构化判断器

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/judge.py`
- Create: `src/stock_analyzer/evaluation/v3_backtest/prompts/v3_backtest_judge_v1.txt`
- Test: `tests/evaluation/v3_backtest/test_judge.py`
- Reuse process isolation pattern only: `src/stock_analyzer/ops/codex_expression_client.py`

**Interfaces:**
- Produces: `FrozenDecisionJudge.judge(day_packet) -> DailyJudgmentBatch`。
- 不复用旧 Phase 3 的 prompt、decision lock、分数、权重或推荐结论。

- [ ] **Step 1: 写结构化输出测试**

判断器必须为每个进入比较层的候选输出：唯一主要机会、辅助因素、选择命题七部分、适用知识、决定性优势、反证、未知、下一事实、失效条件、建议层级和引用证据。禁止输出分数、概率、机构身份和无证据数字。

- [ ] **Step 2: 写提示泄漏测试**

prompt 中不得出现形成日后的日期、价格、结果字段、已知赢家或“后来”。输入 schema 不包含 future high/low/close。输出引用未提供证据时校验失败。

- [ ] **Step 3: 实现固定模型调用**

使用 Codex CLI `exec --ephemeral --ignore-user-config --sandbox read-only --output-schema`；模型名、reasoning effort、CLI 版本、prompt SHA-256、schema SHA-256 和完整输入哈希写入每次回执。每个形成日只允许一个主判断批次；校验失败最多一次纠正，失败后该日 fail closed，不静默降级为规则评分。

- [ ] **Step 4: 做一致性审计**

在三个烟雾日期各重复两次相同输入。股票集合、主要机会、层级和决定性比较出现不一致时，记录不稳定并停止主回测；不能从两次输出中选择更符合未来结果的一次。

- [ ] **Step 5: 运行并提交**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_judge.py -v`  
Commit: `test: freeze structured V3 backtest judgment`。

### Task 7: 实现无总分的十只压缩和重点/候补分层

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/decision.py`
- Test: `tests/evaluation/v3_backtest/test_decision.py`

**Interfaces:**
- Produces: `compress_research_pool(packet, judgments, incumbents) -> DailyDecision`。

- [ ] **Step 1: 写固定顺序测试**

断言执行顺序为：硬边界 → 唯一选择命题 → 同类/同角色支配比较 → 共同暴露 → 注意力上限 → 重点行动检查。任何阶段失败都保留明确原因，不生成隐藏低分。

- [ ] **Step 2: 写不凑数测试**

只有 7 只有效候选时输出 7 只；只有 2 只具备当前行动价值时输出 2 只重点；不能把内部观察或缺失公告正文的股票填入候补。

- [ ] **Step 3: 写支配和共同暴露测试**

同一风险簇中没有独立驱动的重复公司被淘汰；强势龙头和均衡候选若承担不同角色可以并存；不能为表面分散加入证据较弱股票。每次淘汰保存决定性事实和最强未入选挑战者。

- [ ] **Step 4: 实现分层**

重点要求因果链、当前新增驱动、价格未完全消耗、路径风险、下一事实和失效条件均可表达。`early_validation` 明确缺哪项确认；`high_elasticity_tracking` 明确为何仍可能冲高但今天不占重点名额。

- [ ] **Step 5: 运行并提交**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_decision.py -v`  
Commit: `test: compress V3 research pool without scores`。

### Task 8: 在同一发现流上运行三套名单政策和项目生命周期

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/lifecycle.py`
- Test: `tests/evaluation/v3_backtest/test_lifecycle.py`

**Interfaces:**
- Produces: `FixedInitialPolicy`、`DailyResetPolicy`、`RollingCompetitionPolicy`，三者消费同一个 `DailyDiscoveryFrame`。

- [ ] **Step 1: 写项目身份测试**

连续多日同一股票、同一主要机会仍是一项项目；原项目结束后只有新事实、新价格和新失效条件齐全才可建立新项目。升级为重点时另建行动基准，不改写发现基准。

- [ ] **Step 2: 写替换配对测试**

单日上涨、成交放大、旧候选当天未涨、名单需要变化均不能触发替换。替换必须记录挑战者、被替代者、共同收盘基准、剩余期限、决定性事实和共同风险。

- [ ] **Step 3: 写时间状态测试**

第 1 周更新验证任务；第 2 周缺少原定确认时降级/退出；第 3—4 周为兑现；第 5—6 周只在原逻辑仍成立且有第二波确认时继续；目标触及、硬失效或第 30 日立即结束。第 31 日沿用旧项目必须失败。

- [ ] **Step 4: 实现三政策共享发现流**

首批固定只在失效/目标/到期退出；每日重置不继承旧状态；滚动竞争允许继续、升级、降级、替换和退出。三者不得重新运行不同的六入口或不同模型判断。

- [ ] **Step 5: 运行并提交**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_lifecycle.py -v`  
Commit: `test: add paired V3 candidate lifecycle policies`。

### Task 9: 冻结形成产物，阻断任何提前揭示

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/freeze.py`
- Test: `tests/evaluation/v3_backtest/test_freeze.py`
- Create at execution: `local_archive/experiments/2026-07-17-v3-complete-backtest/formation/*.parquet`
- Create at execution: `local_archive/experiments/2026-07-17-v3-complete-backtest/manifests/formation-freeze.json`

**Interfaces:**
- Produces: `freeze_formation_run(run) -> FormationFreezeReceipt`。

- [ ] **Step 1: 写禁止结果字段测试**

形成目录中出现 `future`、`target_touched`、`terminal_return`、`max_favorable`、`outcome` 或形成日后价格列时冻结失败。

- [ ] **Step 2: 写完整性测试**

主样本必须正好 143 个形成日，扩展样本正好 48 个；每日至少有六条扫描 manifest 和三套政策状态；每个候选、判断、替换和退出都能追溯到事实、公式、知识、prompt、model 和输入哈希。

- [ ] **Step 3: 实现原子冻结和哈希树**

先写 staging，逐文件计算 SHA-256，生成 Merkle 风格清单和行数/业务键审计，再原子重命名。冻结回执包含仓库 HEAD、事实清单哈希、配置哈希、代码哈希和模型回执哈希。

- [ ] **Step 4: 在结果查询前提交冻结回执**

`git diff --check` 后提交人类可读冻结说明和小型清单，commit message: `docs: freeze complete V3 historical formations`。只有提交成功后 runner 才允许 `reveal`。

### Task 10: 揭示路径结果并计算五类独立评价

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/outcomes.py`
- Create: `src/stock_analyzer/evaluation/v3_backtest/statistics.py`
- Test: `tests/evaluation/v3_backtest/test_outcomes.py`
- Test: `tests/evaluation/v3_backtest/test_statistics.py`
- Reuse: `src/stock_analyzer/evaluation/historical_framework_validation.py`

**Interfaces:**
- Produces: `evaluate_frozen_projects()`、`compare_layers()`、`compare_replacements()`、`summarize_occupancy()`、`stationary_block_interval()`、`audit_representative_misses()`。

- [ ] **Step 1: 扩展未来路径测试**

分别计算发现基准、行动基准和替换基准下的 10/20/30 日盘中最高、最低、期末、首次触及、先目标还是先回撤 5%/10%、相对市场和相对行业。停牌日按市场交易日计时，中间无报价沿用上一收盘，期末仍无报价记不完整。

- [ ] **Step 2: 写基础率和匹配测试**

同日全市场基础率和同日期同上市板块匹配样本不得用未来结果选择。热点、业绩和价格透明基线必须使用相同证券范围、形成日和未来口径。

- [ ] **Step 3: 写重点/候补和替换配对测试**

重点与候补从各自冻结基准比较；每次替换同时计算挑战者与被替代者，报告触及、提前量、期末和回撤差。挑战者单独上涨不能算替换成功。

- [ ] **Step 4: 写占位、稳定和遗漏测试**

统计失效后继续占位天数、目标后占位天数、过早退出、每日新增/升级/降级/替换/退出、名单保留率、行业/主题共同暴露。遗漏只复核当日达到目标且满足当日基本可交易条件的代表股票，并按入口漏扫、证据缺失、比较失败或容量限制分类。

- [ ] **Step 5: 写时间依赖不确定性测试**

固定 stationary bootstrap 平均块长度敏感性为 5、10、20 个交易日，固定随机种子集合并同时报告三个结果；不得在看过结果后只保留最有利块长。主样本三个连续块分别报告，扩展样本不并入总体区间。

- [ ] **Step 6: 运行并提交**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest/test_outcomes.py tests/evaluation/v3_backtest/test_statistics.py tests/test_historical_framework_validation.py -v`  
Commit: `test: evaluate frozen V3 candidate mechanisms`。

### Task 11: 先小规模端到端验收，再运行 191 个形成日

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_backtest/runner.py`
- Test: `tests/evaluation/v3_backtest/test_runner.py`

**Interfaces:**
- CLI stages: `preflight`、`form --origins`、`freeze`、`reveal`、`report`。`reveal` 必须验证冻结提交和哈希。

- [ ] **Step 1: 写阶段隔离测试**

`form` 无法导入 outcomes 模块或读取未来目录；没有 freeze receipt 时 `reveal` 必须拒绝；形成文件发生一字节变化时 `reveal` 必须拒绝。

- [ ] **Step 2: 运行三日端到端烟雾实验**

使用 `2025-10-30`、`2026-01-08`、`2026-06-03`，只验证执行完整性，不根据结果调规则。任何入口未扫描、判断不稳定、状态无法复现、生产仓发生写入或证据引用断裂，都停止全量运行。

- [ ] **Step 3: 全量形成阶段**

先运行 143 个主样本日，再运行 48 个扩展样本日；每天按时间顺序提交状态。允许并行预计算只读快照和无状态入口枚举，但最终 `DailyDecision` 与三套生命周期必须严格按交易日单线程推进。

- [ ] **Step 4: 冻结后再揭示**

确认形成清单提交和工作树状态后，执行未来路径读取。若任何结果字段在冻结前已经出现在日志、prompt 或缓存，整批实验作废并重新建立新实验编号。

- [ ] **Step 5: 完整回归**

Run: `.venv/bin/pytest tests/evaluation/v3_backtest tests/test_historical_framework_validation.py tests/test_research_historical_availability.py -q`  
Expected: 全部通过；没有生产事实、派生和运行配置变化。

### Task 12: 写完整结果，不把“触及”包装成准确率

**Files:**
- Create: `docs/superpowers/specs/2026-07-17-v3-complete-backtest-results.md`
- Do not modify: `docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`
- Do not modify: `docs/operations/production-capability-matrix.md`

**Interfaces:**
- Produces: 用户能够理解、数字可复算、失败案例完整的实验报告。

- [ ] **Step 1: 报告数据和执行完整性**

列出 191 个形成日完成数、六入口应扫/实扫、缺失、模型失败、深读边界、候选项目数、每日状态数、哈希和生产仓零写入证明。主样本与扩展样本分开。

- [ ] **Step 2: 按五个问题分别给结论**

分别报告最终十只、重点/候补、替换、生命周期和完整 V3 为“支持继续、证据不足或失败”。不得用一个总命中率覆盖某一层失败。

- [ ] **Step 3: 同时报告目标和路径**

展示 10/20/30 日触及、期末、目标前回撤、先目标/先回撤、提前发现、错误占位、名单变化、共同暴露、三个时间块和代表性遗漏。平均数和中位数同时出现，避免极端上涨拉高均值。

- [ ] **Step 4: 明确下一道门**

即使历史结果较好，只允许建议进入正式实施计划和连续真实冻结；重点不优于候补、滚动不优于对照、替换总体为负、扫描不完整或判断不可复现时，明确返回设计，不进入生产实现。

本轮只报告漏洞、影响和建议方向，不修改分析框架，不编写后续执行设计，不修复生产代码，不激活或部署。是否修正由用户在新的任务中决定。

- [ ] **Step 5: 最终验证和提交**

重新从 Parquet 计算报告全部表格；运行 `git diff --check`、实验测试集和生产仓指纹审计；提交 `test: report complete V3 historical backtest`。

## 停止条件

出现以下任一情况立即停止，不继续跑完后再淡化：

- 形成日看到未来 `available_at`、未来关系或未来价格；
- 主样本不是 143 日、扩展样本不是 48 日，或 6 月 3 日没有完整 30 日未来窗口；
- 任一日期缺少六入口扫描 manifest，却仍生成十只；
- 公告标题在无正文经济证据时直接进入十只；
- 判断器对相同输入的股票集合、主要机会或层级不稳定；
- 不同名单政策使用不同发现流；
- 滚动状态为了并行而乱序；
- 生产事实、派生、数据库、任务或报告发生写入；
- 形成冻结前读取、缓存或提示中出现未来结果；
- 结果文件或形成文件哈希与冻结回执不一致。

## 速度与并行执行边界

执行时间分成四类：

1. 严格快照和派生复算可按日期并行，并缓存相同事实窗口；
2. 六入口枚举和候选证据包在快照冻结后可按日期并行；
3. 最终十只、层级、挑战者和生命周期依赖前一交易日，必须按时间单线程推进；
4. 冻结后的未来路径、统计表和独立复核可以并行。

子智能体不得各自负责一段日期并独立做主观选股，因为这会把不同判断口径混入时间序列；也不得同时修改同一状态机文件。安全用法是：一个主执行者拥有合同、判断协议和顺序状态机；其他智能体分别实现/审查快照与入口、未来结果与统计、测试与哈希审计，在任务边界提交后由主执行者逐项复核。

2026-07-17 已用生产事实的写时复制元数据和只读事实链接完成一次隔离性能基准：`2025-10-30` 单日严格复算耗时 179.362 秒，产生 1 条市场、685 条行业/主题和 5,431 条个股观察，三类特征均无失败。191 日若完全单线程，仅派生复算约需 9.5 小时；三路无状态预计算的理论下限约 3.2 小时，考虑磁盘竞争、缓存、失败重试和合并审计，计划按 4—5 小时估计特征阶段。逐日结构化判断、生命周期、冻结、揭示和复核另计，完整实验不能承诺在 30 分钟内完成。

实际执行采用一个主执行者控制合同、判断协议、逐日十只和生命周期；最多三个子智能体只承担互不共享主观判断的独立工作：严格快照/入口模块、结果/统计模块、测试/哈希审计。特征日期可由三个隔离临时根分片预计算，合并后必须逐日验证输入哈希；主判断和三套名单状态仍按交易日单线程推进。回测结束后立即停止在结果汇报，不继续修改框架、设计后续实施或编写修复代码。
