# ChatGPT审阅结论

## 结论

**通过，带三项边界修正。**

## 用户批准原文

> 同意按 ChatGPT 审阅后的最小清单执行。只做四个现有方法文件的小改，并先修正三处审计表述边界；继续采用公告正文定向人工/ChatGPT取证，不修改公告客户端，不建设平台。

## 批准修改的4个方法文件

- `.agents/skills/industry-research-stage-b/SKILL.md`
- `.agents/skills/industry-research-stage-c/SKILL.md`
- `docs/industry-research/00_逐步执行操作手册.md`
- `docs/industry-research/01_全局执行规范.md`

## 先修正的审计边界

1. 飞荣达 `B2G008` 的报告期为2026Q1，正式零值证据属于2025年报；不得把2026Q1本地null写成 `true_zero`。跨期文件只能支持字段含义、列报方式或会计语义。
2. `not_applicable` 只是当前计算不适用，不是永久删除。同飞股份主题财务以及佳力图、荣亿精密PE都必须记录 `reopen_condition`，并继续按 `review_due` 复核。
3. 四种计算准备状态只约束 `calculation_scope`，不构成公司级数值授权。B3必须同时给出 `allowed_numeric_fields`、`must_remain_unknown`、`readiness_reason` 和适用的 `reopen_condition`。

## 允许同步的关键行为

- B1关键问题固定最好证据、最低可用证据、是否允许替代和缺失后果。
- 营运资金拆成基础项和可选综合项；综合项不完整不丢弃基础项。
- B3只使用 `direct_calculable`、`range_calculable`、`condition_only`、`not_applicable`。
- C1/C2只对直接值和正式范围建立数值请求；条件项不生成三套空表。
- 亏损PE按单项指标不适用，不影响PS、PB和经营事实。
- 行业相对收益和固定长窗口估值保持可选、非阻断。

## 明确排除

不修改公告客户端或建设正文下载体系；不修改本地财务数据、`src`、`tests`、schema、运行模板、历史研究产物、定时任务、D1监控基线、五个股票研究Skill、Forward CSV、D20口径或价格场景；不启动液冷专项回归或AI十二方向研究。

## 回归验收底线

跨期证据不得证明本期数值；`not_applicable` 必须可重开；未列入 `allowed_numeric_fields` 的字段不得计算；`condition_only` 不得产生三套全空数值情景。
