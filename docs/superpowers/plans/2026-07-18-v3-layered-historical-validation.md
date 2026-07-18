# V3 轻量分层历史验证执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan task by task. 本计划由当前主智能体单独执行，不使用子智能体。

**目标：** 用本地已有历史数据，对临时分析框架中当前能够历史复现的部分做三个独立、各连续 30 个形成日的验证；明确哪些逻辑得到支持、哪些逻辑被数据否定、哪些因证据不足无法判断，并给出有数据依据的优化方向。

**原则：** 这是框架验证实验，不是通用回测平台。只写一个最小程序、一组聚焦测试和一份冻结配置；不修改正式分析框架、不修改数据底座、不增加数据源、不自动生成执行设计。运行产生的缓存、明细和报告全部写入 U 盘专用目录。

**技术路径：** 直接读取现有 Parquet，复用生产派生特征函数与已有的时间截断、未来收益计算函数。每个形成日只使用当日可得数据，先形成各发现入口的内部研究召回，再执行统一验证、最多十只压缩、重点五只、替换与生命周期记录，最后统一揭示未来 10/20/30 个交易日结果。统计采用分块一致性、合法对照、路径风险和案例审计，不用单一命中率冒充完整有效性。

---

## 不可越界的约束

- 形成日为三个独立区间，每段严格连续 30 个交易日：
  - A：2025-10-30 至 2025-12-10
  - B：2026-01-26 至 2026-03-16
  - C：2026-04-20 至 2026-06-03
- 未来观察窗为 10、20、30 个交易日；目标是从形成日收盘重新出发，未来盘中最高价是否触及 `+20%`。
- 形成候选时严禁读取形成日之后的价格、财务、估值、热点或其他事实；未来数据只在结果揭示阶段使用。
- 只验证本地数据能够支持的入口：市场环境、热点、盈利事实、价格/成交/流动性，以及候选管理的可执行部分。
- 公司事件、产业/周期、困境反转因本地证据字段不足，只登记为 `not_testable`，不得伪造代理变量或包装成“有限通过”。
- 不继承旧 Phase 3 分数、权重、推荐或表达；不建立综合分数。
- 热点或价格只能负责发现与支持，不能单独构成最终推荐。最终候选至少需要一个当时可得、可审计的公司层机会证据；当前历史实验中主要由盈利事实承担。
- 最多十只不是必须凑满十只；重点五只也不是必须凑满五只。
- 所有运行产物只写入：`/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-18-v3-layered-validation/`。
- 实验结束只报告结果，不修改框架、不写正式执行设计、不开发正式推荐代码。

## 文件范围

**创建：**

- `docs/superpowers/specs/2026-07-18-v3-layered-validation-config.yaml`
- `src/stock_analyzer/evaluation/v3_layered_validation.py`
- `tests/test_v3_layered_validation.py`

**只复用、不修改：**

- `src/stock_analyzer/evaluation/historical_framework_validation.py`
- 生产派生特征函数及本地 Parquet 数据。

**运行输出（仅 U 盘）：**

- `manifests/`：配置快照、输入文件清单、不可验证能力清单、运行状态。
- `tables/`：紧凑的形成日特征、研究召回、候选、重点、项目轨迹、未来结果、模块诊断。
- `reports/v3-layered-historical-validation-results.md`：用户可读最终报告。

---

### Task 1：冻结实验配置与最小契约

**Files:**

- Create: `docs/superpowers/specs/2026-07-18-v3-layered-validation-config.yaml`
- Create: `tests/test_v3_layered_validation.py`
- Create: `src/stock_analyzer/evaluation/v3_layered_validation.py`

**Step 1: 先写失败测试**

测试必须覆盖：

- 三段日期各自恰好映射为连续 30 个本地交易日；
- 观察窗为 10/20/30，目标收益为 20%；
- 输出根目录必须在指定 U 盘目录内，拒绝 Mac 本地路径；
- 配置只能声明三个当前可运行入口和三个不可验证入口；
- `prepare_output_root` 只创建专用子目录，不触碰同盘其他文件。

**Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: 因模块与配置尚不存在而失败。

**Step 3: 写最小配置与契约**

冻结以下值：

```yaml
experiment_id: 2026-07-18-v3-layered-validation
warehouse_root: /Users/ccrt/Documents/股票分析助手/local_warehouse
output_root: /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-18-v3-layered-validation
blocks:
  - {id: A, start: 2025-10-30, end: 2025-12-10}
  - {id: B, start: 2026-01-26, end: 2026-03-16}
  - {id: C, start: 2026-04-20, end: 2026-06-03}
horizons: [10, 20, 30]
target_return: 0.20
candidate_cap: 10
focus_cap: 5
route_recall_cap: 30
supported_routes: [hotspot, earnings, price]
not_testable_routes: [company_event, industry_cycle, distress_repair]
runtime_soft_hours: 6
runtime_stop_hours: 8
usb_soft_bytes: 3221225472
```

实现只需要：配置读取、日期块数据类、输出目录边界校验、目录准备和运行状态写入。

**Step 4: 再跑测试**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: Task 1 测试通过。

---

### Task 2：一次读取数据并按形成日重算可得特征

**Files:**

- Modify: `tests/test_v3_layered_validation.py`
- Modify: `src/stock_analyzer/evaluation/v3_layered_validation.py`

**Step 1: 先写失败测试**

用小型合成数据验证：

- 某形成日的特征输入不包含未来行；
- 财务事实按 `available_at <= formation_date` 选取，而不是按入库日或报告期结束日穿越；
- 缺少供应商 `pct_chg` 时，使用相邻收盘价统一复算，不混用口径；
- 同一只股票同一形成日只保留当时最新且合法的财务记录；
- 输出表不包含原始日线全量复制。

**Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: 新测试失败。

**Step 3: 实现最小数据装载与特征批处理**

- 直接用 pandas/pyarrow 读取本地 Parquet；不得实例化会写目录的 `ResearchWarehouse`。
- 每张必要表只读取一次，裁剪为最早形成日前所需回看区间至 C 段未来 30 日的必要列。
- 复用生产函数计算市场环境、热点与股票价格上下文；不得另造同名指标。
- 财务入口使用形成日当时已可得的营收、净利润、扣非净利润、经营现金流同比及绝对经营现金流事实。
- 在 U 盘只保存紧凑表和输入文件清单（路径、大小、修改时间、必要时哈希），不复制生产数据集。
- 三个缺证据入口仅写 `capability_manifest`，包含缺失字段及为何不能测试。

**Step 4: 再跑测试**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: Task 2 测试通过。

---

### Task 3：研究召回、十只压缩和重点五只

**Files:**

- Modify: `tests/test_v3_layered_validation.py`
- Modify: `src/stock_analyzer/evaluation/v3_layered_validation.py`

**Step 1: 先写失败测试**

覆盖以下规则：

- 热点、盈利、价格三个入口独立召回，每个最多 30 只；轮转合并不允许单一路径先占满研究池。
- 热点或价格入口发现但没有公司层机会证据的股票，只留在内部召回，不进入最终十只。
- 满足公司层机会证据后，统一验证证据新鲜度、利润与现金一致性、热点支持、价格透支风险、流动性。
- 不计算加权总分；使用硬门槛、Pareto 支配和明确的同档次决胜规则。
- 候选不超过 10、重点不超过 5；证据不足时允许少于上限。
- 容量边界上的不可区分并列不得任意按代码或名称决定，必须记为 `abstain_capacity_tie`。

**Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: 新测试失败。

**Step 3: 实现透明决策协议**

每个形成日依次执行：

1. 三入口各自召回，保留入口理由和必要事实。
2. 轮转合并为内部研究池，去重但保留多入口命中。
3. 先做公司层证据门槛、流动性门槛和明显透支风险检查。
4. 对剩余股票比较五个独立维度，不相加：证据新鲜度、盈利/现金一致性、热点广度与持续性、当前价格消耗、可交易性。
5. 被另一只股票在所有维度不差且至少一维更好的，标记为被支配；保留非支配集合。
6. 非支配集合超过容量时，按预先冻结的证据层级与风险层级处理；仍无法区分则弃权，不凑数。
7. 重点五只必须同时满足：证据更完整、从当前价仍有新增驱动、路径风险没有明显反对；其余合格者为候补。

每条入选、淘汰、弃权都写机器可审计原因，不写“主力”“机构吸筹”等无证据推断。

**Step 4: 再跑测试**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: Task 3 测试通过。

---

### Task 4：每日发现转为 1—6 周项目与挑战者替换

**Files:**

- Modify: `tests/test_v3_layered_validation.py`
- Modify: `src/stock_analyzer/evaluation/v3_layered_validation.py`

**Step 1: 先写失败测试**

验证状态机只依赖当日及过去信息：

- 首次合格为 `new`，连续保留为 `tracking`，证据增强为 `confirmed`，证据削弱为 `watch_only`，触发失效为 `exit`。
- 第 5/10/20/30 个交易日执行预定检查；第 20 日之后只有原证据仍成立才允许延续，第 30 日后不沿用原项目。
- 新挑战者只有在当前可观察维度明确支配旧候选，或旧候选触发失效时才能替换；不得用后来涨幅决定替换。
- 同一股票跨形成日保留 `project_id`、进入日、占位天数、状态变化和退出原因。

**Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: 新测试失败。

**Step 3: 实现最小状态机**

- 只实现回测需要的状态迁移和挑战者比较，不开发生产级服务、数据库或调度器。
- 每日先复核在位项目，再让当日挑战者参与同一协议比较。
- 同时保存“没有替换时的旧组合”和“实际替换后的组合”，为替换是否改善提供配对比较。
- 记录每日新增、退出、替换、空缺、错误占位天数所需字段。

**Step 4: 再跑测试**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: Task 4 测试通过。

---

### Task 5：未来结果、合法对照和模块诊断

**Files:**

- Modify: `tests/test_v3_layered_validation.py`
- Modify: `src/stock_analyzer/evaluation/v3_layered_validation.py`

**Step 1: 先写失败测试**

覆盖：

- 从形成日收盘出发计算未来 10/20/30 日盘中最大收益、收盘收益、最大不利波动、触及目标所需天数。
- 结果揭示阶段与形成阶段隔离。
- 对照股票只从同形成日、同流动性层、同市场/行业可比集合中产生，不使用未来信息匹配。
- 重点与候补、替换前与替换后使用配对比较。
- 每个模块输出四态之一：`accuracy_supported`、`inaccuracy_supported`、`insufficient_evidence`、`not_testable`。

**Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: 新测试失败。

**Step 3: 实现统计与诊断**

复用 `compute_forward_outcomes` 并补充必要路径字段，分别诊断：

- 发现：各入口及合并研究池对后来触及目标股票的覆盖、提前发现天数、遗漏案例。
- 压缩：十只相对研究池和合法对照是否改善目标命中与路径代价。
- 重点：重点五只相对候补是否更好。
- 替换：实际替换相对“不替换”的配对结果是否改善。
- 生命周期：项目不同阶段的剩余机会、占位时间、退出后表现和错误占位。

结论门槛：

- `accuracy_supported`：合并方向优于合法对照，至少 2/3 区块同向，且不能由单一行业或极少数极端股票解释，路径风险不反对结论。
- `inaccuracy_supported`：合并结果不优于对照且至少 2/3 区块同向为负，或重点显著不如候补、替换显著变差、生命周期持续占位但没有剩余机会。
- 样本太少、区块冲突或效应高度集中：`insufficient_evidence`。
- 本地输入无法形成所需证据：`not_testable`。

同时输出 bootstrap 区间或等价的区块稳健区间，但区间不替代方向、分块和案例检查。

**Step 4: 再跑测试**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py -q`

Expected: Task 5 测试通过。

---

### Task 6：真实运行、时间门和冻结报告

**Files:**

- Runtime only: `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-18-v3-layered-validation/**`

**Step 1: 预检**

依次确认：

- U 盘已挂载且专用目录可写；
- 三段各有 30 个形成日，C 段后有完整 30 日观察窗；
- 所需 Parquet 表和关键字段存在；
- 预计紧凑输出小于 3 GiB；
- 单元测试全部通过。

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py tests/test_historical_framework_validation.py tests/test_research_historical_availability.py -q`

**Step 2: 运行 A 段并实测耗时**

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_layered_validation run --config docs/superpowers/specs/2026-07-18-v3-layered-validation-config.yaml --blocks A`

A 段必须完整跑完 30 个形成日，不能再缩成 10 日样本。记录墙钟时间、峰值内存、U 盘增量和每阶段耗时。

**Step 3: 按冻结时间门决定后续**

- 若 A 段外推总时间不超过 6 小时，继续 B、C。
- 若外推超过 6 小时，只允许一次局部优化：消除重复读取或重复特征计算；不得改变样本、目标、候选规则或统计口径。
- 优化后重新校验 A 段关键输出一致，再继续。
- 若外推仍超过 8 小时，完成 A 段可解释结果并明确停止原因，不盲跑十小时；不得声称完成整体回测。

**Step 4: 运行 B、C 与统一揭示**

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_layered_validation run --config docs/superpowers/specs/2026-07-18-v3-layered-validation-config.yaml --blocks B C`

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_layered_validation reveal --config docs/superpowers/specs/2026-07-18-v3-layered-validation-config.yaml`

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_layered_validation report --config docs/superpowers/specs/2026-07-18-v3-layered-validation-config.yaml`

**Step 5: 审计最终报告**

报告必须逐项回答：

- 哪些分析逻辑得到支持，具体由哪些数字、三个区块的一致性和代表案例支持；
- 哪些分析逻辑被否定，具体由哪些数字和失败案例支持；
- 哪些问题证据不足，缺的是什么，不能把它写成正确或错误；
- 各入口召回、最终十只、重点五只、挑战者替换、1—6 周生命周期各自表现；
- 后来大涨但遗漏的股票，在形成日缺少哪类证据；
- 每日新增退出是否过高、错误候选占位多久；
- 目标触及前的回撤和终点收益，避免只看盘中摸到 20%；
- 优化建议必须对应已发现的失败机制，不自动修改框架。

最终报告要明确声明：这是对“本地数据可复现部分”的历史证据，不是完整 V3 已被证明准确，也不是收益保证。

**Step 6: 完成前验证**

Run: `.venv/bin/pytest tests/test_v3_layered_validation.py tests/test_historical_framework_validation.py tests/test_research_historical_availability.py -q`

Run: `git diff --check`

核对 U 盘：配置快照、输入清单、运行状态、全部紧凑结果表和最终报告均存在且非空；报告中的汇总数字可回溯到明细表。

---

## 完成标准

只有同时满足以下条件才可报告“回测完成”：

- 三个区块各 30 个形成日全部形成成功，并拥有完整未来 30 日结果；
- 形成阶段通过时间穿越审计；
- 五个可执行模块都有数字、分块结果和案例证据；
- 三个不可执行入口明确为 `not_testable`；
- 最终报告清楚区分准确、不准确、证据不足和不可测试；
- 所有运行产物位于 U 盘专用目录，Mac 项目内没有大体积缓存；
- 没有据回测结果自动修改临时框架或继续正式编码。

