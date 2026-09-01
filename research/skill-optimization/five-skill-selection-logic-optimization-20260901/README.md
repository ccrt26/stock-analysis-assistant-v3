# A 股五个 Skill 选股逻辑优化实施报告

## 1. 唯一目标

本轮优化的是五个 Skill 的选股逻辑，不是审计规则、边界系统或交易系统。

目标是让市场、板块、公司、价格和总控五个 Skill 各自回答不同问题，再由总控按“同发动机组内比较 → 跨发动机比较 → 逐只绝对质量判断”形成 0—5 只条件化结果；不以数量、分数、代码顺序或短期结果补位。

## 2. 基线证据

- 基线提交：`e03677c6b57b0288adf3c24caffa3f31c6ddbfac`。
- 冻结样本：8 个行动日、29 条历史正式入选事件、28 只不同股票、78 条候选账、126 条决策证据；行动日为 2026-08-20 至 2026-08-31。
- 版本差异：21 条为 `daily-research-trace-v4`；其余 8 条为 V1/legacy 记录，缺少当前 V4 发动机与确认生命周期，影响矩阵统一标记 `legacy_v1_not_rewritten`，不事后重建。
- 结果窗口：行情仅到 2026-08-31。不同事件只有 D1—D8 左右的早期路径，尚不足以声称 D20 已成熟，更不能把短期涨跌反写为形成日理由。
- 原始基线目录 `selection-sample-2026-08-20-to-2026-08-31` 未覆盖；其 manifest SHA-256 在真实导出前后均为 `0715ebd4bb88ecb125de00617e789b39a673399d6ebb01c604449c88cd3ff6fe`。

详细形成日诊断见 `baseline-diagnosis.md`，逐事件修订见 `selection-impact-matrix.csv`。

## 3. 三批修改结果

### 第一批：分开正式推荐与条件事件

- 修改：`forward_selection.py` 从既有 V4 `research_thesis` 派生非持久化 `selection_output_class`；confirmed active 才进入正式列表，`fresh_event_pending + conditional + pending` 进入事件线索。旧 trace、`candidate_ledger.final_fate` 和 `research_result.selected_stocks` 均未重写。
- 选股影响：conditional 不再占 active 数量、不再补足 5 只、不再默认用行动日开盘启动收益，也不进入 D20 到期结算。以后条件满足也必须形成新的 active trace，原 conditional trace 永不原地晋升。
- 样本依据：融发核电、丽珠集团、亚康股份、中国船舶在形成日均有真实事件，但事件后完整交易日为 0，不能把公司事件质量等同于价格已经接受。
- 负责文件：`src/stock_analyzer/ops/forward_selection.py`、`forward_monitor.py`、两个 ops Prompt 和对应 selection/monitor 测试。
- 刻意未做：没有新增状态机、数据库字段、迁移、自动参与服务或持久化 output class。

### 第二批：改变五个 Skill 的实际取舍顺序

- 修改：市场只改变搜索重点和反证强度；板块先证明共同动力和成员角色；公司按披露新增性与兑现链判断事件；价格按 1/3/5 日连续性、单日贡献、有效收盘、成交推进、回落和组合余量判断；总控先同发动机比较，再跨发动机比较和绝对停止。
- 选股影响：宝新能源形成日涨幅约占 5 日涨幅 84%，按新逻辑不再因它是组内剩余较优者而补位；2026-08-26 洛阳钼业形成日涨幅大于 3 日累计，强财务锚不能覆盖价格确认单日化，修订为停止增加名单。国缆检测、奥克股份、中信银行、四川九洲等仍可 active，但优先级或承接条件发生变化。
- 样本依据：同飞股份对德尔股份、永新股份对宝新能源、洪通燃气对海油工程、盾安环境对四川九洲等近邻比较，以及四条 fresh event。
- 负责文件：五个 `.agents/skills/*/SKILL.md`、V4 合同、selection Prompt、合同测试和 29 行影响矩阵。
- 刻意未做：没有评分器、固定权重、行业配额、股票专用阈值、新发动机或新价格场景。

### 第三批：补齐继续优化所需的结果对照

- 修改：导出器增加 `candidate_outcomes.csv` 和 `conditional_event_outcomes.csv`；正式导出只保留 17 条冻结 V4 confirmed active 与 8 条旧 V1，共 25 条，不包含 4 条 conditional。工作簿汇总公式改为动态正式行边界，验证器同步检查新文件。
- 选股影响：selected、rejected、unresolved 现在有同口径的行动后价格摘要，可区分发现问题、成员比较问题和总控取舍问题；这些结果只用于反馈，不自动生成新分数或阈值。
- 样本依据：78 条候选中 selected 29、rejected 45、unresolved 4；四条 conditional 的人工条件结果为融发核电 `not_met`、丽珠集团 `unknown`、亚康股份 `not_met`、中国船舶 `not_met`。
- 负责文件：现有 exporter、workbook builder、validator、导出测试及本目录真实数据包。
- 刻意未做：没有新增数据源、数据库、依赖、第二个验证器或完整市场回测平台。

## 4. 五个 Skill 的实质变化

- 市场：把 `one_day_repair`、`broad_participation`、`sector_rotation`、`concentrated_speculation`、`weak_market`、`unknown` 映射为下一步搜索重点和市场反证；普涨仍须证明个股相对增量，未知不自动选择也不自动淘汰。
- 板块：固定“共同动力 → leader/core 角色 → 同板块近邻”；板块广度只产生研究线索，具体股票仍须由自身价量和路径成立，四川九洲与盾安环境展示了这两步不能合并。
- 公司：固定“新增性 → 阶段 → 主营联系 → 材料性 → 财务传导 → 兑现时间 → 失败条款”；公司 Skill 证明事件与业务传导，但不宣布价格接受、可靠入口或最终推荐。
- 价格：固定“1/3/5 日连续性 → 单日贡献 → 有效收盘 → 成交推进 → 回落 → 组合余量”；成交放大必须推动收盘，强反证必须造成淘汰、降级、conditional、行动条件收紧或停止。
- 总控：按发动机分组，先组内近邻，再跨组比较，最后逐只做绝对质量判断；不能因为某股是剩余候选中最好的一只而补位，允许在 0、1、2 只时停止。

## 5. active 与 conditional 的最终行为

- 已确认正式推荐：冻结 V4 中 `event_repricing_confirmed`、`sector_broad_diffusion`、`sector_leader_cluster`、`independent_demand_acceleration` 且 `active + confirmed` 的记录。例如海油工程、北矿科技、四川九洲、杭氧股份属于该执行类别；旧 V1 只按历史正式记录读取。
- 待确认事件线索：融发核电、丽珠集团、亚康股份、中国船舶只在事件线索区展示，不计入正式推荐数量。公司事件真实和重要，不等于形成日已有价格确认。
- 条件不满足：记录 `not_met`，`formal_return_started=false`，不使用行动日开盘或后续最高价倒推参与。亚康股份和中国船舶首日弱势只用于条件评价。
- 无法观察：记录 `unknown`。丽珠集团的短窗口不足以确认，既不伪造入口也不回算收益。
- 无可靠入口：正式收益、最大收益和 MAE 保持空值；候选结果文件中的行动日开盘路径仅用于所有候选同口径评价，不代表 conditional 被正式参与。
- 影响矩阵是形成日反事实评估：其中宝新能源和 2026-08-26 洛阳钼业按新逻辑修订为 rejected，但冻结 trace 不被覆盖；新逻辑只约束以后新形成的研究。

## 6. 样本影响

`selection-impact-matrix.csv` 覆盖全部 29 条历史正式入选：

- 分类发生变化：6 条，包括 4 条历史正式语义改为 conditional event，以及 2 条按修订逻辑应拒绝。
- 优先级或行动条件发生变化：8 条。
- 保持形成日取舍不变：7 条。
- 旧 V1 无法无损重建：8 条。

以上四类互斥并合计 29。早期结果单列在 `early_outcome_used_only_for_evaluation`，没有进入 `revised_formation_day_decision`。这些短窗口结果不能证明长期改进，也未用于拟合固定阈值。

## 7. 数据扩展

- `candidate_outcomes.csv`：78 条，覆盖 selected 29、rejected 45、unresolved 4。
- `conditional_event_outcomes.csv`：4 条，condition_result 仅为 `met|not_met|unknown`；本样本四条均无经人工确认的可靠入口，正式收益字段为空。
- `undiscovered_outcome_leads.csv`：未生成。现有提交物只有候选和引用行业/价格的形成日审计切片，没有可回放的“每个形成日完整合格股票范围”快照，无法同时可靠还原板块范围、ST/退市/停牌/板块排除、有效报价和行动日可参与性；因此不建设新平台也不补猜。
- 相对市场和相对板块的行动后字段暂为空，因为当前数据包没有导出与每条候选完全同窗口的事后基准序列。

## 8. 测试与验证

- 基线测试：`554 passed in 66.21s`。
- 第一批定向测试：`225 passed in 2.73s`。
- 第二批定向测试：`273 passed in 3.97s`。
- 第三批导出测试：`9 passed in 0.55s`。
- 完整测试：`565 passed in 55.66s`，多于基线 11 项，无失败或跳过。
- `git diff --check`：最终检查通过。
- 数据包验证：`status=PASS`；17 个哈希通过；隐私扫描 PASS；11 页工作簿可打开；25 条正式记录、78 条候选结果、4 条 conditional 结果均通过计数与语义检查。
- 工作簿 QA：14 个公式单元、0 个公式错误；11 页均完成渲染和视觉检查。
- 原始样本：manifest 哈希导出前后一致，Git 无差异。

## 9. 明确未修改

- 没有增加评分器、固定权重或新发动机。
- 没有修改 11 个价格场景。
- 没有新增数据库表、schema 或迁移。
- 没有新增数据源或依赖。
- 没有连接券商、自动交易、仓位或收益承诺。
- 没有根据当前短期结果调整固定阈值。
- 没有把任务扩大成安全、权限、审批或审计工程。
- 没有重写冻结 trace、候选最终命运或研究结论字段。
- 除仓库规则要求的一次独立审查外，没有启动其他子智能体。

## 10. D20 后再决定的事项

- conditional 线索中哪些条件判定长期稳定，哪些需要保持 `unknown`，以及以后新 active trace 的独立表现。
- 多日连续推进相对单日脉冲在成熟 D20 样本中的命中、回撤和失效差异。
- 同发动机最近替代股是否持续揭示成员选择问题，还是短期噪声。
- 板块共同动力成立后，leader/core 成员的价格接受是否稳定优于弱成员。
- “停止增加名单”是否减少弱选，同时是否造成可解释的遗漏。
- discovery miss 与 decision miss 能否在未来具备完整形成日合格股票范围后可靠区分。

这些问题只在结果成熟且样本扩展后复核；本轮不提前删除发动机、不改场景、不做第二轮调参。
