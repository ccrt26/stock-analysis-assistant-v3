# 申万行业代理与财务指标版本消歧 Implementation Plan

> **Required sub-skill:** Use `superpowers:executing-plans` to execute this plan after the one required independent pre-implementation review has passed.

**Goal:** 用现有本地官方来源事实生成可回放的申万一级行业代理收益，并用 Tushare 官方 `update_flag` 消除可确定的财务指标版本歧义，补齐截至 2026-09-02 的相关缺口。

**Architecture:** 新增独立的 `industry_daily_proxy` 事实集，使用前一交易日自由流通市值加权计算，不覆盖旧 `industry_daily`，并通过显式代理字段进入行业热点和研究健康检查。财务指标保持现有业务键，只在检测到同公告日重复版本时追加请求 `update_flag`，唯一修订版按实际观测时间入库；其余冲突继续保留。

**Constraints:** 不新增定时任务，不恢复旧评分体系，不引入非官方数据源，不购买或绕过 `sw_daily` 权限，不伪装官方指数，不降低时点安全标准，不顺手重构无关代码。工作区已有用户改动，本次不创建提交，只修改计划列明的文件并保留其他改动。

---

### Task 1: 建立行业代理合同和纯计算函数

**Files:**
- Create: `src/stock_analyzer/analysis/industry_proxy.py`
- Modify: `src/stock_analyzer/data/research_contracts.py`
- Test: `tests/test_industry_proxy.py`
- Test: `tests/test_research_contracts.py`

**Steps:**
1. 先写失败测试，覆盖前一交易日权重、当日有效成分、80% 覆盖门槛、输入 `available_at` 上界、零/缺失权重以及不产生官方点位。
2. 运行定向测试，确认因缺少合同和实现而失败。
3. 新增 `industry_daily_proxy` 合同和最小纯函数实现，来源为 `local_derived`，公式版本固定。
4. 运行定向测试，确认通过。

执行期核验补充：申万“综合”行业残留已退市成分，需要用现有证券主表的上市/退市生命周期过滤覆盖率分母。保留仍上市但无行情的成分；证券主表和被排除成分的可用时间也约束代理 `available_at`，避免历史倒灌。已用失败用例验证后实施，不新增数据源或调整覆盖率门槛。

### Task 2: 接入现有分类回填与缺口登记

**Files:**
- Modify: `src/stock_analyzer/data/classification_backfill.py`
- Modify: `src/stock_analyzer/ops/research_data_job.py`
- Modify: `src/stock_analyzer/storage/research_gap_registry.py`
- Test: `tests/test_classification_backfill.py`
- Test: `tests/test_research_data_job.py`
- Test: `tests/test_research_gap_registry.py`

**Steps:**
1. 先写失败测试，覆盖晚间任务在个股收盘事实之后生成行业代理、重跑幂等、覆盖不足登记缺口，以及代理成功后以替代能力关闭旧行业日线缺口。
2. 运行定向测试并确认预期失败。
3. 让现有行业回填入口生成代理事实；保留 `sw_daily` 获取函数作为显式官方能力，但不再作为当前无权限环境的活跃依赖。
4. 增加一个仅针对本次替代关系的缺口关闭方法，记录替代事实集和方法，不泛化成规则引擎。
5. 将现有晚间和次日补偿流程切到代理事实集，不新增调度。
6. 运行定向测试并确认通过。

### Task 3: 接入行业热点、研究健康检查和研究读取

**Files:**
- Modify: `src/stock_analyzer/analysis/hotspot_features.py`
- Modify: `src/stock_analyzer/ops/research_features.py`
- Modify: `src/stock_analyzer/ops/research_health.py`
- Modify: `src/stock_analyzer/ops/forward_selection.py`
- Modify: `.agents/skills/researching-sectors-industries/SKILL.md`
- Test: `tests/test_hotspot_features.py`
- Test: `tests/test_research_feature_job.py`
- Test: `tests/test_research_health.py`
- Test: `tests/test_forward_selection.py`

**Steps:**
1. 先写失败测试，证明代理收益只进入 `proxy_*` 字段，绝不进入 `official_index_*`；并覆盖形成日时点过滤、健康检查最近 250 个交易日、行业研究就绪条件及缺失时的明确降级。
2. 运行定向测试并确认预期失败。
3. 行业热点公式升级为新版本，新增代理收益、相对收益、状态和方法字段；真正的官方主题/指数数据仍使用官方字段。
4. 研究特征加载、健康检查和正式选择就绪条件改用 `industry_daily_proxy`。
5. 更新板块研究 Skill 的事实来源说明和未知处理，不改变其研究职责。
6. 运行定向测试并确认通过。

### Task 4: 用官方 `update_flag` 解决财务指标版本歧义

**Files:**
- Modify: `src/stock_analyzer/data/fundamental_backfill.py`
- Test: `tests/test_fundamental_backfill.py`

**Steps:**
1. 先写失败测试，覆盖：无重复不追加调用；重复时追加请求 `update_flag`；恰好一个 `update_flag=1` 时选择修订版并使用观测时间；无唯一修订版时继续登记冲突；`update_flag` 不进入业务哈希和存储。
2. 运行定向测试并确认预期失败。
3. 在现有获取和时间线归一化流程中加入最小的条件式二次请求与选择逻辑，保持业务键不变。
4. 让定向修复覆盖全部未解决冲突键，包括已有当前事实但仍被冲突阻断的键。
5. 运行定向测试并确认通过。

### Task 5: 执行数据修复、派生重算和全量验收

**Files:**
- Modify: `tools/repair_research_data_gaps.py`
- Modify: `tools/audit_research_gap_closure.py`
- Modify: `README.md`
- Modify: `docs/architecture/current-v3-architecture.md`
- Test: `tests/test_research_data_repair.py`
- Test: `tools/audit_research_gap_closure.py`

**Steps:**
1. 先补失败测试，固定修复目标为最近 250 个交易日、全部未解决财务冲突键和六个派生重算日。
2. 运行定向测试并确认预期失败。
3. 最小修改现有修复与审计工具；沿用其备份、幂等和审计输出，不新建第二套工具链。
4. 更新当前架构和数据源文档，明确官方 `sw_daily` 与本地代理的区别、代理公式和财务修订处理。
5. 运行全部相关测试。
6. 执行修复：先备份，再生成代理、重试财务冲突、重算六个派生日期。
7. 执行截至 2026-09-02 的健康检查和缺口审计，核对关闭数量、剩余数量及原因。
8. 运行完整测试套件或仓库约定的最终验证命令；检查 `git diff --check` 和实际改动范围。

## 最终交付

汇报实际完成内容、测试与审计证据、申万代理覆盖和误差边界、财务冲突关闭/剩余数量、仍需用户处理的真实事项。不得把未解决冲突描述为已补齐，也不得把代理称为官方申万行情。
