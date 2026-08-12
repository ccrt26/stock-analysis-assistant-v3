# 2026-08-11 五 Skill 完整复跑诊断报告

## 结论先行

当前五个 Skill 按同一形成日和完整合格范围复跑后，没有发现已产生的方向线索或股票线索“无声消失”。板块、公司和价格都能独立提交股票；没有当日新公司公告也没有被当作自动淘汰理由；大盘/板块跟涨与个股增量也被分开处理。

本次形成日结论为 3 只：江波龙 `301308.SZ`、恒逸石化 `000703.SZ`、北化股份 `002246.SZ`。这是形成日研究结论，不是收益承诺，也没有使用 2026-08-12 及之后的实际表现。

候选漏斗为：合格范围 4,402 只 → 三个发现 Skill 共提交 20 条股票线索 → 去重 17 只 → 10 只进入共同验证 → 3 只入选、13 只明确淘汰、1 只因关键数据缺口未决。主要阻断是合理的公司传导和价格归因，不是 Skill 间语义冲突。因此本轮结论是：**暂不继续调 Skill**。

## 冻结边界和版本

```yaml
task_type: historical_simulation
research_objective: "未来约20个交易日形成可操作显著上涨路径，重点观察约20%涨幅"
formation_date: 2026-08-11
action_date: 2026-08-12
as_of: "2026-08-11T23:59:59+08:00"
selection_universe: "上海主板、深圳主板和创业板"
future_information_used: false
```

五个 Skill 的冻结版本：

| Skill | SHA-256 |
| --- | --- |
| `orchestrating-stock-research` | `be5809ee7ca401895bae4d62984a4c75703a584b435d2a3b70fbb9cb5436edb4` |
| `interpreting-market-macro` | `7fa0fbcc9ab7f760e80c63eca0db5de1ccc7374a52ac26b6ca30d61cee149b24` |
| `researching-sectors-industries` | `351655acf510f5bb71d3c62796a8e4a6179075c9b8c5c80815ee8bf14ac23965` |
| `researching-company-events` | `8d7a2139d60736429d717aa4c1131075de99300d9da355d50fbc6fdc661fdc10` |
| `analyzing-price-trading` | `b6ce25d29380556666b6fc0f4038e6a2dd260081dee9dd9ac50e845a61275057` |

本地数据边界：

- `local_archive/data_health/2026-08-11.md` 确认收盘核心数据完整。
- `market_context-v2` 于 2026-08-11 21:32:44+08:00 提交，状态 `complete`。
- `sector_hotspot-v3` 于 21:34:05+08:00 提交，686 行，状态 `complete_with_declared_gaps`。
- `stock_trading_context-v2` 于 21:36:15+08:00 提交，5,539 行，状态 `complete_with_declared_gaps`。
- 按形成日有效的 `security_master`，再排除范围外板块、ST/*ST、退市整理、形成日停牌和无可靠价格上下文后，合格范围为 4,402 只：上海主板 1,626、深圳主板 1,418、创业板 1,358。

## 冻结研究简报

- 市场：5 日修复是否足以支持普遍追强，还是只能支持结构性机会？
- 板块：哪些行业是多成员共同增强，哪些只是少数股票拉动或下跌后的同步修复？
- 公司：行业或价格线索能否落到真实业务；直接公司事件能否传导到利润、现金流或预期？
- 价格：个股是否真正超过市场和同类；价格已经反映多少；行动日是否仍有可参与路径？
- 关键未知：公司真实业务联系、核心事件正文/规模、形成日身份和可交易性无法确认时，不正式选择。
- 主要反证：一日涨停、连续拉升、5 日大幅透支、公司利润缺少现金支持、事件主要来自非经常性损益、只有标题而无正文。

本轮定向使用了 `src_cn_factor_momentum_2023`、`src_cn_return_dispersion_risk`、`src_cn_t1_contrarian_2024`、`src_cn_price_limit_momentum_2025`、`src_cn_turnover_momentum_boundary`、`src_cn_illiquidity_operability`、`src_cn_max_overextension`、`src_csrc_disclosure_rules_2025` 和 `src_cn_earnings_disclosure_hierarchy`。它们只改变比较和表达方法，没有变成固定阈值、总分或 Gate。

## 市场 Skill：发现结果

合格范围内的等权统计为：1 日 `-0.42%`、中位数 `-0.67%`、上涨面 `28.17%`；5 日 `+3.87%`、中位数 `+2.32%`、上涨面 `71.44%`；20 日 `+4.28%`、中位数 `+4.95%`、上涨面 `72.74%`。全市场派生观察同时显示 5 日成交额比约 `0.91`、20 日均线上方占比约 `89.05%`、20 日新高占比约 `13.23%`。

```yaml
primary_interpretation: "市场经历了有广度的5日修复，但形成日多数股票回落且成交没有同步放大；环境支持结构性板块和公司事件机会，不支持把所有低位反弹写成个股启动。"
alternative_interpretations:
  - "形成日回落可能只是修复过程中的正常分歧。"
  - "高均线上方占比也可能意味着短期普遍反映较多，后续更依赖增量事实。"
strongest_counter_evidence: "5日上涨面较宽，若成交和新高继续扩散，当前对普涨跟随的谨慎可能偏保守。"
evidence_sufficiency: sufficient
```

市场提交 2 条非股票线索：一条方向线索要求寻找“板块广度＋公司传导”，一条问题线索要求价格 Skill 区分“普遍修复、板块跟随和个股增量”。

## 板块 Skill：全范围轻量发现

为保证候选边界一致，行业关键指标使用形成日有效的申万 L3 成员关系，在 4,402 只合格股票上重新做等权横截面比较；原始 `sector_hotspot-v3` 用于核对覆盖、集中度和限制。

| L3 行业 | 合格成员 | 1日/上涨面 | 5日/上涨面 | 20日/上涨面 | 解释 |
| --- | ---: | ---: | ---: | ---: | --- |
| 医疗研发外包 | 19 | +4.05% / 78.95% | +22.63% / 100% | +19.15% / 84.21% | 多窗口共同增强，但已有较多新高，需检查透支 |
| 半导体材料 | 10 | -1.62% / 20% | +20.79% / 100% | -18.09% / 10% | 典型的短期共同修复，不等于全面启动 |
| 印制电路板 | 42 | -0.41% / 30.95% | +16.92% / 97.62% | -6.37% / 24.39% | 5日扩散明显，20日路径仍弱 |
| 机床工具 | 13 | +2.43% / 69.23% | +10.90% / 100% | +5.67% / 61.54% | 多成员增强，形成日仍有推进 |
| 线下药店 | 8 | +5.44% / 100% | +9.07% / 100% | +10.72% / 87.5% | 广度强，但形成日涨幅集中且追涨风险上升 |
| 数字芯片设计 | 17 | +0.63% / 58.82% | +10.13% / 94.12% | -14.46% / 11.76% | 短期修复，长窗口仍弱 |

板块 Skill 提交 6 条股票线索：

| 代码 | 股票 | 原始板块线索 | 同类比较与待验证问题 |
| --- | --- | --- | --- |
| 301201.SZ | 诚达药业 | 医疗研发外包 | 5日 `+34.25%`，比合格行业高约 11.63 个百分点，但20日落后行业；核对是否有真实业务增量 |
| 300759.SZ | 康龙化成 | 医疗研发外包 | 20日强于行业，但5日低于行业且处于60日高位；与诚达药业比较谁更有增量 |
| 300161.SZ | 华中数控 | 机床工具 | 5日 `+22.88%`，高于行业约 11.98 个百分点，成交放大；核对经营传导和Q1反证 |
| 603883.SH | 老百姓 | 线下药店 | 形成日接近涨停、行业全线上涨；核对回购/激励是否提供公司增量，而非仅板块推动 |
| 300476.SZ | 胜宏科技 | 印制电路板 | 5日 `+36.04%`，显著高于行业；核对基本面与价格透支 |
| 300666.SZ | 江丰电子 | 半导体材料 | 5日 `+26.94%`，但20日 `-18.43%` 且当日成交未放大；区分板块修复与个股确认 |

## 公司 Skill：全范围轻量发现

公司发现扫描了合格范围内形成日前可见的结构化业绩预告、快报、公告标题和公司概况，没有逐股读取全市场公告正文。非经常性损益主导、负向预告或陈旧且无法连接本轮目标的事实没有被硬凑成股票线索。

| 代码 | 股票 | 公司线索 | 可见时间与主要反证 |
| --- | --- | --- | --- |
| 301308.SZ | 江波龙 | H1预告净利润 92—110 亿元、同比约 `+62204%—+74394%`；原因包括存储景气、晶圆供应协议、自研芯片/软件和端侧AI | 2026-08-11 21:32:39+08:00；Q1经营现金流约 `-28.75` 亿元、借款和负债较高 |
| 000703.SZ | 恒逸石化 | H1预告净利润 55—60 亿元、同比约 `+2326%—+2547%`；文莱炼厂、己内酰胺项目和聚酯链改善 | 2026-08-11 21:32:38+08:00；Q1经营现金流约 `-25.73` 亿元、负债率较高 |
| 000408.SZ | 藏格矿业 | H1预告净利润 35.5—37.5 亿元、同比约 `+97%—+108%`；钾肥、锂和巨龙铜业共同改善 | 2026-08-11 21:32:39+08:00；形成日价格大跌，与公司强事实冲突 |
| 000762.SZ | 西藏矿业 | H1预告扭亏，净利润 0.5—0.66 亿元；锂价、销量和产能释放 | 2026-08-11 21:32:39+08:00；规模小于同类，价格尚未识别 |
| 600255.SH | 鑫科材料 | H1预告净利润 0.4—0.5 亿元、同比约 `+103%—+153%`；产品结构、铜价和基地改善 | 2026-08-11 21:32:39+08:00；Q1经营现金流约 `-1.12` 亿元，价格无增量确认 |
| 002246.SZ | 北化股份 | H1预告同比约 `+87%—+134%`，硝化棉毛利改善；形成日前结构化H1报表显示归母净利润约 2.25 亿元、经营现金流约 2.43 亿元 | 预告 2026-08-10 21:31:53+08:00；H1报表 2026-08-11 00:00+08:00；形成日涨停增加行动日风险 |
| 600768.SH | 宁波富邦 | H1预告净利润 0.5—0.6 亿元、同比约 `+417%—+520%` | 2026-08-11 21:32:39+08:00；包含股权处置收益，Q1经营现金流约 `-2.28` 亿元 |
| 002859.SZ | 洁美科技 | 形成日披露发行股份购买资产并募集配套资金报告书（草案） | 2026-08-11 00:00+08:00；本地只有标题和元数据，标的、规模与财务影响无法确认 |

公司另提交“潜能恒信重大合同进展”问题线索，但本地只有公告标题，不能核对合同金额、条件和材料性，因此没有转成股票候选。

## 价格 Skill：全范围轻量发现

价格发现先比较合格范围、有效 L3 行业和个股增量，再结合成交、价格位置和连续拉升检查剩余路径。价格 Skill 独立提交 6 条股票线索：

| 代码 | 股票 | 5日收益 | 相对合格行业 | 20日收益 | 成交额比/60日位置 | 原始问题 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 301051.SZ | 信濠光电 | +60.22% | 约 +52.50pp | +30.36% | 3.07 / 0.87 | 个股增量极强，但5日透支是否已破坏剩余路径 |
| 300903.SZ | 科翔股份 | +60.69% | 约 +43.77pp | -11.29% | 1.68 / 0.46 | PCB中明显独立，但连续拉升和高波动是否不可追 |
| 603990.SH | 麦迪科技 | +34.74% | 约 +33.14pp | +25.98% | 2.00 / 1.00 | 价格异常能否找到公司变化解释 |
| 301308.SZ | 江波龙 | +24.24% | 约 +14.10pp | -22.47% | 1.46 / 0.24 | 有公司事实且短窗口超过行业；长窗口伤痕是否仍是反证 |
| 300161.SZ | 华中数控 | +22.88% | 约 +11.98pp | +20.04% | 4.33 / 0.59 | 价格确认较强，是否有公司经营变化支持 |
| 002859.SZ | 洁美科技 | +35.53% | 约 +26.75pp | +4.94% | 1.14 / 0.45 | 价格与重组标题同步，但事件影响能否验证 |

5日或20日负收益仅作为既有路径，不被用来证明“还没涨”或“有补涨空间”。

## 方向交接表

| lead_id | 类型 | 来源 | 交给 | 结果 | 对应股票/原因 |
| --- | --- | --- | --- | --- | --- |
| M-D1 | direction | 市场 | 板块、公司、价格 | converted_to_stock | 301201、300759、300161、603883、300476、300666 |
| M-Q1 | question | 市场 | 价格 | converted_to_stock | 301051、300903、603990、301308、300161、002859 |
| S-G1 | group | 板块 | 公司、价格 | converted_to_stock | 医疗研发外包 → 301201、300759 |
| S-G2 | group | 板块 | 公司、价格 | converted_to_stock | 机床工具 → 300161 |
| S-G3 | group | 板块 | 公司、价格 | converted_to_stock | 线下药店 → 603883 |
| S-G4 | group | 板块 | 公司、价格 | converted_to_stock | PCB/半导体材料修复 → 300476、300666 |
| C-Q1 | question | 公司 | 公司定向补证 | no_stock_with_reason | 潜能恒信合同仅有标题，金额、条件和材料性未知 |

交接统计：7 条非股票线索中，6 条完成股票转化，1 条有明确理由未转化，0 条未决。

## 完整候选漏斗台账

`company` 为 `sufficient/partial/insufficient/not_yet_checked`；`sector` 为 `supportive/mixed/adverse/unknown`；`price` 为 `stock_specific/sector_or_market_following/overextended/mixed/unknown`。

| 股票 | discovered_by / source_leads | 共同验证 | company / sector / price | 最强反证或关键未知 | final_fate | fate_stage / fate_class / fate_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 诚达药业 301201 | sector / S-G1 | 是 | partial / supportive / mixed | 有真实CDMO业务，但没有形成日前可验证的行业需求新变化；Q1经营现金流为负 | rejected | company_transmission / reasonable_rejection / 只有板块价格变化和业务归属，核心经营传导不足 |
| 康龙化成 300759 | sector / S-G1 | 否 | not_yet_checked / supportive / sector_or_market_following | 5日低于行业、处于60日高位，没有独有增量事件 | rejected | sector_comparison / reasonable_rejection / 同一因果链内不如诚达药业具有短窗口增量 |
| 华中数控 300161 | sector+price / S-G2,P5 | 是 | partial / supportive / stock_specific | Q1亏损约0.79亿元、经营现金流为负，缺少经营新变化 | rejected | company_transmission / reasonable_rejection / 价格确认无法替代公司传导 |
| 老百姓 603883 | sector / S-G3 | 是 | partial / supportive / overextended | 回购与激励的规模和经营传导未确认；形成日接近涨停且处于60日高位 | rejected | price_attribution / reasonable_rejection / 主要是行业共同上涨叠加一日价格透支 |
| 胜宏科技 300476 | sector / S-G4 | 是 | partial / supportive / overextended | 公司业务和Q1利润真实，但本地没有新的行业需求事实；5日已涨36%且波动高 | rejected | price_attribution / reasonable_rejection / 价格已大幅消耗预期，剩余路径不足 |
| 江丰电子 300666 | sector / S-G4 | 否 | not_yet_checked / mixed / sector_or_market_following | 20日仍弱、当日回落、成交额比低于1 | rejected | price_attribution / reasonable_rejection / 更像半导体材料板块共同修复，个股增量不足 |
| 江波龙 301308 | company+price / C1,P4 | 是 | sufficient / supportive / stock_specific | Q1经营现金流为负、负债和借款较高；20日路径仍弱 | selected | selected / selected / 公司事件、业务传导和短窗口个股增量同时成立 |
| 恒逸石化 000703 | company / C2 | 是 | sufficient / supportive / stock_specific | Q1经营现金流为负、负债率较高；20日已上涨约20% | selected | selected / selected / 业绩变化规模大，价格在5日和20日均超过同类且未出现连续涨停 |
| 藏格矿业 000408 | company / C3 | 是 | sufficient / unknown / mixed | 形成日跌7.65%且成交放大，价格与强公司事实冲突 | rejected | price_attribution / reasonable_rejection / 市场识别在形成日显著恶化，行动日路径不清晰 |
| 西藏矿业 000762 | company / C4 | 是 | sufficient / mixed / unknown | 价格仅与市场大致同步，利润规模和同类优势较弱 | rejected | price_attribution / reasonable_rejection / 公司扭亏真实，但尚无必要的市场识别 |
| 鑫科材料 600255 | company / C5 | 否 | sufficient / mixed / unknown | 5日弱于同类，Q1经营现金流为负、利润规模较小 | rejected | price_attribution / reasonable_rejection / 公司变化尚未得到价格确认 |
| 北化股份 002246 | company / C6 | 是 | sufficient / supportive / stock_specific | 形成日涨停，行动日可能无法正常参与或出现透支 | selected | selected / selected / H1利润与现金流支持，个股超过民爆制品同类，保留条件化参与 |
| 宁波富邦 600768 | company / C7 | 否 | sufficient / mixed / mixed | 利润含股权处置，经营现金流为负，价格增量有限 | rejected | company_transmission / reasonable_rejection / 持续经营传导弱于表面利润增幅 |
| 信濠光电 301051 | price / P1 | 否 | not_yet_checked / mixed / overextended | 5日涨60%、60日位置0.87、波动和成交同时放大 | rejected | price_attribution / reasonable_rejection / 已有明显个股增量，但行动日剩余路径被透支反证压倒 |
| 科翔股份 300903 | price / P2 | 否 | not_yet_checked / supportive / overextended | 5日涨61%、高波动，20日仍为负且无公司新变化 | rejected | price_attribution / reasonable_rejection / 价格加速过强，不把前期跌幅当剩余空间 |
| 麦迪科技 603990 | price / P3 | 否 | insufficient / adverse / overextended | 价格在60日高位，无法找到形成日前公司新变化解释 | rejected | company_transmission / reasonable_rejection / 独立价格异常缺少可验证因果链 |
| 洁美科技 002859 | company+price / C8,P6 | 是 | partial / supportive / stock_specific | 重组报告正文、标的、规模和财务影响在本地不可得 | unresolved | joint_validation / data_gap / 关键事件影响无法确认，不能伪装成合理淘汰或正式入选 |

## 最终取舍

```yaml
research_objective: "未来约20个交易日形成可操作显著上涨路径，重点观察约20%涨幅"
formation_date: 2026-08-11
action_date: 2026-08-12
as_of: "2026-08-11T23:59:59+08:00"
selection_universe: "上海主板、深圳主板和创业板；排除科创板、北交所、场内基金、ST/*ST、退市整理、形成日停牌和无可靠报价"
market_search_context: "5日修复有广度，但形成日回落且成交未扩张；优先公司变化与个股增量同时成立的结构性机会。"
selected_stocks:
  - ts_code: "301308.SZ"
    name: "江波龙"
    new_change: "形成日前可见的H1高增长预告与半年度报告公告，原因直接指向存储景气、晶圆供应、自研技术和端侧AI需求。"
    target_thesis: "利润变化规模大且5日价格明显超过数字芯片设计同类，可能继续推动存储业务重估。"
    causal_chain: "存储供需和端侧AI需求改善 → 公司晶圆供应及自研存储方案承接 → 利润预期大幅上修 → 短窗口价格开始独立识别。"
    evidence_by_lens:
      market: ["市场5日修复有广度，但要求个股增量"]
      sector: ["数字芯片设计合格成员5日+10.13%、上涨面94.12%"]
      company: ["H1预告净利润92—110亿元；主营为Flash和DRAM存储器"]
      price: ["5日+24.24%，超过同类约14.10个百分点；成交额比1.46，无5日涨停"]
    why_this_over_alternatives: "相较纯半导体修复股，它同时有直接公司事实和个股价格增量；相较科翔、信濠，5日透支较低。"
    strongest_counter_evidence: "Q1经营现金流约-28.75亿元、借款较高，20日收益-22.47%且仍弱于同类。"
    key_unknowns: []
    secondary_unknowns: ["H1正式报告正文未作为结构化财务事实使用"]
    action_day_participation_conditions: ["存在正常双向成交", "没有脱离原命题的极端跳空或涨停锁死", "成交增加仍能带来相对同类的价格推进"]
    abandonment_conditions: ["新披露否定利润或供应链逻辑", "高成交而价格明显失去相对同类强势", "无法正常成交"]
  - ts_code: "000703.SZ"
    name: "恒逸石化"
    new_change: "H1预告净利润55—60亿元，并披露文莱炼厂、己内酰胺项目和聚酯产业链改善；形成日有半年度报告与新增项目公告。"
    target_thesis: "盈利变化规模大，5日和20日价格均超过炼油化工同类，可能继续反映一体化盈利改善。"
    causal_chain: "炼化和聚酯供需改善＋项目满产 → 单吨盈利及规模利润释放 → H1利润显著增长 → 个股持续超过行业。"
    evidence_by_lens:
      market: ["结构性机会优先于普遍追强"]
      sector: ["炼油化工合格成员5日+4.12%、上涨面88.89%；20日+8.49%"]
      company: ["H1预告净利润55—60亿元，同比约+2326%—+2547%；主营石化和化纤"]
      price: ["5日+10.97%，超过同类约6.85个百分点；20日+20.36%，超过同类约11.86个百分点；无5日涨停"]
    why_this_over_alternatives: "相较仅有行业修复的化工股，它有大规模利润变化和多窗口个股增量；相较藏格矿业，形成日价格没有出现同等级别的负向冲突。"
    strongest_counter_evidence: "Q1经营现金流约-25.73亿元，2026Q1负债约865亿元、负债率较高，20日涨幅已较大。"
    key_unknowns: []
    secondary_unknowns: ["H1正式报告正文未作为结构化财务事实使用"]
    action_day_participation_conditions: ["正常双向成交", "没有明显透支式跳空", "价格继续保持相对炼油化工同类的增量"]
    abandonment_conditions: ["高成交低进展或快速跌回行业共同路径", "现金流或负债出现新的实质恶化", "无法正常成交"]
  - ts_code: "002246.SZ"
    name: "北化股份"
    new_change: "H1利润和现金流正式结构化事实形成日前可见，硝化棉毛利改善得到实际利润确认。"
    target_thesis: "公司盈利和现金流共同改善，形成日价格明显超过民爆制品同类，若行动日可参与，仍可能继续重估。"
    causal_chain: "硝化棉毛利改善 → H1归母利润与经营现金流同步增长 → 市场在形成日开始快速识别。"
    evidence_by_lens:
      market: ["形成日市场多数下跌，个股涨停具有明显相对增量"]
      sector: ["民爆制品合格成员5日+6.97%、20日+21.72%；个股5日仍高于同类"]
      company: ["H1归母净利润约2.25亿元，经营现金流约2.43亿元；主营硝化棉"]
      price: ["形成日约+9.99%，5日+12.35%，成交额比1.85，60日位置0.67"]
    why_this_over_alternatives: "相较只靠行业上涨的机床和药店候选，它有同口径利润与现金流支持；相较短期涨幅更大的价格异动股，5日累计透支较低。"
    strongest_counter_evidence: "形成日已涨停，行动日可能无法正常成交或出现一次性透支。"
    key_unknowns: []
    secondary_unknowns: []
    action_day_participation_conditions: ["不是一字涨停或不可成交状态", "开盘后成交能够正常进行", "放量仍伴随有效推进而非冲高回落"]
    abandonment_conditions: ["无法正常参与", "高开后高成交低进展或快速回落", "新公告改变H1利润质量判断"]
representative_non_selections:
  - {ts_code: "000408.SZ", name: "藏格矿业", reason_not_selected: "公司事实强，但形成日放量下跌7.65%，价格识别与命题冲突。"}
  - {ts_code: "300161.SZ", name: "华中数控", reason_not_selected: "板块和价格强，但Q1亏损且没有经营新变化支撑。"}
  - {ts_code: "300476.SZ", name: "胜宏科技", reason_not_selected: "业务真实、行业扩散，但5日涨幅和波动已明显消耗剩余路径。"}
  - {ts_code: "002859.SZ", name: "洁美科技", reason_not_selected: "重组事件真实存在，但本地缺正文和规模，关键传导无法确认。"}
common_exposure_note: "三只候选分属数字芯片设计、炼油化工和民爆制品，不是同一行业押注；因最终不是恰好5只，未触发五只候选共同暴露检查。"
```

## 漏斗诊断

| 项目 | 数量 |
| --- | ---: |
| 合格股票范围 | 4,402 |
| 市场非股票线索 | 2（1 direction、1 question） |
| 全部非股票交接线索 | 7 |
| 非股票线索转成股票/有理由不转/未决 | 6 / 1 / 0 |
| 板块提交股票线索 | 6 |
| 公司提交股票线索 | 8 |
| 价格提交股票线索 | 6 |
| 股票线索合计/去重候选 | 20 / 17 |
| 进入共同验证 | 10 |
| 最终入选/明确淘汰/未决 | 3 / 13 / 1 |

最先阻断环节：`sector_comparison` 1、`company_transmission` 4、`price_attribution` 8、`joint_validation` 数据缺口 1、`selected` 3。归因类别：`reasonable_rejection` 13、`data_gap` 1、`semantic_conflict` 0、`selected` 3。

因此：

1. 没有发生已产生线索的无声丢失。
2. 主要阻断发生在价格归因，其次是公司传导；这些股票大多是板块跟随、价格透支、没有经营增量，或公司利润缺少持续性。
3. 唯一未决是洁美科技事件正文缺失，属于数据缺口，不是 Skill 语义冲突。
4. 当前没有足够证据支持下一轮继续修改某一个 Skill；**暂不继续调 Skill**。单日复跑只能证明本日链路闭合，不能证明所有日期都已泛化。

## 数据限制

- 行业分钟数据不可用，板块判断只使用形成日可见的日线、成员广度、相对收益和分化。
- `stock_trading_context-v2` 有 2,279 行因部分输入不足只保留可用观察；所有候选均保留对应 `coverage_status`，未用缺失值补猜。
- 2026-08-11 健康摘要记录部分 `financial_indicator` 业务键冲突；本轮没有使用这些冲突指标作选择。
- 多家公司半年度报告标题已可见，但结构化正文财务数据在截止时间前不完整；除北化股份外，未把报告标题写成已核实的正式报表数字。
- 洁美科技重组只取得标题和元数据，按公司 Skill 保持关键影响未知。
- 形成日之后的行情、公告和交易状态均未用于本报告。
