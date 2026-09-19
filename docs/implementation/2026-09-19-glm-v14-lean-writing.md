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

## 试写终态

- 飞凯材料：trial 退出码 2，article_status=failed，execution_verified=false。作者阶段 CLI 正常返回且文章已生成（provider=bigmodel-api、模型 GLM-5.3、单次请求、无 fallback、零工具调用），但 text_only 执行核验未通过：本机 CLI 当日更新后默认提供 10 个工作流工具，固定 --disallowed-tools 清单未覆盖，offered_tools 非空触发"无法确认实际请求为无工具的短上下文"。属共享隔离环境异常，非本股资料或文稿质量。最后草稿已保留，未经审稿。
- 海星股份：未启动。按执行单 S4 共用停止条件（共享隔离环境异常对两篇必然同样触发）停止全部后续真实调用。
- 已知症状初读观察（非审稿结论、非质量评分）：最后草稿中"剔除9月14日其余四个交易日合计仍上涨5.40%""最大日之后三个交易日累计上涨7.00%"等四日/五日衔接表述与"约相当于4.3个近20日平均真实波幅，只是波动尺度""低位置本身不构成上涨空间"等表述，未出现四日/五日误衔接、未把近20日累计涨幅升级为确定行情阶段判断；该草稿是否好读、是否忠实，由用户/ChatGPT阅读判断。
- 上一轮 V1.3 的 W04 审稿端缺口本轮未重测，仍为已知未通过项；因审稿阶段未运行，本轮两篇观察未取得可评估数据。

## 采用前提（本轮不执行）

生产若采用，必须同时部署本代码与精简后的 Obsidian 阅读指南；只更新代码而仍读取旧长指南则减负不完整。
