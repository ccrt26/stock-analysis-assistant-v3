---
name: industry-research-stage-c
description: Use when ChatGPT must build evidence-bound business and scenario assumptions, Codex must calculate them reproducibly, and ChatGPT must form one of four research states plus a monitoring contract.
---

# C阶段：综合研究结论 V3.0

## 角色顺序

ChatGPT C1 → Codex C2 → ChatGPT C3。

## C1：ChatGPT综合草案与计算请求

建立订单/认证/交付或续费到收入、毛利、净利润和现金的链；建立证据绑定的保守/基准/乐观情景；列出扩产、二供、自制、替代、利润池迁移和市场隐含要求。

输出：
- `07_C1_综合研究草案.docx`
- `07_C1_计算请求.yaml`
- 更新 `00_下一步操作.md`

## C2：Codex确定性计算

先原样保存C1文件；严格按批准变量、公式、数据集和as_of计算三情景、主题收入/毛利/新增净利润/现金弹性、估值位置和反向经营假设。

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
