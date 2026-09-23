# 采用、保存与正常页面

隔离验收沿 `stock_ai run nightly` → `recommendation_pipeline.complete` → `_author_articles` → `run_article_cycle` → 原有同股意见核对、采用、`record-trace`、复盘记录、日报装配、`render_prism_web.py` 运行。样本正式名单一只，作者与事实核对各一次真实会话；核对没有提出实质纠错，故未运行作者修订。

- `accepted-recommendation.json` 使用本轮作者/核对合同，研究身份与该日正式名单一致。其推荐分区原样出现在隔离根正式 `daily-research-2026-09-21.md` 和 `final-reply.md` 中，均只出现一次。作者原稿见 [article.md](articles/300658.SZ/article.md)；程序只将股名标题规范为 `### 延江股份（300658.SZ）`，保留作者副标题与后续全文，[adopted-article.md](articles/300658.SZ/adopted-article.md) 是采用正文。
- 隔离根实际生成 `research-trace-2026-09-21.json`、Forward CSV 当日记录、正式复盘 Markdown 及 `prism-a2-report-2026-09-21.html`。从真实 HTML 的 `script#snapshot` 提取的精简 [页面载荷](evidence/page-payload.json) 含延江股份 `statementFull`，与采用稿去掉股票标题后的全文 **逐字符相等**；页面数据的 delivery 为 completed、推荐正文 `1/1`、公司介绍 `1/1`。页面仍有其他历史条目（共46条），其中飞凯等既存复盘项目未因本股装配消失。
- 尝试用 Codex 浏览器打开隔离根的本地页面时，浏览器 URL 安全策略直接拒绝 `file://`。该策略明确禁止改用替代浏览器入口绕过。因此本轮只验证了真实生成 HTML 的完整页面载荷与正文相等，**没有浏览器视觉截图，也未伪造 `page.png`**。用户要求的视觉核验尚待可允许的页面入口。

首次保存失败和首次展示失败仅源于隔离副本少带历史上游文件及带入旧同日正文；补齐原件、保留冲突副本后，均沿同一已采用稿继续，未增加业务模型调用或改变研究和正文。安装的夜间 launchd 任务保持 disabled；没有合并 main、切换正式任务、部署或覆盖生产 WEB。
