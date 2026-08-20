---
name: interpreting-market-macro
description: Use when point-in-time A-share candidate selection or validation needs market breadth, liquidity, risk appetite, style, volatility, concentration, macro or policy context, or market-level counterevidence.
---

# 市场与宏观解释

## 目标与证据等级

用形成日可得事实回答两件事：当前机会分布是什么样，给定候选的上涨命题依赖哪些市场条件。市场视角不预测指数点位，不直接生成股票，不给候选投票，也不作为一票否决。

正式结论必须属于以下三类：

1. **一级事实**：官方制度、指数含义和可复算市场分布。它可以直接描述发生了什么，不能推出未来收益。
2. **二级条件关系**：A 股论文与本地形成日验证都支持的有限关系。当前市场层只有“收益分化偏高会提高随后约20日波动和路径不确定性”达到该等级；它仍不预测涨跌。
3. **验证问题或未知**：有研究依据但本地证据不足、数据不完整或变量不等价。它只能改变下一步核对内容，不能提高或降低候选结论等级。

禁止把官方权威性当收益证明，也禁止把论文历史窗口、阈值、系数或收益复制成选股规则。“20日约20%”只是总控目标和事后标签，不是本 Skill 的市场阈值或承诺。

## 输入、范围与时点

取得总控提供的：

- `phase`：`discovery` 或 `validation`；
- `formation_date`、下一交易日 `action_date`、带时区的 `as_of`；
- 默认股票范围或待验证候选；
- 本轮目标、比较窗口、候选命题和机会类型。

正式形成日研究只使用 `available_at <= as_of` 的事实。`fact_as_of` 是事实对应日或期间，`available_at` 是系统可取得时间，两者不能互换。未来路径只能在候选和理由冻结后用于独立评价。

默认范围是上海主板、深圳主板和创业板，并遵守总控排除项。上证综指包含符合条件的科创板证券，不能当作上海主板的精确等价组合。

## 必须调阅并持久化的本地知识

只使用已经落地的来源和能力：

- `src/stock_analyzer/knowledge/research_registry.yaml`
  - `src_cn_market_breadth_alignment`：指数、等权收益、中位数和上涨面只支持一级分布描述；
  - `src_cn_market_turnover_price_progress`：成交与价格进展必须并列，未来关系证据不足；
  - `src_cn_return_dispersion_risk`：市场分化与后续波动是二级条件关系，不决定方向；
  - `src_cn_market_state_trend_reliability`：市场状态改变追强可靠性的关系仍是验证能力；
  - `src_cn_price_limit_momentum_2025` 与沪深交易规则：只解释制度和可交易性。
- `market_skill_evidence.yaml`：来源质量、采用理由、禁止用途和未采用来源；
- `market_skill_validation_results.yaml`：形成日级结果、区间、样本数和成熟度；
- `market_skill_hypotheses.yaml`：冻结公式和失败标准，只用于审计，不把研究分位数用于生产。

新查阅的官方文件或论文若要进入正式事实、解释或结论，必须先把来源信息、证明边界、允许/禁止用途、数据需求和验证状态写入本地知识库。未登记来源只能列为待核材料，不能临时支撑正式结论。

## 数据质量先决条件

每组事实先检查覆盖，再解释：

- 股票当前价格、成交额和复权因子覆盖至少95%；
- 默认必需指数为 `000001.SH`、`399001.SZ`、`399006.SZ`、`000300.SH`、`000905.SH`、`000852.SH`；
- `000688.SH` 和 `899050.BJ` 是默认范围外的辅助观察，缺失时只使对应观察未知，不降低默认范围整体覆盖；
- 涨跌停计数要求实际涨跌停价覆盖至少95%；
- 精确窗口不足、窗口中断或分母为零时输出未知，不缩短窗口、不跨缺口压缩。

查询失败、历史覆盖不足、当前快照不可回放和真实无记录必须分开写。核心事实不可靠时，不给正式市场解释。

## 固定观察表

不先贴“强市、弱市、风险偏好提升”等标签。依次报告原值、比较基线、证据等级和允许含义。

| 问题 | 必须展示的事实与基线 | 允许含义 | 禁止推论 |
| --- | --- | --- | --- |
| 指数与参与宽度 | 1/3/5/20日股票等权收益、中位数、上涨面；三只范围锚定指数等权收益；`breadth_index_return_gap_*`；20/60日均线上方、新高、新低、涨跌停分布 | 一级描述指数和普通股票是否同向、参与是广还是窄 | 广度一致会提高20日显著上涨概率；指数上涨等于普涨或风险偏好提升 |
| 成交与价格推进 | 当日总成交额、相对含当日过去5/20日均值的成交比；同期等权收益、上涨面、新高和收盘路径 | 一级描述成交与价格推进当前一致或冲突 | 放量等于增量资金、机构/主力买入、趋势确认或未来上涨 |
| 分化 | 当日复权日收益总体标准差、过去20个完整交易日均值及两者比值 | 二级：相对基线偏高时，提高随后约20日波动和路径不确定性的风险权重 | 预测上涨/下跌、推断羊群或投资者身份、把0.4772历史相关变成分数 |
| 波动 | 20日和60日全市场等权日收益年化样本波动及比值 | 一级描述当前短期波动相对中期基线；与分化证据交叉检查 | 波动高必跌、波动低必涨 |
| 领导集中 | 当日正收益股票数及涨幅最高20只占全部正收益贡献的比例；同时看中位数和上涨面 | 一级描述正收益是否主要集中于少数股票 | 集中上升必然反转；由贡献集中识别资金主体 |
| 规模风格 | 沪深300、中证500、中证1000同窗口原始收益和差值 | 一级描述当前大中小盘谁相对领先 | 当日领先会延续、风格切换已经完成 |
| 行业传播 | 只接收板块 Skill 用时点有效成员得到的相对收益、上涨面、集中和扩散事实 | 描述哪些行业贡献当前分布，并形成进一步核对问题 | 市场 Skill 自己用行业名称或单只龙头宣布热点延续 |
| 制度约束 | 形成日有效沪深规则、T+1、实际涨跌停价、停牌和行动日报价成交 | 一级解释可交易性和路径约束 | 制度事实产生收益方向；触及涨停等于行动日可成交 |

“扩大、收敛、放量、集中、扩散”必须对应当前值和历史基线。没有基线就写“只有当前值，无法判断变化”。

## 宏观和政策

宏观、政策和规则只在能够回答具体候选问题时读取，优先使用形成日前官方原文。正式使用时必须写清：

1. 官方文件或统计事实是什么，何时公开；
2. 它通过什么行业、价格、融资或需求渠道影响市场结构；
3. 候选公司是否有真实业务或财务暴露；
4. 哪个环节只有推测，哪个事实会推翻传导链。

没有本地可回放宏观事实时，不用新闻摘要、情绪代理或宏观叙事填空。政策方向不能直接映射为行业或公司收益。

## 发现阶段

发现阶段不做未来有效性断言，只输出“下一步往哪里查、为什么查”：

- 指数、等权、中位数和上涨面共同推进：请板块 Skill 核对哪些行业真正有成员扩散；这只是搜索方向，不是行业延续证据。
- 指数上涨但中位数或上涨面弱、正收益贡献集中：请板块 Skill 查领导是否由少数成员造成，并请公司 Skill 查是否存在独立事件；不得直接偏好某类股票。
- 高成交但价格、新高和上涨面不推进：把供给压力或短期脉冲列为价格 Skill 待核问题；不能直接判弱。
- 分化相对20日基线偏高且覆盖可靠：直接提示未来路径波动风险上升，要求价格 Skill 核对候选回撤、流动性、行动日条件和失效点。
- 规模指数出现相对领先：请板块和价格视角验证是否由足够多成员支持；不宣布风格切换。
- 证据不足或冲突：逐项列出缺失值和需要哪个视角补证，允许没有搜索线索。

输出的是 `research_directions`，不是股票、板块排名或机会加分。

## 验证阶段

只评审总控给出的少量候选。每只候选必须单独回答：

1. `dependency_type`：上涨命题主要依赖 `broad_market`、`sector_diffusion`、`independent_company_change` 还是 `mixed`，并说明依据；
2. `required_market_conditions`：命题成立真正需要哪些可观察条件，不写“市场配合”这种空话；
3. `observed_conditions`：当前事实、基线、质量和成熟度；
4. `market_effect_on_thesis`：只能是
   - `raises_path_risk`：仅在可靠的高分化二级证据下使用；
   - `constraint_or_participation_issue`：由正式交易规则、停牌、涨跌停或行动日事实支持；
   - `question_only`：广度、成交、风格、市场状态等尚未通过方向验证的关系；
   - `no_material_market_effect`：候选主要由独立公司变化驱动，且当前没有可靠市场反证；
5. `strongest_market_counterevidence`：最强的一条市场反证及其为什么相关；
6. `invalidating_change`：哪个可观察变化会使当前判断失效；
7. `unknowns`：缺失、不可回放或变量不等价之处。

市场逆风、窄行情、高成交或所谓强市本身都不能删除或升级候选。只有制度可参与性和已验证的分化—波动关系可以直接改变市场层结论，其余只形成跨视角核对问题。

## 输出合同

```yaml
phase: discovery | validation
objective: ""
formation_date: YYYY-MM-DD
action_date: YYYY-MM-DD
as_of: "带时区时间"
facts:
  - claim: ""
    value: null
    baseline: ""
    formula_version: market-context-v3
    provider: ""
    dataset: ""
    fact_as_of: ""
    available_at: ""
    quality: complete | partial | unreliable
    missing_fields: []
    evidence_maturity: level_1_direct | level_2_direct | validation_capability | forbidden
    allowed_decision_effect: ""
    forbidden_inference: ""
market_structure:
  participation: {observations: [], conflicts: [], unknowns: []}
  turnover_price_progress: {observations: [], conflicts: [], unknowns: []}
  dispersion_volatility_concentration: {observations: [], conflicts: [], unknowns: []}
  size_style: {observations: [], conflicts: [], unknowns: []}
  policy_or_rule_context: {observations: [], transmission_limits: [], unknowns: []}
primary_interpretation: "只概括已展示事实和已验证关系"
alternative_interpretations: []
strongest_counter_evidence: ""
research_directions:
  - lens: sector | company | price
    question: ""
    factual_reason: ""
    maturity: level_1_direct | level_2_direct | validation_capability
candidate_reviews:
  - ts_code: "validation阶段必填；discovery阶段为空"
    dependency_type: broad_market | sector_diffusion | independent_company_change | mixed
    dependency_reason: ""
    required_market_conditions: []
    observed_conditions: []
    market_effect_on_thesis: raises_path_risk | constraint_or_participation_issue | question_only | no_material_market_effect
    strongest_market_counterevidence: ""
    invalidating_change: ""
    unknowns: []
evidence_sufficiency: sufficient | partial | insufficient
```

`primary_interpretation` 不得把一级事实或验证能力改写成收益判断。`candidate_reviews` 在 discovery 阶段必须为空，在 validation 阶段必须与总控候选逐只对应，不能只给一个整体市场结论。

## 禁止事项

- 不生成股票名单、市场总分、固定状态、权重、Gate、仓位、目标价或交易指令；
- 不使用“放量上涨、风险偏好提升、资金认可、风格切换、市场逆风”等词代替原值与基线；
- 不从日线、成交、分化或集中推断机构、主力、散户、账户身份或操纵；
- 不把指数、成交、广度、市场状态、政策或宏观单项变成未来收益结论；
- 不用股票行数冒充市场状态样本量，不用未来行情修订形成日解释；
- 不临时使用未登记来源，不用宏观叙事补足缺失数据。
