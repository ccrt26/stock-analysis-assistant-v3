# V3 Next-Day Entry Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复用 90 个冻结形成日和名单，以次一市场交易日复权开盘价为行动价，验证现行框架股票在买入日起 20/30 个交易日内能否上涨至少 20%，并形成明确的保留/优化报告。

**Architecture:** 新增一个隔离的只读回测模块。模块从上一轮 `outcomes_all.parquet` 提取冻结股票—日期—policy/layer，读取本地日线、复权因子和涨跌停价，先计算唯一行动路径，再展开到冻结层级，生成固定比较、案例、质量清单和中文报告；不调用发现、压缩或生命周期形成代码。

**Tech Stack:** Python 3.11、pandas、numpy、PyArrow、PyYAML、pytest；沿用项目 `.venv`。

## Global Constraints

- 目标与口径以 `docs/superpowers/specs/2026-07-19-v3-next-day-entry-validation-design.md` 为准。
- 直接使用当前本地 `main`；不创建分支、工作树或提交，不使用子智能体。
- 只复用冻结名单，不重跑发现，不优化规则，不生成推荐，不激活或部署。
- A/B/C 各 30 个形成日，共 90 日；机会窗口固定为 20/30 日。
- 行动价固定为下一市场交易日复权开盘价，买入日计为第 1 日。
- 停牌/无报价与一字涨停不进入主可执行分母。
- 所有运行产物只写入 `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-next-day-entry-validation`，不得覆盖来源实验。
- 运行停止上限 20 分钟。

---

### Task 1: 冻结配置、输出边界与单条行动路径

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_next_day_entry_validation.py`
- Create: `tests/test_v3_next_day_entry_validation.py`
- Read: `docs/superpowers/specs/2026-07-19-v3-next-day-entry-validation-config.yaml`

**Interfaces:**
- Produces: `ActionConfig`, `load_config(path)`, `prepare_output_root(config, ...)`。
- Produces: `compute_action_path(prices, formation_date, ts_code, horizon, target_return, retention_windows) -> dict[str, Any]`。

- [ ] **Step 1: 写配置与输出边界失败测试**

```python
def test_config_freezes_next_open_and_90_formation_days():
    config = load_config(CONFIG_PATH)
    assert config.horizons == (20, 30)
    assert config.entry_delay_market_sessions == 1
    assert config.entry_price_field == "open"
    assert config.entry_day_counts_as_session_one is True
    assert [block.id for block in config.blocks] == ["A", "B", "C"]

def test_output_root_must_be_frozen_usb_directory(tmp_path):
    config = load_config(CONFIG_PATH)
    with pytest.raises(ValueError, match="U盘专用目录"):
        prepare_output_root(config, output_override=tmp_path / "wrong")
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `.venv/bin/pytest -q tests/test_v3_next_day_entry_validation.py`

Expected: import/collection failure。

- [ ] **Step 3: 实现配置和 U 盘写入边界**

配置数据类必须包含设计文档中的 blocks、horizons、target_return、retention_windows、entry delay/field/counting、one-price exclusion、runtime 和 supported policies，并拒绝任何偏离冻结值的配置。

- [ ] **Step 4: 写行动价、窗口计数和不可执行失败测试**

```python
def test_next_market_session_open_is_action_price_and_entry_day_counts():
    prices = _prices(
        opens=[10.0, 10.5, 10.6], highs=[10.1, 12.7, 10.8],
        lows=[9.9, 10.4, 10.5], closes=[10.0, 12.5, 10.7]
    )
    row = compute_action_path(prices, "2026-01-05", "A", 1, 0.20, (1, 3, 5))
    assert row["entry_session"] == 1
    assert row["action_price"] == pytest.approx(10.5)
    assert row["first_touch_session"] == 1

def test_one_price_limit_up_is_not_executable():
    prices = _prices(
        opens=[10.0, 11.0], highs=[10.0, 11.0], lows=[10.0, 11.0],
        closes=[10.0, 11.0], up_limits=[11.0, 11.0]
    )
    row = compute_action_path(prices, "2026-01-05", "A", 1, 0.20, (1, 3, 5))
    assert row["entry_status"] == "one_price_limit_up"
    assert row["executable_entry"] is False

def test_no_quote_on_next_market_session_does_not_roll_forward():
    prices = _prices_with_missing_next_day_quote()
    row = compute_action_path(prices, "2026-01-05", "A", 2, 0.20, (1, 3, 5))
    assert row["entry_date"] == pd.Timestamp("2026-01-06")
    assert row["entry_status"] == "no_quote_or_suspended"
    assert pd.isna(row["action_price"])
```

- [ ] **Step 5: 运行失败测试，随后实现最小路径计算**

单条路径必须返回 entry date/status/action price、formation-to-entry gap、complete horizon、target touched/close confirmed、first sessions、retain 1/3/5 observable/value、pre-touch minimum、window minimum、terminal return 和 mechanical sensitivity fields。

- [ ] **Step 6: 验证 Task 1**

Run: `.venv/bin/pytest -q tests/test_v3_next_day_entry_validation.py`

Expected: Task 1 tests pass。

### Task 2: 冻结名单展开、汇总和固定比较

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_next_day_entry_validation.py`
- Modify: `tests/test_v3_next_day_entry_validation.py`

**Interfaces:**
- Produces: `build_action_paths(config) -> tuple[unique_paths, expanded, input_paths]`。
- Produces: `summarize_actions(expanded, ...) -> DataFrame`。
- Produces: `build_comparisons(summary) -> DataFrame`。
- Produces: `validate_action_contracts(unique_paths) -> dict[str, bool]`。

- [ ] **Step 1: 写汇总分母失败测试**

```python
def test_summary_keeps_unexecutable_in_all_plan_yield_but_not_executable_rate():
    outcomes = _summary_fixture_one_success_one_unexecutable()
    row = summarize_actions(outcomes).iloc[0]
    assert row["planned_actions"] == 2
    assert row["executable_entries"] == 1
    assert row["touch_rate_given_executable"] == pytest.approx(1.0)
    assert row["touch_yield_all_plans"] == pytest.approx(0.5)
```

- [ ] **Step 2: 写嵌套和次日日期失败测试**

```python
def test_twenty_day_touch_is_subset_of_thirty_day_touch_on_common_paths():
    validate_action_contracts(_valid_20_30_nested_fixture())

def test_contract_rejects_wrong_entry_session():
    with pytest.raises(ValueError, match="下一市场交易日"):
        validate_action_contracts(_wrong_entry_date_fixture())
```

- [ ] **Step 3: 实现唯一路径构建与冻结结果展开**

读取来源 `outcomes_all.parquet`，只保留 20/30 日，按 `(block, formation_date, ts_code, horizon)` 去重计算行动路径，再 many-to-one 合并回原 policy/layer。读取日线时必须包括 raw open/high/low/close、adj_factor、up_limit；每个形成日之后至少读取 30 日加 5 日保持观察。

- [ ] **Step 4: 实现固定汇总和比较**

每个 `(block or ALL, policy, layer or all, horizon)` 汇总必须包含 planned/executable/unexecutable、entry execution rate、touch/close successes、given-executable rate、all-plan yield、retain 1/3/5、median first touch、median gap、median pre-touch minimum、median window minimum 和 supplementary terminal return。

固定比较只使用 touch、close 和 retain 路径指标，不把窗口末状态当成功指标。

- [ ] **Step 5: 验证 Task 2**

Run: `.venv/bin/pytest -q tests/test_v3_next_day_entry_validation.py`

Expected: all path, denominator and contract tests pass。

### Task 3: 中文报告、质量清单和 U 盘执行器

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_next_day_entry_validation.py`
- Modify: `tests/test_v3_next_day_entry_validation.py`

**Interfaces:**
- Produces: `generate_report_from_frames(frames, path) -> Path`。
- Produces: `run_validation(config) -> Path` and CLI `main()`。

- [ ] **Step 1: 写报告边界失败测试**

```python
def test_report_answers_next_day_action_question_without_claiming_realized_return(tmp_path):
    report = generate_report_from_frames(_report_fixture(), tmp_path / "report.md")
    text = report.read_text(encoding="utf-8")
    assert "次日开盘行动价" in text
    assert "20日机会窗口" in text
    assert "30日机会窗口" in text
    assert "哪些保留" in text
    assert "哪些需要优化" in text
    assert "不是固定卖出日" in text
    assert "保证实现收益" not in text
```

- [ ] **Step 2: 实现报告和解释函数**

报告必须逐项回答研究池、压缩、重点/候补、候选对照和三条入口；每项列出 20/30 日总体、A/B/C、可执行率、盘中达到、收盘确认、保持、跳空和回撤，并依据冻结判定语句写“保留、优化或证据不足”。

- [ ] **Step 3: 实现案例、清单和只写 U 盘的执行器**

输出设计文档列出的全部 Parquet/JSON/Markdown；质量清单必须逐项给出 pass/fail 和计数。运行前后核对来源目录签名，超 20 分钟立即停止。

- [ ] **Step 4: 验证 Task 3**

Run: `.venv/bin/pytest -q tests/test_v3_layered_validation.py tests/test_v3_target_retention_diagnostic.py tests/test_v3_next_day_entry_validation.py`

Expected: all relevant tests pass。

### Task 4: 执行、独立复算和框架登记

**Files:**
- Modify: `docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`
- Writes: `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-next-day-entry-validation/**`

- [ ] **Step 1: 执行冻结回测**

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_next_day_entry_validation --config docs/superpowers/specs/2026-07-19-v3-next-day-entry-validation-config.yaml`

Expected: prints exact U-drive report path and exits 0 within 20 minutes。

- [ ] **Step 2: 独立复算主要数字**

从 `selection_action_outcomes.parquet` 独立重算最终候选、候选对照、研究池、研究对照、重点和候补的 20/30 日 planned、executable、touch/close 和 retain 3；必须与 `action_summary.parquet` 零差异。

- [ ] **Step 3: 检查报告完整性并登记框架**

报告必须含 A/B/C、不可执行、全部计划产出率、可执行条件命中率、形成日至次日跳空、目标前不利波动、保留/优化/证据不足及不可回答内容。将冻结结果和文件路径追加到临时分析框架，不修改尚未由用户确认的正式规则。

- [ ] **Step 4: 最终验证**

Run:

```bash
.venv/bin/pytest -q tests/test_v3_layered_validation.py tests/test_v3_target_retention_diagnostic.py tests/test_v3_next_day_entry_validation.py
.venv/bin/python -m py_compile src/stock_analyzer/evaluation/v3_next_day_entry_validation.py
git diff --check
```

并核对 `quality_checks.json` 的 `all_passed=true`、U 盘报告存在、来源目录签名未变化。
