# V3 Targeted Knowledge Gap Fill Implementation Plan

> **当前状态权威：** 本计划只实施知识治理、只读历史验证和正式知识登记，不证明分析器、报告或生产能力已经启用；当前状态只以 [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md) 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task, `superpowers:test-driven-development` before implementation code, and `superpowers:verification-before-completion` before any completion claim. The user explicitly authorized inline execution on local `main`; do not use subagents, a branch, a worktree, activation or deployment.

**Goal:** 修正三项已丢弃知识仍可调用的登记漏洞，用当前统一研究仓直接验证四项定向补缺知识，只有来源和本地执行都成立的候选才进入正式知识登记，并在不增加数据源、不建立评分器的前提下补强现有热点与因子治理边界。

**Architecture:** 新建一个小型、专用的 `targeted_gap_validation.py`，只包含四项候选合同、四组纯观察公式、三个只读加载入口和一个确定性验证入口。它不复用或扩展成通用实验运行器，不自动作出 `use/discard` 决定。科学裁决单独写入一份恰含四项的 YAML；正式登记只读取已裁决为 `use` 的候选。三项历史知识通过 `historical_only` 与选择器显式过滤形成双重保护。

**Tech Stack:** 项目现有 Python 3.11+、pandas、DuckDB、Pydantic、PyYAML、pytest；不增加依赖。

**Approved Design:** [`docs/superpowers/specs/2026-07-15-v3-targeted-knowledge-gap-fill-design.md`](../specs/2026-07-15-v3-targeted-knowledge-gap-fill-design.md)

## 1. 冻结范围与禁止事项

- 工作目录固定为 `/Users/ccrt/Documents/股票分析助手`，直接使用当前本地 `main`，不创建分支或工作树。
- 计划基线提交为 `ec45b888b9240c216524ee8f4f8104ad06209846`；实施开始时必须重新记录实际 HEAD 和工作区状态。
- 本轮开始时 `local_warehouse/research.duckdb` SHA-256 为 `57b2adb1cbf4d00eb30cae8f2511e8818655864d1ecf8d15dbeac9c404999b73`。由于外部定时任务可能更新仓库，每一次本轮只读验证函数必须自行在调用前后比较同一文件哈希；不能只依赖跨数小时的全局哈希。
- 不修改 `local_warehouse`、研究数据契约、事实表、采集任务、业务键、修订规则、派生特征公式、调度或数据目录。
- 不增加产业价格、库存、产量、销量、分析师预测、社交媒体、订单簿、逐笔委托、账户身份或所谓主力资金数据。
- 不建设通用爬虫、通用因子库、统一实验平台、机器学习模型、热点最终排名、评分器、固定权重、仓位、买入概率或收益保证。
- 不修改正式分析器、推荐、报告、自动任务、激活和部署。
- 研究目标仍是为未来 10—30 个交易日、中心约 20 日的 2—6 周机会提供证据，但“20%”不是知识通过门槛；只验证理论、变量和历史方向是否说得通。
- 知识准入只有 `use` 或 `discard`。运行时个股缺数可记录 `not_applicable` / `blocked_by_data`，但不能把整体不可执行的知识包装成“有限使用”。
- 来源只接受官方原文、DOI 对应出版页或期刊原始出版页。搜索摘要、二手转载、自媒体、券商通俗材料和无法核验样本元数据的经验论文不能进入正式来源登记。
- 不保存大面板、逐股结果、图表、模型文件或候选矩阵。临时源核对和大查询结果只放 `/private/tmp`；Git 中只保存代码、测试、四项结果 YAML、登记修改、设计和本计划。

## 2. 固定变更清单

### 2.1 必须退出选择器的三项历史知识

```text
src_liu_stambaugh_yuan_2019
src_piotroski_2000
src_chan_2003
```

三项来源和历史原因保留，`version_status` 改为 `historical_only`。选择器必须显式跳过 `historical_only`；`superseded` 在其历史有效日期内仍允许被选择，不能一刀切为只选 `current`。

### 2.2 恰好四项候选

| ID | 核心问题 | 数据 | 最低来源要求 |
|---|---|---|---|
| `src_cn_business_segment_materiality` | 热点业务对公司整体收入、成本和利润是否真正重要 | `main_business`、`income_statement`、公司资料和公告 | 财政部 CAS 35 官方原文 |
| `src_cn_earnings_growth_persistence` | 单期增长是否由连续收入、利润、现金和利润率共同支持，并非行业共同波动 | 三张财务表、`financial_indicator`、时点有效行业成员 | A 股同行评议原文且样本元数据可核验 |
| `src_cn_relative_valuation_context` | PE/PB/PS 在同行、自身历史、盈利状态和规模背景下是否已反映较高预期 | `daily_basic`、行业成员、财务事实 | Jansen et al. 2021 与 Li et al. 2024 原始出版信息 |
| `src_cn_turnaround_financial_consistency` | 困境改善是否同时体现在经营、现金、流动偿债、应收存货和减值 | 三张财务表、`financial_indicator` | Zhao et al. 2023 与已通过的 Dechow et al. 2010 |

候选数不得变成五项，也不得因为某项失败临时换入低质量替代品。

### 2.3 恰好两类增强

1. 更新已有 `src_cn_factor_momentum_2023` 的允许使用、前置条件和反证，明确消费现有 `sector_hotspot-v2` 的相对收益、上涨面、中位数、成交占比、强势集中度、新高/涨停和拥挤迹象；它仍不是最终热点排名。
2. 用测试锁定因子治理纪律：时点正确、可比组一致、稳健极值、行业/规模/微盘污染、禁止机械加总、禁止照搬论文阈值、必须保留反证和可操作性。

## 3. 文件责任图

| 文件 | 唯一责任 |
|---|---|
| `src/stock_analyzer/knowledge_validation/targeted_gap_validation.py` | 四项合同、纯观察公式、只读加载器、确定性证据；不作准入裁决 |
| `src/stock_analyzer/knowledge/targeted_gap_validation_results.yaml` | 恰好四项的来源核对、公式、样本、前后期观察、反证和二元决定 |
| `src/stock_analyzer/knowledge/research_registry.yaml` | 三项历史状态、通过候选的来源/知识、热点增强 |
| `src/stock_analyzer/knowledge/selector.py` | 排除 `historical_only`，保持历史 `superseded` 语义 |
| `src/stock_analyzer/knowledge/governance_models.py` | 只在财政部官方域名校验确有需要时增加精确 host；不新增模型层级 |
| `tests/test_targeted_gap_validation.py` | 四项库存、公式、时点、口径、确定性、只读和结果结构 |
| `tests/test_knowledge_selector.py` | 历史不可调用与 superseded 历史回放回归测试 |
| `tests/test_knowledge_registry.py` | 结果与正式登记一致、来源质量、数量和无重复 |
| `tests/test_knowledge_capability.py` | 每个 `use` 项现有数据能力为 `complete` |
| `tests/test_knowledge_governance_acceptance.py` | 热点/因子边界、无评分、无身份推断、无生产激活 |

---

## Task 1：冻结基线并修正三项历史知识可调用漏洞

**Files:**
- Modify: `tests/test_knowledge_selector.py`
- Modify: `src/stock_analyzer/knowledge/selector.py`
- Modify: `src/stock_analyzer/knowledge/research_registry.yaml`
- Modify if needed: `tests/test_knowledge_registry.py`

- [ ] **Step 1.1：记录实施基线**

```bash
git status --short
git rev-parse HEAD
shasum -a 256 local_warehouse/research.duckdb
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_selector.py tests/test_knowledge_registry.py tests/test_knowledge_migration.py -q
```

Expected: 工作区只包含本计划尚未提交的变化；基线测试通过。若存在用户无关改动，保留并避开，不覆盖。

- [ ] **Step 1.2：先写失败测试**

新增两个精确行为测试：

```python
def test_selector_never_returns_historical_only_entry():
    historical = entry(..., version_status="historical_only")
    assert historical.knowledge_id not in selected_ids(select_knowledge(...))

def test_selector_still_returns_superseded_version_on_its_effective_date():
    superseded = entry(
        ...,
        version_status="superseded",
        effective_from=date(2024, 1, 1),
        effective_to=date(2024, 12, 31),
    )
    assert superseded.knowledge_id in selected_ids(select_knowledge(... analysis_date=date(2024, 6, 30)))
```

再增加真实登记回归：三项 ID 都存在以保留审计，但状态均为 `historical_only`。

- [ ] **Step 1.3：确认测试因真实缺陷失败**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_selector.py -q
```

Expected: `historical_only` 仍被返回；不是夹具或导入错误。

- [ ] **Step 1.4：最小修复**

在 `select_knowledge()` 的循环最前面加入：

```python
if entry.version_status == "historical_only":
    continue
```

只把三项真实登记的 `version_status` 改为 `historical_only`。不删来源、不改历史验证结果、不改迁移理由、不改 ID。

- [ ] **Step 1.5：验证并提交**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_selector.py tests/test_knowledge_registry.py tests/test_knowledge_migration.py -q
git diff --check
git add src/stock_analyzer/knowledge/selector.py src/stock_analyzer/knowledge/research_registry.yaml tests/test_knowledge_selector.py tests/test_knowledge_registry.py
git commit -m "fix: retire discarded knowledge from selection"
```

---

## Task 2：冻结四项合同和高质量来源门槛

**Files:**
- Create: `src/stock_analyzer/knowledge_validation/targeted_gap_validation.py`
- Create: `tests/test_targeted_gap_validation.py`
- Modify: `src/stock_analyzer/knowledge/governance_models.py`
- Modify: `tests/test_knowledge_governance_models.py`

- [ ] **Step 2.1：先写四项库存失败测试**

```python
EXPECTED_IDS = (
    "src_cn_business_segment_materiality",
    "src_cn_earnings_growth_persistence",
    "src_cn_relative_valuation_context",
    "src_cn_turnaround_financial_consistency",
)

def test_targeted_contract_is_exactly_four_complete_theories():
    assert tuple(item.knowledge_id for item in TARGETED_GAP_CLAIMS) == EXPECTED_IDS
    assert len(TARGETED_GAP_CLAIMS) == 4
    assert all(len(item.core_theory) >= 60 for item in TARGETED_GAP_CLAIMS)
    assert all(item.source_refs and item.required_facts for item in TARGETED_GAP_CLAIMS)
```

断言来源集合只包含设计中批准的官方 URL/DOI；不允许临时第五项。

- [ ] **Step 2.2：实现合同，不实现公式**

```python
Decision = Literal["use", "discard"]

@dataclass(frozen=True)
class TargetedGapClaim:
    knowledge_id: str
    core_theory: str
    source_refs: tuple[str, ...]
    required_facts: tuple[ResearchDatasetId, ...]

@dataclass(frozen=True)
class TargetedGapEvidence:
    knowledge_id: str
    data_usable: bool
    overall_direction: str
    earlier_direction: str
    later_direction: str
    counter_evidence: str
    observations: dict[str, int | float | str]
```

核心理论逐字保持设计含义，不缩成“低估值更好”等走样口号。

- [ ] **Step 2.3：逐源核对原始页面**

核对并临时记录：题名、作者、出版机构/期刊、日期、A 股适用范围、样本开始结束、方法和限制。固定来源：

```text
https://kjs.mof.gov.cn/zt/kjzzss/kuaijizhunzeshishi/200806/t20080618_46246.htm
10.1016/j.pacfin.2018.10.017
10.1016/j.pacfin.2021.101607
10.1287/mnsc.2023.4904
10.1016/j.irfa.2023.102770
```

规则：

- CAS 35 作为 S 级官方方法来源；只支持分部信息与公司整体报表衔接，不把准则披露门槛变成选股阈值。
- A 级经验论文必须核对完整作者、A 股市场范围和样本起止。Wu et al. 的样本元数据若无法从原始出版信息核实，盈利持续性候选最终必须 `discard`，不得猜测、不得降级来源。
- Jansen et al. 样本为 2000—2019；Li et al. 样本为 2000-07—2019-06；Zhao et al. 财务年度为 2011—2018、结果年度为 2013—2020。实现时仍以原始页复核为准。
- 只保存元数据和简短转述，不保存受版权保护全文。

- [ ] **Step 2.4：财政部 host 最小建模**

先写失败测试：S 级 CAS 35 来源允许 `kjs.mof.gov.cn`，相似拼写或非官方域名仍拒绝。只向 `OFFICIAL_HOSTS` 增加实际使用的精确 host；不要加入通配符，不要放宽为所有 `.gov.cn`。

- [ ] **Step 2.5：验证并提交**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_targeted_gap_validation.py tests/test_knowledge_governance_models.py -q
git diff --check
git add src/stock_analyzer/knowledge_validation/targeted_gap_validation.py src/stock_analyzer/knowledge/governance_models.py tests/test_targeted_gap_validation.py tests/test_knowledge_governance_models.py
git commit -m "test: freeze targeted knowledge gap contracts"
```

---

## Task 3：用纯函数实现业务实质性和增长持续性观察

**Files:**
- Modify: `tests/test_targeted_gap_validation.py`
- Modify: `src/stock_analyzer/knowledge_validation/targeted_gap_validation.py`

- [ ] **Step 3.1：业务分部公式失败测试**

构造包含同公司同报告期 `industry/product/region` 三种分类、空币种、零分母和负利润的最小 DataFrame，断言：

- 只在同一 `classification` 内计算，不能把产品、地区、行业分部相加；
- `sales_share = bz_sales / company_revenue`，分母必须为正且口径可比；
- `profit_share = bz_profit / company_operating_profit` 只在非零、可解释分母下生成；
- `gross_margin = (bz_sales - bz_cost) / bz_sales` 只在销售额为正时生成；
- 保留 `classification`、币种/口径可比标志和无法计算原因；
- 不产生 `score`、`rank`、`prediction`、`institution` 字段。

目标接口：

```python
def business_segment_materiality_observations(frame: pd.DataFrame) -> pd.DataFrame:
    ...
```

- [ ] **Step 3.2：增长持续性公式失败测试**

使用至少两家公司、一个行业、九个季度的有序夹具，断言：

- 通过同公司 `lag(4)` / `lead(4)` 比较同季累计口径，不把相邻季度累计值误作单季增长；
- 收入、营业利润、归母净利润、经营现金流、毛利率和费用方向分别保留；
- 对可能跨零的利润使用相对上年总资产缩放的变化，不用会爆炸的百分比；
- 行业共同部分用同报告期、时点有效成员的行业中位数，输出公司相对行业变化；
- 不合成为总分，不调用分析师预期，不生成“超预期”。

目标接口：

```python
def earnings_growth_persistence_observations(frame: pd.DataFrame) -> pd.DataFrame:
    ...
```

- [ ] **Step 3.3：实现最小向量化公式**

共同纪律：复制输入、稳定排序、不原地污染、除零转缺失、无穷值转缺失、输出顺序确定。只实现上述列，不添加“方便以后”的参数或抽象基类。

- [ ] **Step 3.4：验证并提交**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_targeted_gap_validation.py -q
git diff --check
git add src/stock_analyzer/knowledge_validation/targeted_gap_validation.py tests/test_targeted_gap_validation.py
git commit -m "feat: add business and earnings knowledge observations"
```

---

## Task 4：用纯函数实现相对估值和反转一致性观察

**Files:**
- Modify: `tests/test_targeted_gap_validation.py`
- Modify: `src/stock_analyzer/knowledge_validation/targeted_gap_validation.py`

- [ ] **Step 4.1：相对估值失败测试**

夹具覆盖亏损公司、负净资产、同行极端值、微盘股和多历史日期。断言：

- PE 仅在 `pe_ttm > 0` 时有效；PB/PS 的无效状态明确标注，不静默填零；
- 同日期、同行业、同盈利状态分组计算稳健百分位；样本不足时返回不可比，不跨行业补齐；
- 自身历史百分位只使用当前及之前日期，增加未来行不能改变较早日期结果；
- 市值百分位、盈利、增长和现金质量分别输出，不能给微盘股加分或机械扣分；
- 输出没有总分、买入结论或未来收益预测。

目标接口：

```python
def relative_valuation_context_observations(frame: pd.DataFrame) -> pd.DataFrame:
    ...
```

- [ ] **Step 4.2：困境反转失败测试**

夹具包含“利润转正但现金、偿债和应收恶化”以及“多表一致改善”两类。断言分别输出：

```text
operating_result_change
operating_cash_change
liquidity_change
debt_pressure_change
receivable_inventory_pressure_change
impairment_nonoperating_change
contradiction_count
```

变化与上年同季比较，金额按上年总资产等合理分母缩放；`contradiction_count` 只记录反证数量，不是评分、概率或淘汰阈值。

目标接口：

```python
def turnaround_financial_consistency_observations(frame: pd.DataFrame) -> pd.DataFrame:
    ...
```

- [ ] **Step 4.3：实现、验证并提交**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_targeted_gap_validation.py -q
git diff --check
git add src/stock_analyzer/knowledge_validation/targeted_gap_validation.py tests/test_targeted_gap_validation.py
git commit -m "feat: add valuation and turnaround observations"
```

---

## Task 5：实现三个只读加载器和确定性真实验证入口

**Files:**
- Modify: `tests/test_targeted_gap_validation.py`
- Modify: `src/stock_analyzer/knowledge_validation/targeted_gap_validation.py`

- [ ] **Step 5.1：先锁定时点和只读行为**

用临时 parquet 夹具写失败测试，要求所有加载器：

- 只读取 `available_at <= analysis_date`；
- 同业务键多修订时取分析日可见的最后修订；
- 行业成员按形成日有效区间连接，禁止把当前行业成员回填历史；
- 不写 DuckDB、不写 parquet、不修改输入目录；
- 同输入重复运行顺序和数值完全一致。

- [ ] **Step 5.2：实现最小加载接口**

```python
def load_business_segment_panel(root: Path, analysis_date: date) -> pd.DataFrame:
    ...

def load_financial_history_panel(root: Path, analysis_date: date) -> pd.DataFrame:
    ...

def load_valuation_history_panel(root: Path, analysis_date: date) -> pd.DataFrame:
    ...
```

实现要求：

- 只用 `duckdb.connect(":memory:")` 和 `read_parquet`；
- 复用项目研究契约的事实目录，不创建新数据集；
- `main_business` 按 `classification` 保留多口径，不能跨口径汇总；
- 财务表按 `(ts_code, report_period)` 和可见修订连接，形成报告期历史；
- 估值验证可按固定的每 20 个交易日抽样以控制内存，但必须包含最近日期，抽样规则写死且测试；正式观察函数仍接受任意日频输入；
- 不把未来报告用于形成日特征。`lead(4)` 只作为历史验证标签，并明确不进入实际分析输入。

- [ ] **Step 5.3：实现证据入口**

```python
def validate_targeted_gap_claims(
    warehouse_root: Path,
    *,
    analysis_date: date = date(2026, 7, 14),
) -> tuple[TargetedGapEvidence, ...]:
    ...
```

返回顺序严格等于四项合同顺序。证据只记录可用行数、覆盖期、总体/较早/较晚方向、关系形态和决定性反证；不自动产生 `use/discard`，不以 p 值、命中率、20% 或固定样本数作门槛。

- [ ] **Step 5.4：运行真实仓并证明无写入**

测试必须在同一个测试进程内对调用前后 `research.duckdb` 和事实目录清单做快照比较：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_targeted_gap_validation.py -q
PYTHONPATH=src .venv/bin/python -c 'from pathlib import Path; from stock_analyzer.knowledge_validation.targeted_gap_validation import validate_targeted_gap_claims; print(validate_targeted_gap_claims(Path("local_warehouse")))'
```

若计算失败，先修代码/口径；不能把代码错误当作知识 `discard` 理由。

- [ ] **Step 5.5：提交**

```bash
git diff --check
git add src/stock_analyzer/knowledge_validation/targeted_gap_validation.py tests/test_targeted_gap_validation.py
git commit -m "feat: validate targeted knowledge on local data"
```

---

## Task 6：科学裁决四项并生成唯一结果 YAML

**Files:**
- Create: `src/stock_analyzer/knowledge/targeted_gap_validation_results.yaml`
- Modify: `tests/test_targeted_gap_validation.py`

- [ ] **Step 6.1：先写结果结构失败测试**

结果必须恰含四项且顺序固定；每项字段固定为：

```yaml
knowledge_id:
source_verification:
core_theory:
formula:
required_data:
sample_period:
observation_count:
overall_observation:
earlier_observation:
later_observation:
counter_evidence:
decision: use|discard
decision_reason:
```

禁止值：`limited`、`pending`、`defer`、`blocked`、固定收益门槛、评分或模型概率。

- [ ] **Step 6.2：逐项人工科学复核真实输出**

裁决顺序固定：

1. 原始来源的核心理论和样本元数据是否完整可核验；
2. 当前数据是否直接表达核心变量而非替代变量偷换；
3. 时点和修订是否正确；
4. 总体、较早和较晚时期方向是否基本说得通；
5. 反证是否推翻“可以作为分析证据”的弱主张；
6. 能否用普通话解释它对公司选择意味着什么。

`use` 不表示理论能保证 2—6 周上涨，只表示当前系统能忠实、直接地使用该理论形成证据。任一来源不可核验或核心变量不可执行即 `discard`。

- [ ] **Step 6.3：写 YAML 并验证确定性**

结果数字来自真实执行输出，不手填虚构值。连续运行两次验证入口，结构化结果应完全相同。YAML 不保存逐股数据。

- [ ] **Step 6.4：提交**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_targeted_gap_validation.py -q
git diff --check
git add src/stock_analyzer/knowledge/targeted_gap_validation_results.yaml tests/test_targeted_gap_validation.py
git commit -m "docs: record targeted knowledge decisions"
```

---

## Task 7：只登记通过项，并增强热点和因子治理

**Files:**
- Modify: `src/stock_analyzer/knowledge/research_registry.yaml`
- Modify: `tests/test_knowledge_registry.py`
- Modify: `tests/test_knowledge_capability.py`
- Modify: `tests/test_knowledge_governance_acceptance.py`

- [ ] **Step 7.1：结果驱动的失败测试**

测试从 `targeted_gap_validation_results.yaml` 读取决定：

- `use` 候选必须且只能有一个 `current` 正式登记；
- `discard` 候选不得有 `current` 登记；
- 每个 `use` 候选来源已存在、等级为 S/A、元数据完整、`local_validation.status == validated` 且引用结果 YAML；
- 当前知识 ID、来源 ID 均无重复；
- 三项历史知识仍为 `historical_only`；
- 当前条目总数等于修正后的 24 加本轮 `use` 数，不把两类增强计为新增。

- [ ] **Step 7.2：只添加通过来源和知识**

每项登记保持以下语义：

- 业务实质性：`COMPANY_BUSINESS` / `BUSINESS_TRANSMISSION`，允许比较分部贡献；禁止由概念联系直接推导业绩或涨幅。
- 增长持续性：`FUNDAMENTALS` / `PROFITABILITY_QUALITY`，允许比较多期经营、现金和行业共同部分；禁止超预期或固定收益预测。
- 相对估值：`VALUATION` / `VALUATION_METHOD`，允许同行、自身历史和盈利状态比较；禁止低估值加分、因子收益承诺。
- 反转一致性：`FUNDAMENTALS` / `FINANCIAL_TURNAROUND`，允许分维度观察和反证；禁止 Piotroski 分数、机器学习概率。

每项只声明真实需要的现有 `DataRequirement`，不创建新派生数据要求。

- [ ] **Step 7.3：增强已有热点条目**

更新 `src_cn_factor_momentum_2023`：

- `data_requirements` 引用现有 `sector_hotspot` 所需字段；
- `allowed_uses` 明确多期限相对收益、上涨面、中位数、成交占比、前三强集中度、新高/涨停；
- `counter_evidence` 明确窄参与、高成交低进展、量价背离、冲高回落和拥挤；
- `forbidden_uses` 明确不是最终热点名次、不能推断主力/机构。

不得修改 `sector-hotspot-v2` 公式或数据文件。

- [ ] **Step 7.4：锁定七条因子治理纪律**

验收测试从当前登记中验证：分析时点、同日同行业同盈利状态、稳健极值、行业/规模/微盘控制、无机械总分、无历史论文阈值、反证与交易可行性。不得新建“因子治理知识 ID”。

- [ ] **Step 7.5：能力验证并提交**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_registry.py tests/test_knowledge_capability.py tests/test_knowledge_governance_acceptance.py -q
git diff --check
git add src/stock_analyzer/knowledge/research_registry.yaml tests/test_knowledge_registry.py tests/test_knowledge_capability.py tests/test_knowledge_governance_acceptance.py
git commit -m "feat: admit verified targeted knowledge"
```

---

## Task 8：边界审查、全量验证和最终交付

**Files:**
- Modify only if a test exposes an in-scope defect; any new behavior requires returning to the corresponding TDD task.

- [ ] **Step 8.1：专项测试**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_targeted_gap_validation.py \
  tests/test_knowledge_governance_models.py \
  tests/test_knowledge_selector.py \
  tests/test_knowledge_registry.py \
  tests/test_knowledge_migration.py \
  tests/test_knowledge_capability.py \
  tests/test_knowledge_governance_acceptance.py -q
```

- [ ] **Step 8.2：全量测试**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

若失败，使用 `superpowers:systematic-debugging` 查根因；只修与本轮变化有关的缺陷，不顺便重构。

- [ ] **Step 8.3：静态边界扫描**

```bash
rg -n "score|weight|rank|buy_probability|position|主力|机构买入|必涨|20%门槛" \
  src/stock_analyzer/knowledge_validation/targeted_gap_validation.py \
  src/stock_analyzer/knowledge/targeted_gap_validation_results.yaml \
  src/stock_analyzer/knowledge/research_registry.yaml
rg -n "local_warehouse|write_parquet|copy .*parquet|create table|insert into|update .* set|delete from" \
  src/stock_analyzer/knowledge_validation/targeted_gap_validation.py
git diff --check
git status --short
git log --oneline ec45b888b9240c216524ee8f4f8104ad06209846..HEAD
```

逐条人工判断匹配是否为禁止声明而非违规实现。验证模块不得含写入 SQL。

- [ ] **Step 8.4：仓库无写入证明**

再次执行验证函数，并比较同一调用前后的数据库哈希和事实文件清单。若跨整个实施阶段哈希因外部定时任务改变，只报告该事实；本轮只读证明以单次调用前后相等为准。

- [ ] **Step 8.5：数量和设计对账**

最终打印并人工复核：

```text
原 74 项：3 保留 + 5 更新 + 4 本地验证通过 + 37 暂缓 + 25 退出/验证丢弃 = 12 个原有 current
前轮新增并通过：12 个 current
本轮冲突修正后的实施前 current：24
本轮新增：四项中的 use 数
本轮增强：2 类，不增加条目数
最终 current：24 + 本轮 use 数
```

若仓库实际统计与这组历史对账不同，以逐 ID 集合差异定位，不能改数字掩盖问题。

- [ ] **Step 8.6：最终复查和最后提交**

运行 `superpowers:requesting-code-review` 的单人等价检查清单：需求覆盖、越界、时点泄漏、公式口径、结果/登记一致性、测试缺口、用户可理解性。由于用户要求不使用子智能体，复查由当前代理独立完成并记录在最终汇报，不创建额外评审产物。

如有仅文档/测试收尾修改：

```bash
git add <本轮明确文件>
git commit -m "test: verify targeted knowledge gap fill"
```

最终 `git status --short` 必须为空，所有测试必须有本轮最新输出，才能声明完成。

## 4. 最终汇报固定口径

最终只向用户说明：

1. 修复了什么真实漏洞；
2. 四项各自 `use/discard` 及普通话原因；
3. 原有可用、新增可用、最终可用知识数量；
4. 热点和因子纪律如何被增强但未形成评分器；
5. 专项/全量测试和只读仓库证据；
6. 明确没有修改数据底座、分析器、报告、任务、激活和部署。

不输出内部大矩阵，不要求用户理解统计中间量，不把“测试通过”描述为选股效果已经获得生产验证。
