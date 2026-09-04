# 顶层定时股票研究与价格场景输入实施计划

> 历史记录：本文保留当时方案与事实，不作为当前运行入口或调度依据。当前时序以 `docs/architecture/current-v3-architecture.md` 和 `ops/forward-selection-prompt.md` 为准。

> **执行方式：** 当前工作区已经包含尚未提交的价格 Skill、市场 Skill 和验证代码，本计划在原工作区内按测试先行逐项执行，不创建会丢失这些状态的新 worktree。

**目标：** 让晚间和次晨任务持久化当前价格 Skill 的完整场景就绪输入，移除 Python 启动内层 Codex 的研究路径，并把 09:05 AI 研究收敛为 Codex 原生 Scheduled Task 直接调用总控 Skill。

**边界：** 程序只做时点安全的事实查询、确定性计算、健康检查、结果校验和归档；不自动分配场景结论，不把指标变成评分、Gate 或选股器，不修改三个现有数据任务的取数时刻。

**验收：** 11 个价格场景需要的全部阈值/事件字段可从每日派生分区获得；晚间和次晨派生会生成该分区并参与健康检查；仓库运行路径不再启动 `codex exec`；2026-08-19 已补算且时点、覆盖和幂等性通过；相关测试及全量测试通过。

---

## 任务 1：固化价格 Skill 场景—字段合同

**文件：**
- 修改：`docs/superpowers/specs/2026-08-20-direct-scheduled-stock-research-design.md`
- 新建：`src/stock_analyzer/analysis/price_analysis_features.py`
- 测试：`tests/test_price_analysis_features.py`

1. 在测试中逐项断言 `price_scenario_validation.SCENARIO_THRESHOLD_FIELDS` 与场景分配所需布尔事件字段都属于每日价格场景输入合同。
2. 增加失败测试，输入包含形成日后的极端行情，断言 2026-08-19 结果不变化；输入历史短于 251 个会话时断言长期前高字段为空并带 `limited` 说明。
3. 实现 `PRICE_ANALYSIS_FORMULA_VERSION = "price-analysis-context-v1"` 和组合计算函数：复用现有基线价格路径公式与 `compute_price_indicator_features`，按 `analysis_date, ts_code` 一对一合并，并保留技术组件版本 `price-indicator-conditional-states-v2`。
4. 输出覆盖价格 Skill 的六个信息维度及 11 个场景所需的阈值/事件字段；只输出观察值、质量状态和限制，不输出自动场景票或买卖结论。
5. 运行 `./.venv/bin/pytest tests/test_price_analysis_features.py tests/test_price_indicator_features.py tests/test_price_indicator_validation.py tests/test_price_scenario_validation.py -q`。

## 任务 2：接入晚间和次晨派生任务

**文件：**
- 修改：`src/stock_analyzer/ops/research_features.py`
- 修改：`tests/test_research_feature_job.py`
- 修改：`tests/test_research_data_job.py`

1. 先扩充派生任务测试，断言第四个特征集为 `price_analysis_context`，实体键是 `analysis_date, ts_code`，公式版本正确，行情/复权/指数/涨跌停输入都受同一 `as_of` 约束，并至少请求 251 个形成日及以前的交易会话。
2. 断言输入未变化时四个特征集全部幂等跳过，事实版本变化时只按输入清单重新提交。
3. 在 `run_research_features` 中增加独立的价格场景输入提交边界和 `price_rows` 汇总；复用现有 `ResearchQuery`、输入清单、内容哈希和原子提交。
4. 保持 close 阶段不派生；验证 evening 和 next-morning 仍通过同一个 `run_research_features` 入口生成全部四类派生结果。
5. 运行 `./.venv/bin/pytest tests/test_research_feature_job.py tests/test_research_data_job.py -q`。

## 任务 3：把价格场景输入纳入研究健康检查

**文件：**
- 修改：`src/stock_analyzer/ops/research_health.py`
- 修改：`tests/test_research_health.py`

1. 先增加失败测试，证明缺少、公式过期、文件哈希错误或输入清单过期的 `price_analysis_context` 会令 `derived_ready_for_research=false`。
2. 将 `price_analysis_context: price-analysis-context-v1` 加入预期派生公式合同。
3. 保持允许 `complete_with_declared_gaps`，使短历史股票的明确限制不会被误判为任务失败。
4. 运行 `./.venv/bin/pytest tests/test_research_health.py -q`。

## 任务 4：移除 Python 嵌套 Codex 运行器

**文件：**
- 修改：`src/stock_analyzer/ops/forward_selection.py`
- 修改：`tests/test_forward_selection.py`
- 删除：`ops/launchd/com.ccrt.stock-analysis-assistant.forward-selection.plist.example`

1. 用行为测试定义两个确定性动作：`prepare` 负责冻结/校验形成日、行动日、`as_of`、数据健康和 D20 结算；`record` 读取顶层 Codex 已产生的结构化 JSON，校验五个 Skill、候选资格、0—5 只和时点边界，然后原子归档。
2. 删除 `CodexResearch`、ASCII 临时项目视图、Codex 路径解析、子进程、stderr 活动日志和内层等待循环；任何仓库 CLI 都不得启动模型。
3. 保留现有结果模型、资格校验、空名单语义、重复形成日保护和 D20 一次性结算。
4. 删除 09:05 forward LaunchAgent 模板及其测试；测试 `prepare` 在系统没有 Codex CLI 时仍可完成，`record` 只消费显式结果文件。
5. 运行 `./.venv/bin/pytest tests/test_forward_selection.py -q`。

## 任务 5：更新顶层 Scheduled Task 说明和架构

**文件：**
- 修改：`ops/forward-selection-prompt.md`
- 修改：`docs/architecture/current-v3-architecture.md`

1. 把提示模板改为 Codex 原生 Scheduled Task 的顶层提示：明确调用 `$orchestrating-stock-research`，先运行确定性 `prepare`，冻结早于 09:30 的 `as_of`，再由总控在同一会话使用四个专业 Skill，最后把结构化结果交给 `record`。
2. 明确运行超过 18 分钟或 09:30 不使结果失效；唯一硬边界是不能读取冻结 `as_of` 之后和形成日之后的事实。
3. 更新架构图、运行时职责和健康检查说明；删除 Python → Codex 与本地 09:05 LaunchAgent 的描述。
4. 运行文档/代码引用检查，确认不存在可执行的内层 Codex 启动路径，同时允许文档在“已移除”语境中提及它。

## 任务 6：补算并核验 2026-08-19

**文件：**
- 运行产物：`local_warehouse/derived/price_analysis_context/analysis_date=2026-08-19/`
- 运行产物：`local_archive/data_health/2026-08-19.json`

1. 运行 `./.venv/bin/python -m stock_analyzer data derive --data-date 2026-08-19`，仅使用本地事实仓。
2. 查询派生清单和 Parquet，核对公式版本、技术组件版本、`analysis_date`、股票覆盖、场景字段、形成日截断、`as_of` 输入清单和质量限制。
3. 以相同输入重跑，断言为幂等跳过或内容哈希完全一致。
4. 运行 `./.venv/bin/python -m stock_analyzer data health --data-date 2026-08-19` 并核对 `price_analysis_context` 就绪状态。

## 任务 7：停用旧 09:05 本地任务并完成回归验证

**文件：**
- 只读/外部状态：`~/Library/LaunchAgents/com.ccrt.stock-analysis-assistant.forward-selection.plist`

1. 先用 `launchctl print gui/501/com.ccrt.stock-analysis-assistant.forward-selection` 和明确路径检查旧任务状态；存在时卸载，并把 plist 移到可恢复备份位置，不触碰三个数据 LaunchAgent。
2. 运行相关测试后再运行 `./.venv/bin/pytest -q`。
3. 检查 `git diff --check`、相关文件差异和工作区状态，确认没有覆盖用户的无关改动。
4. 交付 Codex 原生 09:05 Scheduled Task 的最终提示和设置步骤；由于当前会话没有 Scheduled Task 写入接口，这一步由用户在 Codex 界面创建或更新。
