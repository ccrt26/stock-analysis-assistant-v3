# 展示 Web 快照（A2 观察总览）

本目录是已发布展示页的静态快照，供 AI 审阅与离线查看；不参与任何构建，也不代表实时状态。

- `index.html`：自包含单文件（内嵌样式、脚本与冻结数据 JSON），快照对应 2026-09-27 18:30 截止的正式复盘（分析日 2026-09-24，9-25 中秋休市），对应 `ccrt26/prism` 仓库提交 `292800e`，即 Cloudflare Workers 当前线上版本。
- 生成链路：`tools/render_prism_web.py` 渲染 → `~/prism-site/public/index.html` → `ccrt26/prism` → Cloudflare Workers。
- 页面源码与适配器在 `tools/guanlan-prism/`；快照按需手动更新，不随数据自动刷新。
