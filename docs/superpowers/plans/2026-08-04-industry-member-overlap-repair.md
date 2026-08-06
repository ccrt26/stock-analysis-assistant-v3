# Industry Member 有效期重叠修复实施计划

**日期：** 2026-08-04

**范围：** 只修复 `industry_member` 版本语义、健康检查、当前事实数据和 `sector_hotspot` 阻塞；不恢复旧 V3，不开发选股、评分、Gate、报告、发布系统或股票研究 SKILL。

## 已确认根因与证据边界

1. `ClassificationBackfillService._sw_catalog_and_members()` 把上游 `index_member_all.in_date` 直接映射为 `valid_from`，同时把 `available_at` 写成该业务日期收盘后。
2. `industry_member` 正式业务键包含 `valid_from`。月度刷新遇到更晚的 `in_date` 时，事实仓把它视为新业务键；当前分类程序没有关闭同一 `ts_code + industry_system + level` 槽位中的旧开放版本。
3. 2026-08-03 批次新增 258 条成分记录，其中：
   - 48 条没有旧槽位前任，业务起点分布在 2026-06-19 至 2026-07-17，不属于本次重叠修复；
   - 210 条 `valid_from=2026-07-01`，有且只有一个更早、仍开放的槽位前任，涉及 70 只股票，每只 L1/L2/L3 各一条；
   - 210 条中 13 条行业代码未变，正是 `sector_hotspot` 当前直接拒绝的 13 对；
   - 其余 197 条行业代码变化，是同一次行业调整留下的过期旧归属。
4. 210 条新记录都在 2026-08-03 21:30:19 本地接收，上游业务日期都是 2026-07-01；旧记录都在 2026-07-14 左右首次入库且仍开放。新业务日期晚于旧起点，没有倒序或多前任歧义。
5. 当前没有分类原始暂存文件；但事实行保留 `index_member_all` 来源端点，而代码中 `valid_from` 只能由上游 `in_date` 转换得到，因此 2026-07-01 是有可追踪代码路径支持的上游业务日期。
6. 现有 `ResearchWarehouse` 对同业务键实质变更会保存旧修订，修订可见区间以本次接收时间为边界；`industry_member` 已启用 `mask_future_valid_to`。因此只需在分类入口构造正确的旧版本关闭和新版本接收时间，无需全局修改其他数据集时间契约。

## 冻结修复语义

- 身份槽位：`ts_code + industry_system + level`。
- 正式版本业务键保持现状并继续包含 `valid_from`，用于保留真实退出、重入和历史版本。
- 完全相同业务键和内容的重复刷新为幂等，不改变首次已知时间。
- 同槽位出现更晚 `valid_from`：旧开放版本关闭至新起点前一天，新版本保留上游业务起点，但只能从本地接收时间可见；旧版本关闭也只能从该接收时间可见。
- 行业代码变化使用同一规则，因此旧行业归属不会继续开放。
- 已关闭后重新进入同一行业时保留两个不重叠版本。
- 新起点早于已有最新起点，或同一起点出现冲突行业内容时拒绝自动改写。
- `available_at` 不倒退；不修改 `theme_member` 或其他有效期数据集契约。

## 实施顺序

### 1. 先写失败测试

在 `tests/test_classification_backfill.py` 增加：

- 完全相同刷新幂等；
- 同行业更晚起点关闭旧版本；
- 换行业关闭旧归属；
- 新版本只从接收时间可见；
- 旧 `valid_to` 在接收前不泄露；
- 真实退出后同业重入保留两个区间；
- 倒序或同日起点冲突明确拒绝；
- 重复刷新不增加修订。

在 `tests/test_research_health.py` 增加 `industry_member` 槽位重叠检查及定位字段断言。

保留并复跑 `tests/test_hotspot_features.py` 的重叠拒绝测试；增加修复数据可计算及输出唯一测试时优先放在已有派生任务测试中。

在新的迁移测试中覆盖：备份、SHA-256、逐实体收据、修订链、历史查询、幂等、失败回滚和无 `.previous`。

先运行定向测试并记录预期失败输出。

### 2. 最小生产代码修复

在 `classification_backfill.py` 增加范围明确的行业成分版本协调函数：

- 读取当前 `industry_member`；
- 按身份槽位比较当前和本次上游结果；
- 对有可靠更晚业务起点的新版本构造旧行关闭；
- 把新版本 `available_at` 设为本次源响应完成后的 UTC 接收时间；
- 对冲突日期和多开放前任失败关闭；
- 将关闭和新行作为同一事实批次提交，让仓库修订机制保持历史。

不改业务键，不改全局时间合同，不在派生阶段去重。

### 3. 健康检查

扩展 `_effective_interval_audit()`：

- `industry_catalog` 保持现有实体区间检查；
- `industry_member` 按 `industry_system + level + ts_code` 身份槽位检查区间，能够同时发现同代码重叠和跨代码旧归属未关闭；
- 问题文本包含数据集、体系、层级、股票、两个行业代码和具体区间；
- 任一重叠令契约和核心完整性失败。

### 4. 当前数据迁移

新增专用迁移程序，迁移 ID 使用：

`2026-08-04-industry-member-effective-interval-repair-v1`

迁移只自动处理满足全部证据条件的 210 个槽位：

- 新版本本地接收时间为 2026-08-03 批次时间；
- 新 `valid_from` 明确晚于唯一旧开放前任起点；
- 旧版本关闭至 2026-06-30，并把 `is_current` 改为 false；
- 新版本 `available_at` 改为原始 `ingested_at`，不编造更早接收时间；
- 为旧业务键保存迁移前开放版本修订，使接收前 `as_of` 仍看到开放旧归属；
- 不处理 48 条无前任记录；不删除分区或重新抓取。

迁移前备份事实 Parquet，以及 `research_fact_partitions`、`research_fact_keys`、相关 `research_fact_revisions`、分类水位、必要任务元数据和迁移元数据。备份清单、源清单哈希、逐槽位依据、迁移前后区间、行数和文件哈希写入收据。重复执行只验证收据与当前状态并返回 `already_applied`。

### 5. 验证

依序执行：

1. 新增定向测试红转绿；
2. 相关测试文件；
3. `.venv/bin/python -m pytest -q`；
4. 只读 DuckDB 和真实 `ResearchQuery` 检查业务键、槽位区间、倒置、修订可见性、文件哈希、行业目录及公告回归；
5. `.venv/bin/python -m stock_analyzer data derive --data-date 2026-08-03`；
6. `.venv/bin/python -m stock_analyzer data health --data-date 2026-08-03 --latest-only`；
7. 网络和凭据允许时，晚间、次晨任务各运行两次；外部阻塞如实记录；
8. 检查 `.previous`、Git diff、旧 V3 关键词和用户目录状态。

不提交、不推送。
