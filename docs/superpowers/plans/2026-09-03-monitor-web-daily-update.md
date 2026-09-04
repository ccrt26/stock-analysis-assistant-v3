# 方案与实施计划：复盘观察 WEB 每日自动更新

日期：2026-09-03 · 状态：审查通过（修订版）

## 执行提示

- **目标**：每个交易日早上 codex 产出日报数据后，自动把最新日报渲染成本地 WEB 页面（`local_archive/forward_monitor/monitor-report-<date>.html`）；codex 未产出或渲染失败时保持可手动兜底，不报错轰炸。
- **验收标准**：
  1. 交易日 10:10—11:40 有四个检查时点；新产物出现后当日内自动渲染成功并记录日志；
  2. 休市日（本地交易日历 `is_open=false`）默认不启动日常更新，防御性扫描后无新增则记"休市"日志退出；扫描发现异常新增时照常渲染（数据优先）；
  3. codex 未产出时脚本安静退出（exit 0），日志记"等待人工"；渲染失败不改状态文件，重跑可自愈；状态文件损坏或不可读时视为空并全量重渲染重建；
  4. 手动执行与自动执行是同一条命令；全部行为有 pytest 覆盖。
- **范围**：新增 `tools/update_monitor_web.py` + `tests/test_update_monitor_web.py` + 一个 ZCode 定时自动化；复用现有 `tools/render_monitor_web.py` 渲染器。
- **不做事项**：不改 codex 生产任务、launchd 配置、`forward_monitor.py` record 流程；不做网上同步（后续另行接入）；不改历史页面的时点语义；不提交 git；不引入跨进程锁或守护进程。
- **关键约束**：只依赖已归档产物，不读取未冻结数据；时点安全由现有渲染器保证；凭据/个人数据不外传；日志与状态文件放在 `local_archive/forward_monitor/`（gitignored）。

## 背景与 codex 现有约定（已查证）

- codex 数据阶段：launchd `com.ccrt.stock-analysis-assistant.research-data-*`，18:30 / 21:30 / 次日 09:00 三阶段，均 `--data-date auto`。
- **休市口径**：close 阶段先查交易日历，`is_open=false` 直接 `skipped=1` 不处理（`src/stock_analyzer/ops/research_data_job.py:284-290`）。
- **交易日历**：`local_warehouse/facts/trade_calendar/cal_year=<YYYY>/data.parquet`（SSE，`cal_date`/`is_open`），2026 年已覆盖至 11-02，管道持续补齐。
- **重试口径**：旧版每日任务用固定时段 + `--attempt N` 的有界重试而非全天轮询；本方案沿用"固定多时点、脚本幂等"的等价形态。
- **晨间产出节奏**：复盘台账 `as_of` 约为次日 09:05（如 `daily-formal-reviews-2026-09-01.json` as_of `2026-09-02T09:05+08:00`）——交易日的报告在次日上午定稿，因此**不能用"今天"的日期找文件**。

## 设计

### 触发

- ZCode 定时自动化：cron `10,40 10-11 * * *`（10:10 / 10:40 / 11:10 / 11:40），脚本幂等，重复触发安全。
- 自动化仅在 Mac + ZCode 在线时运行；未运行的日子由手动命令兜底（与用户要求一致）。
- 并发说明：四个时点间隔 30 分钟，单次渲染为秒级；即使手动与自动偶发重叠，因按日期幂等渲染、状态文件以原子替换写入（临时文件 + `os.replace`，last-writer-wins 且内容一致），不引入锁。

### 检测（`tools/update_monitor_web.py`）

1. **日历闸门**：读本地交易日历判断"今天"是否 `is_open`（可用 `--today` 覆盖以便测试）。
   - 非交易日：仍做一次防御性扫描；无新增则日志记"休市，不启动"并 exit 0；异常有新增则照常渲染（数据优先）。
   - 日历未覆盖该日期：退化为周一至周五视为候选，日志记警告。
2. **增量检测**：扫描 `snapshot-<date>.json` + `monitor-report-<date>.json` 成对产物（文件名严格匹配日期格式，排除 `pre-*`），对 report、snapshot 与同日期的 `daily-formal-reviews-<date>.json`（缺失时以固定"缺失"占位参与哈希）三个输入文件字节做 sha256，与状态文件 `.web-publish-state.json` 中记录比较；哈希缺失或不同 → 视为待渲染。台账缺失只记警告；报告与快照缺一 → 该日期视为 codex 未完成，跳过。注意：渲染日期 D 的页面会包含更早日期的快照与台账历史，本检测只覆盖 D 当日三件套；历史产物或模板变更不触发级联重渲染，需人工 `--force` 全量重跑。
3. **渲染**：对每个待渲染日期（升序）调用现有渲染器 `render_monitor_web.main(["--date", d])`；若显式传入 `--monitor-dir`，同步透传给渲染器（渲染器的 `MONITOR_DIR` 为导入期常量，仅接受该参数覆盖）；`--project-root` 仅用于本脚本推导 monitor 目录、状态与日志的默认位置。
4. **校验**：渲染后检查 HTML 存在、内嵌 `const DATA = ` 行（单行 JSON）可解析、`analysis_date` 与日期一致，并读取 `stocks` 数量供日志使用。
5. **状态与日志**：校验通过才把该日期的输入哈希原子写入状态文件（临时文件 + `os.replace`）；状态文件 JSON 不可读/损坏时视为空并全量重渲染重建。每次运行追加一行到 `web-update.log`（时间、是否交易日、发布日期列表、各日期股票数与结果）。

### 失败路径

- 渲染或校验异常：该日期状态不写入，日志记错误，exit 1；下个时点 / 手动重跑自愈（已成功日期因状态命中而跳过）。
- 全部候选日期都被跳过（codex 未完成）：exit 0，日志记"等待人工"。
- 手动入口 = 同一脚本：`./.venv/bin/python tools/update_monitor_web.py`（支持 `--today`、`--force`（忽略状态文件、重渲染全部候选日期）、`--monitor-dir`、`--project-root`，便于测试与人工修复）。

### ZCode 自动化（cron `10,40 10-11 * * *`）

提示词要求执行脚本：exit 0 时只回一句话（已更新 / 无新增·休市或等待 codex）；exit 非 0 时读日志尾部报告原因与手动命令；不改文件、不重复发起其他任务。若定时自动化能力不可用，如实报告阻塞，不擅自降级为其他调度机制。

## 实施步骤

1. 编写 `tools/update_monitor_web.py`（日历闸门、增量检测、渲染、校验、状态、日志、CLI）。
2. 编写 `tests/test_update_monitor_web.py`（与 `tests/test_render_monitor_web.py` 同为 pytest、直接 import `tools.` 模块）：日历开/闭/未覆盖三分支、首跑渲染全量、二次运行 no-op、输入变化重渲染、报告缺失跳过并等待人工、状态文件损坏后自愈重建。
3. 运行新测试与既有 `tests/test_render_monitor_web.py`。
4. 真实环境验证三条路径：以 `--today 2026-10-01`（国庆休市，日历已确认 `is_open=false`）验证休市分支；以已发布状态重跑验证 no-op；重置状态文件验证正常渲染 2026-09-02。
5. 创建 ZCode 定时自动化并用 CronList 确认。

## 风险与边界

- Mac 关机 / ZCode 未运行 → 当天自动跳过（用户已知，手动兜底）。
- 渲染器模板或历史产物变更仍需人工 `--force` 全量重渲染（本自动化只管当日内容增量）。
- 日历仅覆盖至 2026-11-02，之后未覆盖日期自动退化为周一至周五候选并记警告，依赖管道持续补齐。
- 不发布到网上；后续接入发布时只在"校验通过"后追加同步步骤。
