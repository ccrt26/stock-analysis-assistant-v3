---
name: industry-research-stage-d
description: Use when an approved monitoring contract must be installed, checked on daily/weekly/monthly/quarterly clocks, and escalated through a Codex-ChatGPT-Codex trigger loop only when material conditions change.
---

# D阶段：持续跟踪

## 必须先读

根 `AGENTS.md`、逐步执行手册、全局规范、当前运行控制文件、C最终结论/监控合同/研究状态和最新状态账。

## 第11步：Codex合同安装与基线

校验指标、来源、频率、阈值语义、review_due与触发路由；记录初始值、as_of、输入清单和质量；unsupported项保留人工/ChatGPT安排；不得修改合同。

输出：

- `10_D_监控基线.json`
- `10_D_安装摘要.md`
- 初始化 `11_D_状态账.csv`

## 第12步：Codex例行守候

- 日/交易日：行情、估值、公告元数据和价格条件；
- 每周：公告、接近条件和数据问题；
- 每月：状态、估值位置、证据到期和缺口；
- 每季度：财报、主营、订单转收入、毛利、现金、应收、存货、资本开支和情景重算。

无重大变化只更新状态；每月输出 `11_D_月度摘要.md`。触发时输出 `12_D_重大触发包.yaml` 与 `12_D_重大触发摘要.md`，冻结自动状态改变，并把下一步指向第13步/ChatGPT。

## 第13步：重大触发闭环

ChatGPT读取触发包，可判断 no_change、update_monitoring、upgrade、downgrade、invalidate、return_to_A、return_to_B、return_to_C；不得修改Codex原始值。

输出 `13_D_ChatGPT复核结论.md` 和必要的新合同草案。用户批准后，Codex生成新版本、更新状态账/review_due并输出 `14_D_状态变更记录.md`；旧合同只读。

必须交回ChatGPT：技术路线/接口/客户架构变化；首次客户/批量订单/第二客户/客户否认；订单不转收入、续费复制失败、验收回款异常；毛利/现金/存货/应收/扩产异常；二供、新进入者、客户自制、价格交期转弱；估值隐含假设明显变化；证据到期或数据源失效。
