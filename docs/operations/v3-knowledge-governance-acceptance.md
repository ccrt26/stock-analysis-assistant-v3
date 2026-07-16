# V3 知识治理重构内部验收记录

> 验收日期：2026-07-15
> 验收范围：知识登记、来源分级、数据能力准入、场景选择、使用审计、旧知识迁移和生产隔离
> 不在范围：市场环境算法、评分、排名、推荐、仓位、正式报告、激活、部署和自动交易

## 1. 批准依据与提交

- 批准设计：[V3 知识治理重构设计](../superpowers/specs/2026-07-15-v3-knowledge-governance-refresh-design.md)
- 执行计划：[V3 知识治理重构实施计划](../superpowers/plans/2026-07-15-v3-knowledge-governance-refresh.md)
- 批准基线：`e5e73566e1f166deaacdbdf69e76347623c09248`
- 最终实现提交：`2d1669f7d45f1358b7bf73cca7f14097935f20a0`
- 本文档是实现提交后的独立验收证据；包含本文档的提交号以 Git 历史和最终交接记录为准，避免在同一提交内容中形成不可实现的自引用哈希。

## 2. 验收结论

本阶段实现了一个独立、只读、可审计的知识治理层。它能够：

- 按 S/A/B 规则校验来源和版本元数据；
- 在知识准入前核对现有研究仓库的数据表、字段、时点和结构质量；
- 按分析日期、模块、机会类型、主题和未来十至三十个交易日场景选择少量适用知识；
- 将 API 原始事实、本地复算观察、模型判断和用户表达分开记录；
- 禁止在缺少逐笔、订单簿和账户身份数据时把价量结果翻译为机构或主力行为；
- 对旧版七十四项知识逐项保留迁移去向，同时不再把旧版静态 `data_exists` 当作权威。

知识治理层尚未接入推荐、报告、自动任务或生产运行。

## 3. 定向与全量测试证据

### 3.1 定向验证

- 时间：2026-07-15 13:03:06–13:03:10 CST
- 命令范围：模型、注册表、能力核对、选择器、使用审计、迁移、验收场景、旧规则保护和研究仓库时点测试
- 结果：`90 passed in 3.81s`
- 结论：本轮治理功能及其旧功能保护测试无失败。

### 3.2 全量验证

- 时间：2026-07-15 13:01:28–13:02:38 CST
- 结果：`1 failed, 897 passed, 1 skipped in 70.03s`
- 唯一失败：`tests/test_config_health.py::test_historical_specs_and_plans_disclaim_current_status_authority`
- 失败对象：`docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`
- 基线核对：测试及该缺失声明在批准基线 `e5e7356` 已同时存在，因此该失败早于本实施；该共同设计草案不在本实施计划允许修改的文件清单内，本轮未越权修改。
- 本轮新增或修改的知识治理代码、登记文件和测试没有产生其他全量测试失败。

## 4. 真实仓库治理审计

- 审计分析日：`2026-07-14`
- 执行时间：2026-07-15 13:03:16–13:03:29 CST
- 审计输出：`/private/tmp/v3-knowledge-governance-audit.json`
- 审计结果：`passed: true`
- 注册表哈希：`09feb432e4a72fb6e21ddd29d9c2daf9824cd082fe44abaae4fa81e6fcaccb43`
- 能力快照哈希：`540c43bbca724d66b5d3c56a2c5f7770bd7e1d44fac51c433c4a065d57e4b0ac`
- 审计哈希：`e3e8480e62530d53222be1eac9ddd6db140f36bb634b335037ed73b5c2c03133`
- 来源数：20
- 激活知识条目数：16
- 受阻激活条目数：0
- 旧知识数：74
- 未映射旧知识数：0
- 审计错误：0

## 5. 来源与迁移审计

### 5.1 来源等级

| 对象 | S 级 | A 级 | B 级 | 合计 |
|---|---:|---:|---:|---:|
| 登记来源 | 11 | 9 | 0 | 20 |
| 当前激活知识 | 7 | 9 | 0 | 16 |

所有 20 个激活来源均通过作者或发布者、原始定位、日期、市场、样本、方法和限制元数据检查，来源复核覆盖率为 100%。2026-07-15 的最终复查逐一重新访问了全部原始定位；北交所和部分 Wiley 页面当次返回站点错误，JSTOR 页面未返回正文，因此只确认已保存并先前核验的元数据，不伪造本次正文复核。无法验证关键样本信息的 SSRN 工作论文未准入，业绩公告方法由可核验的 Sun 与 Wen 同行评审论文替代。

最终复查修正了一处来源英文标题，使其与中央财经大学期刊页面一致；没有发现需要改变已登记允许用途、禁止用途或数据要求的内容。

### 5.2 七十四项旧知识处置

| 动作 | 数量 | 运行时状态 |
|---|---:|---|
| 保留 `retain` | 3 | 指向已准入知识 |
| 更新 `update` | 5 | 指向已准入知识 |
| 重新验证 `revalidate` | 13 | 仅作方法，阈值未启用 |
| 暂缓 `defer` | 37 | 不可调用 |
| 退出 `retire` | 16 | 不可调用 |

全部旧编号恰好出现一次。暂缓和退出项没有活动目标，也没有把“增加新数据源”写成默认后续动作。

## 6. 需求追溯

| 要求 | 验收证据 |
|---|---|
| R1 数据能力先于知识搜索 | `test_active_registry_has_no_blocked_entry`、真实仓库审计 |
| R2 核心数据结构性缺失不得激活 | `test_globally_missing_core_dataset_is_blocked_not_limited`、不可用周期场景 |
| R3 严格执行 S/A/B | `test_s_official_rule_requires_effective_date_and_official_host`、`test_b_source_cannot_create_hard_boundary` |
| R4 官方规则版本和有效期明确 | `test_current_rule_versions_cannot_overlap`、日期选择测试 |
| R5 只选择当前场景相关知识 | `test_selector_filters_by_module_opportunity_topic_and_10_30_session_horizon`、六个固定验收场景 |
| R6 不机械遍历七十四项 | `test_selector_excludes_blocked_knowledge_instead_of_returning_all_entries` |
| R7 四种执行状态含义独立 | `tests/test_knowledge_use_audit.py` 的四类状态测试 |
| R8 冲突与执行状态分离 | `test_conflict_can_coexist_with_correct_execution` |
| R9 四层事实与表达分离 | `test_all_four_trace_layers_are_separate_required_fields`、业绩事件验收场景 |
| R10 禁止由价量推断主体身份 | `test_daily_or_minute_facts_cannot_claim_trader_identity`、程序化交易验收场景 |
| R11 热点特征只是证据 | `test_sector_hotspot_remains_evidence_not_ranking` |
| R12 七十四项均有去向 | `test_migration_ids_equal_all_legacy_ids_exactly_once` |
| R13 不建设爬虫或连续数据扩展 | `test_governance_package_has_no_network_or_ingestion_dependency`、变更路径审计 |
| R14 不改变数据底座 | `test_inspection_does_not_change_duckdb_sha256`、仓库校验值复核 |
| R15 不接入评分、报告或生产 | `test_governance_is_not_imported_by_production_paths`、架构差异审计 |
| R16 来源由 Codex 阅读核对 | `test_every_active_source_has_complete_review_metadata`、最终二十项来源复查 |
| R17 经验阈值先做本地时点验证 | `test_empirical_threshold_requires_completed_local_validation`、九项 A 级方法均为 `method_only` |

## 7. 数据底座不可变证据

- 研究仓库：`local_warehouse/research.duckdb`
- 实施前后 SHA-256：`b988c0bee9c99356eca602d3d6ec33c875ab471a3c3e4051e440f91d5c685747`
- `shasum -a 256 -c /private/tmp/v3-knowledge-governance-warehouse.before.sha256`：`OK`
- 数据、存储、分析、报告、运维、CLI、流水线、Supabase、函数和仓库目录无本轮差异。

## 8. 已知限制

- 九项经验研究目前全部是方法知识，不含买入阈值、预测权重、固定持有期或历史收益承诺。
- 当前 `sector-hotspot-v3` 只提供可复算热点证据，不是最终热点排名；股票收益输入采用 `close * adj_factor`。
- 当前底座没有完整产品价格、行业库存、产能利用率、行业销量、订单簿和账户身份能力，因此相关周期和交易主体知识不激活。
- 公告库不等于完整新闻库；新闻与无新闻反应方法只能在正式公告覆盖范围内有限解释。
- 部分外部原始页面可能临时不可访问；离线登记可复现已审核元数据，但下一次版本复核不得假装网页已成功打开。
- 全量测试仍有一项批准基线已经存在的、范围外的文档健康失败，详见第 3.2 节。

## 9. 下一道门

下一步必须先由用户验收本知识治理结果。用户确认前，不开始市场环境逻辑、评分、报告样式、推荐集成、激活或部署。
