# V3 Thirteen Knowledge Direct Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not use subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用现有研究仓库直接论证十三项 `revalidate` 知识是否可用于 A 股分析，并把每项收敛为 `use` 或 `discard`。

**Architecture:** 删除当前通用验证实验室，改为一个直接验证模块。模块内只有七个具名计算函数，共用少量只读、复权和时间检查辅助函数；计算只产生易读历史证据，不用硬指标自动判定，最后逐条人工复核十三项知识。

**Tech Stack:** Python 3.11+、pandas、NumPy、现有 DuckDB/Parquet 研究仓库、pytest；不新增依赖。

## Global Constraints

- 直接在本地 `main` 工作，不创建分支、工作树或子智能体。
- 不修改 `src/stock_analyzer/data/`、`src/stock_analyzer/storage/`、`local_warehouse/`、数据接口、表、分区或派生特征公式。
- 不使用固定样本数、收益、显著性、胜率或未来 20% 目标作为机械门槛。
- 统计量只帮助观察总体方向、时间一致性、关系形态、驱动来源和反证。
- 每项最终只有 `use` 或 `discard`；计算失败必须修复，不能作为知识结论。
- 不接入评分、排名、推荐、报告、自动任务、部署或交易。
- 中间面板不入库、不提交，验证结束即删除。

## File Responsibility Map

| File | Responsibility |
|---|---|
| `src/stock_analyzer/knowledge_validation/direct_validation.py` | 十三项理论、七组直接计算、只读辅助函数和证据输出 |
| `src/stock_analyzer/knowledge_validation/__init__.py` | 只导出直接验证入口和必要类型 |
| `src/stock_analyzer/knowledge/direct_validation_results.yaml` | 唯一十三行结果记录 |
| `tests/test_direct_knowledge_validation.py` | 十三项对账、七组公式、时点、复权和确定性 |
| `src/stock_analyzer/knowledge/strategy_v2_migration.yaml` | 将十三项 `revalidate` 改为最终 `update` 或 `retire` |
| `src/stock_analyzer/knowledge/research_registry.yaml` | 仅把通过方法对应的当前知识改为已验证；丢弃项不可调用 |

删除：`models.py`、`samples.py`、`signals.py`、`spec_registry.py`、`statistics.py`、`studies.yaml` 和四个 `test_knowledge_validation_*` 文件。

---

### Task 1: Replace the generic laboratory with thirteen direct claims

**Files:** Create `direct_validation.py`, `test_direct_knowledge_validation.py`; modify `__init__.py`; delete旧通用文件与测试。

**Interfaces:**

```python
@dataclass(frozen=True)
class KnowledgeClaim:
    legacy_id: str
    target_ids: tuple[str, ...]
    calculation: str
    core_theory: str
    required_facts: tuple[ResearchDatasetId, ...]

@dataclass(frozen=True)
class HistoricalEvidence:
    legacy_id: str
    calculation: str
    data_usable: bool
    overall_direction: str
    earlier_direction: str
    later_direction: str
    relationship_shape: str
    main_drivers: str
    counter_evidence: str
    observations: dict[str, int | float | str]

CLAIMS: tuple[KnowledgeClaim, ...]
```

- [ ] 写失败测试：`CLAIMS` 恰好覆盖迁移表十三项 `revalidate`，无重复，只引用七个计算名；测试逐项要求明确登记研究对象、核心变量关系、方向或时序、适用边界，不用字符数替代理论完整性复核。
- [ ] 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_direct_knowledge_validation.py -q`，确认因模块不存在而失败。
- [ ] 创建两个冻结数据类和十三项 `CLAIMS`。十三项核心理论直接依据已核验原文及现有登记，不写成“低估值会涨”式口号。
- [ ] 删除六个通用实现、`studies.yaml` 和四个旧测试；`__init__.py` 只导出 `CLAIMS`、`HistoricalEvidence`、`KnowledgeClaim`、`validate_all_claims`。
- [ ] 运行新测试和 `tests/test_knowledge_migration.py tests/test_knowledge_registry.py`，确认通过。
- [ ] 提交 `refactor: simplify direct knowledge validation contracts`。

### Task 2: Add only the shared historical evidence helpers

**Files:** Modify `direct_validation.py`, `test_direct_knowledge_validation.py`。

**Interfaces:**

```python
def adjusted_return(base_close: float, base_factor: float,
                    future_close: float, future_factor: float) -> float
def chronological_views(frame: pd.DataFrame, value: str) -> dict[str, float | str]
def describe_ordered_groups(frame: pd.DataFrame, group: str, value: str) -> str
def concentration_description(frame: pd.DataFrame, date_col: str, value: str) -> str
```

- [ ] 写失败测试：复权同时使用前后因子；按日期排序后较早和较晚历史不可随机切分；有序分组描述保留每组方向；驱动检查能够指出结果是否集中在少数日期或微小市值股票。
- [ ] 实现上述四个短函数。`chronological_views` 只返回完整、较早、较晚的描述性结果，不产生通过线；`concentration_description` 只报告集中现象，不打分。
- [ ] 增加只读仓库打开函数，继承现有 `ResearchWarehouse` 的读取方法但不执行其写入初始化；用仓库 SHA-256 测试证明打开和读取不改变数据库。
- [ ] 运行直接验证测试和 `tests/test_research_as_of.py`，确认通过。
- [ ] 提交 `feat: add minimal historical evidence helpers`。

### Task 3: Implement seven named calculations without a framework

**Files:** Modify `direct_validation.py`, `test_direct_knowledge_validation.py`。

**Interfaces:**

```python
def validate_size_value(query: ResearchQuery) -> dict[str, HistoricalEvidence]
def validate_short_reversal(query: ResearchQuery) -> dict[str, HistoricalEvidence]
def validate_common_factor_momentum(query: ResearchQuery) -> dict[str, HistoricalEvidence]
def validate_daily_event_method(query: ResearchQuery) -> dict[str, HistoricalEvidence]
def validate_earnings_reaction(query: ResearchQuery) -> dict[str, HistoricalEvidence]
def validate_formal_announcement_shocks(query: ResearchQuery) -> dict[str, HistoricalEvidence]
def validate_financial_improvement(query: ResearchQuery) -> dict[str, HistoricalEvidence]
def validate_all_claims(warehouse_root: Path) -> tuple[HistoricalEvidence, ...]
```

- [ ] 分别写七个小型失败测试，使用手算数据确认：规模与估值分组、过去收益与随后反转、共同因子扣除前后、市场调整公告窗口、业绩公告反应、正式公告匹配措辞、六项财务变化方向。
- [ ] 实现前三个价格类函数。只展示完整历史、时间前后、有序关系和驱动来源；未来结果与形成变量分开。
- [ ] 实现三个事件类函数。公告按正式发布时间映射交易日；盘后映射下一交易日；只写“未匹配本地正式公告”。
- [ ] 实现财务改善函数。保持 Dechow、Sloan、Piotroski、Novy-Marx 各自理论差异，不能用一个总分使四项知识自动一起通过。
- [ ] 实现 `validate_all_claims`，固定七函数顺序，把七组证据展开回十三项并按迁移表顺序返回；同一输入输出顺序和文本稳定。
- [ ] 运行直接验证测试、知识治理测试和研究时点测试，确认通过。
- [ ] 提交 `feat: implement seven direct historical validations`。

### Task 4: Run once and decide thirteen use/discard results

**Files:** Create `direct_validation_results.yaml`; modify migration and registry YAML。

- [ ] 记录运行前 `local_warehouse/research.duckdb` SHA-256，确认工作区只含本计划变更。
- [ ] 对当前仓库运行 `validate_all_claims(Path("local_warehouse"))`，只将紧凑证据打印到终端；不保存历史面板。
- [ ] 对每项回到原理论核对六类证据：总体方向、时间前后、关系形态、驱动来源、反证和数据可执行性。不得根据单个均值或 p 值裁决。
- [ ] 创建唯一结果文件，格式固定为：

```yaml
schema_version: v3-direct-validation-v1
results:
  - legacy_knowledge_id: src_example
    core_theory: 保留对象、变量、方向、条件和限制的完整中文理论
    calculation: size_value
    evidence_summary: 总体、前后时期、关系形态和主要驱动的简洁事实
    counter_evidence: 最重要的相反证据；没有则明确写未发现决定性反证
    decision: use
    reason: 为什么现有历史足以或不足以支持直接用于分析
```

- [ ] 逐项复核十三行：只允许 `use/discard`；无执行失败；理论保留原文对象、变量关系、方向或时序和适用边界；相同计算组的知识允许不同结论。
- [ ] 对 `use`：迁移 action 改为 `update` 并保留 target；对应目标登记的 `local_validation.status` 改为 `validated`，引用该结果文件。对 `discard`：迁移 action 改为 `retire`、清空 target，理由引用本地反证或不可执行性。若同一目标仍被其他 `use` 项支持，不退出目标登记。
- [ ] 运行知识迁移和登记测试，确认最终迁移表不存在 `revalidate`。
- [ ] 提交 `data: decide thirteen direct knowledge validations`。

### Task 5: Final minimality and safety verification

**Files:** Modify本计划和必要验收测试，不创建额外报告。

- [ ] 运行直接验证、迁移、登记、治理验收和研究时点测试。
- [ ] 运行全量测试 `PYTHONPATH=src .venv/bin/python -m pytest -q`。
- [ ] 校验研究仓库 SHA-256 与 Task 4 前完全相同。
- [ ] 使用 `rg` 确认生产分析、报告和任务目录没有导入 `knowledge_validation`。
- [ ] 使用 `rg` 确认最终实现不存在 `MethodStatus`、`RelevanceStatus`、`ValidationRegistry`、`moving_block_bootstrap`、`benjamini_hochberg`、`score`、`weight` 或 `recommend` 等旧实验平台与评分字段。
- [ ] 检查最终版本化产物只有一个直接验证模块、一个测试文件和一个十三行结果文件；无历史面板和重复报告。
- [ ] 提交 `chore: verify minimal direct knowledge validation`。
