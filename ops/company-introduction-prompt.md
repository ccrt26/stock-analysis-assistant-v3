# 公司介绍运行提示（晚间共同收尾调用）

本文由 `ops/forward-selection-prompt.md` 的"研究归档后的网页同步（共同收尾）"调用，写作方法以 `.agents/skills/writing-company-introductions/SKILL.md` 为准。这是正式推荐归档后的附属资料生成，不改变研究阶段，不重跑选股或复盘，不读取未来数据。

## 调用时机与范围

正式归档成功并完成第一次网页同步后执行。时间上下文沿用 selection prepare 返回并已在收尾使用的三个字段：`formation_date`、`action_date`、`selection_as_of`，逐字传递，不得改写。

先运行备料：

```bash
./.venv/bin/python -m stock_analyzer.ops.company_introduction prepare \
  --formation-date <formation_date> \
  --action-date <action_date> \
  --as-of <selection_as_of> \
  --output <临时目录>/intro-facts-<formation_date>.json
```

- 备料把本轮输出写入临时 facts-file，供写作和 record 核对，可被本轮数篇文章共用；它不是第二份正文或永久证据库。
- `scope` 中 `intro_status` 为 `missing` 的股票才需要写作；`reusable` 直接复用，不改写、不更新 `generated_at`。
- 名单为空、只有条件事件或比较记录时，不调用写作，直接回到收尾；不补位。
- 本地数据缺失、查询失败或 `warehouse_unavailable` 不等于介绍失败：只要 prepare 已返回可核对的正式 context/scope，就按 Skill 主动去 WEB 取得关键官方原文。blocks 为空也可在证据足够后引用 official_document 保存，不能捏造 warehouse 来源。
- prepare 命令本身失败时，先按错误检查参数、原 trace 路径和现有运行环境，完成有依据的调用修正；不直接放弃，也不自动维护或修复事实仓。原 trace 缺失、研究未完成或身份/时间矛盾不能靠 WEB 代造，更不能手写 formal facts-file 绕过 prepare。仍无法取得有效备料上下文时才保留缺项、说明具体错误并回到原收尾。

## 逐只写作（按 scope 顺序）

对每只 `missing` 股票：

1. 读取该股在 facts-file 中的 blocks、computed、gaps，先形成对核心生意与盈利来源的认识，列出影响理解的待核问题；本地数据不为空也可能需要业务原文。初次写作或初稿像摘要时，按 Skill 读取写作对照参考。
2. 以原截止前最新可用报告为起点，对关键缺口主动定向 WEB 补证。已有链接 404、接口不支持或工具读取失败时，按 Skill 换官方检索/API、静态文档入口、交易所/公司官网或已有读取工具。不限“一次补读”，有有效线索就继续；资料足够或合理路径仍无结果时停止该项。实际失败方法留临时工作记录，不写进正文。
3. 核对文档公司、报告期、版本和历史公开时间；外部事实存入文章官方 sources，保留定位、公开时间依据、实际取得时间及关键原值。数字用既有计算或临时 Python 核算，不改原 facts-file，不把外部事实伪装成本地行。
4. 按 Skill 逐篇写单篇 JSON（`schema_version=company-introduction-v1`），身份字段逐字使用 facts-file context 的值；`generated_at` 用当前上海时间。表头逐列清楚，正文解释经营含义，技术问题留工作记录。沿用 sections/sources/limitations，无需增加 schema 或输出状态。
5. 完成 Skill 的逐篇自检，尤其核对增长归因、正文与限制的一致性、未核实断言和原截止；修正文后保存临时文件并运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.company_introduction record \
  --intro-file <临时目录>/intro-<ts_code>.json \
  --facts-file <临时目录>/intro-facts-<formation_date>.json
```

- 返回 `recorded` 记为本轮新增；`already_exists` 视为已有复用，不算新增。
- record 报错时按错误定位修正一次再试；仍失败则该篇保留缺项，继续下一只，不循环重试。这是保存命令的失败处理，不限制写作前定向寻找证据的方法或次数。
- 身份已核实但核心业务认识不足时先完成必要官方补证；合理路径仍不能建立核心认识才保留该只缺项，不以空洞全文交差。非核心未知可省略或准确说明，不要求凑栏目。
- 程序或网络问题导致一只失败不影响其他股票；任何失败都不撤销推荐、不阻断网页同步。

## 收尾与第二次同步

全部股票处理完后统计：本轮是否新增保存了介绍（`recorded`），以及第一次网页同步是否失败。满足任一条件，就用与第一次完全相同的三参数同步命令再同步一次；两个条件都不满足则不再同步。第二次同步失败不循环重试：研究和已保存介绍都保留，后续只需重新执行同一同步命令。

对外报告按晚间 Prompt 的唯一格式输出；介绍相关内容不进入正式推荐正文。仅当确有缺项时，在报告末尾追加一行实际情况，例如："网页已更新；甲公司的完整公司介绍暂缺：官方业务资料未能取得。"介绍全部成功或全部复用时，不追加说明。
