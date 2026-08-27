---
name: industry-research-stage-d
description: Use when Codex must install and maintain an approved monitoring contract, and material triggers must be interpreted by ChatGPT before Codex records a new version.
---

# D阶段：持续跟踪 V3.0

## 角色顺序

Codex D1/D2 → 重大触发交 ChatGPT D3 → 用户批准 → Codex留痕。

## D1：Codex安装基线

先原样保存C3文件；校验指标、来源、频率、阈值语义、review_due和触发路由；记录初始值、as_of、输入清单和质量；unsupported项保留人工/ChatGPT安排。

输出：
- `10_D_监控基线.json`
- `10_D_安装摘要.md`
- 初始化 `11_D_状态账.csv`

必须commit+push，不修改合同。

## D2：Codex例行守候

交易日更新行情/估值/公告元数据；每周汇总变化；每月检查状态、证据到期和缺口；每季度更新财务、主营和情景。无重大变化只更新状态并输出月度摘要。

触发时输出：
- `12_D_重大触发包.yaml`
- `12_D_重大触发摘要.md`

冻结自动状态改变并交回ChatGPT。

## D3：ChatGPT解释，Codex留痕

ChatGPT只可给出 no_change、update_monitoring、upgrade、downgrade、invalidate、return_to_A、return_to_B、return_to_C；不得修改Codex原始值。用户批准后Codex生成新版本、更新状态账和review_due，旧版本只读。
