# 普通详评（深度复盘）四点标准历史回填方案

**创建：** 2026-09-06 ｜ **状态：** 已执行完成（2026-09-06 审查通过修订版；31篇全部落盘，WEB已刷新，257项测试通过）
**执行模型要求：** 逐篇真实撰写，禁止模板拼接；小批量推进，逐批自检（AGENTS.md 既有纪律）

## 0. 目标与边界

把 2026-08-21 以来各期 monitor-report 中**普通详评（regular_detail，即"今日深入复盘"）**的正文，按 2026-09-06 已批准并已入库的四点合同重写：①为什么是它；②原推荐理由更强还是更弱、伤在哪一环；③目标余程＋现实评估＋最大障碍；④接下来盯什么（判断收束，非预设验证条件）。文风按 `ops/forward-monitor-prompt.md` 文风基准与两个已入库范例。

**不动：** 节点详评正文（已按六项标准完成）、简评正文、全部结构化字段、账本 JSON、快照 JSON、股票集合与三路分组、报告 JSON 结构、程序代码、测试。**两篇例外：09-04 奥克股份、09-04 中国广核正文＝已入库范例本身，保持原样不重写。**

## 1. 范围盘点（已核实）

| 日期 | 普通详评数 | 明细（代码 股票 D几 / view_change） |
|---|---|---|
| 08-21 | 0 | —（当日无普通详评，跳过） |
| 08-24 | 1 | 300832 新产业 D2/unchanged |
| 08-26 | 2 | 601998 中信银行 D2/unchanged；603969 银龙股份 D4/weakened |
| 08-27 | 2 | 002274 华昌化工 D2/unchanged；300473 德尔股份 D2/unchanged |
| 08-28 | 3 | 601998 中信银行 D4/weakened；300082 奥克股份 D2/weakened；300832 新产业 D6/unchanged |
| 08-31 | 3 | 000801 四川九洲 D2/strengthened；003816 中国广核 D2/unchanged；300832 新产业 D7/unchanged |
| 09-01 | 3 | 600583 海油工程 D7/strengthened；601998 中信银行 D6/strengthened；300107 建新股份 D4/strengthened |
| 09-02 | 5 | 600583 海油工程 D8/weakened；002274 华昌化工 D6/unchanged(stop)；002440 闰土股份 D2/weakened；300170 汉得信息 D2/weakened；300832 新产业 D9/unchanged(stop) |
| 09-03 | 6 | 600980 北矿科技 D9/invalidated(stop)；601998 中信银行 D8/weakened；300107 建新股份 D6/weakened；301289 国缆检测 D6/invalidated(stop)；002430 杭氧股份 D4/strengthened；300910 瑞丰新材 D4/weakened |
| 09-04 | 8→6重写 | 德尔股份 D8、金岭矿业 D6、闰土股份 D4、汉得信息 D4、中航西飞 D2、银龙股份 D11 重写；奥克股份、中国广核保持原样 |

**合计：重写 31 篇，覆盖 10 个日期。** 现状：除 09-04 的 6 篇为完整正文外，其余 25 篇均为 50—134 字短摘要桩。

## 2. 每篇写作输入与硬性要求

- **输入（全部已存在，只读）：** 当日 `snapshot-<date>.json` 对应 episode（原推荐理由/反证、review_context 固定口径价格事实、相对市场与行业窗口、公告、量价字段）、`daily-formal-reviews-<date>.json` 结构化判断（view_change 及原因、outlook、current_assessment、tracking_decision）、报告 alert 的 why_reported 与四路变化字段。
- **硬性要求：** 第一句＝一句话观点更新且直接回应当日入选原因；②定位到行业带动/股票自身相对强度/公司侧/价格量能的具体一环；③使用 `price_levels.remaining_return_to_target` 与剩余交易日数，现实评估用五种既定表述之一；④判断收束；与账本结构化判断零矛盾；每个数字可追溯到当日快照/报告字段；各篇开头句互不相同；D2 短历史不虚构数日叙事；无增量时按"没新闻体检"写并明说；固定标签词（核心预期/当前阶段/最有证据的解释/行业扩散等）禁用。

## 3. 实施机制（沿用 restore-node-bodies 先例）

1. **备份：** 改动前把 10 期 `monitor-report-*.json/.md` 复制到 `local_archive/review_format_acceptance/2026-09-06-regular-detail-four-point/backup/`。
2. **逐批撰写：** 9 批＝9 个日期（08-24 → 08-26 → 08-27 → 08-28 → 08-31 → 09-01 → 09-02 → 09-03 → 09-04），每批先写 `bodies-<date>.json`（episode_id → 正文），人写不拼模板。
3. **落盘脚本（每批同一流程）：** 加载报告 V2 模型 → 仅替换目标 episode_review 的 `current_review` → `model_validate` 往返校验 → 复用 `_three_route_grouping`＋`_validate_regular_detail_priority`＋`_validate_detailed_review_priority` 校验分组未变 → `_atomic_write_json` 写 JSON → `_render_markdown(report, snapshot, daily_ledger)` 渲染并原子写 MD。（不走 record 命令：已存在文件会触发 report_conflict，先例即直接写文件。）
4. **逐批自检：** JSON 与备份 diff 确认仅 current_review 变化；MD 含新正文；逐篇核对四点、开头句差异、数字可追溯、与账本一致。
5. **收尾：** 全部完成后运行 `tools/update_monitor_web.py` 重建 index.html；抽查 payload 中 31 篇 copy 与新正文一致。

## 4. 验收标准

1. 31 篇正文全部重写为四点标准；09-04 两篇范例原样未动；
2. 每批 JSON diff 仅 current_review 字段变化；分组/结构校验通过；
3. 既有测试不回归（`pytest tests/test_forward_monitor.py tests/test_render_monitor_web.py -q`）；
4. index.html 中 31 篇与 bodies 文件一致；
5. 全程未动账本、快照、代码、schema、定时任务。

## 5. 回滚

用 backup 目录整体还原 10 期 JSON/MD，再重跑 update_monitor_web。
