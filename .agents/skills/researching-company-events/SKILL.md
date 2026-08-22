---
name: researching-company-events
description: Use when an A-share research task needs point-in-time company fundamentals, business transmission, corporate events, announcements, company-specific counterevidence, or candidate discovery and validation before an action date.
---

# 公司与事件研究

## A股短周期发动机 V4 最终合同（优先级最高）

每个主要事件保存预告、修正、快报、正式报告和更正披露链，并使用V4六类 `new_information_level`。正式报告数字大不等于新催化；`fresh_event_pending` 只允许收盘后首次且 `substantive_new` 的重大直接信息。


## 核心问题

判断形成日前公司发生了什么真实变化，变化能否传导到业务、收入、利润、现金流或市场预期，以及什么公司事实最可能推翻这条命题。

每次解释必须分开给出：`company_catalyst` 是形成日前的新变化及其可能引发的新增需求；`fundamental_anchor` 是业绩、估值、现金流、主营和资产负债对命题的支持边界；`company_risk` 是公司层反证。业绩增长、估值便宜、现金流良好或低位本身只能成为催化事实或基本面锚，不能单独证明“为什么是现在”，也不能替代短期上涨发动机和价格确认。

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

公告表中的链接或相对 `pdf_path` 只证明官方原文入口存在，不等于本地已有正文。

空值、非法时间、查询失败、覆盖不足和真实无记录是不同状态。历史公司概况或公告正文缺失时写“未知”，不得用当前信息倒推。

## 每日读取方式

发现第一轮只查形成日截止新增可见的结构化财务、业绩预告/快报、回购、减持、解禁和公告元数据，不扫描全部历史公告正文。共同验证时再只查总控给出的少量候选及直接相关事实，不把全量公司事实重复送入模型。

## 发现阶段

使用紧凑的公司、财务、业绩和事件事实寻找 0 个或多个线索。第一轮不得扫描全市场公告正文。

对每条线索依次回答：

1. 形成日前出现了什么新变化？
2. 在 `available_at <= as_of` 的同类历史披露中，它是 `first_disclosure | incremental_update | repeat_disclosure | history_insufficient` 哪一种？新增信息等级是 `major_new_information | material_increment | limited_increment | no_new_information | unknown` 哪一种，依据是哪条此前披露和本次新增事实？
3. 哪个事实证明公司确实涉及相关业务？
4. 变化如何可能传导到收入、利润、现金流或预期？
5. 它是新增催化，还是只提供基本面锚？若是催化，可能通过什么新增需求作用于股票？
6. 影响是否具有可辨认的规模、阶段和新鲜度？
7. 哪个事实最可能推翻传导？
8. 还需要板块传播和价格确认回答什么？

价格尚未启动不能删除公司线索。只有概念标签、关联词或公告标题时，不得声称直接受益。

“首次”只表示在形成日截止的本地可见历史中第一次披露同一经济事项，不表示公司历史上绝对首次；历史覆盖不足时必须用 `history_insufficient`。正式报告重复预告或快报中已知内容时属于 `repeat_disclosure`；只有金额、范围、阶段、条件或风险出现可辨认新增时才是 `incremental_update`，并按实际材料性给出新增信息等级。该等级不是分数，也不预测收益。

## 验证阶段

只研究总控给出的少量候选：

- 核对公司身份、主营和同一口径财务；
- 检查收入、利润与经营现金流是否相互支持；
- 核对事件阶段、条件、规模和可见时间；
- 只在这一轮共同验证中，对当前少量候选按需读取公告正文：本地只有标题和官方原链接，且金额、条件、阶段、业务材料性或风险提示可能改变取舍时，才可沿该原链接定向读取 `available_at <= as_of` 时已公开的官方原文；
- 检查减持、解禁、质押、回购阶段、负债、现金流恶化及其他反证；
- 给出公司视角下为什么可能优于同类，但把同类板块表现和价格可执行性交还其他 Skill。

验证外部变化命题时，不因没有当日新公司事件就单独降为 `insufficient`。使用形成日前已可见且仍能支持当前命题的主营、收入、利润、订单、客户、产能或其他公司事实验证传导；找不到真实业务联系或核心传导时，仍为 `insufficient`。

定向读取只允许一轮、只补当前候选；不得搜索替代来源、批量下载、补全公告库或借机扩展候选池。官方原文读取失败或无法确认截止时点时，只能确认公告存在、标题、来源和时间；合同金额、约束条件、风险提示和业务影响继续保持未知。

需要原文时，先确认元数据 `available_at <= as_of`，使用其 `pdf_path`；`www` 地址不可用时只切换到巨潮官方静态域名。下载到临时文件并校验 PDF，优先用 `pypdf`、必要时用 `pdfplumber` 提取本轮所需内容，然后删除临时文件。不缓存、不 OCR、不建全文库，不新增 Python helper 或依赖；失败时保持正文未知，不用新闻网站补写。

## 输出合同

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
    ts_code: ""
    company_catalyst: ""
    company_information_novelty:
      disclosure_novelty: first_disclosure | incremental_update | repeat_disclosure | history_insufficient | not_applicable
      new_information_level: major_new_information | material_increment | limited_increment | no_new_information | unknown | not_applicable
      basis: ""
      event_id: null
      event_available_at: null
    fundamental_anchor: ""
    company_risk: ""
    possible_demand_transmission: ""
    engine_question: ""
    strongest_counter_evidence: ""
    missing_evidence: []
questions_for_other_lenses: []
evidence_sufficiency: sufficient | partial | insufficient
```

本 Skill 的线索通常使用 `stock` 或 `question`。不得用行业方向或概念标签代替具体公司的业务与事件证据。

每个 `candidate_leads` 至少分开说明股票、公司催化、基本面锚、公司风险、可能的需求传导、发动机待验问题和待补证据。它不是推荐、排名或买入信号，公司材料更完整也不提高其跨类型优先级。

判定证据充分性：

- `sufficient`：历史时点、公司业务联系和传导均有直接事实，且已检查主要反证；
- `partial`：存在真实变化，但正文、规模、业务材料性或关键风险仍缺失；
- `insufficient`：只有标签、标题、传闻、无法确认的时间或无法建立传导。

## 禁止越界

- 不判断市场环境、板块领导和价格是否透支；
- 不输出目标价、买入条件、总分、权重或固定阈值；
- 不把回购计划当成已经完成，不把业绩预告当成正式报表；
- 不把业绩、估值、现金流、低位或公司材料完整度写成短期上涨发动机或价格确认；
- 不从新闻语气、标题或概念标签补写事实；
- 除验证阶段上述官方原链接定向读取外，不通过一般网页搜索或替代来源补证，不创建采集、财务指标或公告分析系统。

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
