---
name: industry-research-stage-c
description: Use when ChatGPT must build evidence-bound business and scenario assumptions, Codex must calculate them reproducibly, and ChatGPT must form one of four research states plus a monitoring contract.
---

# C阶段：综合研究结论 V3.0

## 角色顺序

ChatGPT C1 → Codex C2 → ChatGPT C3。

## C1：ChatGPT综合草案与计算请求

建立订单/认证/交付或续费到收入、毛利、净利润和现金的链；建立证据绑定的保守/基准/乐观情景；列出扩产、二供、自制、替代、利润池迁移和市场隐含要求。

先读取B3的 `calculation_scope`、四种计算准备状态、`allowed_numeric_fields`、`must_remain_unknown`、`readiness_reason` 和适用的 `reopen_condition`。只有 `direct_calculable` 或具有正式可核验边界的 `range_calculable` 才能发出数值请求；`condition_only` 只写商业链、证据最低线、升级/失效条件和反证，`not_applicable` 写明当前原因与重开条件后退出对应计算。只有存在直接值或正式范围时才建立三情景，否则使用简洁条件表达，不生成三套空表。`true_zero` 只接受同一报告期、同一合并口径的正式证据，跨期文件只能支持字段含义、列报方式或会计语义。

输出：
- `07_C1_综合研究草案.docx`
- `07_C1_计算请求.yaml`
- 更新 `00_下一步操作.md`

## C2：Codex确定性计算

先原样保存C1文件；严格按批准变量、公式、数据集和as_of计算三情景、主题收入/毛利/新增净利润/现金弹性、估值位置和反向经营假设。

只计算B3列入 `allowed_numeric_fields` 的字段：`direct_calculable` 做确定性计算，`range_calculable` 只能在正式边界内计算。`condition_only` 返回条件、反证、`missing_reasons` 和触发条件，不生成三套全空数值情景；`not_applicable` 退出对应计算，不进入当前待修数据缺口。计算准备状态只约束 `calculation_scope`，不得把它解释为整家公司其他字段的授权。

PE按单项指标判断：TTM归母净利润非正、PE无经济含义时，该PE为 `not_applicable`，但PS、PB和经营事实不受影响；存在部分有效正值样本时只披露真实样本及覆盖范围，不补值，也不把单项样本不足写成公司全部估值故障。主题数值缺失继续保留未知，不得削弱C3的产品、关系、生意、业绩、质量、持续性和预期差判断。

输出：
- `08_C2_计算结果.json`
- `08_C2_计算摘要.md`
- `08_C2_数据缺口.json`
- 更新 `00_下一步操作.md`

必须commit+push。不得增加总分、推荐阈值或修改产业假设。

## C3：ChatGPT最终结论

依次检查产品匹配、关系证据、生意成立、业绩重要、质量、持续性和预期差；硬门失败不得由其他高分补救。

输出：
- `09_C_综合研究结论.docx`
- `09_C_监控合同.yaml`
- `09_C_研究状态.csv`
- 更新 `00_下一步操作.md`

状态只为 research_candidate、continue_observing、insufficient_evidence、thesis_invalidated。不得自动交易。
