# 股票分析助手 V3 生产运营与部署设计

> **Lifecycle:** Historical operations design. Scheduler and publication code may exist without being production-data-ready or activated. Current status is tracked only in [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md).

## 1. 定位

本设计是 V3 MVP、Tushare Ingestion V1、Storage Governance Continuation 之后的连续下一章，不是孤立补丁。V3 已经完成真实生产首跑、Supabase 决策账本、本地 `local_warehouse`、本地 `local_archive`、容量保护、选择性写入和 Cloudflare Pages 密码门代码。下一章目标是先把系统变成每天稳定自动运行的本机生产流程，再继续建设线上发布、Strategy V2 和 Product UI。

本设计采用“分期连续建设”：

1. **Phase 1：本机 Mac 每日自动运行和发布准备**。
2. **Phase 2：Cloudflare 线上发布自动化**。
3. **Phase 3：Strategy V2 回测、推荐质量复盘和策略升级**。
4. **Phase 4：Product UI，包含报告首页、历史报告、观察池、证据包查看**。

Phase 2-4 是必建阶段，不是可选项；只是为了减少一次性 scope，Phase 1 先让自动化和发布流程跑通。

## 2. Phase 1 目标

Phase 1 只建设“稳定每天自动跑 + 准备发布包 + 线上 smoke 命令”：

- 本机 Mac 使用 `launchd`，每天 18:30 首跑。
- 失败后先自检和分类；可重试失败在 19:00、19:30 最多重试两次。
- 每次重试前自动清理当天 `trade_date` 的部分结果，避免半截数据和重复数据。
- 非交易日不运行分析，只写状态，不覆盖旧报告。
- 交易日判断优先读取 Supabase `market_calendar`；缺失时用 Tushare 补齐并写回；两者都不可用时标记 `calendar_unknown` 并需要人工介入。
- 成功后准备 Cloudflare Pages 发布包到 `dist/pages`，但不自动上传。
- 提供线上 smoke 命令，供手动 Cloudflare 发布后验证登录、报告日期、fixture/sample 和密钥泄露。
- 只在需要人工介入时弹 Mac 通知；成功、无推荐、非交易日、warning 不打扰。

Phase 1 不做：

- 自动 Cloudflare 上传。
- Strategy V2 回测。
- Product UI 改版。
- GitHub Actions 生产 `run-daily`。

## 3. 用户产物与机器产物

用户真正关心的是分析结果，不是运行报告。系统必须把两类产物分开：

**用户可见主产物：**

- 今日股票分析报告。
- 今日推荐。
- 重点观察池。
- 证据包。
- 历史报告。

**机器可读运行产物：**

- `logs/run-daily/YYYY-MM-DD.log`
- `logs/run-daily/latest-status.json`
- 当天 retry 记录。
- 错误分类。
- 清理记录。
- 修复建议。
- 运行健康检查结果。

机器运行产物默认不进入报告首页，不抢占分析结果。报告最多显示轻量数据状态，例如“数据状态：正常/有警告”。如果生产运行失败，则不发布当天新报告，保留旧报告。

## 4. 状态模型

Phase 1 的 job 状态必须让系统能自动判断是否正常、哪里不正常、如何修复。

状态至少包括：

- `success_with_recommendations`
- `success_no_recommendations`
- `skipped_non_trading_day`
- `calendar_unknown`
- `warning`
- `failed_retryable`
- `failed_needs_human`

`latest-status.json` 至少包含：

- `trade_date`
- `attempt`
- `scheduled_slot`: `18:30`、`19:00` 或 `19:30`
- `started_at`
- `finished_at`
- `status`
- `stage`
- `failure_class`
- `retryable`
- `cleanup_performed`
- `cleanup_summary`
- `recommendations`
- `evidence_packages`
- `evaluation_tasks`
- `market_price_daily_current_day_rows`
- `daily_basic_indicator_current_day_rows`
- `supabase_database_size_mb`
- `report_index_exists`
- `archive_manifest_exists`
- `warehouse_updated`
- `deploy_artifact_prepared`
- `publish_skipped_reason`
- `fix_suggestion`
- `error_message_redacted`

不得写入任何密钥原文。

## 5. 重试和清理

失败后不能盲目重跑。流程是：

1. 记录失败阶段。
2. 自检并分类。
3. 若属于可重试失败，清理当天部分结果。
4. 重新运行。
5. 仍失败则重复一次。
6. 三次均失败后停止，保留旧报告，弹 Mac 通知。

重试时间：

- 18:30 首跑。
- 19:00 第一次重试。
- 19:30 第二次重试。

重试前自动清理范围必须锁定为当天 `trade_date`：

- Supabase：当天 `recommendation_daily`、`focus_watchlist_state`、`evidence_package_index`、`evaluation_task`、`market_price_daily`、`daily_basic_indicator`、`data_source_run`。
- 本地报告：`reports/daily/YYYY-MM-DD/`。
- 本地 archive：当天 manifest 和当天 report 副本。
- 本地 warehouse：当天 parquet 分区重写或替换。

禁止：

- 删除历史日期。
- 清空整张 Supabase 表。
- 删除整个 `stock_master`。
- 删除整个 `local_archive` 或 `local_warehouse`。
- 清理失败后继续重试。

## 6. 失败分类

由系统科学判断失败类别。原则是“小波动自动恢复，重大风险停止并提醒人工介入”。

**自动重试：**

- Tushare 当日数据暂时不可用。
- 网络超时、DNS、临时连接失败。
- Supabase 单次请求超时或 5xx。
- 报告生成临时 IO 问题。
- 发布包准备发现上一步产物尚未完成。

**停止重试，人工介入：**

- `.env.local` 缺失。
- Supabase key 或 Tushare token 缺失/无效。
- Supabase 容量达到 400 MB stop。
- 数据清理失败。
- Python import error、schema mismatch、migration drift。
- 检测到可能全市场数据写入 Supabase。
- fixture/sample 进入生产报告。
- 报告产物缺失或 JSON 结构不对。
- 三次尝试后仍失败。
- 交易日历无法判断。

**成功但带 warning：**

- 推荐数少于 10，但系统正常执行。
- 当天无推荐，且未降低标准凑数。
- 个别股票行情缺失但覆盖率达标。
- Supabase 容量超过 350 MB 但低于 400 MB。
- 发布包已准备但尚未上传。

## 7. 非交易日

非交易日不跑分析，不生成新推荐，不清理旧报告，不准备新的发布包。

非交易日只写：

- `latest-status.json`，状态为 `skipped_non_trading_day`。
- 当天 job log。

非交易日默认不弹 Mac 通知。

## 8. Cloudflare 发布

Phase 1 必须建设 Cloudflare 发布能力，但不自动上传。

成功生产运行后自动准备 `dist/pages`：

- 复制当前 `reports/` 静态产物。
- 带上 `functions/_middleware.ts`。
- 不包含 `.env.local`、`.git`、`.venv`、`local_warehouse`、`local_archive`、`logs`、`data/cache`、`data/raw`、`.superpowers`。

手动发布命令由 runbook 提供，例如：

```bash
npx wrangler pages deploy dist/pages --project-name stock-analysis-assistant-v3
```

Phase 1 必须提供线上 smoke 命令，验证：

- 未登录访问 `/` 跳转 `/login`。
- `/login` 可访问。
- 正确密码能进入报告。
- 首页报告日期正确。
- 页面不包含 fixture/sample。
- 页面不包含密钥变量名或敏感值。
- 失败时输出修复建议。

自动上传 Cloudflare 是 Phase 2 必建内容。

## 9. 通知

Phase 1 通知方式：

- 本地日志和 `latest-status.json` 永远写。
- 只在 `failed_needs_human` 时弹 Mac 通知。
- 成功、无推荐、非交易日、warning、正在重试的失败不弹。
- 不接入微信、邮件、Telegram、Webhook。

Mac 通知内容必须是脱敏摘要和处理建议，不包含 token、service-role key、Cloudflare token、`.env.local` 原文。

## 10. 模型和执行治理

后续执行采用 Subagent-Driven Development。模型策略以效率和准确性为目标，不为了表面节省降级导致返工。

- Phase 1 implementer 默认 GPT-5.5 xhigh。
- Phase 1 reviewer 默认 GPT-5.5 xhigh。
- 生产自动化、清理重试、Supabase、Cloudflare、告警、安全边界、交易日历、最终 review 必须 GPT-5.5 xhigh。
- Strategy V2、Product UI 设计和最终 review 必须 GPT-5.5 xhigh。
- 禁止使用 mini 模型处理生产安全、金融策略、密钥、迁移、部署、自动化、清理重试。
- 只有纯格式化文档或非常机械的非生产测试命名变更，才可以另行请求用户允许低配模型。

## 11. Phase 2-4 必建路线

**Phase 2：Cloudflare 自动发布**

- 成功后自动 `wrangler deploy`。
- 部署后自动线上 smoke。
- 失败不覆盖上一份线上可用报告。
- Cloudflare token 脱敏和权限最小化。

**Phase 3：Strategy V2**

- 5/20/40 交易日回测。
- 推荐质量评分。
- 行业/市值/流动性约束。
- 每日结果复盘。
- 任何策略改动必须先通过回测和新设计，不直接手工调参上线。

**Phase 4：Product UI**

- 报告首页升级。
- 历史报告。
- 观察池。
- 证据包查看。
- 移动端和桌面端可读性。

## 12. Phase 1 验收

Phase 1 完成时必须满足：

- 可安装但默认不启用的 `launchd` 配置存在。
- 18:30/19:00/19:30 调度规则写入配置和 runbook。
- 非交易日跳过逻辑可测试。
- 交易日历优先 Supabase，缺失时 Tushare 补齐。
- 可重试失败会在重试前清理当天部分结果。
- 不可重试失败会停止并给出修复建议。
- `latest-status.json` 机器可读。
- Mac 通知只在需要人工介入时触发。
- 成功后准备 `dist/pages`，但不上传 Cloudflare。
- 线上 smoke 命令存在。
- 本地测试全量通过。

## 13. 参考资料

- Cloudflare Pages build configuration: https://developers.cloudflare.com/pages/configuration/build-configuration/
- Cloudflare Pages Direct Upload: https://developers.cloudflare.com/pages/get-started/direct-upload/
- Cloudflare Pages Functions middleware: https://developers.cloudflare.com/pages/functions/middleware/
- GitHub Actions workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

## 14. Approval

Approved direction: 分期连续建设。Phase 1 聚焦本机 Mac 自动运行、重试清理、状态自检、Mac 通知、发布包准备和线上 smoke；Phase 2-4 为后续必建阶段。
