# 推荐作者文件工作方式：候选实现

显式配置 `recommendation_authoring_profile=astra-files-v1` 才启用。缺省保留旧作者合同和模型路线；本变更不激活调度，不修改实际知识库或长期配置。

现有选股研究通过 `selection-handoff.json` 的 `stocks[ts_code].authoring_note` 交清原有意见、依据、反证与条件，并延续完整 trace 的身份与指纹绑定。历史 `replay-files` 则调用实际研究 handoff-only 阶段生成便笺，只绑定所读取原包的字节、内容和身份，不声称已核对未读取的完整 trace。空 risk_acceptance 字段不会被程序自动判为决定性研究缺口。

`recommendation_pipeline._author_articles` 和 `recommendation_trial.replay_files` 都使用 `run_article_cycle`。角色通过 `article_stage` 的文件适配复用已有状态、问题处理和有限修订机制；文件辅助模块仅构造输入、读取输出并规范 Markdown。作者按需读完整原包、研究便笺、唯一简明指南和时点适用范文，输出 Markdown；审稿输出完整意见及原回执字段。研究问题优先澄清，不送审空稿。固定历史回放的澄清和表达修订各最多一次；旧预算缺省不变。

新阶段明确使用 Astra xhigh、禁备用；文件阶段允许本地工具，关闭网络、实时搜索、继续委派和隐式项目指导。新旧作者、审稿和研究交接合同分别标识。实际型号、强度与会话来自 turn_context、请求传输和可见工具记录，不能用预期配置代替。输出不导出隐藏推理、系统指令、加密内容或认证头。

每个文件阶段使用独立真实目录，输入原件和来源进入索引；调用后及缓存复用前核对不变性。所有草稿、回执和失败记录保留。新一轮只改标题标记并在送审前完成规范；最终装配不再次润色。三个固定小标题不再是推荐文章的格式门槛，股票身份、名单、顺序、实际正文与独立复盘分区仍受原校验约束。

完成且同输入的阶段复用；输入、来源、任务合同、profile、模型和强度进入身份。终态失败、坏回执或未核实执行不能重新抽样。明确中断且原会话无完成/失败事件时，`--resume` 仅续接该会话，保留部分输出与原次数；缺中断记录则说明不能确认恢复，不新建替代会话。

新增命令：`recommendation_trial.py replay-files`，参数见其 help。此入口不执行正式 prepare、record、freeze、render 或数据库初始化。已完成回放不允许再次 resume。文章 ready 只表示本次程序和审稿回执状态，不代表用户文章认可、日常长期稳定或生产部署。

验证使用真实文件包、路由、缓存、共享入口与临时合成仓，只替代模型/子进程边界。实际调用、测试数量、生成提交和暂停证据保存于本地复核包；不将私人文章、范文、输入事实或会话日志提交版本库。

CLI 接口依据：[非交互执行](https://developers.openai.com/codex/noninteractive)、[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。现成 CLI 的版本与 help 另存本地证据；未升级工具。

离线记录：相关回归 299 通过；一次全量 1693 通过、4 失败、1 跳过。两个额外纯标题断言分别在 `test_pipeline_repair_acceptance` 与 `test_statement_display`，按执行单必要表外依赖条款先说明后同步，未修改其数据、身份或来源保护。其余两项是 `test_prism_a2_preview` 的 `test_assemble_series_builds_theme_comparisons` 和 `test_series_theme_conflict_against_snapshot_industry_raises`，均在读取候选工作树空交易日历时抛错；不修改事实仓或 Prism。测试修订后仅定向复测，不把初次全量报告改成全绿。

两处旧格式断言同步后的定向回归：39 通过。程序代码在上述一次全量后没有变化。


固定生成版本的唯一真实回放：交接由 Astra xhigh 完成，实际会话型号、强度和文件读取证据可见。交接明确维持原判断，却将一项非决定性比较核验缺口记录在 research_issues；原入口错误地把数组非空等同于决定性阻断，返回 needs_research，作者和审稿未启动，没有文章。这是接入缺陷，不是模型不可用或研究自动改判。

生成后的离线修正：交接提出的问题进入已有 resolve_article_issues，沿用本轮一次澄清总预算，由现有 resolutions/unresolved 语义决定是否继续。程序不按“非阻断”等关键词放行，也不由开发者作研究判断；澄清后的同版视图同时提供作者和审稿。此修正仅做合成边界验证，本轮不再次发起真实调用、不改旧 summary、不把旧交接标为新源码生成。生成版本与后续候选修正版本分别记录，后者尚未经过真实回放。
