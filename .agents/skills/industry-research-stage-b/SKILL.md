---
name: industry-research-stage-b
description: Use when ChatGPT must define a business-specific local verification contract, Codex must execute point-in-time entity/financial/disclosure/valuation/price checks, and ChatGPT must decide which local facts are valid for synthesis.
---

# B阶段：本地定量核查 V3.0

## 角色顺序

ChatGPT B1 → Codex B2 → ChatGPT B3。Codex不得自行决定查什么业务指标，也不得改写产业命题。

## B1：ChatGPT定义合同

按精确节点、实体和业务模式定义数据集、字段、as_of、公式、替代口径、反证、三情景变量和禁止推断。对关联关系、重复生意、主题业绩与现金、持续性和估值等关键问题，逐项写明 `best_evidence`、`minimum_usable_evidence`、`substitution_allowed`、`missing_consequence`；最低证据拿不到时必须按预先约定降级或保留未知，不得临时补替代口径。

输出：
- `04_B1_本地核查合同.yaml`
- `04_B1_口径说明.md`
- 更新 `00_下一步操作.md`

## B2：Codex本地核查

先原样保存A最终包和B1合同；唯一映射实体；只使用 `available_at <= as_of`；提取财务、主营、公告链、估值、价格和反证；保存输入清单和质量状态。

营运资金必须分两层：先分别输出应收账款、存货、合同负债、经营活动现金流、销售回款等基础风险项；只有适用字段齐全、报告期相同且合并口径相同时，才计算含合同资产、预收款项等可选项的综合营运资金强度。字段不全时综合项写 `partial` 并列出 `missing_fields`，但不得丢弃已取得的基础项。预收款项只有正式报表另行列示且确认未与合同负债重复时才能纳入；不得因为存在合同负债就自动把预收款项写成不适用。

`true_zero` 只允许由同一报告期、同一合并口径的正式证据确认。本地 `null`、未单列或跨期正式文件都不能证明本期为零；跨期文件只能支持字段含义、列报方式或会计语义。

输出：
- `05_B2_本地核查.json`
- `05_B2_本地核查摘要.md`
- `05_B2_数据缺口.json`
- 更新 `00_下一步操作.md`

必须commit+push。不得给研究候选或买入结论。

## B3：ChatGPT语义验收

检查实体、时间、主营和指标是否对应精确产业节点；区分缺失、零、无记录和查询失败；决定哪些事实进入C。不得修改Codex原始值。

每个计算作用域只能标为 `direct_calculable`、`range_calculable`、`condition_only`、`not_applicable` 之一，并同时给出 `calculation_scope`、`allowed_numeric_fields`、`must_remain_unknown`、`readiness_reason`，适用时再给出 `reopen_condition`。这些状态只约束所列计算作用域，不是公司级授权；未列入 `allowed_numeric_fields` 的字段不得计算，允许计算的字段与必须未知的字段可以并存。例如主题收入和毛利可算时，主题净利润与现金仍可保持未知；单项PE不适用不影响PS、PB或经营事实。

`direct_calculable` 只接受同一报告期、同一合并口径、同一业务场景的直接正式披露；`range_calculable` 只接受正式合同、正式上下界或可核验限制，不能用规划、产能、行业数据、媒体报道或历史经验凑区间。`condition_only` 只进入商业链、证据最低线、升级/失效条件和反证，不向C2发出数值情景请求。`not_applicable` 必须写明当前原因和 `reopen_condition`，仍按 `review_due` 复核，不登记为当前待修数据缺口。

主题拆分缺失可以进入观察，但阻断对应主题数值结论；是否升级为 `research_candidate` 仍由C3决定。行业相对收益和固定长窗口估值属于可选比较项，缺失不得阻断主流程。

输出：
- `06_B_验收报告.md`
- `06_B_交给C阶段.yaml`
- 更新 `00_下一步操作.md`

状态只为 accepted、accepted_with_gaps、return_to_B、blocked。最多一次有限纠正。
