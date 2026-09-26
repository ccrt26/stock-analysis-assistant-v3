# 改动对应关系

| 执行单要求 | 落点 |
| --- | --- |
| 三态、结束原因、首次初始化、缺资料、旧 episode 不复活 | `src/stock_analyzer/ops/forward_monitor.py` 的账本字段与状态校验；活动复盘 Skill |
| 状态不变简评、变化全覆盖、一股一份正文 | `record_daily_formal_reviews`、`record_forward_monitor`、`_render_state_change_markdown`；`ops/forward-monitor-prompt.md` |
| 节点内部化、D20 固定结案、原延长保留 | 原 snapshot/ledger/final 字段与保存校验；不从 final 字段在公开日报追加文章 |
| 同股事实去重、各 episode 原依据和风险保留 | `build_state_change_input`；一次输入索引内嵌一套指南与两篇教学 |
| 新任务绑定策略、旧任务不跨策略 | `tools/stock_ai.py` 的 run_policy 和动态 Prompt；legacy Prompt/Skill 保留 |
| 当前参与意见独立、同股单正文 | `tools/recommendation_pipeline.py` 的当前意见交接；内部 D20 无新参与意见 |
| 日报与页面读取 | `tools/nightly_report.py`、`tools/render_monitor_web.py`、`tools/render_prism_web.py`、`tools/web_display_contract.py`、PRISM A2 数据适配与标签渲染 |
| 活动规则无旧长写义务 | 活动 Skill、两份 Prompt、`AGENTS.md` 冲突条文、`docs/state-change-review-v1.md` |

未增加数据库、队列、股票池、AI 摘要员、独立文风模型或新定时任务。未改选股规则和推荐作者 profile。
