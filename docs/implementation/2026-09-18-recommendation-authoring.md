# 2026-09-18 推荐成稿职责改造（article-v1）实施摘要

性质：实现摘要（公开版，无本机路径与私人数据）。任务来源：已获用户确认的《GLM_执行指令_推荐成稿改造与真实试写_V1.0.md》。
状态：代码与测试完成；真实GLM试写已完成并停在「待文章评估」；未合并 main、未切换生产、未删除远端分支。

## 基线

- 唯一验收分支 `fix/recommendation-authoring-20260918`，基于 BASE_COMMIT `54e27c9`（本机实际运行版本，包含 9月17日备份 `e415a04` 为祖先，另含一个更晚的有效程序改动；未从落后的 origin/main 开工，未回退本机实现）。
- 独立方案审查按指令执行恰好一次：生产 `run_stage(stage='plan-review', provider='glm', fallback=False, text_only=True)` 真实GLM调用，结论「通过（以修订版为准）」，修订 R1（凭据装载确认）、R2（基线漂移核查：`54e27c9` 未触及本轮四个核心文件）、R3（推送前隐私扫描）均已落实。

## 职责流程（改动后）

```
同一晚间任务、原截止
├─ 选股研究会话：pending trace + 市场说明（research-reply.md 的 `## 今天的市场情况`）+ selection-handoff.json
├─ 逐股作者会话（普通循环，每股全新会话）：按单股研究包完整成稿（ops/recommendation-authoring-prompt.md）
├─ 独立审稿会话：读者理解 + 同版研究核对（ops/recommendation-review-prompt.md）
│     表达问题 → 原作者步骤有限次修改（上限2）；研究问题 → 返研
├─ 研究负责人定向返研：同步 pending 与交接 → 重建受影响单股材料 → 回到作者（不跳过成稿；上限1次/轮）
├─ 独立复盘会话：按原 forward-monitor-prompt 合同执行当日复盘（已有同版产物则复用）
└─ 汇合核对 → accepted-recommendation.json → 既有 freeze/CSV 合同 → 程序原样装配原四个分区（不调用模型总结）
```

## 主要改动（文件 → 职责）

- `tools/recommendation_pipeline.py`
  - 新增 `handoff_from_trace` / `selection_handoff`：同版研究的确定性交接视图；`build_article_packet`：九字段单股包（identity/judgment/reasoning/evidence/comparisons/counterevidence/conditions/unknowns/source_refs/gaps + 本股裁剪事实与必要定义），只做确定性提取，不计算新分数；
  - 新增 `author_prompt` / `review_prompt` / `parse_author_output` / `parse_review_output`；
  - 新增 `run_article_cycle`：作者→审稿→有限表达修订的共用循环，返回 ready / needs_research / needs_revision / failed；
  - 新增 `article_stage`：未冻结阶段按「阶段+输出合同版本+实际Prompt全文+会话身份（路线/model_ref/base_url/text_only）」复用；旧缓存缺输入身份→保留旧文件重建；同输入可恢复；
  - 新增 `_author_articles`：逐股循环+定向返研回作者；`assemble_stock_section`：按正式名单顺序只补逐股标题行；
  - 重写 `complete()`：选股研究→逐股作者→独立复盘会话→汇合核对→冻结→装配（新流程）；旧四分区研究回复的已有采用稿继续原恢复路径；
  - `run_stage` research 交接文本去掉“复盘已归档”前提；`recover_research_handoff` 改为 pending 身份+合同+市场说明；
  - `json_object` 增加未转义内引号修复（模型在字符串值里引用含ASCII引号原句时）；`parse_review_output` 对“列了问题却标ready”的自相矛盾按未就绪处理；
  - 删除旧首次写作路径 `edit_stage`/`editor_prompt`/`parse_edit`/`apply_edits` 及 `ops/recommendation-editing-prompt.md`（无真实历史调用方，避免两套并行生产管线）；`recommendation_draft` 仅保留给历史恢复。
- `tools/stock_ai.py`：`write_monitor_prompt` 新增（独立复盘会话启动说明）；`write_nightly_prompt` managed 说明改为选股研究only；managed 标记 `article-v1`；其余调度、默认路线、launchd 不变。
- `tools/nightly_report.py`：新增 `market_section_text` 与 `assemble_from_sources`（由市场说明+已存复盘+正式统计+采用正文装配原四个总标题；装配前合同检查与原 `assemble_reply` 相同）。
- `tools/recommendation_trial.py`：人工验收试写薄入口（prepare/run），调用与生产相同的 `run_article_cycle`；无正式 record/freeze/发布能力；退出码 0/2/3/4。
- `src/stock_analyzer/ops/recommendation_context.py`：未改（无新分数/门槛）。
- Prompt / Skill：`ops/recommendation-authoring-prompt.md`、`ops/recommendation-review-prompt.md` 新增；`ops/forward-selection-prompt.md`、`ops/forward-monitor-prompt.md`、总控与复盘 SKILL、`ops/stock-ai-usage.md` 仅改执行分工条款；`selection-writing-calibration.md` 教学保留原样（与作者合同无冲突措辞）。
- 测试：新增 `tests/test_recommendation_authoring.py`（18用例）、`tests/test_recommendation_trial.py`（6用例）；`tests/test_recommendation_pipeline.py`、`tests/test_astra_nightly.py` 中旧写审流程用例改写为等价新流程用例。

## 验证（实际命令与结果）

- 任务清单十文件：`pytest -q`（pipeline/authoring/trial/stock_ai/astra_nightly/forward_selection/forward_monitor/forward_monitor_prompt/render_monitor_web_statement/recommendation_readability）→ **577 passed**。
- 全部常规测试集（除4个人工浏览器检查脚本）→ **1566 passed / 1 skipped / 2 failed**。
  - 2个失败为 `tests/test_prism_a2_preview.py` 两用例：工作树不含 gitignore 的 `local_warehouse` 数据分区（交易日历）所致；在原生产工作区运行同两用例通过 → 工作树环境性基线失败，非本轮改动；未以删除断言或放宽合同隐藏。
- `git diff --check` 通过。真实模型试写（任务7）与 mock 测试分离：mock 全部合成数据，不请求任何模型。

## 真实GLM试写（摘要）

- 对象：飞凯材料 300398.SZ、捷捷微电 300623.SZ、中天科技 600522.SH（来自正式 trace research-trace-2026-09-17，固定原时点研究，as_of=2026-09-17T18:30:00+08:00；范文=中国巨石、国际复材）。
- 路线：全部调用 `provider=glm、fallback=False`（bigmodel/glm-5.3-flash，专用 base_url 与凭据）。configured_model 已记录；本机 ZCode rollout 未保留试写会话的主请求 model 字段（model-io 文件被CLI轮转清理），evidence_model 如实标注「模型身份未完整核验」，会话ID/token用量/输入存在性与零工具核对均已留存。
- 版本对应：RUN-1（初版代码）暴露两个实现缺陷→修复提交；RUN-2（修复后）重跑受影响试写；RUN-3（最终代码）补齐受影响单股两轮。三轮各自新目录、不跨轮复用缓存；涉及正式文件（trace/CSV/日报告/复盘账本/报告/snapshot/A2两页）前后 SHA256 三轮均一致。
- 最终评估集（每股两版，均为完整正文）：飞凯材料 两版 needs_research（研究缺口：如员工持股解锁供给量级缺数、比较口径核对；其中一例作者疑点经与packet事实核对为误读，已如实注明）；中天科技 两版 needs_research（缺口：解锁供给量级、分业务收入缺细分）；捷捷微电 两版 needs_revision（两轮表达修订后审稿仍有可读性意见，草稿与意见保留）。
- 按合同不把 needs_research/needs_revision 冒充通过；退出码语义（0/2/3/4）在三轮中均有真实命中。逐股状态、会话证据与具体缺口见交付的《交给ChatGPT评估_运行说明.md》。

## 待采用状态

- 停在「待文章评估」：文章与运行证据交用户/ChatGPT 评估；质量采用后另行按合同快进合并 main、再清理临时工作树/分支。本轮未自动合并、未切换生产、未删除远端分支。
