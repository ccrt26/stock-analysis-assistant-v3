# 股票分析助手 V3

这是一个面向中国大陆 A 股的报告优先型分析助手。系统用于生成观察建议、重点关注状态、证据包和后评估任务，不用于自动交易。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,data]"
python -m stock_analyzer health-check
python -m stock_analyzer run-daily --trade-date 2026-07-07
```

如果本机没有 `python` 命令，可改用 `python3`。

## 密钥

- Tushare token 默认读取 `/Users/ccrt/.tushare_token`。
- 也可以通过 `TUSHARE_TOKEN_PATH` 指定本地 token 文件。
- Supabase 写入使用 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`。
- Cloudflare 报告密码使用 `REPORT_PASSWORD`。
- 不要把任何 token 写入 Git。

## 报告

固定入口是 `reports/index.html`。

Cloudflare Pages 只发布报告成品，不发布原始数据、日志、规则编辑器、数据库后台或其他内部调试产物。

## 第一阶段验收

- `python -m stock_analyzer health-check` 能输出四类健康状态。
- `python -m stock_analyzer run-daily --trade-date 2026-07-07` 能生成 `reports/index.html`。
- 每日推荐数量不超过 10 只。
- 重点关注状态和推荐状态分离。
- 每条推荐生成证据包和评估任务。
- 报告内容不包含 `TUSHARE_TOKEN`、`SUPABASE_SERVICE_ROLE_KEY`、`DEEPSEEK_API_KEY`、`BIYING_LICENCE`。
