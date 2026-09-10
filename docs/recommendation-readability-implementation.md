# 首次推荐说明减负：实施记录（2026-09-10）

执行对象：用户提供的《裕同科技_推荐说明优化_GLM5.3执行包_V1》（含 00—03 四份文件，设计方 ChatGPT，用户指示严格执行）。基线 `ed84b52`，工作区干净起始。授权边界：只改首次推荐说明的表达与重复展示，不改五个选股 Skill 的选择规则、三类复盘、D20、采集与调度，不重写正式历史。

## 1. 实际修改

| 文件 | 修改 |
|---|---|
| `ops/forward-selection-prompt.md` | "今天明确推荐的股票"的个股模板整段替换：保留"公司主要做什么/为什么会选它/什么情况会让我改变看法"三个外层入口，删除"行业或外部变化/股票自身表现/公司经营/主要不利因素/综合判断"必写栏目、每段2—4句、每只350—650字、正反分段与阶段标签要求；数字按解释价值挑选；新增"推荐说明写作前的定向阅读"（读仓库教学+知识库本类指南）。第7节七项必答明确为"研究与写前自检问题，不是七段公开提纲"；三段类型化输出要求合并为一段"表达由主要依据决定"；补"冻结前证据判断仍由原流程完成，冻结后发现冲突报告问题、不静默删股重排" |
| `.agents/skills/orchestrating-stock-research/SKILL.md` | 仅替换"名单冻结后的用户说明"的对外表述段（原五条固定提纲+内部词语禁用示例段）：改为连贯论证职责说明，格式与定向阅读指向唯一 Prompt 与教学文件；`selection_reason`/`strongest_counterevidence`/`nearest_comparison` 实质要求未动 |
| `.agents/skills/orchestrating-stock-research/references/selection-writing-calibration.md` | 新建，内容为执行包 03 通用教学全文（不含私人报告） |
| `tools/guanlan-prism/src/app.js` | `reviewBody` 前新增 `originalRiskMarkup(s,collapsed)`；原推荐 tab 有非空 `statementFull` 时风险摘录改为原生 `<details>` 默认折叠（summary"原始风险摘录（展开核对）"），无全文时风险继续直接显示；HTML 转义保留 |
| `tests/test_v4_operational_prompts.py` | 四处旧格式断言定向更新（详见 §3）；研究合同、空名单、来源边界、历史材料测试未动 |
| `tests/test_recommendation_readability.py` | 新建：辅助函数折叠/展开/转义 3 项、真实 `reviewBody` 两分支 2 项、`extract_daily_statement` 三段提取 1 项 |
| 本地 Obsidian（不入 Git） | 新增 `10_方法与范文/推荐说明范文/`（00_阅读指南 + 裕同候选 draft）与 `改稿对照/推荐说明/裕同减负对照`；`00_已确认写作要点` 分类映射增加本类一行 |

未改：四个专业 Skill、选股阈值与 schema、current_opportunity/D20 合同、采集/调度/数据库、公司介绍方法、历史 trace/CSV/JSON/Markdown、`tools/render_monitor_web.py`（保留为共享 payload 与提取模块）。

## 2. 裕同候选核对（本地原档）

- 身份确认：formation 2026-09-09、action 2026-09-10、as_of 2026-09-09T18:30:00+08:00（daily-research-2026-09-09.md / 同日 trace / CSV 第112行，selected、优先级1）。
- 候选稿全部数字与原档一致（9.59→约9.6、4.26→约4.3、3.59→约3.6、27.81/28.18/29.13、1.50→1.5、21/46、+0.23%/+1.10%、-1.50%/-3.54%）；原条件组合与价位未变。
- 价位出处：28.18 见于原 trace（8次）；**27.53 未在原 trace/CSV 出现**——出处未保存，已按执行包要求在知识库候选与对照中注明缺口，不编造解释。
- 板块型小练习（百亚股份，原行动日 2026-09-09）已做，仅留 `local_archive/review_trials/recommendation-readability-2026-09-10.md`；公司事件型如实说明缺口（最近一例阳光股份 09-02 的日报原文未保留），待下次真实事件型推荐直接按新格式执行。

## 3. 测试与验证（真实结果）

```text
pytest tests/test_recommendation_readability.py tests/test_v4_operational_prompts.py
       tests/test_render_monitor_web.py tests/test_prism_web_contract.py  → 97 passed
node --check tools/guanlan-prism/src/app.js                                → 通过
git diff --check                                                          → 干净
```

- 旧格式断言更新点：三处测试不再要求五栏目/2—4句/350—650字/阶段措辞存在，改为断言新三入口、旧门槛"不存在"、教学文件存在；`recommendation_headings` 期望改为新三标题；固定研究包中的历史样稿断言保持原样。
- 浏览器验证（真实页面，本地临时服务+预览页，`--out`+`--no-publish` 不改固定入口）：百亚股份"当初为什么选它"页——全文逐字保留；风险摘录默认折叠为"原始风险摘录（展开核对）"；点击后 `details.open=true` 且风险全文可读。无全文场景的展开显示由单测覆盖（真实 `reviewBody` 两分支用例）。
- 未执行：全仓 1250 项回归（本轮无引擎合同改动，按执行单不默认重跑）。

## 4. 生效方式与未验证项

- 新表达格式自下一次真实晚间任务的首次推荐说明生效；历史日报与旧页面不重写，旧文章在新页面仍为旧文（仅追加风险默认折叠）。
- 裕同候选稿为 **draft，待用户确认**后改 approved 并更新指南索引；本类暂无 approved 范文，日常写作按仓库教学文件执行。
- 真实定时任务对新 Prompt 的实际采用未观察（以 B 阶段观察为准）；本次代码提交不等于模型已在真实任务使用新格式。
