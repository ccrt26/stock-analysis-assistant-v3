# 股票分析助手 V3

这是一个面向中国大陆 A 股的报告优先型分析助手。系统用于生成观察建议、重点关注状态、证据包和后评估任务，不用于自动交易。

## 当前生产状态与文档权威

截至 2026-07-10，Strategy V2 确定性分析逻辑和正式失败关闭框架已经通过离线测试，但正式生产主备客户端、生产数据契约、默认依赖工厂和正式分析适配尚未接通。默认正式任务会安全停止，不会获取完整真实数据或生成正式分析报告。Supabase 正式迁移未应用，launchd 未加载，Cloudflare 首次发布和自动发布未启用。

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

默认 `health-check` 只做本地配置和凭据状态检查，不访问外部网络。旧的有限 Tushare provider 不能绕过正式数据门禁；正式生产路线补齐前，非 fixture 生产命令必须失败关闭，也不能把内置样例数据写入 Supabase。

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

- Tushare token 默认读取 `/Users/ccrt/.tushare_token`。
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

Cloudflare Pages 只发布报告成品，不发布原始数据、日志、规则编辑器、数据库后台或其他内部调试产物。

## Operations

- Current production capability matrix: [docs/operations/production-capability-matrix.md](docs/operations/production-capability-matrix.md)
- Phase 1 runbook: [docs/operations/runbook.md](docs/operations/runbook.md)
- Cloudflare Pages manual publish and smoke: [docs/operations/cloudflare-pages.md](docs/operations/cloudflare-pages.md)
- Phase 2 Cloudflare automation: see `docs/operations/cloudflare-pages.md` and `docs/superpowers/specs/2026-07-09-v3-phase-2-cloudflare-automation-design.md`.
- Deprecated historical phase roadmap (not a current-status source): [docs/operations/mandatory-next-phases.md](docs/operations/mandatory-next-phases.md)

Operations are approval-gated. Do not enable launchd, run a real production job, run production cleanup, or deploy Cloudflare Pages without explicit approval.

## 验证边界

- `python3 -m pytest` 使用本地 fake Supabase client 和内存仓库，不证明真实 Supabase 项目已连通。
- 录制或合成的正式就绪测试不证明默认生产依赖工厂、真实主备客户端或真实数据链已经接通。
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
