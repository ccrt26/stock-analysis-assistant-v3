# 股票知识库与 Skill 优化复盘：本轮执行报告（2026-09-09）

执行对象：`GLM_execution_stock_knowledge_review_v1.md`（V1.0），经一次独立方案审查后按"通过（以修订版为准）"的修订版执行。起始提交 `a0442a53b01c5ebba7b42a4ec3991c0009d8424d`（与执行单基线一致）。

## 1. 实际改动文件及行为变化

| 文件 | 改变的行为 |
|---|---|
| `tools/export_skill_optimization_dataset.py` | E0—E7 全部修复（见第 2 节）；包版本升为 `a-share-skill-optimization-sample-v3` |
| `tools/validate_skill_optimization_dataset.py` | 重写为动态校验：边界与数量全部读自包内 manifest 与文件本身；旧 v1/v2 包继续可验证 |
| `tests/test_export_skill_optimization_dataset.py` | 新增 T01—T19；两处旧用例按新合同更新（条件事件接口、episode 身份），原断言意图保留 |
| `tests/test_validate_skill_optimization_dataset.py` | 新建（此前不存在），4 项通用批次校验测试 |
| `ops/forward-selection-prompt.md` | 仅新增"方法版本辅助记录"小节（第 5 节），选股步骤与取舍规则未动 |
| `ops/forward-monitor-prompt.md` | 仅新增"写作前可选读取已确认范例"入口段（第 6.5 节），文风基准与正式合同未动 |
| `ops/company-introduction-prompt.md` | 同上，在逐只写作第 1 步下加入入口段 |
| `ops/stock-knowledge-prompt.md` | 新建：知识子库唯一整理入口（人工触发，三种模式） |
| `docs/architecture/stock-knowledge-and-skill-review-v1.md` | 新建：分层、口径与批量复盘方法的正式说明 |
| `AGENTS.md` | 仅加一行指向上述两个新文件 |
| `docs/stock-knowledge-review-implementation-20260909.md` | 本报告 |

本地新增（不提交 Git）：`local_archive/knowledge-vault-path.txt`（知识子库本机路径）；`local_archive/skill_optimization/kb-review-2026-09-02-to-2026-09-08-through-2026-09-08/`（真实试跑包）。Obsidian 子库 `股票分析/` 已按第 6 节实际安装（路径唯一核实，未使用 vault-preview 降级）。

## 2. E0—E7 逐条状态

- **E0（审查修订新增，备份文件过滤）— 本轮完成**：trace / monitor-report / daily-formal-reviews / snapshot 四类输入只接受规范名 `<前缀>-YYYY-MM-DD.json`；不改名、不删除用户既有备份。`duplicate canonical trace` 仅对规范名冲突触发。导出记录保留 `source_file`。真实试跑证实其必要性：归档中 2026-08-20 至 09-01 几乎每个日期都有 2—3 份备份副本。
- **E1（去硬编码）— 本轮完成**：校验器不再含旧样本常数；工作簿变为可选附件（存在才扫可读性与公式错误，页数仅当 manifest 声明时核对）；合法空名单可导出（带表头空 CSV）；无研究 trace 明确报错；README/manifest 全部从本批实际资料生成。v3 包不写工作簿，旧包继续可读。
- **E2（真实交易日历 + 固定 20 日口径）— 本轮完成**：编号改用 `facts/trade_calendar` 开市日，第 1 日即原行动日，整日缺行情不前移编号；当前观察上限 30 个交易日，`fixed_d20_*` 只取原 1—20 日；12 个固定字段与 `not_applicable → missing_path(日历) → no_reliable_entry → not_mature → missing_path(路径) → complete` 的状态顺序全部落地；收盘触达容差沿用正式 Forward 的 `0.20 - 1e-12`；`formal_result_consistency`（match/mismatch/unavailable）对照正式冻结值，不覆盖正式文件。
- **E3（候选逐日路径 + 同窗市场对照）— 本轮完成**：新增 `data/candidate_daily_price_volume.csv`；沪深300 按 `action_open_to_same_close` 同窗对照，基准三字段写入每日路径；缺指数开盘时相对字段为空并注明，不借用近 5 日收益。行业对照按执行单只接已有可信口径——本地暂无同窗行业基准，`relative_sector_return_if_available` 保持空并记 `relative_sector_missing_reason`，已列入后续最小补充清单。
- **E4（条件事件不再依赖 9 月 1 日旧矩阵）— 本轮完成**：新增 `--condition-review-file`，无输入/无匹配/观测晚于截止均记 `unknown` 并注明原因，不再使整批失败；决策证据按 `(run_id, ts_code, decision_id)` 关联（单条缺 run_id 时仅唯一无歧义匹配才兼容）；条件事件行固定 `formal_return_started=false` 且固定正式 20 日为 `not_applicable`；`candidate_outcomes` 增加 `selection_output_class`（rejected/unresolved 恒为 `not_formal_candidate`）与 `outcome_usage=candidate_price_comparison`。真实试跑中 5 条条件事件以 unknown 正常导出。
- **E5（每日判断账本导出）— 本轮完成**：新增 `data/daily_formal_reviews.jsonl`；文件头 `analysis_date/as_of` 展平进每条记录，`review_kind/review_origin` 取自账本行（审查修订二）；简评正文只在账本、详评正文只在报告，空正文不覆盖；`(episode_id, analysis_date)` 关键唯一；账本/报告共同字段不一致记入包缺口。episode 身份修正为按形成日（与真实 episode_id 同构）后，本批 8 条正式记录全部与快照 episode 对上。
- **E6（区分"当时用过"与"事后重算"）— 本轮完成**：派生上下文每行带 `context_origin`（决策证据引用的 formula_version 命中为 `frozen_used`，否则 `retrospective_reconstruction`）与实际 `formula_version`。
- **E7（可复核但不做成审计平台）— 本轮完成**：manifest 记录 `exported_at`、`research_action_dates`（含零入选研究日）、`fixed_d20_maturity`、实际缺口；复用既有文件哈希；无签名、队列、巡检或上传。

执行中发现并按合同处理的两处真实数据事实：①冻结 log 与 trace 存在 3 处措辞差异（见第 5 节），两份原文均保留、差异显式记账，未改任何原文件；②自 9 月合同起条件事件不再写入正式 log 的 selected 行，导出器相应跳过条件线索的 log 配对要求（与 V4 合同一致，8 月旧数据仍可导出）。

## 3. 方法版本辅助记录接入状态

Prompt 入口已加入 `ops/forward-selection-prompt.md`；本轮无新正式研究运行，故尚无实际 `research-run-context-*.json` 产物，自下次 `record-trace` 成功起生效。历史版本全部无法确认，导出时按 `version_status=unknown` 处理；本批试跑的方法版本在批量草稿中如实记为 unknown。

## 4. 知识库安装状态与产物数量

子库已实际安装（真实路径已核实并写入本地路径文件），结构：`AGENTS.md`（十条规则）、`00_首页.md`、`10_方法与范文/`（含 `00_已确认写作要点.md`、`经验教训.md` 初版 5 条摘录、三个空范例目录）、`20_个股档案/`、`30_批量复盘/`、`31_优化史.md`、`90_专题/`、`99_模板/` 四件模板。本轮产物：**个股试稿 1 篇**（世纪华通 2026-09-08，source_excerpt，按"最新行动日、同日 P1"规则选取）、**批量草稿 1 篇**（draft）、**范文提名 2 篇**（银龙股份 D10、奥克股份停止跟踪，均 draft 待确认）、**优化史回填 1 条**（2026-09-01 三批修改，注明基于早期样本、收益改善未被完整窗口证明）。

## 5. 真实试跑范围与数量

范围（按 8.2 固定规则，不按收益挑选）：最近 5 个不同行动日 `2026-09-02` 至 `2026-09-08`（形成日 09-01/02/03/04/07），批内全部原候选进入；行情截止取最新已归档收盘分析日 `2026-09-08`。

数量：研究日 5（全部有正式 trace）；正式入选 8 次 / 8 只不同股票；候选账 32 条；决策证据 110 条；条件事件 5 条（全部 unknown）；每日判断账本 23 条；正式逐日路径 23 行（每条最多 30 日）；候选逐日路径 92 行；成熟 **0** / 未成熟 **8** / 缺失 **0**。校验器结果 PASS（17 个文件校验和、隐私扫描通过）。无完整 20 日记录，因此按 8.2 未生成任何"结案证明"，批量草稿主要结论为"已能持续收集与对照，尚不能评价 20 日效果"。

## 6. 实际执行的测试与结果

```text
./.venv/bin/python -m pytest -q tests/test_export_skill_optimization_dataset.py
  tests/test_validate_skill_optimization_dataset.py   → 31 passed
./.venv/bin/python -m pytest -q tests/test_forward_selection.py tests/test_forward_monitor.py
  tests/test_forward_monitor_prompt.py tests/test_engine_contract_v4.py
  tests/test_engine_contract_knowledge_v4.py          → 371 passed
./.venv/bin/python -m pytest -q                        → 1201 passed, 1 failed
git diff --check                                      → 仅既有无关文件（docs/plans/2026-09-08-…）一处 EOF 空行提示
```

唯一失败 `test_v4_operational_prompts.py::test_archived_execution_instruction_is_a_verbatim_copy` 为基线既有环境问题：该测试要求本机 Downloads 目录存在一份 2026-08 的历史执行指令 Markdown，与本轮改动无关（本轮未触碰该测试及其目标文件）。两个工具测试文件均先写测试后改实现；未执行跳过的测试：无。另有三个既有本地未提交改动（`tools/render_monitor_web.py` 等）不属于本轮范围，未触碰。

三个使用动作（8.3）已逐项验证通过：个股笔记可回溯原 trace、账本记录与结案状态（episode 身份唯一，同股多次推荐不混用）；知识入口读取路径有效且无确认范文时按既有规则回退；批量草稿可跳到 32 条候选、110 条决策证据与含基准列的同窗价格，行业与版本缺口在 README 可见。

## 7. 仍保留的限制

同窗口行业基准缺失（相对行业收益为空并注明原因）；历史运行方法版本无法确认；条件事件判定依赖人工文件，本轮 5 条全部 unknown；冻结 log 与 trace 的 3 处历史措辞差异只能并存记账；最新快照不保留已结束 episode 的完整历史，跨批导出靠 trace+log 身份兜底（E5 设计已覆盖）；数据包无法重建各形成日完整合格股票范围，不做"全市场漏选率"统计。

## 8. 明确未改变

五个选股 Skill 与复盘判断规则；V4 合同、七类机会定义、11 个价格场景；Forward CSV 口径与正式身份派生；冻结 trace、原推荐理由、已保存日评与 D20 冻结结论；定时任务、launchd、网页渲染；无新增数据库、向量检索、社区插件、依赖、评分器或自动触发。已提交的 8 月/9 月历史研究数据包未重导出、未覆盖。

## 9. 下一批优先验证的问题

本轮无成熟收益证据，**不建议改任何选股规则**。下一批（本批 8 条陆续到 D20，最早约 2026-09-30 前后）优先验证一个问题：**板块扩散类入选（本批 5/8 条）在完整 20 日窗口的达标与回撤分布，是否支持"剔除最大日后仍有多日进展"这一入选条件的有效性**。届时以同一导出口径复算 `fixed_d20_*`，成熟率仍为 0 时先查交易日历与行情覆盖。条件事件的 5 条 unknown 待人工判定文件补齐后可单独评价。

---

# V2 执行单实施说明（2026-09-09，同日追加）

对象：`GLM5.3_执行单_Obsidian复盘分类阅读与写作改进_V2.md`。接续同日 V1 成果执行，未重建知识库、未覆盖已有文件（知识子库与 `local_archive/` 既有产物全部保留）。

## 1. 本地基线与知识库路径配置

本地 HEAD 与 V1 时相同（`a0442a5`），全部 V1 改动以未提交形式在本地工作区。知识子库根目录为 V1 已核实的本机路径，通过仓库 `local_archive/knowledge-vault-path.txt`（一行绝对路径，本地忽略不提交）定位；定时任务在仓库根目录以普通文件读取取得该路径，不依赖终端环境变量，仓库外 AGENTS.md 不参与加载。未新增第二份路径配置（执行单 6.4 的 `stock_knowledge/knowledge-root.txt` 兜底因此不需要）。

## 2. 修改文件清单（旧 → 新）

| 变更 | 位置 |
|---|---|
| 主 Prompt 样稿块（"以下文风样本已经用户确认…"至简评范例，4922 字符）原样迁出 | `.agents/skills/reviewing-stock-recommendations/references/review-writing-legacy-examples.md`（新建，标注"历史样稿与更正记录，默认不作为每日必读范文"），原位置留指针 |
| "可选读取"段替换为必须实际打开的运行版（按当天类型读指南与范文全文，取消跨类型至多两篇限制，失败如实降级） | `ops/forward-monitor-prompt.md` |
| "今天发生了什么"栏目区分三类正文语义 | `ops/forward-monitor-prompt.md` |
| 文风引用与"无条件读取"改为分类入口 + 兜底；新增三类分工句 | `.agents/skills/reviewing-stock-recommendations/SKILL.md` |
| 复盘写作入口改为一句话强制转交（覆盖正常、already_selected、补跑） | `ops/forward-selection-prompt.md` |
| 常规必读说明改为分类匹配/兜底（教学正文未动） | `references/regular-review-calibration.md` |
| 迁出样稿的断言改读归档文件；新增"主 Prompt 保留分类入口"断言 | `tests/test_forward_monitor_prompt.py`（25 项全过） |
| 分类目录、四份阅读入口、七篇材料、AGENTS 补充、首页导航 | 知识子库（见下） |

知识子库新增/重构：`复盘范文/{关键节点复盘,深度复盘,简单复盘}/` 与 `改稿对照/`三类目录；`00_已确认写作要点.md` 重写为共同要点 + 三类固定映射；三份 `00_阅读指南.md`（含节点适配表与索引表）；范文五篇——银龙第10日（正式归档正文 + 2026-09-08 用户认可标题，注明旧版范文为另一版本、禁止拼合）、银龙第11日（正式归档正文；按用户既有意见替换"外层所说…"句，原句与替换句并录）、奥克股份（正式归档正文，已不含被纠正推论）、杭氧股份（2026-09-07 用户认可教学定稿）、银龙简评（2026-09-08 用户批准）；对照两篇——银龙第11/14日论证比较（第14日练习稿全文 + 用户认可的比较原文原样保存，标注不同日期写法比较、练习稿非正式归档、"D11与D4"已厘清）、杭氧与中钢条件对照。V1 的两篇提名草稿（银龙D10、奥克）被上述正式文件取代并移除，编辑说明中记录。`20_个股档案/`、`30_批量复盘/`、优化史、公司介绍范文、经验教训原样保留。

## 3. 全文核实状态

已核实且可默认读取（五篇范文均含完整采用稿正文）：银龙第10日、银龙第11日、奥克股份、杭氧股份（教学稿）、银龙简评。仍缺/待确认：第1/3/5/20日节点范文暂缺（指南已写明按合同写作，不拿第10日充数）；仓库旧样稿中的已纠正推论只存在于历史归档并带使用边界；杭氧、中钢、轮换教学保留在仓库 calibration 文件，知识库存分类摘要与链接。

## 4. 三类运行如何选资料、知识更新如何生效

运行顺序：任务入口与复盘 Skill → 事实与三路分配（不变）→ 读 K/AGENTS 与共同要点（每次任务一次）→ 只读当天出现类型的指南 → 按类型/节点阶段/写作问题选读适用范文全文（有不同阶段或难点才增读）→ 问题直接相关时读已确认对照 → 回到本股事实撰写。更新流程：用户反馈任务中把认可写法合并进对应指南"当前采用写法"、旧条目标 superseded，下次任务读取更新后的指南；日常任务对知识库只读，新稿不自动升级。

## 5. 测试与试写的真实结果

- `pytest tests/test_forward_monitor_prompt.py`：**25 passed**（迁出样稿的断言改钉归档文件，六项/四项/互斥/600字符/唯一正文等原合同断言全部保留）。
- `git diff --check`：仅既有无关文件（docs/plans/2026-09-08-checkpoint-review-titles.md）一处 EOF 空行提示，非本轮引入。
- 10.1 文件核对脚本：五个入口文件全部可读非空，三个改稿对照目录存在（STOCK_KNOWLEDGE_ROOT 取自已核实路径文件，仅验收用临时变量）。
- 只读演练：从路径文件 → K/AGENTS → 共同要点 → 指南 → 范文/对照全文逐层打开全部成功，均为普通文件读取，无链接依赖。
- 三篇试写（`local_archive/stock_knowledge/writing-preview-20260909.md`，原稿未动）：世纪华通 D1 节点——补上原稿缺失的"按原条件正常参与"执行性一环；杭氧普通详评——原稿已符合指南，试写增益有限，如实记录未宣布胜出；中信银行简评——合并原稿中同一判断的两次表述。三篇均无新数字、必答内容齐全。第11/14日既有比较是教学资料，未替代同事实比较。

## 6. 串稿核对与超范围发现

以 2026-09-08 正式报告核对：15 篇正文（7 节点 + 8 普通）episode_id 与正文一一对应、无一同文，节点 558—657 字、普通 397—434 字；Markdown 呈现层各正文均可定位（节点正文首段在 MD 中为标题行，属格式化而非缺失）。**未发现源文本或呈现层的串稿证据**；如用户所见"文字一致"指论证相似，属允许范围，本任务未扩展到网页重构。

## 7. 未验证部分（如实区分）

- **真实定时运行尚未观察**：以上入口演练为只读验证；晚间 18:45 真实任务中"必须读取"是否按预期执行、失败降级是否如实说明，要等下一次真实运行确认，本轮不声称已验证。
- 定时任务配置（launchd）未读取、未修改——无访问工具，按执行单不声称核实。
- 知识库未提交 GitHub：仓库变更与本地产物均保留在工作区，等待用户对提交/推送的明确授权；`git add` 将逐文件进行，不使用 `git add .`。
