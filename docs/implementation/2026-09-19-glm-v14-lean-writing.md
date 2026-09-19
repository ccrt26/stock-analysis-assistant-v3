# V1.4 推荐说明减负实施记录（脱敏）

日期：2026-09-19。分支 fix/recommendation-authoring-20260918，接续 c6073350bd0633c7f35c54edd3196532b6bf87a1。本文不包含真实文章、私有材料或本机路径。

## 实际修改

- `ops/recommendation-authoring-prompt.md`、`ops/recommendation-review-prompt.md`：按执行包 runtime 全文替换（任务接口不变，输出合同仍为同一 JSON 接口；解释权限与整体审稿要求更新）。
- `.agents/skills/orchestrating-stock-research/references/selection-writing-calibration.md`：整篇改为短导航；表达指导唯一文本入口是 Obsidian 阅读指南。
- `tools/recommendation_pipeline.py`：仅 `AUTHOR_CONTRACT_VERSION`/`REVIEW_CONTRACT_VERSION` v3→v4，`_author_material` 改为只返回 `reading_guide` 与 `examples`；辅助脚本以 AST 核对其余函数与常量完全未变。
- `tests/test_recommendation_v13_contract.py`：仅两个版本预期 v3→v4，其余断言不动。
- 新增 `tests/test_recommendation_v14_inputs.py`：9 个输入回归（合同版本、作者仅收指南+范文且 packet 不变、修订/审稿同材料、指南与范文变化会改变实际请求、诊断字段不再注入、无指南不回退旧教学、读取器筛范文、fact 类意见程序行为）。

## 未改项

`writing_material` 范文选择、`build_article_packet`、`run_article_cycle`、`build_effective_packet`、`complete`、预算与缓存恢复逻辑、问题枚举与审稿解析器、澄清合同（仍 v2）、正式研究逻辑、事实仓、trace、CSV、复盘、D20、WEB、自动任务、实际 Obsidian 均未改。共同要点原件仍在实际知识库中保留。

## 离线验证（本轮实际运行）

- 包 SHA256 核对一致。
- 基线（应用前新测试）：5 failed / 4 passed，失败均为行为差异（v3 常量、旧教学注入仍在），非导入错误。
- 应用后：`test_recommendation_v14_inputs.py` + `test_recommendation_v13_contract.py` 全部通过；相关保护（pipeline/authoring/trial/stock_ai/readability）全部通过。
- V1.2 外部五例（从原保存路径 test_handoff_acceptance.py 运行）：5/5 通过。
- 全量 pytest：1624 passed / 1 skipped / 2 failed；两失败仍为 `tests/test_prism_a2_preview.py` 已知用例，原因仍是验收工作树 `local_warehouse/facts/trade_calendar` 为空（与 V1.2/V1.3 基线相同的环境失败，非本轮引起）。
- 旧文本断言零调整；无断言降级或 mock 受测函数。

## 试写状态

两篇（固定股票、repeats=1、仅 GLM-5.3-flash、fallback=False）准备与运行状态见运行根记录；本文在生成提交时先记录"待运行"，终态在试写完成后更新，不以通过数预填。

## 采用前提（本轮不执行）

生产若采用，必须同时部署本代码与精简后的 Obsidian 阅读指南；只更新代码而仍读取旧长指南则减负不完整。
