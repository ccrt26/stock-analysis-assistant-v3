# 股票分析助手 V3：selection_lab、机会类型建模与 GitHub 交付正式执行 Prompt

**冻结日期：** 2026-08-17
**适用仓库：** `ccrt26/stock-analysis-assistant-v3`
**执行分支：** `feat/selection-lab-opportunity-types`
**唯一业务目标：** 在形成日已经掌握的信息下，判断能否从同日真实冻结候选池中，把未来更可能在行动日起 20 个真实交易日内以复权收盘价相对行动日开盘上涨至少 20% 的股票稳定排到前面，并判断是否已有证据支持每日 0—5 只的高精度影子选择。

本文是本轮唯一正式执行合同。出现冲突时，依次服从 `AGENTS.md`、当前架构文档、当前五个研究 Skill、本文件；历史报告只提供日期污染和既有证据，不自动成为新规则。

## 1. 执行纪律

1. 开始实现前完整阅读：
   - `AGENTS.md`；
   - `README.md`；
   - `docs/architecture/current-v3-architecture.md`；
   - `.agents/skills/orchestrating-stock-research/SKILL.md`；
   - `.agents/skills/interpreting-market-macro/SKILL.md`；
   - `.agents/skills/researching-sectors-industries/SKILL.md`；
   - `.agents/skills/researching-company-events/SKILL.md`；
   - `.agents/skills/analyzing-price-trading/SKILL.md`；
   - `docs/` 中候选链、成熟历史回放、三组对照、最终取舍、候选发现和前期上涨惩罚的全部现有报告。
2. 本 Prompt 已按 `AGENTS.md` 完成唯一一次 `gpt-5.6-sol`、`xhigh` 独立审查，并直接采用完整修订语义；不复审，不再启动其他智能体。
3. 主智能体连续完成设计、计划、TDD 开发、实验、验证、报告、提交、推送和 draft PR。只有权限、凭据或本地数据形成真实阻碍时才停止对应动作。
4. 不从历史报告文字重建机器候选链，不用当前证券身份倒填历史，不用未来收益定义机会类型。
5. 在任何未来标签生成前，先冻结并哈希：形成日/行动日/标签窗口/split、历史日期使用清单、特征字典/公式/来源/列顺序/缺失语义、机会类型合同、模型/预处理/超参数/排序/阈值规则，以及评价指标与结论判定。
6. 标签揭示状态分开审计：`features_frozen`、`development_labels_opened`、`validation_labels_opened`、`final_test_labels_opened`。
7. 在最终测试标签第一次打开后，禁止新增特征、修改机会类型、标签、日期、评价口径、模型族、超参数候选、阈值候选或成功条件。
8. 已知主轨数据不足不取消本地工具、合同和审阅交付，但不得用次级轨结果回答主业务问题。

## 2. 冻结版本与基线

### 2.1 Git

```yaml
base_commit: ad7d1385dbeb1c91771af66a3294da74b857c2b0
base_branch: main
remote_tracking_branch: origin/main
work_branch: feat/selection-lab-opportunity-types
preexisting_untracked_paths:
  - bingo/
  - who-is-it/
```

`bingo/` 和 `who-is-it/` 属于用户既有内容，不读取、不修改、不暂存、不提交。所有提交必须显式列出路径，禁止对混合工作树使用无审查的 `git add -A`。

### 2.2 五个 Skill SHA-256

```yaml
orchestrating-stock-research: 48f733f30a9aeeb1b03ebd2ecfe859c16b0f51a132c97515133d7246aace8d47
interpreting-market-macro: 6471ea1f6ac667a47c9c52395fd9d3f82e7d98a1c38458245c568cf731c8faa5
researching-sectors-industries: 8107dcd47150c65721b7e4e148e417a40bcddac78490e12b58f8fc79433d620c
researching-company-events: af041e6f97001188fb7de5db67715c364089d9fe6694fe1f1afd7eb0ebb718a4d
analyzing-price-trading: a320abf2c60e8a97fa1fa84b285dccc5c9bf104360bb30bdd358c93b14eb5a4d
```

第一阶段以这些哈希冻结候选发现语义。影子排序实验完成前不得修改 Skill。机会类型语义修正必须单独提交，并明确它是职责修正，不是经过收益验证的改进。

### 2.3 测试与工具基线

```yaml
python: ">=3.11"
baseline_command: ".venv/bin/python -m pytest -q"
baseline_result: "361 passed in 78.25s"
gh_version: "2.93.0"
gh_auth_status: "installed but current github.com credential is invalid"
```

GitHub 认证只影响最终推送/PR，不得妨碍本地实现和验证；若最终仍无权限，报告准确阻碍，不得推到 `main`。

## 3. 本地数据覆盖与能力冻结

只读盘点于 2026-08-17 完成，未读取本轮冻结日期的未来标签统计。

### 3.1 事实仓

```yaml
equity_daily: {partition_range: [2021-07-14, 2026-08-14], rows: 6399786, quality: passed}
adj_factor: {partition_range: [2021-07-14, 2026-08-14], rows: 6478684, quality: passed}
daily_basic: {partition_range: [2021-07-14, 2026-08-14], rows: 6381468, quality: passed}
stock_limit: {partition_range: [2021-07-14, 2026-08-14], rows: 8217385, quality: passed}
index_daily: {partition_range: [2021-07-14, 2026-08-14], rows: 9680, quality: passed}
trade_calendar: {partition_range: [2021, 2026], rows: 1850, quality: passed}
industry_daily: {partition_range: [2025-07-02, 2026-08-14], rows: 8494, quality: passed}
theme_daily: {partition_range: [2025-07-02, 2026-08-14], rows: 65486, quality: passed}
announcement: {partition_range: [2025-07, 2026-08], rows: 733966, quality: passed}
earnings_forecast: {partition_range: [2021-07, 2026-08], rows: 20616, quality: passed}
earnings_express: {partition_range: [2022-01, 2026-08], rows: 6350, quality: passed}
financial_statements: {report_period_range: [2021-12-31, 2026-06-30], quality: passed}
main_business: {report_period_range: [2021-12-31, 2026-06-30], rows: 508470, quality: passed}
security_master:
  rows: 5882
  earliest_available_at: "2026-07-13T23:38:30.798194+08:00"
  limitation: "2026-07-13 之前无法严格回放证券名称、ST 状态和完整身份"
```

### 3.2 已派生观察

`market_context`、`sector_hotspot`、`stock_trading_context` 各有 29 个已提交分区，但只有 26 个不同 `analysis_date`：`2025-08-15`，以及 `2026-07-13` 至 `2026-08-14` 的 25 个交易日。同一日期可能存在多个公式版本，不得把分区数写成已有日期数。未提交日期可按冻结公式从时点安全事实重算，但只能写入被忽略的本地实验目录，不得冒充原有已提交观察。

### 3.3 研究记录能力

- Git 中的历史报告含叙述性候选链和聚合统计，但当前本地归档没有可直接导入的、逐日机器可读且不可变的完整 `candidate_chain` 文件。
- 不得从报告文字事后重建候选池并冒充原始 AI 候选池。
- 因此 `frozen_candidate_chain` 是主评价轨，但只有实际发现合格机器记录时才能运行；当前预检状态为 `unavailable`。
- `deterministic_research_surface` 可从时点安全行情及其他事实构建次级探索轨，但无法证明默认证券身份、ST 和完整合格范围，只能标记为身份不完整的探索轨。
- `full_universe` 只有在每个形成日都能以 `available_at <= formation_as_of` 取得合格范围身份和排除信息时才启用；全部冻结日期早于 `security_master` 首次可用时间，因此预检状态为 `blocked_by_point_in_time_security_master`。

数据不存在、覆盖不足、查询失败、当前快照不可回放和真实无记录必须分别编码。不得用当前证券名称、当前 ST 状态或未来修订补齐历史。

### 3.4 已知能力对结论的约束

除非执行时发现此前遗漏且确实在形成日冻结的机器记录，否则：主轨样本为零；当前 AI 入选/淘汰、隐性公司 Gate、完整范围基础率、机会类型对主轨排序的收益效果均不可评价；主业务结论必须为 `实验阻塞`。次级轨即使出现良好数字，也只能写“身份不完整的探索结果”，不能升级主结论。这不阻碍本地程序、合同、测试和审阅包交付。

## 4. 研究轨道与业务边界

### 4.1 三条轨道

1. `frozen_candidate_chain`：唯一主轨。机器记录必须证明当时实际候选集合、`selected | rejected | unresolved`、原始来源/理由、形成日/`as_of`/冻结时间，以及未由未来或报告重建。只有该轨可比较 AI fate、评价真实候选池影子排序、审计隐性公司 Gate 或支持主业务排序结论。
2. `deterministic_research_surface`：每个冻结形成日纳入所有可由 `available_at <= formation_as_of` 事实重算 `stock_trading_context` 的代码，不使用 Top-N、未来结果或赢家筛选。`eligibility_status` 必须为 `unknown_identity_history`，不得写 `eligible: true`；没有形成日冻结因果命题时 `opportunity_type: null`。该轨可验证数据、标签、切分、基线和无类型模型管道，不得称为真实候选池或完整范围。
3. `full_universe`：只有形成日可取得证券身份、上市状态、板块范围、ST、退市、停牌和可靠报价时启用。能力不足即关闭，禁止用当前快照、代码或涨跌停幅度推断并冒充完整范围。

不默认扩大候选池，不因单只历史牛股追加 Skill 文字，不恢复固定评分、权重或 Gate。允许 0—5 只和空名单，不按数量补位。

### 4.2 明确不做

- 实际买入日期或价格区间；
- 用户持仓；
- 目标兑现日期预测；
- 卖出提醒、止盈止损、仓位；
- 券商连接、自动交易；
- 云端发布；
- Supabase、Cloudflare 或旧 V3 路径；
- 每日无人值守 AI 选股运行器；
- XGBoost、LightGBM、神经网络、深度生存模型、强化学习、大模型微调、多模型堆叠、自动特征搜索或大规模超参数搜索。

## 5. 时间、入口和标签合同

每个股票—形成日样本冻结：

```yaml
formation_date: YYYY-MM-DD
formation_as_of: "YYYY-MM-DDT23:59:59+08:00"
action_date: "形成日后的第一个真实交易日"
```

形成日特征只允许 `available_at <= formation_as_of`。行动日正常可执行时以行动日开盘价为统一离线实验入口；这是实验入口，不是未来买入建议。

行动日计作第 1 个交易日，观察第 1—20 个真实交易日。任一日复权收盘价相对统一入口达到 `>=20%` 即：

```yaml
hit_20pct_close_within_20d: true | false | null
```

盘中最高价触及不算主标签；第 21 日才达标仍为 false；已经在第 1—20 日收盘达标的股票不能因第 20 日回落改判；标签窗口不完整为 null，不得当作 false。

同时生成：

```yaml
executable_on_action_date: true | false | null
first_hit_day: 1-20 | null
max_close_return_20d: float | null
terminal_return_20d: float | null
terminal_relative_market_20d: float | null
max_adverse_move_before_hit_or_end: float | null
giveback_from_max_close_to_terminal: float | null
```

入口、收盘、最低价和最高价必须使用一致复权口径。停牌、一字涨停/跌停、无可靠开盘或报价时按明确可执行性合同处理。排名在形成日冻结，不得看到行动日可执行性后递补候选。

同时报告：`policy_precision@K` 按形成日原 Top-K 计算，不可执行视为未实现且不递补；`executable_precision@K` 只在原 Top-K 中实际可执行股票上计算，作为辅助指标。主成功条件使用 policy 口径，避免行动日未来状态优化候选集合。

## 6. 日期冻结与防泄漏

日期只依据交易日历、数据截止、历史文档日期使用记录和 20 日标签完整性选择；没有读取这些日期的标签比例或模型表现。

### 6.1 开发形成日（30）

```text
2025-12-30,
2026-01-05, 2026-01-06, 2026-01-07, 2026-01-08, 2026-01-09,
2026-01-12, 2026-01-13, 2026-01-14, 2026-01-15, 2026-01-16, 2026-01-19,
2026-01-22, 2026-01-23, 2026-01-27, 2026-01-28, 2026-01-29, 2026-01-30,
2026-02-02, 2026-02-03, 2026-02-04, 2026-02-05, 2026-02-06,
2026-02-10, 2026-02-11, 2026-02-12, 2026-02-13, 2026-02-26,
2026-03-02, 2026-03-04
```

最后一个开发形成日 `2026-03-04` 的行动日为 `2026-03-05`，标签窗口结束于 `2026-04-01`。

### 6.2 验证形成日（10）

```text
2026-04-02, 2026-04-03, 2026-04-09, 2026-04-10,
2026-04-13, 2026-04-14, 2026-04-15, 2026-04-16,
2026-04-17, 2026-04-20
```

第一个验证形成日 `2026-04-02` 严格晚于开发标签末日；两组形成日之间有 20 个完整交易日。最后一个验证形成日 `2026-04-20` 的行动日为 `2026-04-21`，标签窗口结束于 `2026-05-21`。

### 6.3 最终测试形成日（10）

```text
2026-05-26, 2026-06-02, 2026-06-04, 2026-06-05,
2026-06-12, 2026-06-16, 2026-06-22, 2026-06-29,
2026-07-01, 2026-07-02
```

第一个最终测试形成日 `2026-05-26` 严格晚于验证标签末日；两组形成日之间有 22 个完整交易日。最后一个测试形成日 `2026-07-02` 的行动日为 `2026-07-03`，标签窗口结束于 `2026-07-30`。

这 50 个形成日均未在冻结时的 base commit `docs/*.md` 中作为日期字面量出现。实现必须基于 `base_commit` 的 Git 内容生成 `previously_used_formation_dates.json`，不能扫描当前 Prompt/设计/本轮新文件造成自污染；日期出现须区分真正 formation date、验证/确认/留出/揭盲日期和普通数据/公告/业务日期。最终测试日期若在 base commit 中确曾作为形成日且未来已打开，不替换日期，只标污染并减少独立测试日数；不足 10 个时不得给“有稳定排序信号”。

### 6.4 时间切分规则

- 禁止随机拆分股票行；同一形成日所有行必须属于同一 split。
- 必须从交易日历重算并测试：`max(development.label_end) < min(validation.formation_date)` 和 `max(validation.label_end) < min(final_test.formation_date)`。
- 训练插补、标准化、one-hot 类别和模型只能在训练数据拟合。
- 验证集只选择预先冻结的超参数；最终测试标签不能参与特征选择、机会类型定义、阈值或超参数选择。
- 主轨最低门槛：开发 30 个形成日、30 个正例行、10 个正例日期；验证 10/10/5；最终测试 10/10/5。每个 split 同时存在正负两类。
- 主轨存在但未满足门槛时只能是初步证据或没有证明；主轨机器记录为零或无法证明冻结时必须为 `实验阻塞`。不得用次级轨代替主轨证明。

## 7. 数据集、血缘和本地边界

每行一只股票在一个形成日的状态，至少包含：

```yaml
formation_date: ""
formation_as_of: ""
action_date: ""
ts_code: ""
research_track: frozen_candidate_chain | deterministic_research_surface | full_universe
eligibility_status: eligible | ineligible | unknown_identity_history
candidate_status: selected | rejected | unresolved | non_candidate
rejection_reason_code: ""
opportunity_type: company_catalyst | sector_diffusion | independent_price_anomaly | null
opportunity_type_status: assigned | not_assignable | missing_evidence
secondary_opportunity_types: []
opportunity_type_confidence: ""
opportunity_type_evidence: []
market_features: {}
sector_features: {}
company_features: {}
price_features: {}
data_quality_features: {}
future_labels: {}
```

形成日数据和未来标签分开物理保存并分别哈希；打开标签不得重写最终测试特征文件。逐样本或逐构建批次保存：provider、dataset、fact_as_of、available_at、quality、missing fields、capability status、特征公式版本、输入分区/清单哈希、base/实现 commit、数据集构建版本和标签揭示状态。

新增隔离目录：

```text
local_warehouse/selection_lab/
local_archive/selection_lab/
local_models/selection_lab/
```

三者均加入 `.gitignore`。完整数据集、预测和模型只能写入这些本地目录。不得提交 DuckDB、Parquet 完整样本、逐股完整预测、pickle/joblib/二进制模型、Token、`.env*`、日志、本地绝对路径、原始大体量行情/公告或用户个人产物。

## 8. 机会类型合同

每个候选或实验样本必须包含：

```yaml
opportunity_type: company_catalyst | sector_diffusion | independent_price_anomaly | null
opportunity_type_status: assigned | not_assignable | missing_evidence
secondary_opportunity_types: []
opportunity_type_confidence: high | medium | low | null
opportunity_type_as_of: ""
opportunity_type_evidence: []
opportunity_type_assignment_reason: ""
```

主要类型表示：去掉哪一条因果起点后，该股票在形成日便不再构成原机会命题。多来源不能按 Skill 数量投票；其他真实类型写入次要类型。类型只能使用形成日事实，不得根据未来涨跌倒填。

### 8.1 `company_catalyst`

核心起点是公司自身的新变化，如业绩预告/快报、订单、产品/产能/价格、重组收购、经营改善、重大合同或公司特有传导。必须验证直接公司事实、阶段、新鲜度、材料性、对收入/利润/现金流/预期的传导、非经常性损益和公司反证。没有直接公司事实时不得分类为 `company_catalyst`，不只是降低置信度。

### 8.2 `sector_diffusion`

核心起点是行业、主题或产业链共同增强和成员扩散。必须验证形成日有效成员关系、板块相对市场、成员广度、中位数收益、成交份额、扩散、集中/分化/退潮、候选同类增量和真实业务归属。不要求形成日存在新公司公告；公司 Skill 只确认身份、主营联系和重大反证。

### 8.3 `independent_price_anomaly`

核心起点是市场和板块共同变化不能充分解释的个股相对价格与成交异常。可无新公司公告，但必须更严格检查相对市场、相对行业/同类、成交推进、高成交低推进、冲高回落/上影、价格效率、波动/ATR、价格位置、涨停及后续、流动性、停牌交易状态、低流动性瞬时波动、透支、假突破和公司重大负面事实。

无法形成因果命题时必须使用 `opportunity_type: null` 与 `opportunity_type_status: not_assignable | missing_evidence`，不得为 one-hot 强猜。机会类型不是 Gate、配额、评分、优先级、投票或补位规则；不得每类固定数量/权重，不得天然贬低独立价格异常，不得用代码顺序处理并列。`deterministic_research_surface` 没有原始形成日命题时默认类型为 null。

## 9. 隐性公司 Gate 审计

结构化淘汰原因：

```text
no_direct_company_catalyst
company_transmission_weak
sector_diffusion_weak
peer_advantage_missing
price_not_independent
price_overextended
volume_price_divergence
liquidity_or_tradability
data_quality_block
major_counterevidence
other
```

对每个完整候选链日期逐只审计：

1. `sector_diffusion` 是否仅因没有新公司公告被淘汰；
2. `independent_price_anomaly` 是否仅因没有公司催化被淘汰；
3. 公司 Skill 是否把“没有新变化”写成“公司不相关”；
4. 总控是否文字允许多类型、最终却把公司催化当必要条件；
5. 同类入选/淘汰是否使用不对称标准；
6. 行为出现的日期数和股票数；
7. 这些股票的主标签只用于评价错误代价，不得改写形成日类型和理由。

```yaml
sole_company_gate_rejection: true | false | null
```

只在主要类型为 `sector_diffusion` 或 `independent_price_anomaly`、本类型核心证据已具备、没有身份/可交易性/重大负面阻碍，而主要淘汰理由仅为缺少新公司催化时为 true。输出总体与逐类型交叉统计。没有机器可读完整候选链时，`gate_audit_status: not_evaluable` 且 `sole_company_gate_rejection: null`，不能从报告叙述确认或否认 Gate。

## 10. 冻结特征范围

所有数值保留缺失指示；插补器只在训练集拟合。优先复用现有确定性公式，不重建数据平台。在读取任何标签前，`feature_dictionary.json` 必须冻结每个字段的精确列名、类型、公式、窗口、来源数据集、`available_at` 规则、缺失语义、公式版本以及是否进模型/仅审计。下列通配名称必须在开标签前展开为固定列清单；没有明确公式或时点安全来源的列排除，不得看开发结果后补充。

### 10.1 市场白名单

- `equal_weight_return_{1,5,20}d`、`median_return_{1,5,20}d`、`breadth_{1,5,20}d`；
- `turnover_ratio_{5,20}d`；
- `above_ma_{20,60}d_share`；
- `new_high_{20,60}d_share`、`new_low_{20,60}d_share`；
- `return_dispersion_1d`、`realized_volatility_20d_annualized`；
- `limit_up_share`、`near_limit_up_share`、`limit_down_share`；
- 覆盖率和质量缺失指示。

### 10.2 板块白名单

- `relative_return_{1,5,20}d`、`median_return_{1,5,20}d`、`breadth_{1,5,20}d`；
- `turnover_share_average_{1,5,20}d`、`turnover_share_change_{3,5}d`；
- `top3_positive_contribution_1d`、`return_dispersion_1d`；
- `new_high_{20,60}d_share`、`limit_up_share`；
- `high_volume_low_progress_flag`、`upper_wick_reversal_flag`、`narrow_participation_flag`、`turnover_return_divergence_flag`；
- 候选相对板块/同类收益与历史成员覆盖质量。

### 10.3 公司白名单

- 公司事件是否存在、事件类型、首次可用时间、距形成日天数、阶段、是否修订；
- 业绩预告中值；收入、利润、经营现金流方向及是否同向改善；
- 非经常性损益风险、合同/事项规模；
- 回购阶段、减持、解禁、质押；
- 负债和现金流反证；
- 公告正文完整性和所有数据质量/缺失标记。

只使用结构化、形成日可见事实；文本嵌入、文档长度和证据条数不进入第一轮。

### 10.4 价格白名单

- `return_{1,5,10,20,60}d`、`relative_return_{1,5,10,20,60}d`；
- 相对板块和最接近同类收益；
- `beta_60d`、`downside_beta_60d`、`benchmark_correlation_60d`；
- `realized_volatility_20d_annualized`、`atr_ratio_20d`；
- `price_location_{60,82}d`；
- `current_amount_ratio_20d`、`up_down_amount_ratio_60d`；
- 高成交价格推进效率、`high_volume_*`、`countertrend_*`；
- `recent_limit_up_count_5d`、最近涨停日、涨停后行为；
- 流动性、`pe_ttm`、`pb` 及可用历史分位；
- 覆盖质量和缺失指示。

### 10.5 禁止特征

未来价格、未来公告、后续修订、未来名称、行动日可执行性、文档长度、研究文字字数、证据条数、来源 Skill 数量、报告完整度、股票代码或输入顺序、AI 是否入选、未来才知道的数据质量状态和未来标签的任何变形都禁止。`current_ai_fate` 只用于基线与误差分析。

## 11. 模型、基线与排序输出

可选依赖：

```toml
[project.optional-dependencies]
selection-lab = ["scikit-learn>=1.5,<2"]
```

生产最小依赖不增加 scikit-learn。

### 11.1 必须比较

1. 完整合格范围基础达标率（只有 `full_universe` 可用时）；
2. 当前候选池基础达标率；
3. 按形成日、固定种子随机选择；
4. 5 日相对市场收益；
5. 20 日相对市场收益；
6. 成交推进简单排序；
7. 公司事件新鲜度简单排序；
8. 当前冻结 AI 选择（仅完整原始候选链日期）；
9. 不含机会类型的 L2 逻辑回归；
10. 含 `opportunity_type` one-hot 的 L2 逻辑回归。

随机基线固定种子 `20260817`，做 1,000 次日期内可复现随机排列并报告均值和区间。所有方法报告 Top 1、3、5；并列只使用 `sha256("20260817|formation_date|ts_code|dataset_version")` 的稳定伪随机键打破，不使用代码字典顺序。

形成日候选数为 `n` 时，`effective_k=min(K,n)`，`Precision@K=policy_hits_in_top_effective_k/effective_k`；`n=0` 时该日为 null 并单列无候选日期。所有排序先冻结，再打开行动日可执行性和标签。

### 11.2 冻结逻辑回归

```yaml
numeric_pipeline:
  imputer: {strategy: median, add_indicator: true}
  scaler: StandardScaler
categorical_pipeline:
  imputer: {strategy: most_frequent}
  encoder: {type: OneHotEncoder, handle_unknown: ignore}
classifier:
  type: LogisticRegression
  penalty: l2
  solver: liblinear
  class_weight: null
  max_iter: 2000
  tol: 1.0e-6
  random_state: 20260817
hyperparameter_candidates:
  C: [0.1, 1.0, 10.0]
selection_rule: "验证集形成日等权 policy Precision@5 最高；并列时依次选 Brier 更低、C 更小"
```

两个模型必须使用相同样本行、数值特征、基础分类特征、训练日期、预处理和调参规则；唯一差异是第二个模型加入主要 `opportunity_type` one-hot，次要类型与类型证据不进入模型。训练集只有一个标签类别时状态为 `not_trainable`。

每个模型独立按相同规则选 C。只有含类型模型的验证集 `policy Precision@5` 比无类型模型至少高 2 个百分点且 Brier 不更差，才冻结含类型模型；否则或不可评价/并列时冻结无类型模型。冻结变体与 C 后，允许在开发加验证数据重拟合同一管道，再一次性评价最终测试。保存特征顺序、超参数、系数和截距，不保存模型二进制到 Git。

Walk-forward 使用固定 `C=1.0`、不调参的同一模型，两折固定为：开发训练/验证测试；开发加验证训练/最终测试。每折训练标签窗口必须早于测试形成日。稳定结论要求两折相对候选池的 `policy Precision@5` 方向均为正；主轨不可用时为 null。

### 11.3 0—5 只

Top 1/3/5 是比较指标，不等于强制每日选满。0—5 影子选择只对验证后冻结的最终模型执行。阈值候选固定为 `0.10, 0.15, ..., 0.90`，步长 0.05；每日选择概率不低于阈值的最多前 5 只，不足不补位。

验证阈值须同时满足至少 7/10 个非空日期、至少 20 个总选择、每日不超过 5。选择规则：空名单日期精度记 0 后日期等权精度最高；并列依次用非空日期条件精度、非空日期数、较高阈值。没有阈值满足覆盖约束时 `zero_to_five_status: not_supported`、`threshold: null`。

阈值冻结后原样用于最终测试。只有最终测试至少 7 个非空日期、至少 20 个选择、相对候选池提高至少 5 个百分点、入选高于同日剩余候选、提升来自不止一个日期且无泄漏，才可写“已有 0—5 影子选择初步支持”。主轨不可用时为 `not_evaluable`，不得声称支持生产决策。

## 12. 评价口径

所有总体指标先按形成日计算，再对形成日等权汇总。

主要指标：

- `policy Precision@1/@3/@5` 与 `executable Precision@1/@3/@5`；
- 相对候选池 `Lift@1/@3/@5`；
- 相对当前 AI 入选的提升；
- AI 入选/淘汰达标率；
- 模型 Top 5 达标率、Top 5 与剩余候选差异；
- 按日期胜负数量；
- 以形成日为抽样单元的固定种子 bootstrap 95% 区间（10,000 次，种子 `20260817`）。

辅助指标：首次达标日、最大收盘收益、第 20 日终点、相对市场终点、达标前最大不利变化、达标后回吐、不可执行比例、空名单比例、每日平均选择数、固定分箱校准、Brier score、市场状态分组和机会类型分组。AI 某日空名单时条件精度为 null 并报告空名单，不能静默删除。

每种机会类型分别报告：样本数、正例数、形成日数、候选池达标率、AI 入选率、AI 入选/淘汰达标率、模型 Top 5 覆盖、模型精度、主要淘汰原因和 `sole_company_gate_rejection`。少于 30 行、5 个正例或 5 个形成日时写“不可稳定评价”。系数只解释关联，不写成因果或固定规则。

## 13. 成功、证据不足和阻塞

最终测试打开前冻结成功条件：

1. 最终测试候选池内模型 `policy Precision@5` 相对候选池基础率至少提高 5 个百分点；
2. 存在可比 AI 历史结果时，相对 AI 入选至少提高 5 个百分点；
3. 模型 Top 5 达标率高于剩余候选；
4. 提升不只来自一个形成日；
5. 两个预注册 walk-forward 测试折方向均为正；
6. 无数据泄漏；
7. 机会类型在形成日前冻结；
8. 不是靠大量空名单提高命中率；
9. 候选池提升和 Top 5 对剩余候选差异的形成日 bootstrap 95% 区间下界均大于 0。

结论只能是：

```text
有稳定排序信号
有初步排序信号，但证据不足
没有证明排序信号
实验阻塞
```

判定：

- **有稳定排序信号**：主轨达到全部最低样本门槛和全部成功条件。
- **有初步排序信号，但证据不足**：主轨至少有一个可评价日期且方向改善，但样本、置信区间、独立日期、污染或覆盖不足。次级轨单独改善不能得到该主结论。
- **没有证明排序信号**：可评价主轨满足最低门槛但预注册成功条件未达到。
- **实验阻塞**：没有可用主轨机器记录，或无法构建时点安全候选/特征/标签，或无法证明记录在未来揭示前冻结。当前预检若未发现新机器记录必须使用该结论。

机会类型效果另行使用 `改善 | 未改善 | 不可稳定评价 | not_evaluable`；隐性公司 Gate 使用 `confirmed | not_confirmed | not_evaluable`，其中 `not_confirmed` 必须有足够完整候选链证据。

失败后不得现场换日期、追加特征/模型、修改标签或继续调到通过。

## 14. 模块与 CLI

新增隔离模块，文件可按现有结构小幅调整但职责必须独立：

```text
src/stock_analyzer/selection_lab/
├── __init__.py
├── schemas.py
├── opportunity_types.py
├── dataset_builder.py
├── labels.py
├── feature_builder.py
├── temporal_split.py
├── baselines.py
├── ranker.py
├── evaluation.py
├── audit.py
└── reporting.py
```

在现有 CLI 下增加：

```text
python -m stock_analyzer selection-lab build-dataset
python -m stock_analyzer selection-lab audit-opportunity-types
python -m stock_analyzer selection-lab evaluate-baselines
python -m stock_analyzer selection-lab train-ranker
python -m stock_analyzer selection-lab walk-forward
python -m stock_analyzer selection-lab build-review-bundle
```

CLI 只能读本地事实仓和已有冻结研究结果；所有逐股产物写被忽略目录。`build-dataset` 默认只构建形成日输入，标签按 development、validation、final-test 分离生成；final-test 标签只有 split、特征、模型变体、C 和阈值冻结清单存在且哈希一致时才允许打开。缺少可选依赖或数据能力时返回非零并输出结构化阻碍，不联网取数、不隐式运行正式数据任务。

## 15. TDD 与必须覆盖的测试

所有生产代码先写失败测试并观察预期失败，再最小实现。至少覆盖：

1. `available_at` 晚于形成日的事实不能进特征；
2. 行动日计算正确；
3. 第 1—20 个真实交易日计数正确；
4. 第 3 日达标返回 `first_hit_day=3`；
5. 第 21 日才达标为 false；
6. 盘中最高触及但收盘未达标为 false；
7. 入口和后续价格复权一致；
8. 停牌、一字涨停或无可靠开盘的可执行性；
9. 同一形成日不跨 split；
10. purge/embargo 至少 20 个交易日；
11. 训练插补/标准化不读取验证/测试；
12. 最终测试标签不参与特征/调参；
13. `company_catalyst` 无直接公司事实不能高置信；
14. `sector_diffusion` 无新公司公告仍保留资格；
15. `independent_price_anomaly` 无公司催化仍保留资格；
16. 缺公司催化不能是后两类唯一硬淘汰原因；
17. 独立价格异常检查相对市场、同类、成交推进、流动性和透支；
18. 不允许机会类型配额；
19. 多类型保存主类型和次类型；
20. 类型分配不接受未来标签字段；
21. 固定种子、相同输入产生相同排序；
22. `current_ai_fate` 不进训练特征；
23. 评估先逐形成日再等权；
24. review bundle 无本地绝对路径、Token 或完整原始数据；
25. Skill YAML frontmatter 和合同验证通过；
26. `git diff --check` 通过。
27. 不可执行 Top-K 不递补；
28. 两个相邻 split 的标签窗口严格不重叠，并验证 20/22 个交易日间隔；
29. 最终测试标签在预注册冻结前不能打开；
30. 当前 Prompt 和本轮文件不造成日期自污染，普通业务日期不误判成 formation date；
31. `security_master` 不可回放时关闭 `full_universe`，不用当前名称/ST 倒填；
32. 没有机器候选链时主结论为 `实验阻塞`，Gate 为 `not_evaluable` 且数字为 null；
33. 无因果命题时机会类型允许 null，不强猜；
34. 并列不使用股票代码顺序；
35. 两种模型除 opportunity type 外输入完全相同；
36. C、模型变体和阈值按预注册规则冻结；
37. 阈值覆盖约束和每日 0—5 上限正确。

验证命令至少包括：

```bash
.venv/bin/python -m pytest tests/selection_lab -q
.venv/bin/python -m pytest -q
.venv/bin/python -m stock_analyzer selection-lab --help
.venv/bin/python -m stock_analyzer selection-lab build-dataset --help
.venv/bin/python -m stock_analyzer selection-lab audit-opportunity-types --help
.venv/bin/python -m stock_analyzer selection-lab evaluate-baselines --help
.venv/bin/python -m stock_analyzer selection-lab train-ranker --help
.venv/bin/python -m stock_analyzer selection-lab walk-forward --help
.venv/bin/python -m stock_analyzer selection-lab build-review-bundle --help
git diff --check
```

## 16. Skill 语义修正

影子排序基线完成后，单独修改：

```text
.agents/skills/orchestrating-stock-research/SKILL.md
.agents/skills/researching-sectors-industries/SKILL.md
.agents/skills/researching-company-events/SKILL.md
.agents/skills/analyzing-price-trading/SKILL.md
```

总控候选账和最终输出增加主要/次要机会类型、证据和置信度。总控明确：公司催化需要直接变化；板块扩散不要求新公司事件但需要真实成员、扩散和同类增量；独立价格异常不要求公司事件但需更严量价、流动性、透支和假突破检查；公司 Skill 对后两类主要查身份和重大反证；类型不是配额、评分、投票或 Gate；类型不能由未来结果决定。

板块 Skill 提交建议类型并明确无新公告不自动淘汰；公司 Skill 明确后两类没有新公司变化不等于公司不相关；价格 Skill 明确独立价格异常的严格证据。专业 Skill 可建议，总控根据完整因果链确定主要类型。

报告必须写：

> 这是语义和职责修正，不是已经通过未来收益验证的选股改进。

不得用已打开最终测试期反复调 Skill。

即使当前 Gate 为 `not_evaluable`，仍执行用户明确要求的合同语义修正，但不得声称已确认历史误杀或提升命中率。

## 17. 设计、报告与 review bundle

先写：

```text
docs/selection_lab/2026-08-17-selection-lab-design.md
```

说明问题、实验边界、数据流、机会类型、防泄漏、模型、评价、Skill 修正及本地/GitHub 边界。

在任何标签打开前创建并哈希：

```text
docs/selection_lab/review/previously_used_formation_dates.json
docs/selection_lab/review/feature_dictionary.json
docs/selection_lab/review/split_manifest.json
```

后续不得用实验结果改写这些预注册定义；实际行数、能力状态和标签揭示状态写入数据血缘与结果文件。

实验报告：

```text
docs/selection_lab/2026-08-17-selection-lab-and-opportunity-type-report.md
```

必须直接回答：候选池是否优于完整范围；AI 入选是否优于淘汰；简单规则能否超过 AI；两种逻辑回归是否有排序能力；机会类型是否改善；Top 5 是否稳定；信号来自哪些特征；哪些特征改善主标签但恶化终点/回撤；三类机会差异；是否确认隐性公司 Gate；后两类是否被系统性误杀；Skill 改了什么及为何不能称为命中率提升；数据是否足够；下一步应保持、积累、使用影子裁判、让 AI 结构化调整或停止路线。

若没有可靠数据，所有数字字段使用 `null` 并附阻碍，不伪造空的 0% 指标。报告必须先回答主候选池是否可取得；主轨不可用时，次级探索不能冒充主业务答案。

提交小体量审阅包：

```text
docs/selection_lab/review/README.md
docs/selection_lab/review/previously_used_formation_dates.json
docs/selection_lab/review/data_lineage_manifest.json
docs/selection_lab/review/feature_dictionary.json
docs/selection_lab/review/split_manifest.json
docs/selection_lab/review/baseline_metrics.json
docs/selection_lab/review/ranker_metrics.json
docs/selection_lab/review/opportunity_type_audit.json
docs/selection_lab/review/model_coefficients.json
docs/selection_lab/review/rank_examples.json
docs/selection_lab/review/verification.json
```

`data_lineage_manifest.json` 包含 base/实现/报告 commit、数据截止、日期范围、各 split、行数/候选/正例/正例日期、特征/数据集版本、输入哈希、标签揭示状态和限制。`ranker_metrics.json` 包含各轨道/split/模型的 policy 与 executable Precision@K、lift、AI baseline、入选/淘汰、日期/类型/路径指标、阈值、空名单、覆盖和结论理由。`opportunity_type_audit.json` 包含三类及 null 数量、置信度、AI fate、达标率、原因交叉表、sole gate、有限案例和 Gate 结论。`model_coefficients.json` 只含模型类型、超参数、特征、系数、截距和版本。主轨不可用时 `rank_examples.json` 必须为空数组并说明原因，不用次级轨冒充。`verification.json` 记录全部命令、退出码、结果、重现性、diff/status、本地数据未提交检查和 Skill 验证。

所有 JSON 使用确定性 key 顺序、UTF-8、无本地绝对路径。

## 18. Git 提交和 GitHub 交付

不得合并到 `main`。按逻辑至少四个提交：

1. 冻结 Prompt、设计、历史日期清单、特征字典和 split；
2. selection_lab 程序、CLI、依赖、忽略规则和测试；
3. 四个 Skill 合同及架构文档语义修正；
4. 实验报告和 review bundle。

README 只在当前能力/命令入口实际变化时同步。架构文档必须区分“已实现的隔离实验工具”与“仍不存在的自动 AI 选股器”。

推送 `feat/selection-lab-opportunity-types`，创建 draft PR，不推送到 main。建议标题：

```text
feat: add selection lab and opportunity-type research contract
```

PR 描述说明目标、实验结果、排序信号、隐性公司 Gate、Skill 只是语义修正还是性能调优、测试、本地数据未提交和重点审阅文件。推送前检查暂存/提交范围、敏感信息、本地路径和大文件。

## 19. 最终汇报固定格式

```text
执行状态：
最终结论：
排序信号结论：
机会类型结论：
隐性公司 Gate 结论：
Skill 是否修改：
为什么修改或不修改：
训练/验证/最终测试日期：
核心指标：
全量测试结果：
分支：
draft PR：
提交 SHA：
git status --short：
未同步到 GitHub 的本地产物：
仍然存在的风险：
建议下一步：
```

明确区分：已完成、已验证、仅设计、仅语义修正、因样本不足无法证明、尚需未来真实日期验证。不得把测试通过、报告完整、候选链守恒、Skill 合同正确或开发集表现好描述成“选股已经调准”。

## 20. 本轮真正的完成定义

完成不要求模型一定更好。完成要求建立一套以后不会继续追着历史赢家改规则的、时点安全、可重复、可审阅、可滚动验证的方法；如实证明排序信号、证明没有信号，或准确证明当前数据为什么还不能回答，三者都属于有效结果。
