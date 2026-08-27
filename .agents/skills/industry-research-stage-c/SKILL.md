---
name: industry-research-stage-c
description: Use when approved industry evidence and local facts must be combined through business realization, earnings/cash scenarios, sustainability and expectation-gap analysis into one of four research states and an executable monitoring contract.
---

# C阶段：综合研究结论

## 必须先读

根 `AGENTS.md`、逐步执行手册、全局规范、当前运行控制文件、A最终包、B事实/验收包和全部未解决冲突。

## 第8步：ChatGPT综合草案与计算请求

按业务模式建立订单—交付/续费—收入—毛利—净利润—现金链；建立保守/基准/乐观情景；每个假设绑定证据与时间；列出扩产、二供、客户自制、技术替代、利润池迁移和价格隐含问题。

输出：

- `07_C_综合草案.md`
- `07_C_计算请求.yaml`

不得先得出高利润结论再倒推数字。下一步指向第9步/Codex。

## 第9步：Codex可复算计算

严格按已批准变量计算三情景、主题收入/毛利/新增净利润/现金弹性、估值历史位置和反向经营假设；无法计算写未知；不得添加总分或推荐阈值。

输出：

- `08_C_计算结果.json`
- `08_C_计算摘要.md`
- `08_C_数据缺口.json`

下一步指向第10步/ChatGPT。

## 第10步：ChatGPT最终综合结论

依次检查产品匹配、关系证据、生意成立、业绩重要、质量、持续性和预期差七道硬门；写最强证据、最强反证和关键未知。

需要补算时最多输出一次 `09_C_定向补算请求.yaml`。

通过时输出：

- `09_C_综合研究结论.docx`
- `09_C_监控合同.yaml`
- `09_C_研究状态.csv`

研究状态只为 research_candidate、continue_observing、insufficient_evidence、thesis_invalidated。不得自动交易。用户同意监控后下一步指向第11步/Codex。
