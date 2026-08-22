# A股短周期发动机最终修复审计

**基线：** `b6a951b5f40abd29f39bbaca19a972c1d75d717f`

本修复只收紧个人助手的研究合同。它不新增数据源、数据库、定时任务、评分器、模型、服务或研究平台。

修复后，新每日轨迹使用V4七种发动机、四种状态、六种市场传播模式和高分化风险覆盖；广泛扩散与领导集群分开；公司保存披露链；价格支持增加路径质量；条件性事件收窄为收盘后首次实质新信息；事件反应增加时点、形成日行业成员和窗口回撤；知识库增加四个独立边界；D20按发动机分组。

Forward CSV、D20、事实仓、DuckDB、定时任务和11个价格场景均保持不变。最终验收以用户本地针对性测试、完整pytest和 `git diff --check` 为准。

## 硬性验收矩阵

| 验收项 | 实现位置 | 预期 |
|---|---|---|
| 七种发动机/四种状态 | `forward_selection.py`、V4合同 | PASS |
| 新形成日必须V4 | 版本分派与测试 | PASS |
| `fresh_event_pending`窄通道 | 同事件公司支持、行动条件、公告前风险 | PASS |
| 已确认价格支持最小原值和路径质量 | V4价格校验 | PASS |
| 六种市场传播和高分化覆盖 | V4轨迹、市场Skill、合同 | PASS |
| 广泛扩散与领导集群分离 | V4模型和板块Skill | PASS |
| 领导成员逐只原值 | `SectorLeaderMemberEvidenceV4` | PASS |
| 完整披露链 | `CompanyInformationV4`、公司Skill | PASS |
| 事件时点/形成日成员/窗口回撤 | `compute_event_reaction_features_v3` | PASS |
| 四个独立知识条目 | `research_registry.yaml` | PASS |
| 按七种发动机复盘 | 复盘Prompt | PASS |
| 未新增平台/数据库/任务 | 变更范围 | PASS |
