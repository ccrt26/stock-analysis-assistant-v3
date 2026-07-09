# 股票分析助手 V3 Phase 2 Cloudflare 自动发布设计

## 1. 定位

Phase 2 是 Phase 1 生产运营基础之后的连续建设阶段，不是孤立补丁。Phase 1 已经完成本机生产运行、重试清理、状态自检、`dist/pages` 发布包准备、Cloudflare 密码门和线上 smoke 命令。Phase 2 只负责把已经生成好的分析报告安全、简单、自动地发布到 Cloudflare Pages。

Phase 2 不判断股票推荐是否靠谱。推荐质量、回测、评分、行业/市值/流动性约束和每日复盘属于 Phase 3 Strategy V2。

Phase 2 的用户目标是：第一次人工一键发布，成功后系统自动切换为全自动发布。发布不能成为用户负担。

## 2. 已确认方案

采用方案 A：本机最简单闭环。

- 第一次由用户运行一个固定命令，例如 `stock-analyzer-publish`。
- 第一次发布成功并通过线上 smoke 后，系统自动启用后续全自动发布。
- 之后每天本机生产流程最终成功后自动发布到 Cloudflare。
- 发布失败时系统自动自检、自动修复可恢复问题、最多重试 1 次。
- 新版本已经上线但线上 smoke 失败时，系统自动回退到本地保存的上一版正常发布包。
- 只有不能自动修复的问题才提醒用户。
- 成功只反馈一句结论和网站链接；详细过程留给机器状态和本地诊断文件。

## 3. 第一版范围

Phase 2 第一版必须建设：

- 本机一键发布命令。
- 发布前自动选择当天成功且有推荐的报告。
- 发布前重新准备 `dist/pages`。
- 发布前检查本机配置、Cloudflare 凭据、报告密码保护配置、Supabase 容量状态。
- 使用 Wrangler 执行 Cloudflare Pages Direct Upload。
- 发布后自动线上 smoke。
- 保存上一版成功发布包，作为 last known good。
- smoke 失败时自动回退上一版并再次 smoke。
- 本地发布状态文件。
- 只显示结论的本地状态页。
- Mac 通知，只在需要人工介入时提醒。
- 第一次发布成功后自动打开全自动发布开关。
- 与 Phase 1 `run-daily-job` 衔接：18:30 首跑或 19:00/19:30 重试最终成功后触发自动发布。

Phase 2 第一版不做：

- Strategy V2 推荐质量优化。
- Product UI 改版。
- GitHub Actions 自动发布。
- Cloudflare API 直接部署。
- 发布结果写入 Supabase。
- 桌面双击入口。
- 微信、邮件、Telegram、Webhook 通知。

## 4. 用户操作方式

第一次发布只有一个人工操作：运行固定命令。

命令行为：

1. 自动判断今天是否有可发布报告。
2. 自动准备发布包。
3. 自动上传 Cloudflare。
4. 自动线上检查。
5. 成功后输出一句结论和线上链接。
6. 成功后自动启用后续全自动发布。

用户不需要输入日期。默认发布当天报告。

允许提供高级参数用于人工补发历史日期，但这不是默认流程。历史补发属于人工介入场景，例如次日重新跑前一交易日后补发。

成功反馈必须简短，例如：

```text
发布成功：线上报告 2026-07-08，链接：https://example.pages.dev
```

## 5. 发布选择规则

默认发布当天报告：

- 今天是交易日，当天生产成功且推荐数大于 0：发布当天报告。
- 今天不是交易日：不发布，线上保留上一版。
- 今天是交易日但当天还没有成功运行：不发布，提示今天还没有可发布报告。
- 今天成功运行但推荐数为 0：不发布，记录当天无推荐。
- 推荐数为 1 到 9：发布。这是策略质量问题，交给 Phase 3 优化。
- Supabase 容量到危险线：不发布，保留上一版并提醒人工处理。

发布流程只发布分析报告网站，不发布 `.env.local`、Supabase key、Tushare token、Cloudflare token、本地数据库、日志、原始缓存或内部运行材料。

## 6. 发布编排

新增发布编排器，职责是串联 Phase 1 已有产物和 Cloudflare 发布：

1. 读取本地生产状态。
2. 判断是否满足发布条件。
3. 检查配置和容量。
4. 调用现有 artifact preparation，重新生成 `dist/pages`。
5. 检查发布包禁止路径和敏感内容。
6. 调用 Wrangler 上传 `dist/pages`。
7. 调用现有 `smoke-report-site` 验证线上报告。
8. 成功后保存 last known good 发布包。
9. 写本地发布状态。
10. 生成本地状态页。
11. 如这是首次成功发布，启用全自动发布。

全自动发布接在 Phase 1 整个生产流程最终成功之后。18:30 首跑成功就发布；如果 18:30 失败但 19:00 或 19:30 重试成功，也发布；最终失败则不发布。

## 7. Cloudflare 发布方式

第一版使用官方 Wrangler 命令发布 Cloudflare Pages Direct Upload。

原因：

- Wrangler 是 Cloudflare 官方发布工具。
- 当前 Phase 1 文档已经采用 `wrangler pages deploy dist/pages`。
- Cloudflare 官方 Direct Upload 文档说明 Wrangler 可上传一个构建输出目录。
- 当前报告需要 `functions/_middleware.ts` 密码门；Cloudflare 文档说明带 `functions` 目录的 Pages Functions 发布应使用 Wrangler。
- 第一版目标是快速、稳定跑通流程，不在第一版重造 Cloudflare API 发布层。

后续优化保留 Cloudflare API 方向，用于更精细地读取 deployment id、版本列表和回退能力。

## 8. 配置和凭据

Phase 2 第一版使用本机 `.env.local` 中的长期环境变量。设计需要读取变量名，但不能打印、复制、提交或写入报告。

需要的配置包括：

- Cloudflare 发布凭据。
- Cloudflare Pages project name。
- 线上报告地址，例如 `REPORT_SITE_URL`。
- 报告访问密码。
- 报告 session secret。
- Supabase 配置，用于读取容量和生产状态。

`REPORT_SITE_URL` 第一版固定写入本机配置，便于自动 smoke。后续可从 Cloudflare 发布结果自动推断线上链接。

GitHub Secrets / GitHub Actions 发布作为后续优化方向，不进入第一版实现。

## 9. 线上 Smoke

线上 smoke 不判断股票推荐质量，只判断网站是否正常、安全发布。

必须检查：

- 未登录访问 `/` 会跳转 `/login`。
- `/login` 可访问。
- 正确密码可以进入报告。
- 首页报告日期是预期交易日。
- 页面不包含 fixture/sample/test 标记。
- 页面不包含密钥变量名或疑似密钥内容。
- 页面可正常打开。

发布前还要检查本机是否具备密码保护所需配置。发布后再通过线上 smoke 证明密码保护实际生效。

## 10. 自动恢复

发布失败处理遵循“小波动自动恢复，重大问题停止并提醒”的原则。

可自动恢复的问题包括：

- 网络临时失败。
- Cloudflare 临时 5xx 或超时。
- Wrangler 单次执行失败但配置完整。
- 发布包刚生成后文件还未稳定。

自动恢复策略：

- 自动自检原因。
- 能修复时先修复，例如重新准备发布包。
- 最多重试 1 次。
- 如果新版本已经上传但线上 smoke 失败，使用本地 last known good 发布包回退。
- 回退后再次运行线上 smoke，确认旧版可用。

需要人工介入的问题包括：

- Cloudflare 凭据缺失或无效。
- Cloudflare 权限不足。
- Cloudflare Pages project name 或线上 URL 配置错误。
- 报告密码或 session secret 缺失。
- Supabase 容量到危险线。
- 发布包疑似包含密钥、测试数据或禁止路径。
- 当天没有成功生产报告。
- 当天成功但 0 推荐。
- 回退失败。
- 重试 1 次后仍失败。

## 11. 用户提醒

只有需要人工介入时才提醒用户。

提醒方式：

- Mac 通知弹出一句清楚提醒。
- 本地状态页显示当前待处理问题。
- 本地发布状态文件保留机器可读详情。

用户看到 Mac 通知后可以关掉。这只表示用户知道了，不表示问题已经解决。问题状态仍保留在本地状态页，下一次发布或自检恢复正常后系统自动清除。

提醒必须使用人话，至少包含：

- 出了什么问题。
- 系统已经自动做了什么。
- 线上现在是否安全，是否已回退上一版。
- 用户需要做哪一步。

## 12. 本地状态页和状态文件

本地状态页面向用户，只显示结论：

- 当前线上报告日期。
- 最近一次发布是否成功。
- 是否有待处理问题。
- 线上报告链接。
- 如有问题：一句原因和用户需要做什么。

本地机器状态文件面向系统自检，至少包含：

- 发布状态。
- trade_date。
- attempt。
- started_at / finished_at。
- published_url。
- Cloudflare project name。
- redacted deployment summary。
- smoke checks。
- rollback_performed。
- last_known_good path。
- failure_class。
- fix_suggestion。
- auto_publish_enabled。

机器状态文件不得包含任何密钥原文。

发布状态暂时只写本地，不写 Supabase。

## 13. Last Known Good

每次发布成功并通过线上 smoke 后，系统保存当前发布包为 last known good。

用途：

- 新版本上线后 smoke 失败时自动回退。
- Cloudflare 历史版本行为变化时仍有本地可控回退路径。
- 用户无需理解 Cloudflare 版本管理。

保存位置必须是本地生成目录，并保持未跟踪。它不能进入 Git，也不能发布到 Cloudflare 除非用于回退。

## 14. 安全边界

Phase 2 不得：

- 打印 `.env.local` 内容。
- 打印 Cloudflare token、Supabase service-role key、Tushare token、报告密码或 session secret。
- 将任何密钥写入日志、报告、状态页、发布状态文件或 Cloudflare 静态文件。
- 发布 `local_warehouse`、`local_archive`、`logs`、`data/cache`、`data/raw`、`.git`、`.venv`。
- 在非交易日发布新报告。
- 发布 0 推荐报告。
- 在 smoke 失败后把失败状态当作成功。
- 在回退失败后继续静默运行。

## 15. 测试和验收

Phase 2 实现完成时必须验证：

- 一键发布命令在 mock Wrangler 下能完整跑通。
- 首次成功后自动打开全自动发布状态。
- 当天无成功报告时不发布并给出人话原因。
- 非交易日不发布。
- 0 推荐不发布。
- 1 到 9 推荐允许发布。
- 发布前重新生成 `dist/pages`。
- 禁止路径不会进入发布包。
- 发布前配置缺失会停止并脱敏提示。
- Supabase 容量危险会阻止发布。
- Wrangler 临时失败会自动重试 1 次。
- smoke 失败会触发 last known good 回退。
- 回退后再次 smoke。
- Mac 通知只在人工介入时触发。
- 本地状态页只显示结论，不暴露技术细节和密钥。
- 本地机器状态文件脱敏。
- 全量测试通过。

真实 Cloudflare 部署验证必须在用户明确批准后执行。

## 16. 模型和执行治理

Phase 2 属于生产发布、安全边界、Cloudflare 自动化和失败恢复工作。所有 implementer、reviewer 和相关 subagent 必须使用 GPT-5.5 xhigh。不得使用 mini 模型处理 Phase 2 设计、实现、review、发布验证、密钥、Cloudflare、Supabase 容量和自动化。

后续执行必须采用 Subagent-Driven Development 或等价的 Superpowers 执行流程，并在实现前写详细 implementation plan。

## 17. 后续优化方向

后续优化包括：

- GitHub Actions / GitHub Secrets 发布。
- Cloudflare API 精细化部署、deployment id 管理和版本回退。
- 从 Cloudflare 发布结果自动推断线上链接。
- 桌面双击发布入口。
- 更丰富的通知渠道。
- 更完整的线上监控。
- Phase 3 Strategy V2。
- Phase 4 Product UI。

这些方向必须记录，但不进入 Phase 2 第一版实现范围。

## 18. 参考资料

- Cloudflare Pages Direct Upload: https://developers.cloudflare.com/pages/get-started/direct-upload/
- Cloudflare Pages Functions middleware: https://developers.cloudflare.com/pages/functions/middleware/
- Cloudflare Pages Rollbacks: https://developers.cloudflare.com/pages/configuration/rollbacks/
- Existing Phase 1 design: `docs/superpowers/specs/2026-07-09-v3-production-operations-and-deployment-design.md`
- Existing Cloudflare runbook: `docs/operations/cloudflare-pages.md`

## 19. Approval

用户已确认采用方案 A：本机一键发布，第一次成功后自动转为全自动发布；失败自动自检、最多重试 1 次、必要时回退上一版；只有不能自动修复的问题才用人话提醒用户。
