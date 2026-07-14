# 股票分析助手 V3

这是一个面向中国大陆 A 股的报告优先型分析助手。系统用于生成观察建议、重点关注状态、证据包和后评估任务，不用于自动交易。

## 当前生产状态与文档权威

截至 2026-07-14，正式报告的分析逻辑和用户表达正在重新设计。此前 Phase 3 和已发布报告只保留为历史证据，不代表当前认可的产品结果。旧的自动分析、报告生成和发布任务已经停用；在用户认可新的分析框架与报告样式前，系统不会自动生成、激活或部署正式报告。

当前已激活的是纯数据任务。每天 18:30 获取收盘核心数据，21:30 更新公告、板块与低频资料，次日 08:00 补融资融券和晚到数据。三个阶段均已用 2026-07-13 真实数据试跑通过，只写本地统一事实库，不调用分析、报告、Supabase 激活或 Cloudflare 发布。

统一事实库已经完成全市场行情去重、板块与概念、公司资料、财务、公告、公司行动和融资融券补齐。日常选股默认读取最近 82 个交易日，市场和板块环境最多读取最近 250 个交易日；只有体量小且确有长期参照价值的行情、复权、估值与公司行动保留较长历史。每天只增量获取当天事实和明确缺口，不重新下载五年全量。

旧行情目录曾因同一业务日期保留多个 Parquet 版本而产生大量物理重复。迁移已确认这些版本之间没有事实冲突，统一事实区按业务键只保留一份当前事实，并保留来源、时间、版本和校验信息；严格迁移审计通过后，旧的 2,252 个行情文件已按清单清理。当前完整健康检查显示核心数据完整，所有已保存数据集均无重复业务键、缺文件或哈希不符。

此前 `STORE-004` 宽表存储迁移的历史验收仍为 `PRODUCTION_WRITE_VERIFIED`，其旧 `local_warehouse/formal_evidence` 已不存在；这项历史证据与当前统一事实区的 `STORE-005` 去重清理分别保留。

已知限制仍明确保留：当前官方账号不能稳定取得历史分钟数据，因此系统不能用日线或所谓“主力资金流”证明机构买卖身份；部分官方主题指数不公开成分；个别新股的财务资料尚未披露。前两类标为来源能力限制，不会无止境重试；个别公司资料只按具体股票代码定向追补。

当前能力、缺口、验证等级和激活状态只以 [`docs/operations/production-capability-matrix.md`](docs/operations/production-capability-matrix.md) 为准。`docs/superpowers/specs/` 保存设计约束，`docs/superpowers/plans/` 保存历史执行记录；历史文档中的“完成”不能替代能力矩阵中的当前证据。

## 本地运行

需要 Python 3.11 或更新版本。推荐路径：创建虚拟环境并安装 editable package 后运行。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m stock_analyzer health-check
python3 -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07
```

默认 `health-check` 只做本地配置和凭据状态检查，不访问外部网络。旧的有限 Tushare provider 不能绕过正式数据门禁；非 fixture 生产命令必须具有实时能力凭证并通过完整正式契约，否则会失败关闭，也不能把内置样例数据写入 Supabase。正式窗口、盘后边界和基准指数由单一策略模块管理；交易日、候选代码、路径、环境身份、凭据和激活目标不得固化在生产流程中。

未安装 editable package 的开发路径：使用 `PYTHONPATH=src` 直接运行源码。这是当前 smoke 已验证命令路径。

```bash
PYTHONPATH=src python3 -m stock_analyzer health-check
PYTHONPATH=src python3 -m stock_analyzer run-daily --dry-run --trade-date 2026-07-07
PYTHONPATH=src python3 -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07
```

真实 Tushare smoke 必须显式选择，并且只应在本地已安装 `tushare` 且配置了非提交的 token 后运行：

```bash
python3 -m pip install "tushare>=1.4.19"
PYTHONPATH=src python3 -m stock_analyzer health-check --live-tushare-smoke
```

## 密钥

- Tushare token 默认读取当前运行用户的 `~/.tushare_token`。
- 也可以通过 `TUSHARE_TOKEN_PATH` 指定本地 token 文件。
- 生产报告渲染必须设置 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`。`SUPABASE_SERVICE_ROLE_KEY` 只用于服务端/本地受控脚本访问 Supabase，不能写入报告产物、前端代码或 Git。
- 生产 `run-daily` 还需要真实行情接入、Tushare token 和数据依赖；缺失时会失败，不会持久化样例推荐。
- 本地样例报告必须显式使用 `--fixture-mode`，或设置 `STOCK_ANALYZER_FIXTURE_MODE=1`。
- Cloudflare Pages 报告访问需要同时配置 `REPORT_PASSWORD` 和 `REPORT_SESSION_SECRET`。`REPORT_PASSWORD` 是访问报告时输入的共享密码；`REPORT_SESSION_SECRET` 用于 HMAC 签名 `report_session` Cookie，缺失时中间件会返回 `503`，避免发布无会话保护的报告站点。
- 可用 `openssl rand -base64 32` 生成 `REPORT_SESSION_SECRET`，把输出作为 Cloudflare Pages 的环境变量/Secret 配置，不要提交到仓库。
- 在 Cloudflare Pages 项目中进入 Settings -> Environment variables，为 Production（需要时也为 Preview）分别配置 `REPORT_PASSWORD` 和 `REPORT_SESSION_SECRET`。
- 不要把任何 token 写入 Git。

## 路径

- 默认项目根目录从当前源码所在仓库推导，worktree 开发时会写入当前 worktree。
- 可用 `PROJECT_ROOT` 覆盖项目根目录。
- 可用 `REPORTS_DIR` 覆盖报告输出目录。

## 报告

固定入口是 `reports/index.html`。

`render-report --trade-date YYYY-MM-DD` 默认只渲染 Supabase 中已存储的分析记录；如果没有存储记录会失败并提示先写入生产分析记录。要生成本地样例报告，使用 `render-report --fixture-mode --trade-date YYYY-MM-DD`。

生产 `render-report` 会要求每条存储推荐都有匹配证据包，并且对应评估任务已注册；如果 Supabase 中只有部分推荐、证据或评估任务，命令会失败，不会发布回退到推荐理由的成品报告。

正式可读报告先运行 `prepare-formal-report-candidate --trade-date YYYY-MM-DD`。该命令生成并验证隔离候选，但不改动当前报告或 Supabase 激活账本。人工阅读候选并明确接受后，才可用候选的完整哈希和 `--accept-readability` 执行 `activate-formal-report-candidate`；激活不会重新抓取数据或再次调用 Codex。

Cloudflare Pages 只发布报告成品，不发布原始数据、日志、规则编辑器、数据库后台或其他内部调试产物。

## Operations

- Current production capability matrix: [docs/operations/production-capability-matrix.md](docs/operations/production-capability-matrix.md)
- Phase 1 runbook: [docs/operations/runbook.md](docs/operations/runbook.md)
- Cloudflare Pages manual publish and smoke: [docs/operations/cloudflare-pages.md](docs/operations/cloudflare-pages.md)
- Phase 2 Cloudflare automation: see `docs/operations/cloudflare-pages.md` and `docs/superpowers/specs/2026-07-09-v3-phase-2-cloudflare-automation-design.md`.

Operations are approval-gated. Do not enable launchd, run a real production job, run production cleanup, or deploy Cloudflare Pages without explicit approval.

## 验证边界

- `python3 -m pytest` 使用本地 fake Supabase client 和内存仓库，不证明真实 Supabase 项目已连通。
- 默认入口的录制响应测试证明生产工厂、主备客户端和内部数据链已经离线接通，但不证明任何实时端点、真实字段语义、限流、盘后可用性或生产环境写入。
- 默认 `health-check` 不访问网络；`--live-tushare-smoke` 是显式 opt-in 的真实 Tushare 访问路径。
- 真实 Supabase smoke 应验证非 `--dry-run` 的 `run-daily` 使用真实行情源，且在配置或行情不可用时清晰失败、不写样例数据。
- `--dry-run` 可以不设置 Supabase，且不会持久化分析状态。

## 第一阶段验收

- 安装 editable package 后，`python3 -m stock_analyzer health-check` 能输出四类健康状态。
- `health-check` 输出 token 状态（例如 `tushare_token: present:env`），不输出 token 值。
- 未安装 editable package 时，`PYTHONPATH=src python3 -m stock_analyzer run-daily --dry-run --trade-date 2026-07-07` 能完成不持久化 smoke。
- 本地样例报告需显式执行 `PYTHONPATH=src python3 -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07`。
- 每日推荐数量不超过 10 只。
- 重点关注状态和推荐状态分离。
- 每条推荐生成证据包和评估任务。
- 报告内容不包含 `TUSHARE_TOKEN`、`SUPABASE_SERVICE_ROLE_KEY`、`DEEPSEEK_API_KEY`、`BIYING_LICENCE`。
