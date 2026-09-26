# 改动对应

| 文件/函数 | 必要变化 |
|---|---|
| forward_monitor.final_review_history | 新策略验证正式报告结构、同日期/截止/策略，承认有效最终对象交付；保留最早冻结、旧模式原语义 |
| _daily_review_history / prepare_forward_monitor | 校验历史文件日期和截止；携带同episode最早正式live停止依据，不改历史三态；保留原停止日期/原因 |
| _previous_tracking_stop / _validate_state_change_ledger | 旧停止可内部结案，拒绝brief、复活或改原因；_previous_tracking_state保持原含义 |
| build_state_change_input | 实际下发停止来源、最早冻结及来源、仅待补交付标记和三篇新知识正文 |
| stock_ai.nightly_run_policy / recommendation_pipeline.run_stage | 本任务可选astra_reasoning_effort=xhigh复用已有Astra配置/回执校验；monitor/介绍不变为文件作者角色 |
| 活动复盘Skill/Prompt、总控Review段 | 单套写法、正确legacy链接、原会话通读正文；不改选股方法与作者预算 |
| tests/test_state_change_repair.py | T01—T12：真实prepare/save/assemble、同股意见、文件作者缓存与假进程命令；不新建测试平台 |

同股当前意见入口已有current_opportunity=None跳过逻辑，本次只验证不改动。D20价格计算、WEB布局、数据库与调度均未修改。
