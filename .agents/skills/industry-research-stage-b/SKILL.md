---
name: industry-research-stage-b
description: Use when an approved stage-A package must be translated into a business-specific quantitative contract, point-in-time local entity/financial/disclosure/valuation/price facts, and a ChatGPT acceptance package without changing the industry thesis.
---

# B阶段：本地定量核查

## 必须先读

根 `AGENTS.md`、逐步执行手册、全局规范、当前三个运行控制文件、A阶段最终三文件。

## 角色门

只执行当前步骤；完成后更新运行状态和下一步操作；默认只允许一次定向纠正。

## 第5步：ChatGPT定量合同

按硬件、系统工程、AIDC、软件、平台、数据/安全等业务模式，逐实体定义必需字段、as_of、允许数据集、公式、替代口径、三情景变量和禁止推断。

输出：

- `04_B_定量核查合同.yaml`
- `04_B_假设与口径说明.md`

不得提前形成综合研究状态。下一步指向第6步/Codex。

## 第6步：Codex本地定量核查

必须：唯一映射实体/代码；区分 complete/partial/unsupported/query_failed/no_record/unknown；只用 available_at <= as_of；按合同提取财务、主营、公告链、估值、价格与反证；保存输入清单和版本。

输出：

- `05_B_本地核查.json`
- `05_B_本地核查摘要.md`
- `05_B_数据缺口.json`

不得改产业命题、证据等级或给出买入结论。下一步指向第7步/ChatGPT。

## 第7步：ChatGPT语义审查与验收

检查数字是否对应目标节点、正确业务模式和正确时间；缺口是否决定性；不得直接改Codex原始值。

需要纠正时最多输出一次 `06_B_定向纠正请求.yaml`，只允许修映射、查询、时间边界或已批准计算。

通过时输出：

- `06_B_验收报告.md`
- `06_B_交给C阶段.yaml`

验收状态只为 accepted、accepted_with_gaps、return_to_B、blocked。不得形成研究候选。用户批准后下一步指向第8步/ChatGPT。
