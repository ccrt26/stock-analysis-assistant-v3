# GLM 定向修补与日常运行核验 V1.2 实施摘要（脱敏）

日期：2026-09-19｜分支：fix/recommendation-authoring-20260918｜生成版本：64a8acd（GENERATION_COMMIT）
性质：现有验收分支上的定向修补，不重做架构。前两轮方案不叠加为待办；本轮只执行 S0—S5 与 A1—A4 四组修补。生产目录、launchd、长期模型路由、正式历史全程未动。

## A1 有效材料一致（S2）

- 新增纯函数 `build_effective_packet(initial_packet, resolutions)`：深复制原包；仅当处理为 `resolved_existing`/`resolved_added`、非阻塞、不改变原判断时应用 `effective_updates`。条件恢复要求 source_ref 在包内可解析、证据与源值匹配、恢复文字与已核证据逐字一致；补充事实要求不晚于原 as_of 的公开时点证明。未通过核对的一律不应用并记入 `effective_packet.unapplied`，原问题保持阻塞；不清空其他真实缺口，不覆盖判断、参考价、时间、股名、排名与观察目标。
- `run_article_cycle`：澄清返回非阻塞处理后，包替换为有效包，其后作者与审稿使用同一份有效材料与同一版已核实处理；`review_prompt` 新增可选 `issue_resolutions` 与 `pending_issue_checks`（旧调用兼容）。检查点保存 `packet-initial.json`、`packet-effective.json`、`issue-resolutions.json`、`issues-open.json`。
- 同一 issue_id 同时出现在 resolutions 与 unresolved：在 `parse_clarification_output` 即拒绝（缓存写入前），未决优先，不再 setdefault 静默。
- 预算子项由 `scope+code` 稳定派生（清除 `_cycle_scope` 死代码）；审稿问题沿用稳定 ID（quote+problem 相同不换新 ID）。

## A2 语义错误必须处理（S3）

- `parse_review_output` 增加小枚举 `issue_kind`：`condition`/`metric_basis`/`fact`/`inference`/`reasoning_gap`/`expression`；前五类无论放在哪个分栏、无论 blocking 标记，一律强制阻塞；仅 `expression` 可为建议性小修。非法 kind 拒绝解析。
- 核销以 `pending_issue_checks`（输入）驱动：上轮审稿阻塞问题逐项核对 `issue_checks`（fixed/not_an_error/unresolved + 当前正文原句），缺失条目=未核销=阻塞，引句必须真实存在于正文；本轮列表为空或 ready=true 不能绕过。研究问题的处理已经 issue_resolutions 随同一有效包交付审稿核对，不重复计入 issue_checks。
- 审稿 Prompt 增加全文逐处条件核对（中段缩写同为错误；同窗口约数可保留，换窗口不是四舍五入）与 issue_kind/issue_checks 输出合同；作者 Prompt 增加指令语边界（写作要求不写进正文；可合并重复解释、不可删主要反证或添加研究外理由）。

## A3 日常可恢复（S4）

- `stage_execution_verified` 收紧：`verified is True`、会话与型号字段齐备、`route_evidence_matches(...) is True` 严格判定（原为 `is not False`）。澄清阶段（实际新调用或核验过的缓存复用）计入 `execution_verified`；预算耗尽未调用时不计。
- 预算与进度持久化：`article_cycle_counts[scope]`（expression/clarification/research_repair）与 `article_cycle_progress[scope]`（next_stage+counts）按 scope+code 稳定子项写入原 state；实际新调用前计数，缓存复用不扣新次数，恢复不清零。生产实质返修次数持久化，返修阶段执行核验不通过不冻结；采用文章要求 `execution_verified is True`，否则不冻结（生产与试写同一标准）。
- `complete()` 重排：共享准备/时点核对完成后，独立复盘先行（已有同版正式产物则复用），随后选股研究+作者/审稿。两路普通失败（OSError/ValueError/RuntimeError）分别记录、互不阻断；KeyboardInterrupt/SystemExit 穿透；失败时核对 pending 身份未被改变（改变即硬抛）。复盘失败而推荐完成→保存 `accepted-draft-checkpoint.json`（不冻结、不冒充发布）；推荐失败而复盘完成→复盘产物保留；任一部分失败以"部分完成"上抛走原失败通知。恢复时优先采用同身份检查点（过 `_recommendation_section_issues` 核对），零模型调用；两路都完整才走原汇合核对+冻结。既有 accepted 恢复路径保持零模型调用不变。
- `trial.run --resume`：读取原 state，逐项核对股票/时间身份/模型策略/输入清单摘要/重复次数，一致才恢复；不符明确拒绝（exit 2），不静默混版；state 缺失按新运行，损坏拒绝。新建 state 记录输入摘要与策略。

## A4 可复查交付（S5）

- `check-review` C4 改为全链：审稿初稿→澄清→有效包→作者修改→复审，全程生产共用函数；包装层核对初稿不 ready、处理非阻塞、初始包逐字未改、修订文数字归属配对（同子句内核对）、复审 ready。C1 夹具改为"中段条件错、结尾对"。期望标签不进入模型 Prompt。
- `export` 改为 GLM_V12_复核包结构：按 expected_samples 列全 6 条；各阶段实际输入、原始回复、解析结果、review/issue_checks、resolution、initial/effective packet、state 与执行证据全部带出；审稿挑战目录按挑战结构读取；反截断回读核对保留；失败样本导出最后草稿并注明未采用。

## 合同版本与测试

- AUTHOR/REVIEW/CLARIFICATION 合同版本升为 v2（输入/输出 schema 变化，旧缓存自然失效）。
- 包内五个外部反例（同源澄清、误分类口径、冲突 resolution、澄清核验、resume）修复前 5/5 失败，修复后 5/5 通过；断言未降级、未 mock 受测函数。
- 仓库相关 620 项测试通过；全量 1609 通过/1 跳过/2 失败（prism 两用例为 worktree 缺 local_warehouse 的已知环境性基线失败，原工作区通过，与本轮无关）。
- 新增集成例：作者失败仍得完整复盘、复盘失败得未冻结草稿检查点、两路成功才冻结、空选仍复盘、取消停止全部、检查点恢复零模型调用、resume 拒绝换输入、语义 blocking、issue_checks 核销、预算恢复不清零。complete 使用真实实现，仅 mock 模型/外部 IO。

## 真实运行（GLM-5.3-flash，provider=glm、fallback=False）

- 审稿挑战 6/6 通过（exit 0），C4 全链真实走通。
- 六篇最终回放全部 ready+执行核验通过：飞凯/捷捷/中天（2026-09-17 cutoff）各 1 次，中材（2026-09-16）2 次，海星（2026-09-15）1 次。海星首次澄清输出违反 effective_updates 合同（conditions 输出为数组）→ 按设计失败保留现场；`--resume` 读取原 state（澄清计数 1→2 未清零、失败原文保留）恢复后 ready。其余五篇一次通过。中天样本呈现完整行为链：事实类意见→澄清（resolved_existing×2+resolved_added×1）→有效包应用→复审 issue_checks 核销（fixed+正文原句+依据）→ready。

## 生产隔离核验

- production-before/after 逐项对比：生产关键文件哈希零差异；launchd 6 任务配置与加载无变化；生产 main HEAD 54e27c9 不变；无新增正式任务 state；被引用日期的 trace/CSV/复盘内容核对未变。全部真实调用经试验入口显式指向验收工作树。

## 边界与未满足项

- 文章质量是否接近范文由实际阅读复核判定，不用模型自评分代替；本轮报告只声明技术修补与运行核验结果。
- 澄清模型可能伪造 published_at 本身属模型判断残余风险，程序只保证时点声明完备性校验（fail-closed）。
- prism 两用例环境性失败未处理（非本轮事项）。
