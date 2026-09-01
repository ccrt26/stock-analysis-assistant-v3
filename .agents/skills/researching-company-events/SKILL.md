---
name: researching-company-events
description: Use when A-share candidate discovery, validation, or post-selection review needs point-in-time company fundamentals, business transmission, corporate events, announcements, or company-specific counterevidence.
---

# 公司与事件研究

## A股短周期发动机 V4 最终合同（优先级最高）

每个主要事件保存预告、修正、快报、正式报告和更正披露链，并使用V4六类 `new_information_level`。正式报告数字大不等于新催化；`fresh_event_pending` 只允许收盘后首次且 `substantive_new` 的重大直接信息。

## 唯一职责和固定传导顺序

公司 Skill 独占披露链、法律或业务阶段、主营联系、材料性、收入/利润/现金流传导、兑现时间和失败条款。固定顺序是：新增性 → 阶段 → 主营联系 → 材料性 → 财务传导 → 兑现时间 → 失败条款。

- 新增性先区分首次、实质增量、重复确认和历史不足，不能因文件更完整就写成新催化。
- 阶段必须区分意向、公告、获批、中标、签约、生效、履约和确认收入等实际状态；不得把中标通知、框架协议或远期交付直接等同当期利润。
- 主营联系和材料性必须分别证明；概念相关、客户匿名、规模口径不明或非经常性只能保留对应未知。
- 财务传导必须写清收入、利润与现金流中哪些会受影响，兑现时间落在哪个期间，以及哪些终止、审批、交付、回款或客户条件会使传导失败。

本 Skill 不宣布价格接受、可靠入口或最终推荐。真实且重大的公司事件可以提交线索；是否已有市场识别、是否仍有路径以及能否正式选择，必须交给价格 Skill 和总控。


## 核心问题

判断形成日前公司发生了什么真实变化，变化能否传导到业务、收入、利润、现金流或市场预期，以及什么公司事实最可能推翻这条命题。

每次解释必须分开给出：`company_catalyst` 是形成日前的新变化及其可能引发的新增需求；`fundamental_anchor` 是业绩、估值、现金流、主营和资产负债对命题的支持边界；`company_risk` 是公司层反证。业绩增长、估值便宜、现金流良好或低位本身只能成为催化事实或基本面锚，不能单独证明“为什么是现在”，也不能替代短期上涨发动机和价格确认。

自主发现时，从公司自身变化寻找线索；验证总控随板块或价格候选提交的待验外部变化命题时，把该命题作为输入，只核对公司真实业务联系、传导、材料性和公司反证。价格异动本身不是外部经营变化，板块动力和价格解释仍交回对应 Skill。

只形成公司视角的候选线索和验证意见，不作买入结论。

本 Skill 只负责单家公司的身份、业务变化、事件阶段、财务影响和因果传导。市场分布、板块扩散和个股量价可执行性分别交给对应 Skill。

## 输入要求

必须取得总控提供的：

- `phase`：`discovery`、`validation` 或 `review`；
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

对每条线索严格按固定传导顺序依次回答：

1. 形成日前出现了什么新变化？
2. 在 `available_at <= as_of` 的披露链中，它是 `first | repeat | unknown | not_applicable` 哪一种？V4 新增信息等级是 `substantive_new | incremental_detail | confirmation_only | repeat_or_no_new_information | not_applicable | unknown` 哪一种，依据是哪条此前披露和本次新增事实？
3. 哪个事实证明公司确实涉及相关业务？
4. 当前法律或业务阶段是什么，离签约、生效、交付、回款或收入确认还有哪些条件？
5. 材料性是否有可解释的金额、产能、客户、订单或经营口径，而不是只有形容词？
6. 变化如何可能传导到收入、利润和经营现金流；三者不一致时哪个反证最重要？
7. 兑现可能落在哪个期间，是否远于本轮约 20 个交易日目标？
8. 哪项终止、审批、履约、回款、客户或会计确认条款最可能使传导失败？
9. 它是新增催化，还是只提供基本面锚；还需要板块传播和价格确认回答什么？

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

## 最终名单的公司介绍补充

当总控已经冻结正式名单并只要求对外解释时，本 Skill 可以对最终入选股票补充一段简明公司介绍。这个动作只服务于用户理解，不属于再次发现或验证，不得改变候选、排序、发动机、价格判断或形成日结论。

只使用现有本地 `company_profile`、`main_business` 和形成日已经使用的公司事实，回答两件事：

1. 公司主要卖什么产品或提供什么服务，客户或应用场景是什么；
2. 本次推荐所依赖的板块、事件或价格需求，对应公司哪一块真实业务。

介绍控制在80—150个中文字，不写公司沿革、注册地址、管理层履历和无关概念标签。没有新公司事件的价格型候选，要明确说“本次入选不依赖新的公司公告，公司业务和财务只作为经营背景”。

资料缺失和公司风险必须分开。没有取得中报三表、公告正文或主营细分，只能写“暂时无法完整核实”，不能写成公司经营一定恶化；利润下降、现金流恶化、合同兑现周期长等已知事实才属于公司风险。

公司介绍不能被总控当成新的入选理由，也不能因为某家公司介绍更完整就提高优先级。

## Review 阶段

`phase: review` 只复盘已有记录，不重新推荐股票。必须分别写清“公司事实现在怎么看”和“股价对这件事有没有实际反应”：核对当时事件或经营变化是否仍是真实事实，后续公告属于新增、重复确认、修正还是相反变化，原先的业务传导后来是否得到正式事实支持，以及哪个公司事实最可能推翻原判断。

股价下跌不能否定公告事实本身，公告真实也不能证明短期上涨判断仍然成立。只有公告标题时只确认标题存在，不补写收入、利润、订单或业务影响。

## 输出合同

每条关键事实同时保留统一的数据质量信息。`fact_as_of` 表示事件发生日、报告期或事实对应期间，`available_at` 表示系统何时能够取得；两者不得互换。顶层 `as_of` 仍是本轮形成日决策截止时点。`quality` 使用 `complete | partial | unreliable`，`capability_status` 使用 `supported | partial | unsupported`。正文缺失、历史覆盖不足、查询失败、只有当前快照和真实无记录必须分开写入 `missing_fields` 或 `unknowns`。这些字段只解释证据边界，不计分或投票；无法确认形成日前可得的事实不能支持候选命题。

严格返回：

```yaml
phase: discovery | validation | review
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
    company_information:
      first_or_repeat: first | repeat | unknown | not_applicable
      disclosure_chain:
        prior_forecast: null
        forecast_revision: null
        earnings_express: null
        formal_report: null
        correction: null
        comparison_basis: ""
      new_information_level: substantive_new | incremental_detail | confirmation_only | repeat_or_no_new_information | not_applicable | unknown
      event_id: null
      event_available_at: null
      event_stage: ""
      business_link: direct | indirect | unknown | not_applicable
      materiality: ""
      tradable_sessions_since_event: null
      basis: ""
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
