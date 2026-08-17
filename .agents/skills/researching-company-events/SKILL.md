---
name: researching-company-events
description: Use when an A-share research task needs point-in-time company fundamentals, business transmission, corporate events, announcements, company-specific counterevidence, or candidate discovery and validation before an action date.
---

# 公司与事件研究

## 核心问题

判断形成日前公司发生了什么真实变化，变化能否传导到业务、收入、利润、现金流或市场预期，以及什么公司事实最可能推翻这条命题。

自主发现时，从公司自身变化寻找线索；验证总控随板块或价格候选提交的待验外部变化命题时，把该命题作为输入，只核对公司真实业务联系、传导、材料性和公司反证。价格异动本身不是外部经营变化，板块动力和价格解释仍交回对应 Skill。

只形成公司视角的候选线索和验证意见，不作买入结论。

本 Skill 只负责单家公司的身份、业务变化、事件阶段、财务影响和因果传导。市场分布、板块扩散和个股量价可执行性分别交给对应 Skill。

## 输入要求

必须取得总控提供的：

- `phase`：`discovery` 或 `validation`；
- `formation_date`、`action_date`、`as_of`；
- 股票范围或待验证候选；
- 本轮公司问题和未知条件。

缺少带时区的 `as_of` 时停止。只使用 `available_at <= as_of` 的历史版本；等于可用，晚于排除。

## 证据边界

按问题选择公告、利润表、资产负债表、现金流、财务指标、主营、业绩预告、业绩快报、股东交易、解禁、回购、质押和公司概况。不要为了完整感全部读取。

区分：

- 提议、计划、批准、实施和完成；
- 经营目标、预算或管理层展望不得当作业绩预告；区分业绩预告及其修正、业绩快报和正式报告；结构化分类与可见原文语义冲突时，以原文语义为准并说明冲突；
- 公告标题、正文和链接；
- 事件发生时间、报告期和 `available_at`；
- 当前版本和形成日可见版本。

空值、非法时间、查询失败、覆盖不足和真实无记录是不同状态。历史公司概况或公告正文缺失时写“未知”，不得用当前信息倒推。

## 发现阶段

使用紧凑的公司、财务、业绩和事件事实寻找 0 个或多个线索。第一轮不得扫描全市场公告正文。

对每条线索依次回答：

1. 形成日前出现了什么新变化？
2. 哪个事实证明公司确实涉及相关业务？
3. 变化如何可能传导到收入、利润、现金流或预期？
4. 影响是否具有可辨认的规模、阶段和新鲜度？
5. 哪个事实最可能推翻传导？
6. 还需要市场、板块或价格视角回答什么？

价格尚未启动不能删除公司线索。只有概念标签、关联词或公告标题时，不得声称直接受益。

## 验证阶段

只研究总控给出的少量候选：

- 核对公司身份、主营和同一口径财务；
- 检查收入、利润与经营现金流是否相互支持；
- 核对事件阶段、条件、规模和可见时间；
- 按需读取候选公告正文；
- 检查减持、解禁、质押、回购阶段、负债、现金流恶化及其他反证；
- 给出公司视角下为什么可能优于同类，但把同类板块表现和价格可执行性交还其他 Skill。

验证外部变化命题时，不因没有当日新公司事件就单独降为 `insufficient`。使用形成日前已可见且仍能支持当前命题的主营、收入、利润、订单、客户、产能或其他公司事实验证传导；找不到真实业务联系或核心传导时，仍为 `insufficient`。

正文不存在时，只能确认公告存在、标题、来源和时间。合同金额、约束条件、风险提示和业务影响均为未知。

## 输出合同

候选使用统一机会类型词汇 `company_catalyst | sector_diffusion | independent_price_anomaly | null`。本 Skill 主要负责 `company_catalyst`：没有形成日可见的直接公司事实时不得归入该类型，而不只是降低置信度。对 `sector_diffusion` 和 `independent_price_anomaly`，本 Skill 验证公司身份、主营联系、核心传导和重大公司反证；没有当日新公司公告本身不构成淘汰理由，也不得把“没有新变化”写成“公司不相关”。

机会类型不是 Gate、配额、评分、优先级、投票或补位规则。它不改变公司证据充分性判断，也不让公司视角成为所有类型的前置门槛。

每条关键事实同时保留统一的数据质量信息。`fact_as_of` 表示事件发生日、报告期或事实对应期间，`available_at` 表示系统何时能够取得；两者不得互换。顶层 `as_of` 仍是本轮形成日决策截止时点。`quality` 使用 `complete | partial | unreliable`，`capability_status` 使用 `supported | partial | unsupported`。正文缺失、历史覆盖不足、查询失败、只有当前快照和真实无记录必须分开写入 `missing_fields` 或 `unknowns`。这些字段只解释证据边界，不计分或投票；无法确认形成日前可得的事实不能支持候选命题。

严格返回：

```yaml
phase: discovery | validation
facts: [{claim, value, provider, dataset, fact_as_of, available_at, quality, missing_fields, capability_status}]
primary_interpretation: ""
alternative_interpretations: []
supporting_evidence: []
strongest_counter_evidence: ""
unknowns: []
candidate_leads:
  - lead_type: direction | group | stock | question
    name: ""
    rationale: ""
    missing_evidence: []
questions_for_other_lenses: []
evidence_sufficiency: sufficient | partial | insufficient
```

本 Skill 的线索通常使用 `stock` 或 `question`。不得用行业方向或概念标签代替具体公司的业务与事件证据。

每个 `candidate_leads` 至少说明股票、公司变化、可能传导、现有支持、最强反证和待补证据。它不是推荐、排名或买入信号。

判定证据充分性：

- `sufficient`：历史时点、公司业务联系和传导均有直接事实，且已检查主要反证；
- `partial`：存在真实变化，但正文、规模、业务材料性或关键风险仍缺失；
- `insufficient`：只有标签、标题、传闻、无法确认的时间或无法建立传导。

## 禁止越界

- 不判断市场环境、板块领导和价格是否透支；
- 不输出目标价、买入条件、总分、权重或固定阈值；
- 不把回购计划当成已经完成，不把业绩预告当成正式报表；
- 不从新闻语气、标题或概念标签补写事实；
- 不联网补证，不创建采集、财务指标或公告分析系统。

## 快速自检

- 每项关键事实是否满足截止时间并可追溯？
- 是否证明“公司真实涉及”，而不只是“行业听起来相关”？
- 是否写清变化的阶段和传导，而不只是复述公告？
- 是否把利润增长与现金流、负债等反证一起检查？
- 正文或历史概况缺失时是否明确未知？
- 是否把公司强误写成可以买？

任一项不满足时降低证据充分性，不得补猜。

## 典型冲突

净利润增长但经营现金流明显恶化时，把利润改善作为支持，把现金流恶化作为强反证或备选解释；不要用一个数字覆盖另一个。公司事件很强但市场、板块和价格未知时，只提交候选线索并请求其他视角验证。
