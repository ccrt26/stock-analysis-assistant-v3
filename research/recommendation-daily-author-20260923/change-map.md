# 改动与核对位置

| 目标 | 实际接线 | 定向验证 |
|---|---|---|
| 同版完整原研究直接给作者 | `build_article_packet` 保留判断、反证、未知、全部行动条件与原出处；`validate_research_packet` 核对身份及必要内容，不强制额外便笺；`run_article_cycle` 直接进入作者 | `test_complete_original_without_note_uses_two_roles`、`test_all_action_condition_fields_are_kept`、`test_missing_actual_research_does_not_masquerade_as_note_gap` |
| 短作者任务、事实含义核对 | 活动作者与核对 Prompt 被替换；`stage_spec` 作者取得认可范文，核对者仅取得同版研究、文章与必要处理，双方共享权威 `packet.json` | `test_author_and_checker_receive_only_their_materials`、`test_complete_shared_files_cycle_keeps_reviewed_bytes_and_cache` |
| 无错采用、有错集中纠正一次 | 沿用 `run_article_cycle` 的逐篇作者、核对、单次修订/复核和问题核销；稳定预算不因当前意见负责人记录清零 | `test_blocking_condition_overrides_ready_and_needs_revision`、`test_one_revision_and_full_recheck`、`test_revision_budget_survives_new_directory`、原问题核销测试 |
| 中断与旧合同隔离 | 作者与核对合同升级；逐股 `cycle-ready`、顶层 checkpoint/accepted 和 `stock_ai` 同身份快捷复用均检查合同；正式旧历史只读 | `test_changed_contract_rejects_old_stage_cache`、`test_unfrozen_old_accepted_cannot_skip_new_author`、作者后恢复测试 |
| 正常入口、原保存与页面 | `stock_ai run nightly` 仍进入 `recommendation_pipeline.complete` → `_author_articles` → `run_article_cycle`；沿原 `record-trace`、日报装配和渲染路径 | 原入口定向测试；隔离历史日的真实入口记录见 [integration.md](integration.md) |
| 内部业务模型保持批准配置 | `astra-files-v1` 仍固定 `gpt-6-astra / xhigh`，无 fallback | `test_business_model_remains_approved_astra_xhigh`、实际阶段记录 |

正常研究提示、研究合同修复和当前意见负责人提示不再强制额外 `authoring_note`；历史试写用的独立 handoff 工具仍保留供旧材料复核，不在日常活动路径调用。没有修改五个选股 Skill、投资阈值、复盘与页面布局。
