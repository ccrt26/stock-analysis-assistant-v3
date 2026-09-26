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

## 正式续跑发现的必要局部适配

`tools/recommendation_file_io.py::read_output`：真实核对稿用`fidelity_issues.issue_kind=omission`表示原研究必要理由遗漏；提示未枚举类别，既有适配器拒收。只在内存将此精确别名规范为现有`reasoning_gap`，再运行原校验。原文件与哈希不变、blocking和ready不变、真实研究问题全部保留；其他非法类别和非布尔/缺失blocking仍拒绝。不改Prompt、输入身份、作者循环、预算或路由，利用现有failed_output_hashes恢复原审稿，不再次抽样。原独立审查者就这一具体新失败补审通过（以修订版为准）；无新角色。验证并入原T10。

`tools/recommendation_pipeline.py::parse_clarification_output`：第二份真实回执在resolutions以requires_research_change/阻塞描述问题，并在unresolved重述同一未决事实。仅在对应ID两组各一条、类型为原BLOCKING_TYPES且blocking严格true时允许共存，两组内容原样保留；其他跨数组冲突仍拒绝，不新增一般重复治理。现有resolve_article_issues继续将其列入blocking，原输出恢复不新增澄清会话。原审查者对具体新故障补审通过；原T10包含真实处理函数和否定分支验证。不修改循环、预算、研究方法或路由。
