# 股票分析助手 V3

这是一个面向中国大陆 A 股的报告优先型分析助手。系统用于生成观察建议、重点关注状态、证据包和后评估任务，不用于自动交易。

## 本地运行

需要 Python 3.11 或更新版本。推荐路径：创建虚拟环境并安装 editable package 后运行。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev,data]"
python3 -m stock_analyzer health-check
python3 -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07
```

生产 `run-daily` 在真实行情接入实现前会明确失败，不会把内置样例数据写入 Supabase。

未安装 editable package 的开发路径：使用 `PYTHONPATH=src` 直接运行源码。这是当前 smoke 已验证命令路径。

```bash
PYTHONPATH=src python3 -m stock_analyzer health-check
PYTHONPATH=src python3 -m stock_analyzer run-daily --dry-run --trade-date 2026-07-07
PYTHONPATH=src python3 -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07
```

## 密钥

- Tushare token 默认读取 `/Users/ccrt/.tushare_token`。
- 也可以通过 `TUSHARE_TOKEN_PATH` 指定本地 token 文件。
- 生产报告渲染必须设置 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`。
- 生产 `run-daily` 还需要真实行情接入；当前 MVP 未实现接入时会失败，不会持久化样例推荐。
- 本地样例报告必须显式使用 `--fixture-mode`，或设置 `STOCK_ANALYZER_FIXTURE_MODE=1`。
- Cloudflare 报告密码使用 `REPORT_PASSWORD`。
- 不要把任何 token 写入 Git。

## 路径

- 默认项目根目录从当前源码所在仓库推导，worktree 开发时会写入当前 worktree。
- 可用 `PROJECT_ROOT` 覆盖项目根目录。
- 可用 `REPORTS_DIR` 覆盖报告输出目录。

## 报告

固定入口是 `reports/index.html`。

`render-report --trade-date YYYY-MM-DD` 默认只渲染 Supabase 中已存储的分析记录；如果没有存储记录会失败并提示先写入生产分析记录。要生成本地样例报告，使用 `render-report --fixture-mode --trade-date YYYY-MM-DD`。

Cloudflare Pages 只发布报告成品，不发布原始数据、日志、规则编辑器、数据库后台或其他内部调试产物。

## 验证边界

- `python3 -m pytest` 使用本地 fake Supabase client 和内存仓库，不证明真实 Supabase 项目已连通。
- 真实 Supabase smoke 在生产行情接入完成前应验证非 `--dry-run` 的 `run-daily` 清晰失败且不写样例数据。
- `--dry-run` 可以不设置 Supabase，且不会持久化分析状态。

## 第一阶段验收

- 安装 editable package 后，`python3 -m stock_analyzer health-check` 能输出四类健康状态。
- 未安装 editable package 时，`PYTHONPATH=src python3 -m stock_analyzer run-daily --dry-run --trade-date 2026-07-07` 能完成不持久化 smoke。
- 本地样例报告需显式执行 `PYTHONPATH=src python3 -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07`。
- 每日推荐数量不超过 10 只。
- 重点关注状态和推荐状态分离。
- 每条推荐生成证据包和评估任务。
- 报告内容不包含 `TUSHARE_TOKEN`、`SUPABASE_SERVICE_ROLE_KEY`、`DEEPSEEK_API_KEY`、`BIYING_LICENCE`。
