---
name: industry-research-stage-b
description: Use when ChatGPT must define a business-specific local verification contract, Codex must execute point-in-time entity/financial/disclosure/valuation/price checks, and ChatGPT must decide which local facts are valid for synthesis.
---

# B阶段：本地定量核查 V3.0

## 角色顺序

ChatGPT B1 → Codex B2 → ChatGPT B3。Codex不得自行决定查什么业务指标，也不得改写产业命题。

## B1：ChatGPT定义合同

按精确节点、实体和业务模式定义数据集、字段、as_of、公式、替代口径、反证、三情景变量和禁止推断。

输出：
- `04_B1_本地核查合同.yaml`
- `04_B1_口径说明.md`
- 更新 `00_下一步操作.md`

## B2：Codex本地核查

先原样保存A最终包和B1合同；唯一映射实体；只使用 `available_at <= as_of`；提取财务、主营、公告链、估值、价格和反证；保存输入清单和质量状态。

输出：
- `05_B2_本地核查.json`
- `05_B2_本地核查摘要.md`
- `05_B2_数据缺口.json`
- 更新 `00_下一步操作.md`

必须commit+push。不得给研究候选或买入结论。

## B3：ChatGPT语义验收

检查实体、时间、主营和指标是否对应精确产业节点；区分缺失、零、无记录和查询失败；决定哪些事实进入C。不得修改Codex原始值。

输出：
- `06_B_验收报告.md`
- `06_B_交给C阶段.yaml`
- 更新 `00_下一步操作.md`

状态只为 accepted、accepted_with_gaps、return_to_B、blocked。最多一次有限纠正。
