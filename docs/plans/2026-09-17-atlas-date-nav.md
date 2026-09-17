# 观察星图日期回看 · 执行提示（2026-09-17）

## 目标

A2 主用页「观察星图」新增按交易日回看能力：用户可在页面右上角（原「收盘快照」徽标位置）用 `◀ ▶` 逐交易日步进、点日期开日历弹层选任意内嵌交易日，星图与右侧详情面板按所选日期整体重算。解决「第一批记录满 20 个交易日后从图上消失、无法回头翻看」的问题——观察期内任意一天都可翻回。

## 用户已确认的定稿决策

1. 日期选择器＝**日历弹层**（仅内嵌交易日可选，非交易日置灰，最新日白框标记）。
2. **不做**「显示已结案」开关；**不显示**已出观察期（第 > 20 个交易日）记录的后续走势。星图在任何视图日期只显示「当时在场且仍在观察期内（第 1—20 天）」的记录；已满 20 日的记录不再出现在图上，翻回其观察期内的日期即可再看。
3. 交互形态（设计稿 demo-map-date-nav.html 已确认）：最新态＝现有白色「收盘快照」徽标 + 箭头；回看态＝琥珀色「回看」徽标 + 「回到最新」按钮 + 图表左上角水印「回看 YYYY-MM-DD · 非最新快照」；键盘 `← →` 步进、`Esc` 关日历。

## 代码事实（已核对）

- 星图全部逻辑在 `tools/guanlan-prism/concept-a/overview-a2-shell.html` 内联脚本：`atlasPage`（~608 行）、`atlasGroups/atlasGroupClose/atlasPlottable/atlasBasis/atlasRecordPoint/atlasBadge/atlasRange/atlasData`（517—575 行）、`groupPanel/recordPanel/mapPanelContent/updateMapMeta/drawAtlas`（604—780 行）。
- 所有点位计算硬编码 `const i = indexOfDate(DATA.analysis_date)`；`SESSIONS=resolveDates(DATA)`、`LAST`、`indexOfDate`（365—367 行）。
- 复盘观点已按日期组织：`orderedReviews(s,date)`（373 行）过滤 `r.date<=date`；`latest(s)` 默认 `DATA.analysis_date`。
- 记录字段：`recDate`（ISO）、`recIndex`（recDate 在 SESSIONS 的下标）、`ref`、`d0`、`days`、`candles`（与 SESSIONS 对齐，`[3]`=收盘、`[4]`=成交额亿元）、`reviews[]`（含 `date`/`as_of`）。
- 快照 JSON（`<script id="snapshot">`）顶层含 `sessionDates`（当前 33 个交易日，2026-08-03→09-16，起点＝最早行动日−20 天）、`analysis_date`、`as_of`。
- 部分辅助函数被总览工作台页共用：`closeOnDate/returnOnDate/daysAt/latest/isInvalid/opinionLabel/opinionCode`。总览页行为不得变化。
- `tests/test_prism_a2_preview.py::test_render_embeds_snapshot_verbatim_and_replaces_template_only_once` 用 token 列表锁定模板内容（84 行）。
- 正式渲染入口 `tools/render_prism_web.py`（用仓库 `.venv`，`PYTHONPATH=src`），产出 `local_archive/forward_monitor/prism-a2-report-<date>.html` 并发布 `style-preview/prism-a2.html`。渲染管线、数据合同、快照 schema 均不需要改动。

## 实施步骤

S1 备份：`cp concept-a/overview-a2-shell.html → overview-a2-shell.html.backup-before-date-nav.html`（.gitignore 已覆盖 `*.backup-*.html`）。

S2 参数化「时点」：为上述共用辅助函数加可选日期参数（默认 `DATA.analysis_date`，总览页零变化）：`latest(s,date)`、`isInvalid(s,date)`、`opinionLabel(s,date)`、`opinionCode(s,date)`、`closeOnDate(s,date)`、`returnOnDate(s,date)`、`daysAt(s,date)`。星图族函数（`atlasGroupClose/atlasPlottable/atlasBasis/atlasRecordPoint`）把内部 `indexOfDate(DATA.analysis_date)` 改为传入的视图日下标 `iV`。

S3 视图日状态：`state` 增加 `mapDate:null`（null＝最新）。派生 `atlasAsOf()` → `{date,iV,review:boolean}`：null 时 `{DATA.analysis_date,indexOfDate(…),false}`，否则取 `indexOfDate(state.mapDate)`。日期步进＝在 `SESSIONS` 中移动下标，到边界禁用按钮；日历弹层按 `SESSIONS` 集合标记可选日。

S4 在场与窗口过滤（`atlasData` 以视图日为准）：
- 记录「在场」＝ `recDate <= 视图日`（等价 `recIndex <= iV`）。
- 在场且 `d0`（首观察日未到）→ 进「暂未绘制」名单，理由沿用「待首日观察」。
- `day = iV - recIndex + 1`；`day > OBS_DAYS`（20）→ 已出观察期，不显示、不进暂未绘制，仅在统计行计数。
- 可绘性沿用 `atlasPlottable`（改为 iV）：缺参考价 / 视图日无真实收盘 → 暂未绘制。
- 股票视角 anchor＝该股在场记录中最早一条（与现状一致：组只要在场，全局最早记录必然 ≤ 视图日）；badge 与右侧「全部入选明细」只列在场记录。

S5 UI 与交互：
- `atlasPage()` 页头右侧替换为日期导航：`◀ [📅 收盘快照 09.16 周三] ▶`＋状态行（最新态显示 as_of；回看态琥珀色、显示「回看 YYYY-MM-DD · 原快照数据截至 …」＋「回到最新」按钮）。
- 日历弹层：覆盖 `SESSIONS[0]` 至最新的月份网格，仅交易日可选；`Esc`／点空白关闭；选中高亮、最新日白框。
- 图表回看水印（琥珀小字，绘图区左上）；统计行改为「截至 YYYY-MM-DD · N只股票 · M条在场（观察期内）· Z条有坐标 · K条暂未绘制 · J条已满20日未显示（J>0 时）」。
- 悬停明细「第 N 天 / 较参考价 / 当日成交额」按视图日取值；右侧面板（groupPanel/recordPanel）的观察进度、收盘、成交额、观点（`orderedReviews(s,视图日)` 最新一篇）全部按视图日。
- 键盘 `← →` 在星图页步进（无输入焦点时）；模式切换保留所选日期；切换日期保留当前选中（记录在新日期不在场时面板走既有空态）。
- 窄屏（≤720px）：日期导航保持可见可换行（现 `.report-meta` 在窄屏隐藏的规则不得连带隐藏导航）；弹层宽度自适应。
- 样式沿用页面 CSS 变量与既有控件形态（segmented/border/mono），不新增配色（琥珀仅用于回看态，页面已有 `--amber`）。

S6 文档与测试：
- `docs/06-修改记录.md` 置顶新条目（含回退备份名）。
- `tests/test_prism_a2_preview.py` token 列表增加 `'dateNav'`、`'回到最新'`。
- 重跑 `node --check`（抽出内联脚本）与该测试文件全部用例。

S7 渲染与验收：`PYTHONPATH=src .venv/bin/python tools/render_prism_web.py` 重出页面；浏览器实测：
- 最新视图与改前逐点一致（回归）；
- 步进/日历选日至 `2026-09-14`，与归档 `prism-a2-report-2026-09-14.html` 的星图对照（在场记录、第 N 天、较参考价涨跌应一致——两页共用冻结行情）；
- 边界：最早日空态、「回到最新」、模式切换、悬停、暂未绘制点击；
- 总览工作台页无任何变化。

## 验收标准

- 上述浏览器验收全过；`pytest tests/test_prism_a2_preview.py` 全绿；`node --check` 通过；渲染输出包含新控件且无 `mapDate` 前的旧行为残留。
- 不改任何 Python 渲染逻辑、数据合同、冻结归档；总览页零变化。

## 范围外（明确不做）

- 内嵌窗口（33 个交易日）更早日期的回看（需加长渲染窗口，另议）。
- 已出观察期记录的走势显示或开关（用户已否）。
- 总览工作台页的日期回看；停更备用 A 页同步。
- demo 设计稿文件清理（保留作设计记录）。

## 风险与回退

- 风险集中在共用辅助函数参数化遗漏（总览页回归）——以「默认参数＝原值」控制，验收含总览页对照。
- 回退＝复制 S1 备份回原名并重跑渲染；模板改动前与 git HEAD 一致，也可 `git checkout`。

## 审查修订（2026-09-17 独立子智能体审查结论：通过（以修订版为准），已并入）

1. S4 在场口径统一为 `recIndex <= iV`（d0 条目 recIndex=LAST、recDate 为次日且不在 SESSIONS，按 recDate 口径会连最新视图都不在场）。
2. S7 渲染前先把 `prism-a2-report-2026-09-16.html` 与 `style-preview/prism-a2.html` 复制到 /tmp 作改前对照，验收后删除。
3. 修改记录路径为 `tools/guanlan-prism/docs/06-修改记录.md`。
4. 窄屏断点实为 `@media(max-width:980px)`（壳模板 266 行）隐藏 `.report-meta`；日期导航用独立 class `dateNav` 不受影响，按 ≤980px 验收。
5. 「在场子集」消费点补全：groupPanel 全部入选明细、「最新一次」块、sel-since 行、atlasBadge 均基于子集。
6. `isInvalid(s,date)` 回看态只按 `orderedReviews(s,视图日)` 推导，不读 `s.invalidated`/`s.stage`；`opinionTagClass` 一并参数化。
7. 键盘 ←/→ 条件：`state.page==='map'`、无输入焦点、详情 dialog 未开、日历未开；Esc 与原生 dialog 共存。
8. token `'dateNav'` 用作容器真实 class。
9. 数据边界说明：记录第 31 个交易日后被上游剔除、SESSIONS 起点随最早行动日滚动，回看仅对仍在内嵌窗口与快照中的记录成立。
