# 当前机会复盘与批量研究连接：实施报告（2026-09-10）

执行对象：`GLM5.3_精确执行单_V3.0`（经一次独立方案审查，"通过（以修订版为准）"，6 条修订 R1—R6 全部吸收）。基线 `61e697f`，工作区干净起始。授权边界：本轮不改五个选股 Skill 的发现/验证/最终选择规则，只产出演练与提案。

## 1. 真实修改

| 文件 | 修改 |
|---|---|
| `src/stock_analyzer/ops/forward_monitor.py` | 新增 `CurrentOpportunityV1`（成对 reference 校验、consider 需参照）与 `DailyFormalReviewV1.current_opportunity` 可选字段；`current_opportunity_changed()` 辅助函数纳入普通详评优先组（R3：仅 `_validate_regular_detail_priority`，另一旧校验路径未动）；prepare 快照新增 `current_opportunity_required`；record 对新快照 live 行强制对象、校对 reference 日/价、同股同日一致（R2）；Markdown 状态行/目标标注"原推荐参考价/原20%观察目标"，详情块新增"当前机会"区域（从已保存账本读取） |
| `tools/web_display_contract.py` | 新增纯函数 `current_opportunity_for_display`（R1 方案 b：中文文案载荷侧预算，前端只渲染；缺失/未识别返回 None，unknown 不归并 sideways） |
| `tools/render_monitor_web.py` | 两处 review 组装附 `currentOpportunity`；V4 模板复盘行新增"未来5—10日/参与意见/改变判断" |
| `tools/guanlan-prism/src/app.js` | 详情观点面板新增当前机会块；参考价/目标标签加"原" |
| `tools/export_skill_optimization_dataset.py` | C1 `build_monitor_records(valid_episode_ids=...)` 按本批原始身份读历史报告；C2 `build_research_run_records` 接入 research-run-context（recorded/dirty/unknown+mismatch，R6：run_id null 不抛错）；C3 派生行一律 `retrospective_reconstruction`（公式版本命中不再视为 frozen_used，原 formation_values 原样保留）；C4 `fixed_d20_*` 新增市场基准四字段 + missing_dates 与日历配对修复（None 行不再崩溃）；C5 manifest 按实际声明 `current_opportunity_contract` |
| `tools/validate_skill_optimization_dataset.py` | R5：声明合同则包内至少一行含新对象且枚举合法，未声明则不得出现 |
| `ops/forward-monitor-prompt.md` | 新节点六项、新普通详评四项（替换旧版，不叠加）；"当前机会意见"与"第20日新旧分离"两节（含 B1 五点、晚补结案规则）；展示分工 |
| `.agents/skills/reviewing-stock-recommendations/SKILL.md` | 职责改为含当前机会综合；对象语义；六项/四项同步；schema 行兼容说明 |
| 四专业 Skill + 总控 + 买入决策 | 仅 review 阶段增补（市场含义/同业变化/公司新信息/当前价格与参与代价/分工澄清/与完整买入研究衔接）；发现与验证规则未动 |
| `ops/forward-selection-prompt.md` | 转交句提 current_opportunity 合同 |
| `ops/selection-method-review-prompt.md`（新） | 03 号文件全文接入；默认 diagnose；批准后才 implement |
| `ops/stock-knowledge-prompt.md` | 模式三改引用新入口；diagnose 边界写明 |
| 知识子库 | 共同要点与三指南改为当前机会目的；旧范文标"可学习的局部能力"；三份模板按 03 结构更新 |
| 架构文档 | `current-opportunity-review-v1.md`（新）；`stock-knowledge-and-skill-review-v1.md`、`forward-monitoring-v1.md`、根 `AGENTS.md` 同步（可选/两篇旧文案删除；schema 兼容说明） |
| 测试 | `tests/test_current_opportunity_review.py`（新，19 项：起始单测 + T01/T02/T03/T04/T06/T07/T10/T11/T12/T14/T15/T23/T24/T25）；导出测试新增 T17/T18/T20/T21（T08/T09/T19 由既有 T04/T05/T14 覆盖；T13 由 previous 透传机制与账本模型测试覆盖；T16 幂等由既有 record 测试覆盖）；`tests/test_forward_monitor.py` 夹具补新对象、标签期望更新；`tests/test_forward_monitor_prompt.py` 钉住句随新六项更新（R4） |

## 2. 测试命令与真实结果

```text
pytest tests/test_current_opportunity_review.py tests/test_forward_monitor.py
  tests/test_forward_monitor_prompt.py tests/test_forward_review_context.py   → 254 passed
pytest tests/test_render_monitor_web.py tests/test_render_prism_web.py
  tests/test_prism_web_contract.py                                            → 109 passed
pytest tests/test_export_skill_optimization_dataset.py
  tests/test_validate_skill_optimization_dataset.py                           → 35 passed
pytest tests/test_forward_selection.py tests/test_engine_contract_v4.py
  tests/test_engine_contract_knowledge_v4.py tests/test_update_monitor_web.py
  tests/test_prism_atlas.py tests/test_v4_operational_prompts.py              → 190 passed, 1 failed
node --check core.js / app.js                                                 → 通过
git diff --check                                                              → 干净
pytest（全量）                                                                → 见文末补充
```

唯一失败仍为基线既有环境项（要求本机 Downloads 存在 8 月历史执行指令文件），与本轮无关，未删测试、未补造文件。

## 3. 三类试写（local_archive/review_trials/current-opportunity-v1/）

- **深度复盘（银龙第14日，当前机会改写）**：新四项下把旧稿两处重复的"此前涨得好不保证继续涨"合并为一处，腾出篇幅写旧稿没有的"当前价格下的参与代价"；current_opportunity = sideways/wait，理由与 1—3 日整理一致不重复正文。
- **关键节点（银龙第10日，历史改稿练习、非盲测）**：只用 D10 归档事实；新版差异是第①项开门见山给当前方向与参与、第⑤项从"目标主导"改为"当前价格下的机会与代价"；"十天分两段读"的组织与缩量边界句原样保留。
- **简评（中信银行 9/8 第一条 brief，按账本顺序取样）**：正文不再重复"维持观望"（外层已显示当前意见），字数让给 5—10 日看不清的理由；unclear 未写成横盘。
- **第20日（虚构价格、明确标注）**：同一数据下"触达过目标+期末回落 8%"的固定结案与"当前偏弱、暂不参与"的当前意见并存互不改写（T07/T08 类分离）。
- 原稿更好之处如实记录：第14日原稿对 9 月初历史的用法、第10日原稿的阶段组织、中信银行原稿反证句的位置，均保留。

## 4. 首次批量研究演练（E3）

- 范围（按规则确定并记录）：最早未做过方法研究的连续 5 个研究日，action_date 2026-09-01 至 2026-09-07；行情截止 2026-09-09；数据包 `local_archive/skill_optimization/current-opportunity-2026-09-01-to-2026-09-07-through-2026-09-09/`（不覆盖既有包），校验 PASS。
- 数量：研究日 5（研究动作日 09-01/02/03/04/07）、推荐 8 次、不同股票 8、正式完整20日 **0**、未成熟 8、缺失 0、无可靠入口 0、条件事件 3（unknown）、legacy 0；manifest 未声明 current_opportunity_contract（账本早于功能启用，不补造）。
- 分析稿：同目录旁 `analysis-current-opportunity-.../00_问题与范围.md`、`02_研究结论与后续验证.md`。结论：**目前不改**——固定研究问题（价格连续性确认的代价）需成熟窗口与近邻对照，本批证据不足；待本批约 2026-09-29 后陆续成熟再复算 fixed_d20_* 并对照 candidate_outcomes 近邻。

## 5. 真实运行的有限证据与未观察项

- **真实定时任务已读取上轮 Prompt 的客观痕迹**：2026-09-09 晚间运行写下了首个 `research-run-context-2026-09-10.json`（V1 新增机制的首个真实产物）；但本轮 V3 的当前机会合同是今日凌晨实现，**下一次真实运行是否按新合同产出 current_opportunity，尚未发生、未观察**。
- 两个网页的端到端渲染已由单测覆盖载荷组装；真实晚间任务生成的页面显示效果待下一次运行核对。
- deploy 状态：改动已推送 main；若晚间任务工作目录即本仓库（现有 launchd 指向），则下一次运行将使用已验证版本——这一指向性核对以任务配置为准，本报告不声称已审计 launchd。

## 6. 明确未改变与未获批提案

五个选股 Skill 的发现/验证/最终选择规则、V4 七类机会、11 价格场景、0—5 只、身份派生、原 20 日公式、原 trace/Forward CSV/已保存日评/结案、定时任务配置：**全部未改**。review 协作修改仅限各 Skill 的 review 阶段增补与总控分工澄清。**未获批提案：无**——首次演练证据不足，按合同输出"目前不改"；固定研究问题留待本批成熟后回答。
