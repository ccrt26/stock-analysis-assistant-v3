# V3 Target Retention Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重跑发现流程、不改变冻结名单的前提下，为 90 个形成日追加 10/20/30 日机会观察窗口内的盘中触及、收盘确认、确认后严格保持 1/2/3/5 日和失守路径，并把所有运行产物写入 U 盘独立目录。10/20/30 日不是固定持有期或卖出日，窗口末状态只作补充路径快照。

**Architecture:** 新增一个只读诊断模块，读取上一轮冻结 selections、evidence、decisions 和本地复权日线。模块先按唯一 `(block, formation_date, ts_code, horizon)` 计算路径，再展开到冻结 policy/layer，生成固定比较汇总、形成特征描述、案例、质量清单和中文报告。不得调用发现、压缩或生命周期形成函数。

**Tech Stack:** Python 3.11、pandas、numpy、PyArrow、PyYAML、pytest；沿用项目 `.venv`。

## Global Constraints

- 目标和非目标以 `docs/superpowers/specs/2026-07-19-v3-target-retention-diagnostic-design.md` 为准。
- 直接使用当前本地 `main`，不创建分支或工作树；用户已明确授权。
- 不使用子智能体，不提交、不激活、不部署。
- 所有运行产物只能写入 `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-target-retention-diagnostic`。
- 不覆盖 `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-18-v3-layered-validation`。
- 不改数据源、不重建特征、不调权重、不选择最优阈值、不生成新推荐名单。
- 运行停止上限 20 分钟。

---

### Task 1: 冻结配置、输入和 U 盘写入边界

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_target_retention_diagnostic.py`
- Create: `tests/test_v3_target_retention_diagnostic.py`
- Read: `docs/superpowers/specs/2026-07-19-v3-target-retention-diagnostic-config.yaml`

**Interfaces:**
- Produces: `RetentionConfig`, `load_config(path)`, `prepare_output_root(config, allowed_volume_root=...)`, `write_input_manifest(config)`。

- [ ] **Step 1: 写失败测试**

```python
def test_config_freezes_scope_and_forbids_rule_optimization():
    config = load_config(CONFIG_PATH)
    assert [block.id for block in config.blocks] == ["A", "B", "C"]
    assert config.horizons == (10, 20, 30)
    assert config.retention_windows == (1, 2, 3, 5)
    assert config.target_return == pytest.approx(0.20)
    assert config.rule_optimization_allowed is False

def test_output_root_must_be_exact_frozen_usb_directory(tmp_path):
    config = load_config(CONFIG_PATH)
    with pytest.raises(ValueError, match="U盘专用目录"):
        prepare_output_root(config, output_override=tmp_path / "wrong")
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/pytest tests/test_v3_target_retention_diagnostic.py -q`

Expected: collection failure because the new module does not exist.

- [ ] **Step 3: 实现最小配置和输出边界**

```python
@dataclass(frozen=True)
class RetentionConfig:
    experiment_id: str
    source_experiment_root: Path
    warehouse_root: Path
    output_root: Path
    blocks: tuple[Block, ...]
    horizons: tuple[int, ...]
    target_return: float
    retention_windows: tuple[int, ...]
    primary_horizon: int
    runtime_stop_minutes: int
    supported_policies: tuple[str, ...]
    rule_optimization_allowed: bool

def prepare_output_root(config, *, output_override=None, allowed_volume_root=Path("/Volumes/ZHUTONG")):
    output = Path(output_override) if output_override else config.output_root
    expected = Path(allowed_volume_root) / "股票分析助手-V3回测" / config.experiment_id
    if output.resolve(strict=False) != expected.resolve(strict=False):
        raise ValueError("输出路径必须是冻结的U盘专用目录")
    for child in ("manifests", "tables", "reports"):
        (output / child).mkdir(parents=True, exist_ok=True)
    return output
```

- [ ] **Step 4: 验证 Task 1**

Run: `.venv/bin/pytest tests/test_v3_target_retention_diagnostic.py -q`

Expected: Task 1 tests pass.

### Task 2: 计算唯一股票路径与右端观察状态

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_target_retention_diagnostic.py`
- Modify: `tests/test_v3_target_retention_diagnostic.py`

**Interfaces:**
- Consumes: `RetentionConfig`。
- Produces: `compute_retention_path(prices, formation_date, ts_code, horizon, target_return, retention_windows) -> dict`。
- Produces: `build_unique_paths(config) -> pandas.DataFrame`。

- [ ] **Step 1: 写触及、收盘确认、保持和观察不足测试**

```python
def test_touch_without_close_is_not_confirmed_or_retained():
    prices = _prices([10.0, 11.8, 11.4], highs=[10.0, 12.1, 11.5])
    row = compute_retention_path(prices, "2026-01-05", "A", 2, 0.20, (1, 2, 3, 5))
    assert row["target_touched"] is True
    assert row["close_confirmed"] is False
    assert pd.isna(row["retain_1"])

def test_close_confirmation_and_strict_retention_are_nested():
    prices = _prices([10.0, 12.0, 12.1, 12.2, 11.9, 12.4])
    row = compute_retention_path(prices, "2026-01-05", "A", 1, 0.20, (1, 2, 3, 5))
    assert row["close_confirmed"] is True
    assert row["retain_1"] is True
    assert row["retain_2"] is True
    assert row["retain_3"] is False
    assert row["first_close_loss_sessions"] == 3

def test_incomplete_post_confirmation_window_is_not_failure():
    prices = _prices([10.0, 12.0, 12.1])
    row = compute_retention_path(prices, "2026-01-05", "A", 1, 0.20, (1, 2, 3, 5))
    assert row["retain_1_observable"] is True
    assert row["retain_2_observable"] is False
    assert pd.isna(row["retain_2"])
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/pytest tests/test_v3_target_retention_diagnostic.py -q`

Expected: failures for undefined path functions.

- [ ] **Step 3: 实现路径计算**

```python
def compute_retention_path(prices, formation_date, ts_code, horizon, target_return, retention_windows):
    stock = prices[prices["ts_code"].astype(str) == str(ts_code)].sort_values("trade_date")
    formation = stock[stock["trade_date"] == pd.Timestamp(formation_date)]
    discovery = float(formation.iloc[0]["adj_close"])
    target = discovery * (1.0 + target_return)
    future = stock[stock["trade_date"] > pd.Timestamp(formation_date)].reset_index(drop=True)
    attainment = future.iloc[:horizon]
    touch_positions = np.flatnonzero(attainment["adj_high"].ge(target).to_numpy())
    close_positions = np.flatnonzero(attainment["adj_close"].ge(target).to_numpy())
    # First close confirmation determines the post-confirmation observation start.
    # retain_k is nullable when fewer than k quoted market sessions are available.
    # A missing stock close in an otherwise available market session makes that k unobservable.
```

The returned mapping must contain these exact fields: `first_touch_date`, `first_touch_session`, `first_close_confirm_date`, `first_close_confirm_session`, `retain_1_observable`, `retain_1`, `retain_2_observable`, `retain_2`, `retain_3_observable`, `retain_3`, `retain_5_observable`, `retain_5`, matching `advance_k`, `first_close_loss_date`, `first_close_loss_sessions`, `first_close_loss_return`, `post_confirm_max_close_return_5`, `post_confirm_min_close_return_5`, `post_confirm_max_drawdown_5`, `terminal_return` and `terminal_above_target`. `advance_k` is true only when `retain_k` is true and a later close in the same `k` window exceeds the confirmation close. `post_confirm_max_drawdown_5` is the minimum of `close / prior_running_max_close - 1` over the observable five-session path.

- [ ] **Step 4: 契约核对原盘中触及标签**

Join unique paths to the source `outcomes_all.parquet` on `(block, formation_date, ts_code, horizon)` and assert zero mismatches for `target_touched` and `formation_close` within floating tolerance.

- [ ] **Step 5: 验证 Task 2**

Run: `.venv/bin/pytest tests/test_v3_target_retention_diagnostic.py -q`

Expected: all path tests pass.

### Task 3: 展开冻结层级、形成固定汇总与规律探索表

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_target_retention_diagnostic.py`
- Modify: `tests/test_v3_target_retention_diagnostic.py`

**Interfaces:**
- Consumes: unique paths, source selections, frozen evidence and decisions。
- Produces: `expand_selection_outcomes(...)`, `summarize_retention(...)`, `summarize_route_combinations(...)`, `build_feature_diagnostics(...)`。

- [ ] **Step 1: 写汇总分母和嵌套测试**

```python
def test_summary_excludes_unobservable_retention_from_denominator():
    outcomes = pd.DataFrame({
        "block": ["A", "A"], "policy": ["research_union"] * 2,
        "layer": ["research"] * 2, "horizon": [20, 20],
        "target_touched": [True, True], "close_confirmed": [True, True],
        "retain_3_observable": [True, False], "retain_3": [True, pd.NA],
    })
    summary = summarize_retention(outcomes)
    assert summary.iloc[0]["retain_3_observations"] == 1
    assert summary.iloc[0]["retain_3_successes"] == 1

def test_close_confirmation_is_always_subset_of_touch():
    with pytest.raises(ValueError, match="收盘确认必须是盘中触及子集"):
        validate_outcome_contracts(_invalid_close_without_touch())
```

- [ ] **Step 2: 实现固定层级汇总**

Each `(block or ALL, policy, layer or all, horizon)` row must include:

```text
observations, touch_successes, touch_rate,
close_confirm_successes, close_confirm_rate, touch_to_close_rate,
retain_k_observations, retain_k_successes, retain_k_rate_all,
retain_k_rate_given_close, advance_k_successes, advance_k_rate_given_close,
right_censored_k, median_first_close_loss_sessions,
terminal_above_target_rate, median_terminal_return
```

`retain_k_rate_all` uses all horizon-complete records that also have observable post-confirmation status; `retain_k_rate_given_close` uses observable close-confirmed records. The report must display both and identify the denominator. `terminal_above_target_rate` and `median_terminal_return` remain supplementary path fields and must not enter the core support/reject comparison.

- [ ] **Step 3: 实现路线组合与形成特征描述**

Use one row per frozen research-pool `(formation_date, ts_code)` and classify into:

```text
no_touch
touch_only_no_close
close_confirm_no_retain_3
strict_retain_3
```

For the frozen fields, report counts and medians only. Do not search cut points or calculate weights.

- [ ] **Step 4: 验证 Task 3**

Run: `.venv/bin/pytest tests/test_v3_target_retention_diagnostic.py -q`

Expected: all summary and contract tests pass.

### Task 4: 生成质量清单、案例和详细中文报告

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_target_retention_diagnostic.py`
- Modify: `tests/test_v3_target_retention_diagnostic.py`

**Interfaces:**
- Produces: `generate_report(config) -> Path`, `run_diagnostic(config) -> Path`。
- Writes only to the frozen U-drive directory.

- [ ] **Step 1: 写报告边界测试**

```python
def test_report_names_touch_and_retention_without_calling_them_strategy_returns(tmp_path):
    report = generate_report_from_frames(_report_fixture(), tmp_path / "report.md")
    text = report.read_text(encoding="utf-8")
    assert "盘中触及率" in text
    assert "收盘确认率" in text
    assert "严格保持" in text
    assert "不是固定持有期或卖出日" in text
    assert "真实策略收益率" not in text
    assert "不能作为全新样本外证明" in text
```

- [ ] **Step 2: 实现报告章节**

The report must contain:

1. 写死目标与不能回答的问题；
2. 数据范围、完整性和观察不足；
3. 10/20/30 日机会观察窗口内的触及→收盘确认→保持漏斗，并明确窗口末收盘只作补充、不是卖出日；
4. 研究池与研究对照；
5. 压缩前后；
6. 重点与候补；
7. 三条入口和路线组合；
8. 形成特征描述性规律；
9. 代表性稳定、冲高回落、确认后失守案例；
10. 哪些现有样本支持、反对、证据不足、当前不可回答；
11. 下一轮规则设计允许使用的假设和禁止外推内容。

- [ ] **Step 3: 写质量清单**

`manifests/quality_checks.json` must include exact pass/fail and counts for:

```text
formation_dates_90
blocks_30_each
touch_contract_mismatches_zero
close_subset_touch
retain_nested_on_common_observable
unconfirmed_never_retained
right_censor_not_failure
summary_recomputable
source_directory_unchanged
runtime_within_limit
```

- [ ] **Step 4: 验证 Task 4**

Run: `.venv/bin/pytest tests/test_v3_target_retention_diagnostic.py -q`

Expected: all tests pass.

### Task 5: 运行、独立复算与交付检查

**Files:**
- Read: all source and generated files.
- Write: only frozen U-drive runtime artifacts.

**Interfaces:**
- CLI: `python -m stock_analyzer.evaluation.v3_target_retention_diagnostic --config <path>`。

- [ ] **Step 1: 运行完整相关测试**

Run: `.venv/bin/pytest tests/test_v3_target_retention_diagnostic.py tests/test_v3_layered_validation.py tests/test_historical_framework_validation.py -q`

Expected: zero failures.

- [ ] **Step 2: 运行诊断**

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_target_retention_diagnostic --config docs/superpowers/specs/2026-07-19-v3-target-retention-diagnostic-config.yaml`

Expected: exit 0 within 20 minutes and final report path on U drive.

- [ ] **Step 3: 独立复算关键数字**

Use a separate short Python process to read generated Parquet files and verify:

```python
assert unique_paths["formation_date"].nunique() == 90
assert unique_paths.groupby("block")["formation_date"].nunique().to_dict() == {"A": 30, "B": 30, "C": 30}
assert not ((unique_paths["close_confirmed"]) & (~unique_paths["target_touched"])).any()
assert quality_checks["all_passed"] is True
```

Recompute the 20-day research/control, compression and focus/candidate rates from `selection_retention_outcomes.parquet`; compare exact values to `retention_summary.parquet` and report text.

- [ ] **Step 4: 检查文件与格式**

Run: `git diff --check`

Run: `find /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-target-retention-diagnostic -maxdepth 2 -type f -print | sort`

Expected: only manifests, tables and reports under the new experiment directory; source experiment remains unchanged.

- [ ] **Step 5: 更新工作计划并交付**

Final response must link the design, implementation plan and U-drive report; summarize supported, rejected, insufficient and unanswerable findings without overstating exploratory evidence.
