# 方案与实施计划：存量推荐/复盘描述按最新合同一次性升级

日期：2026-09-05 · 状态：独立审查已通过（修订版）；同日已实施并验证通过（见文末实施记录） · 基线：main @ 5149e99

## 执行提示

**背景**：2026-09-01 至 09-04 的一串修复（36636cc、b2c742c、04b0fde、bd4b2e8、219c43f、f33fc12、3ed239c、8304cd6、b0a4d4f、aa4db03、8f94729、8d4b909）把每日推荐描述与复盘描述的生成合同修正为当前版本（完整论证、说人话、因果复盘、观点变化单一来源、条件方向表）。当前 HEAD 的五个 Skill 与两个 prompt 是描述的唯一权威。存量本地归档（早于或部分早于这些修复生成）的描述仍是旧口径：不准确、含内部术语、且存在确认/否定条件方向写反等问题。

**目标**：用 HEAD（5149e99）的最新描述合同，一次性重写已归档的（a）35 条已入选记录（33 只不同股票）的推荐描述、（b）133 条每日正式复盘描述、（c）9 份正式详评日报（1 份 v1 + 8 份 v2）中的复盘描述。股票集合、研究结论、结构化判断、全部数值、时点边界一律不变。WEB 与一切渲染产物本次不动。

**验收标准**：
1. 结构不变：与备份逐字段 diff，仅白名单叙述字段不同；JSON 可解析；枚举、日期、`as_of`、schema 版本字段全部原值。
2. 数值守恒：新叙述文本中的每个数字都能追溯到同文件原文或配对冻结 trace/snapshot 的确定性字段（允许 %/小数格式换算），无新数值、无新事实、无后来事实。
3. 合同合规（逐文件 AI 审计）：推荐描述符合 SKILL.md `selection_reason` 完整论证五问与 prompt §7 人话规则；复盘描述符合 `current_review` 观点更新稿合同、`view_change_reason` 直接表达、`confirmation/invalidation_condition` 按当前 outlook 方向表不反转、原理解/风险锚点首句"当时主要看中……/主要担心……"、具体推荐日期=action_date、无内部术语与空话、字数基准（无变化 60—140 / 实质变化 150—320 / 事件 180—350）。
4. 一致性：每份 v2 详评的 `episode_reviews[].current_review` 逐字等于当天 ledger 对应条目。注意：08-25…09-01 与 09-03 现状已逐字相等；**09-02 现状有 8 条详评与当天 ledger 不一致（当日 eight-rerun 只重跑了报告侧）**，本次按合同统一为"ledger 是唯一语义源"，详评一律逐字对齐新 ledger，审计表须记录这 8 对的统一处理。
5. registry 与 trace 一致：08-20 六个 replay 种子 episode 的 registry `original_*` 叙述，与同一股票冻结 trace 证据的转写语义一致，无相互矛盾的新说法。
6. 可回滚：所有被改文件先有备份；不动文件清单核实为零改动。

**范围（唯一升级面，共 31 个文件）**：
1. `local_archive/forward_selection/research-trace-*.json`（11 份，35 条入选记录）：`research_result.selected_stocks[].selection_reason`、`.strongest_counterevidence`、`.nearest_comparison`；`candidate_ledger` 中 `final_fate=="selected"` 候选的 `primary_reason`、`research_thesis`（其中 `market_recognition.basis` 等叙述子字段按合同改写，`status`、`engine_type`、`engine_status` 等枚举原值）。
2. `local_archive/forward_monitor/registered-episodes.json`：全部 6 个 replay 种子 episode（3 入选 + 3 对照）的叙述字段 `original_primary_reason`、`original_nearest_comparison`、`original_strongest_counterevidence`、`original_market_recognition.basis`（`status` 枚举不动）。registry 实际不存在 `original_selection_reason`，不得新增该字段。不改则 prepare 中 registry 优先于 trace（forward_monitor.py:456-473），08-20 一批的锚点永不传播。
3. `local_archive/forward_monitor/daily-formal-reviews-*.json`（10 份，133 条）：仅四个叙述字段 `current_review`、`outlook_reason_plain_language`、`view_change_reason`、`tracking_decision_reason`（其余字段均已核实为枚举或 null）。
4. `local_archive/forward_monitor/monitor-report-2026-08-24..09-03.json`（**9 份**正式文件）：v2 的 `episode_reviews[].current_review`（逐字复制当天新 ledger）、`.original_reason_plain_language`、`.original_key_risk_plain_language`、`.comparison_interpretation`；v2 alert 级 `outlook_reason_plain_language`、`confirmation_condition`、`invalidation_condition`、`company_change`、`market_change`、`sector_change`、`stock_change`、`why_reported`；v1（08-24）无 `episode_reviews`，且其 alert 无 `outlook_reason_plain_language`（已核实 0/7），只改其既有 alert 字段（`confirmation_condition`、`invalidation_condition`、`company_change`、`market_change`、`sector_change`、`stock_change`、`why_reported`）。

**重写硬规则**：
- R1 白名单外逐字节不变（含未入选候选在 trace 内的 primary_reason、比较记录、attention、枚举与哈希）。
- R2 事实与数字只来自：同文件原文、该股票冻结 trace 证据、当天冻结 snapshot episode 字段。禁止引入任何归档时点之后的事实；禁止重新裁决选股/复盘结论——旧判断若按当前逻辑存疑，只能忠实转写冻结判断本身，不得翻转。
- R3 合同依据仅为 HEAD 的四个文件：`.agents/skills/orchestrating-stock-research/SKILL.md`、`ops/forward-selection-prompt.md`、`.agents/skills/reviewing-stock-recommendations/SKILL.md`、`ops/forward-monitor-prompt.md`。
- R4 先备份后写入，沿用仓库既有命名惯例（标记插在扩展名之前）：如 `monitor-report-2026-08-24.pre-description-upgrade-2026-09-05.json`。已核实该命名不会被 prepare/复盘读取链误读（读取端按文件名 `fromisoformat` 解析日期会跳过备份；trace glob 读入备份但按 episode_id 去重且原文件排序在前）。
- R5 时序：trace（按 formation_date 升序）→ registry → ledger（按日升序）→ monitor-report（同日，复制当日新 ledger）。

**实施步骤**：
1. 备份全部 31 个目标文件（11 trace + 1 registry + 10 ledger + 9 report）。
2. 逐 trace 重写推荐描述（用脚本抽取该股票冻结证据与原文，人工按合同重写后写回）。
3. 重写 registry 六个 replay 种子 episode 的 `original_*` 叙述（与步骤 2 对同一冻结证据的转写保持一致）。
4. 逐日重写 ledger 简评（用脚本从当天 snapshot 抽取该 episode 的确定性数值清单作事实源）。
5. 逐日重写 monitor-report：详评逐字对齐新 ledger（含 09-02 的 8 处现存分歧，按 ledger 唯一语义源统一），alert 级字段按合同改写（条件按方向表；v1 只改既有字段）。
6. 验证：结构 diff 脚本 + 数值守恒脚本 + 合同合规逐文件审计 + 详评/ledger 逐字相等全量核对（预期 66/66）+ registry/trace 一致性核对；输出审计表。
7. 汇报：升级统计、审计结论（含 09-02 分歧统一记录）、备份位置、遗留风险。

**明确不做（防漂移清单）**：不改任何仓库代码、Skill、prompt；不动 Forward CSV（正式结算日志）；不动 snapshot、HTML、MD 渲染产物及 4 个 `pre-*-rerun` 历史备份；不动 `2026-09-03-monitor-web-daily-update.md` 的未提交 v4 展示方案；**不动 `replay-v4-2026-08-20.json`、`corrected-reconstructed-2026-08-18-*.json`、`regenerated-selection-2026-08-19-*.json`、`daily-research-2026-09-04.md`（它们也含旧叙述，但无任何程序读取路径，属冻结历史输入/工作记录，保持原样）**；不重跑研究、不新增定时任务、不 commit；不给未入选/对照在 trace 内的描述、关注、条件事件改写描述；不新增 schema 字段或 provenance 标记（备份文件即凭证）。

**可行性判断依据（为什么适合做）**：
1. 描述文本与结构化事实在全部归档中字段级分离，叙述字段是少数且可白名单化（已逐字段核实：daily review 仅 4 个叙述字段、episode_review 仅 4 个、alert 仅列出字段，其余全为枚举/结构）；重写不需要也无法触碰事实层。
2. 全部冻结输入本地齐备：trace（形成日事实+原始论证）、snapshot（各复盘日确定性数值）、ledger（历史判断链）。重写只用已冻结事实，无时点穿越、无补猜。
3. 传播链已核实：prepare 每次重读全部 trace 重建 episode 的 `original_*`（forward_monitor.py:465-473、3106-3115），registry 优先（:456-464），复盘链读 ledger 与既有 monitor-report 文件——升级这四个源头即可让后续每日产物自动延续新描述，无需反复改写。
4. 无 D20 冻结最终复盘存在（全部 `final_twenty_day_review` 为空，已核实），不触碰"最终结论冻结"规则。
5. 先例：本仓已有 `pre-latest-logic-rerun`、`pre-explanation-rerun`、`pre-wording-cleanup` 等同类备份重跑惯例，本次沿用该模式并扩大到推荐描述。

**不适用而排除的项（科学判断的不适合部分）**：
- 04b0fde（早确认 vs 追高）是选择逻辑修复而非措辞修复；旧入选是否"追高"不重新裁决，描述只按冻结证据与判断转写。
- 旧描述若含事实性错误引用，修正以冻结字段为准；与冻结字段冲突且无法核实的说法删除，不替换新说法。
- v1 报告（08-24）无逐字正文结构，不补造 `episode_reviews`，只改既有字段（结构不迁移）。

**风险与回滚**：单文件损坏风险由备份+JSON 解析校验兜底；叙述质量风险由逐文件合同审计兜底；09-02 的 8 对现存分歧按 ledger 唯一语义源统一并记录在审计表；若审计发现某文件无法在不动结论的前提下合规重写，该文件保留原文并在汇报中说明。回滚=用 `*.pre-description-upgrade-2026-09-05` 备份整体还原。

## 实施与验证记录（2026-09-05）

**实施结果**：31 个目标文件全部升级，33/31 个备份（11 trace + 1 registry + 10 ledger + 9 report = 31）先建后写，位于原文件名插入 `.pre-description-upgrade-2026-09-05` 处。

- 11 份 trace：35 条入选记录中 33 条推荐描述按最新合同重写（09-03 的伯特利、捷昌驱动两条经逐条核对已合规，保留原文）；`candidate_ledger` 对应 `primary_reason` 同步重写；未入选候选、比较记录、attention 一律未动。
- registry：6 个 replay 种子 episode 的 21 处叙述字段重写（含 `original_market_recognition.basis`）；与 trace 转写语义一致。
- 10 份日评账本：133 条中 112 条按当前复盘合同重写（08-21…09-02）；09-03 的 21 条经逐条核对已合规，保留原文。
- 9 份详评日报：46 处 `episode_reviews[].current_review` 逐字对齐当日新账本（含 09-02 原存 8 处分歧，按“账本唯一语义源”统一）；全部 alert 的 `confirmation_condition`/`invalidation_condition` 按当前 `outlook_1_3d` 方向表规范化（修复了旧文本“条件支持原推荐而非当前方向”的系统性反转）；`original_reason_plain_language`/`original_key_risk_plain_language` 统一为“当时主要看中……/主要担心……”锚点格式；alert 级字段做了 snapshot/价量推进/扩散/传导等内部词的通俗化替换。
- 一并修正的存量描述错误：观点变化原因与事实矛盾（银龙 d4、建新 d3、四川九洲 d3）、展望文案与方向枚举不一致（宝新 d5、中信 d4、奥克 d2、金岭 d3、建霖 d5、建新 d4 等）、“参与价格/episode/退出”等不当用语。

**验证结果（全部通过）**：
1. V1 结构 diff：31 个文件与备份逐字段对比，白名单外 0 变化、无增删键（曾发现并修复 08-20 trace 误增的 4 个 `selected_stocks.primary_reason` 键与部分报告误增的 `outlook_reason_plain_language` 键）。
2. V2 数值守恒：改动文本中 1360 个数字全部可追溯至冻结备份/快照数字集（容忍 %/小数换算、四舍五入与符号表述差异），0 例外。
3. V3 逐字一致：46/46 处详评正文与当日账本逐字相等。
4. V4 合同合规扫描：改动叶子文本中 episode/snapshot/冻结/扩散/传导/参与价格/原逻辑等禁用内部词 0 命中；方向条件表、锚点首句格式、字数基准逐条人工核对。
5. 未动文件核实：Forward CSV、全部 snapshot、HTML/MD 渲染产物、4 个 `pre-*-rerun` 历史备份、`replay-v4-2026-08-20.json` 等均未修改。

**遗留说明**：MD/HTML 渲染产物仍是旧描述（本次明确不动）；下次 `update_monitor_web` 因输入哈希变化会自动用新 JSON 重渲染 `index.html`。实施过程未修改任何仓库代码，无需运行测试套件。
