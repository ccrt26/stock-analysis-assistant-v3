# 三机制与验证映射

本轮候选沿用61f0ebbd719845e44aae3fb5449f0b74b15bf1ad，不改五个选股Skill、复盘方法、D20、采集时间、供应商默认策略或WEB布局。

- `recommendation_pipeline.complete`：独立研究与复盘交付验证后，先调用`prepare_current_research`，作者之前一次集中处理原职责分歧；最终实际文章仍调用独立`current-opinion`合同。缺少相关日评、current_opportunity、正文或截止身份会阻塞，不能算空交集。研究前核对与文字核对共享一次研究处理额度。
- `recommendation_file_io.author_packet`：当前完整含义由原研究职责形成的authoring_note提供。程序只投影事实、比较与来源，去除旧reasoning、历史处理及重复判断。原conditions字段可能包含内部旧价争论，不再作为作者第二份条件依据；必要条件必须在当前note内完整保留。事实核对额外读取完整`authoritative-research.json`，能检查note漏项。整理并不证明内容正确，真实试验逐篇核对。
- `reader_stage_spec`及`stock_ai.run_codex`：独立Astra xhigh、只内嵌文章/股名代码/阅读标准及前轮纯阅读问题，CLI严格禁用工具、插件、浏览、记忆与Skill注入。离线实际请求捕获tools=[]，生产式阶段同时验证配置和可见会话记录。
- 阅读完成后才调用事实核对，确定性合并，两者必须都通过。每任务本股初稿后最多一次修订，换目录或研究版本不清零；已读阶段中断恢复不重抽。旧顶层采用稿、新正文/研究含义不能沿用旧审查。
- 实验只增加`initial_author_spec`有限供料入口，仍执行同一`run_article_cycle`，事实审查取得该作者真正使用的材料。正式默认入口不使用此参数。

## 自动测试对应

| 条目 | 自动证据 |
|---|---|
| T01 | same_day_consistency::test_complete_unresolved_preserves_both_drafts_and_never_records；reader_first::test_T01… |
| T02–T03 | same_day_consistency中的空交集、解释差异、多episode核对测试 |
| T04–T05 | same_day_consistency负责人撤回/不改历史与D20、实际保存及恢复测试；current_opportunity_review、d20_web_readiness |
| T06 | same_day_consistency实际文章引句与未决验证；最终文字阶段仍独立执行 |
| T07–T10 | reader_first相应编号；files_profile实际CLI配置测试；离线能力捕获 |
| T11–T16 | reader_first集中双审修订、两种失败合并、ready冲突、合法删句核销 |
| T17–T18 | reader_first稳定预算及事实中断仅恢复缺失阶段 |
| T19 | normal_recommendation_files::test_unchanged_stock_material_allows_only_trace_rebinding |
| T20 | reader_first::test_T20_modified_article_or_conditions_invalidates_top_level |
| T21–T22 | pipeline_repair_acceptance已有部分完成/空选保存测试；新same_day未决不保存测试 |
| T23 | reader_first固定供料共用循环；files_profile replay及正常作者入口测试 |
| T24 | tests只用tmp_path或外部边界模拟；真实实验另有生产前后核验 |
| T25 | files_profile规范化与装配保留；真实H3日常渲染另验 |
| T26–T27 | reader_first缺日评/条件/时点/正文拒绝；旧任务合同、same_day旧accepted拒绝 |

测试用假模型只证明机制，不证明真人稿质量。原始命令与所有失败日志在tests/。全量一次1791 passed、3 failed、1 skipped，三个失败在未改动baseline复现。相关最终174 passed。不修改无关WEB/公司介绍测试凑全绿。
