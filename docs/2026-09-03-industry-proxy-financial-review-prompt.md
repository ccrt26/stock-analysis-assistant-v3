# 独立审查提示：申万行业代理与财务指标版本消歧

你是本任务唯一的实施前独立审查者。只审查，不实施，不修改文件，不启动任何子智能体。

请完整阅读：

- `AGENTS.md`
- `docs/architecture/current-v3-architecture.md`
- `docs/superpowers/specs/2026-09-03-industry-proxy-financial-indicator-resolution-design.md`
- `docs/superpowers/plans/2026-09-03-industry-proxy-financial-indicator-resolution.md`
- `.agents/skills/researching-sectors-industries/SKILL.md`
- `.agents/skills/researching-company-events/SKILL.md`
- 计划涉及的现有实现和测试

审查目标是判断该方案是否与用户要求一致、完整、可执行，是否存在矛盾、遗漏或过度工程化。重点检查：

1. 是否用独立代理事实集而非覆盖或冒充官方申万指数；是否只使用交易日 `t` 当日有效成分及 `t-1` 可得自由流通市值权重，并正确传播输入 `available_at`。
2. 代理字段、健康检查、正式研究就绪条件和旧 `industry_daily` 的处理是否语义清晰；是否避免新增任务、非官方来源、通用规则引擎或无关重构。
3. 财务指标业务键是否保持不变；是否只在重复版本时请求官方 `update_flag`；唯一 `update_flag=1` 是否按实际观测时间入库而不回填到原公告日；无法唯一判定时是否继续保留冲突。
4. 修复是否覆盖最近 250 个行业交易日、2026-08-26/09-01/09-02、全部未解决财务冲突键，以及 08-26、08-27、08-28、08-31、09-01、09-02 六个派生日期。
5. TDD、幂等、备份、缺口审计和最终验收是否足够且与风险相称，不包含过度安全设计。

只允许返回以下三种结论之一：

- `通过`
- `通过（以修订版为准）`，随后给出可直接执行的完整修订提示
- `阻塞`，随后指出主智能体无法自行消除的真实阻碍

若只是可由你在修订版中明确的小问题，不要判定阻塞。
