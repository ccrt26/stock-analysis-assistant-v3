# V3 Compression Revalidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用最小、可审计的改动取消“五项财务指标全满足”统一硬门，把每日用户结果简化为一个最多十只的关注名单，并复用冻结 90 个形成日验证新压缩是否减少已知机会损失。

**Architecture:** 新建隔离的压缩重算模块，读取既有 90 日 `evidence.parquet` 和次日开盘行动路径，不重新扫描行情或重建特征。模块先从已有形成日事实派生后台公司驱动状态，再按同角色第一层 Pareto 比较形成最多 10 只关注名单；后台审计字段保留在结果表和技术附录，不形成用户分类。

**Tech Stack:** Python 3.12、pandas、NumPy、PyArrow、PyYAML、pytest；现有 `v3_next_day_entry_validation` 汇总与行动路径表。

## Global Constraints

- 只使用当前本地 `main`，不创建分支或工作树，不启动子智能体。
- 本轮唯一优化目标是修复研究池压缩损失；不修改数据源、派生特征、生命周期、挑战者替换、退出、仓位、激活或部署。
- 用户每日只看到一个 `关注名单`，合计最多 10 只，不排名；不足时不凑数。
- `研究池`、`比对组`、公司驱动状态和内部比较角色只出现在技术报告或审计表中，不进入用户名单。
- 不建立满足项计数、固定权重或综合总分；普通单项同比为正最多形成部分公司依据。
- 第一轮只复用冻结 90 日结果；全部运行表、清单、日志和报告写入 `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-compression-revalidation`。
- 本轮不提交、不暂存现有工作树文件；完成后由用户决定版本管理动作。

---

## 执行中确认的最小修正

第一轮两层实现暴露两个容量错误：硬凑五只重点，以及为后台角色设置隐性轮转配额。删除这两个错误后，额外优先层仍不能稳定优于其余候选。按照框架原有“不能优于候补就删除重点层”的边界和用户减少分类的要求，最终实现改为单一关注名单。下方任务中的 `重点/观察` 代码片段保留为测试先行过程记录，不代表最终用户界面；最终权威规则和结果以设计文档第 7 节、工作框架第 18.25 节及 U 盘报告为准。

### Task 1: 纯函数公司状态与两层压缩

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_compression_revalidation.py`
- Create: `tests/test_v3_compression_revalidation.py`

**Interfaces:**
- Consumes: 单日 `evidence.parquet` 的原始列，包括 `company_evidence`、`hard_invalid`、四项财务事实和现有决策维度。
- Produces: `derive_company_driver_state(row: pd.Series) -> str`；`compress_decision_list(evidence: pd.DataFrame, *, candidate_cap: int = 10, focus_cap: int = 5) -> pd.DataFrame`。

- [ ] **Step 1: 写公司状态和用户两层的失败测试**

```python
def test_only_two_user_layers_and_partial_or_absent_company_evidence_can_be_observed():
    evidence = pd.DataFrame([
        _row("FULL", company_evidence=True, tr=10, net=10, core=10, cash=100),
        _row("PART", company_evidence=False, tr=10, net=-2, core=-3, cash=-1),
        _row("PRICE", routes="price", company_evidence=False, tr=np.nan, net=np.nan, core=np.nan, cash=np.nan),
        _row("BAD", company_evidence=True, hard_invalid=True),
    ])

    result = compress_decision_list(evidence, candidate_cap=10, focus_cap=5)
    selected = result[result["user_layer"].isin(["重点", "观察"])]

    assert result.set_index("ts_code").loc["FULL", "user_layer"] == "重点"
    assert result.set_index("ts_code").loc["PART", "user_layer"] == "观察"
    assert result.set_index("ts_code").loc["PRICE", "user_layer"] == "观察"
    assert result.set_index("ts_code").loc["BAD", "user_layer"] == "不展示"
    assert set(selected["user_layer"]) <= {"重点", "观察"}
    assert "score" not in result.columns
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `.venv/bin/pytest tests/test_v3_compression_revalidation.py -q`
Expected: FAIL，错误为 `ModuleNotFoundError` 或函数尚未定义。

- [ ] **Step 3: 实现公司驱动状态，不用满足项计数决定重点**

```python
FINANCIAL_FIELDS = ("tr_yoy", "netprofit_yoy", "dt_netprofit_yoy", "n_cashflow_act")


def derive_company_driver_state(row: pd.Series) -> str:
    if bool(row.get("hard_invalid", False)):
        return "excluded"
    if bool(row.get("company_evidence", False)):
        return "confirmed"
    has_report = pd.notna(row.get("report_period"))
    has_directional_support = any(
        pd.notna(row.get(field)) and float(row.get(field)) > 0
        for field in FINANCIAL_FIELDS
    )
    if has_report and has_directional_support:
        return "partial"
    return "absent"
```

`confirmed` 暂时只继承旧五项完整条件，作用仅为竞争重点；`partial` 允许进入观察；单项负数不产生 `contradicted`，因为现有正负号不足以判断行业季节性或重要性。

- [ ] **Step 4: 实现分角色 Pareto 次序和两层名单**

```python
LANE_DIMENSIONS = {
    "focus_candidate": (
        "evidence_freshness", "earnings_cash_consistency", "hotspot_support",
        "price_consumption_safety", "liquidity",
    ),
    "company_observation": (
        "evidence_freshness", "earnings_cash_consistency", "hotspot_support",
        "price_consumption_safety", "liquidity",
    ),
    "elasticity_observation": (
        "hotspot_support", "price_consumption_safety", "liquidity",
    ),
}


def _pareto_order(frame: pd.DataFrame, dimensions: tuple[str, ...]) -> list[int]:
    remaining = list(frame.index)
    ordered: list[int] = []
    while remaining:
        frontier = []
        for index in remaining:
            values = frame.loc[index, list(dimensions)].astype(float)
            dominated = any(
                bool((frame.loc[other, list(dimensions)].astype(float) >= values).all())
                and bool((frame.loc[other, list(dimensions)].astype(float) > values).any())
                for other in remaining if other != index
            )
            if not dominated:
                frontier.append(index)
        frontier.sort(key=lambda item: (str(frame.loc[item, "routes"]), str(frame.loc[item, "ts_code"])))
        ordered.extend(frontier)
        remaining = [item for item in remaining if item not in frontier]
    return ordered


def _round_robin_indexes(groups: list[list[int]], cap: int) -> list[int]:
    queues = [list(group) for group in groups]
    selected: list[int] = []
    while len(selected) < cap and any(queues):
        for queue in queues:
            if queue and len(selected) < cap:
                selected.append(queue.pop(0))
    return selected


def compress_decision_list(evidence: pd.DataFrame, *, candidate_cap: int = 10, focus_cap: int = 5) -> pd.DataFrame:
    prepared = evidence.copy().reset_index(drop=True)
    prepared["company_driver_state"] = prepared.apply(derive_company_driver_state, axis=1)
    prepared["internal_lane"] = np.select(
        [
            prepared["company_driver_state"].eq("confirmed"),
            prepared["company_driver_state"].eq("partial"),
        ],
        ["focus_candidate", "company_observation"],
        default="elasticity_observation",
    )
    prepared["user_layer"] = "不展示"
    prepared["decision_reason"] = "capacity_or_evidence_not_selected"
    prepared.loc[prepared["hard_invalid"].astype(bool), "decision_reason"] = "hard_invalidation"

    eligible = prepared[~prepared["hard_invalid"].astype(bool)]
    focus_order = _pareto_order(
        eligible[eligible["internal_lane"].eq("focus_candidate")],
        LANE_DIMENSIONS["focus_candidate"],
    )
    focus = focus_order[:focus_cap]
    prepared.loc[focus, ["user_layer", "decision_reason"]] = ["重点", "confirmed_company_driver"]

    observation_lists = []
    for lane in ("company_observation", "elasticity_observation", "focus_candidate"):
        lane_frame = eligible[eligible["internal_lane"].eq(lane) & ~eligible.index.isin(focus)]
        observation_lists.append(_pareto_order(lane_frame, LANE_DIMENSIONS[lane]))
    observation = _round_robin_indexes(observation_lists, candidate_cap - len(focus))
    prepared.loc[observation, ["user_layer", "decision_reason"]] = ["观察", "needs_one_or_more_confirmations"]
    return prepared
```

- [ ] **Step 5: 增加容量、硬边界和跨角色不支配测试**

```python
def test_caps_and_hard_invalidations_are_enforced_without_cross_lane_dominance():
    rows = [_row(f"F{i}", company_evidence=True) for i in range(8)]
    rows += [_row(f"P{i}", routes="price", company_evidence=False) for i in range(8)]
    result = compress_decision_list(pd.DataFrame(rows), candidate_cap=10, focus_cap=5)
    selected = result[result["user_layer"].isin(["重点", "观察"])]
    assert len(selected) == 10
    assert selected["user_layer"].eq("重点").sum() <= 5
    assert selected["user_layer"].eq("观察").sum() <= 10
    assert selected["hard_invalid"].eq(False).all()
```

- [ ] **Step 6: 运行纯函数测试**

Run: `.venv/bin/pytest tests/test_v3_compression_revalidation.py -q`
Expected: PASS。

---

### Task 2: 冻结配置、90 日读取和次日行动结果连接

**Files:**
- Create: `docs/superpowers/specs/2026-07-19-v3-compression-revalidation-config.yaml`
- Modify: `src/stock_analyzer/evaluation/v3_compression_revalidation.py`
- Modify: `tests/test_v3_compression_revalidation.py`

**Interfaces:**
- Consumes: 90 个形成日 evidence 文件；`unique_action_paths.parquet`；旧 `selection_action_outcomes.parquet`。
- Produces: `CompressionConfig`、`load_config()`、`prepare_output_root()`、`build_recompressed_outcomes()`。

- [ ] **Step 1: 写配置与 U 盘路径失败测试**

```python
def test_config_freezes_sources_caps_and_user_layers():
    config = load_config(CONFIG_PATH)
    assert config.candidate_cap == 10
    assert config.focus_cap == 5
    assert config.horizons == (20, 30)
    assert config.user_layers == ("重点", "观察")
    assert config.source_layered_root.name == "2026-07-18-v3-layered-validation"
    assert config.source_action_root.name == "2026-07-19-v3-next-day-entry-validation"


def test_output_root_rejects_non_usb_location(tmp_path):
    with pytest.raises(ValueError, match="U盘专用目录"):
        prepare_output_root(load_config(CONFIG_PATH), output_override=tmp_path / "wrong")
```

- [ ] **Step 2: 建立冻结 YAML**

```yaml
experiment_id: 2026-07-19-v3-compression-revalidation
source_layered_root: /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-18-v3-layered-validation
source_action_root: /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-next-day-entry-validation
output_root: /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-compression-revalidation
blocks: [A, B, C]
horizons: [20, 30]
candidate_cap: 10
focus_cap: 5
user_layers: [重点, 观察]
runtime_stop_minutes: 10
```

- [ ] **Step 3: 实现配置加载和严格输出目录检查**

```python
@dataclass(frozen=True)
class CompressionConfig:
    experiment_id: str
    source_layered_root: Path
    source_action_root: Path
    output_root: Path
    blocks: tuple[str, ...]
    horizons: tuple[int, ...]
    candidate_cap: int
    focus_cap: int
    user_layers: tuple[str, ...]
    runtime_stop_minutes: int


def load_config(path: str | Path) -> CompressionConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    config = CompressionConfig(
        experiment_id=str(payload["experiment_id"]),
        source_layered_root=Path(payload["source_layered_root"]),
        source_action_root=Path(payload["source_action_root"]),
        output_root=Path(payload["output_root"]),
        blocks=tuple(str(value) for value in payload["blocks"]),
        horizons=tuple(int(value) for value in payload["horizons"]),
        candidate_cap=int(payload["candidate_cap"]),
        focus_cap=int(payload["focus_cap"]),
        user_layers=tuple(str(value) for value in payload["user_layers"]),
        runtime_stop_minutes=int(payload["runtime_stop_minutes"]),
    )
    if config.blocks != ("A", "B", "C") or config.horizons != (20, 30):
        raise ValueError("必须保留冻结的A/B/C区间和20/30日窗口")
    if config.candidate_cap != 10 or config.focus_cap != 5:
        raise ValueError("名单上限必须保持10只和5只重点")
    if config.user_layers != ("重点", "观察"):
        raise ValueError("用户层只能是重点和观察")
    return config


def prepare_output_root(config: CompressionConfig, *, output_override=None, allowed_volume_root=DEFAULT_ALLOWED_VOLUME_ROOT) -> Path:
    output = Path(output_override) if output_override else config.output_root
    expected = Path(allowed_volume_root) / "股票分析助手-V3回测" / config.experiment_id
    if output.resolve(strict=False) != expected.resolve(strict=False):
        raise ValueError("输出路径必须是冻结的U盘专用目录")
    for child in ("manifests", "tables", "reports"):
        (output / child).mkdir(parents=True, exist_ok=True)
    return output
```

- [ ] **Step 4: 连接新名单与既有行动路径**

```python
def build_recompressed_outcomes(config: CompressionConfig) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    evidence_files = sorted(config.source_layered_root.glob(
        "tables/formations/block=*/formation_date=*/evidence.parquet"
    ))
    if len(evidence_files) != 90:
        raise ValueError("必须读取冻结的90个形成日证据")
    decisions = pd.concat(
        [compress_decision_list(pd.read_parquet(path), candidate_cap=config.candidate_cap, focus_cap=config.focus_cap)
         for path in evidence_files],
        ignore_index=True,
    )
    selected = decisions[decisions["user_layer"].isin(config.user_layers)].copy()
    selected["policy"] = "v3_recompressed"
    paths_file = config.source_action_root / "tables" / "unique_action_paths.parquet"
    paths = pd.read_parquet(paths_file)
    outcomes = selected.merge(paths, on=["formation_date", "ts_code"], how="left", validate="one_to_many")
    outcomes["layer"] = outcomes["user_layer"]
    if outcomes["action_price"].isna().all():
        raise ValueError("新名单未连接到次日行动路径")
    return decisions, outcomes, [*evidence_files, paths_file]
```

- [ ] **Step 5: 运行配置与连接测试**

Run: `.venv/bin/pytest tests/test_v3_compression_revalidation.py -q`
Expected: PASS；测试使用临时 Parquet 构造，不写 U 盘。

---

### Task 3: 比较、验收和用户可读报告

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_compression_revalidation.py`
- Modify: `tests/test_v3_compression_revalidation.py`

**Interfaces:**
- Consumes: 新压缩行动结果、旧最终候选行动结果、研究池行动结果。
- Produces: `summary_metrics.parquet`、`acceptance_checks.parquet`、`decision_examples.parquet`、中文详细报告和质量清单。

- [ ] **Step 1: 写验收测试**

```python
def test_acceptance_requires_improvement_over_old_and_smaller_research_loss():
    comparisons = pd.DataFrame([
        {"horizon": 20, "metric": "touch_yield_all_plans", "new": .30, "old": .27, "research": .34},
        {"horizon": 20, "metric": "close_yield_all_plans", "new": .27, "old": .25, "research": .28},
        {"horizon": 30, "metric": "touch_yield_all_plans", "new": .40, "old": .36, "research": .43},
        {"horizon": 30, "metric": "close_yield_all_plans", "new": .36, "old": .34, "research": .37},
    ])
    checks = evaluate_acceptance(comparisons)
    assert checks["new_not_below_old_touch_and_close"] is True
    assert checks["research_compression_loss_shrunk"] is True
```

- [ ] **Step 2: 实现汇总和冻结验收**

从旧行动结果中只取旧最终候选和研究池，再与新结果合并：

```python
source_actions = pd.read_parquet(
    config.source_action_root / "tables" / "selection_action_outcomes.parquet"
)
old_and_research = source_actions[
    source_actions["policy"].isin(["v3_partial_candidate", "research_union"])
].copy()
summary = summarize_actions(
    pd.concat([new_outcomes, old_and_research], ignore_index=True),
    supported_policies=("v3_recompressed", "v3_partial_candidate", "research_union"),
)
```

验收函数必须逐项返回布尔值，不压成总分：

```python
def evaluate_acceptance(comparisons: pd.DataFrame) -> dict[str, bool]:
    core = comparisons[comparisons["metric"].isin(["touch_yield_all_plans", "close_yield_all_plans"])]
    return {
        "new_not_below_old_touch_and_close": bool((core["new"] >= core["old"]).all()),
        "research_compression_loss_shrunk": bool(((core["research"] - core["new"]) < (core["research"] - core["old"])).all()),
        "both_horizons_present": set(core["horizon"]) == {20, 30},
    }
```

保持 3 日与窗口最低收益中位按以下布尔规则检查：

```python
retain = comparisons[comparisons["metric"].eq("retain_3_yield_all_plans")]
risk = comparisons[comparisons["metric"].eq("median_window_min_return")]
checks["retention_not_worse_both_horizons"] = not bool((retain["new"] < retain["old"]).all())
checks["path_risk_not_worse_both_horizons"] = not bool((risk["new"] < risk["old"]).all())
block_touch = comparisons[
    comparisons["metric"].eq("touch_yield_all_plans")
    & comparisons["block"].isin(["A", "B", "C"])
]
checks["not_all_blocks_lose_to_research"] = not bool(
    block_touch.groupby("horizon").apply(lambda frame: (frame["new"] < frame["research"]).all()).all()
)
```

- [ ] **Step 3: 实现两层用户报告和技术附录**

报告正文固定先回答：

```markdown
# V3 压缩优化重算报告

## 给用户的直接结论

- 每日只保留“重点”和“观察”，两层合计最多 10 只。
- 新压缩相对旧压缩：20 日、30 日盘中达到、收盘确认和保持质量分别如何变化。
- 哪些规则可以保留，哪些仍不行，以及下一步是否进入完整回放。

## 为什么发生变化

- 五项全满足不再是统一硬门。
- 部分公司依据和纯弹性机会都可以进入观察，但不能直接成为重点。

## 技术附录

研究池和比对组只在本节出现，用于证明新规则是否真的优于旧规则。
```

- [ ] **Step 4: 增加质量契约**

质量清单必须验证：90 个形成日、A/B/C 各 30 日、每日总名单不超过 10、重点不超过 5、用户层只有重点/观察、无硬无效对象、20 日达到为 30 日达到子集、来源目录签名未变化、汇总可独立重算、运行时间不超过 10 分钟。

- [ ] **Step 5: 运行完整测试集**

Run: `.venv/bin/pytest tests/test_v3_compression_revalidation.py tests/test_v3_layered_validation.py tests/test_v3_next_day_entry_validation.py -q`
Expected: PASS。

---

### Task 4: 90 日快速重算、报告与框架登记

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_compression_revalidation.py`
- Modify: `docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`
- Runtime outputs: `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-compression-revalidation/**`

**Interfaces:**
- Consumes: 冻结配置和前述模块。
- Produces: U 盘完整实验目录、详细结论、框架中的冻结结果登记。

- [ ] **Step 1: 运行新压缩重算**

Run:

```bash
.venv/bin/python -m stock_analyzer.evaluation.v3_compression_revalidation \
  --config docs/superpowers/specs/2026-07-19-v3-compression-revalidation-config.yaml
```

Expected: 10 分钟内完成，并输出 U 盘报告绝对路径。

- [ ] **Step 2: 独立核对输出**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_v3_compression_revalidation.py \
  tests/test_v3_layered_validation.py \
  tests/test_v3_next_day_entry_validation.py -q
```

Expected: PASS。随后只读检查 `quality_checks.json` 的 `all_passed=true`，并独立从 `recompressed_action_outcomes.parquet` 重算每天数量和核心比率。

- [ ] **Step 3: 根据实际结果更新框架**

只登记真实运行数字：20/30 日盘中达到、收盘确认、严格保持 3 日、窗口最低收益中位、重点/观察差异、A/B/C 分段方向、相对旧压缩和研究池变化。若验收失败，明确写“方案 1 当前实现未通过”，不调文案掩盖；若通过，写“允许进入完整端到端回放”，不写成可部署正式推荐。

- [ ] **Step 4: 最终验证**

Run: `git diff --check`
Expected: 无输出、退出码 0。确认 U 盘实验目录包含 `manifests/`、`tables/`、`reports/`，项目目录未生成回测大表。
