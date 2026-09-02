---
name: analyzing-price-trading
description: Use when point-in-time A-share candidate selection, validation, or post-selection review needs price and volume confirmation, relative performance, remaining price path, overextension, drawdown, liquidity, tradability, or conditional action-date participation checks.
---

# 价格与交易研究

## A股短周期发动机 V4 最终合同（优先级最高）

已确认价格 `support` 必须有观察日期、绝对变化、成交、相对变化和路径质量。事件使用 `compute_event_reaction_features_v3`；`awaiting_first_session` 只能作为条件性行动条件，不能伪装成支持。11个既有场景保持不变。

## 唯一职责和固定比较顺序

价格 Skill 独占个股的多窗口连续性、单日脉冲、成交推进、有效收盘、事件反应、回落、组合余量、流动性和可参与性。固定顺序是：1/3/5 日连续性 → 单日贡献 → 有效收盘 → 成交推进 → 回落 → 组合余量。

使用现有字段组合判断，不增加指标或拟合阈值：

- 连续性同时比较绝对收益、相对市场、相对申万二级行业和同发动机近邻；不能把 5 日累计上涨直接写成多日推进。
- 单日贡献同时查看最近单日对 3 日和 5 日路径的占比、最大单日贡献和涨停贡献；高度集中只能形成强反证，不能机械设线。
- 有效收盘与成交推进必须一起看：放量后多个收盘继续抬升才是推进，放量停滞、上影或回落会降级价格支持。
- 回落与组合余量同时使用形成日前累计路径、价格位置、真实突破、目标 ATR 距离、波动和催化是否继续强化；任何单项都不能证明“还有空间”。

最强价格反证必须在提交给总控的 `decision_role`、`decision_changed`、行动条件或停止增加名单建议中产生可见后果，不能只写进风险段后维持原优先级。conditional 只允许服务于符合 V4 的 `fresh_event_pending` 首日行动条件；普通价格反证不能把其他发动机改成 conditional。价格 Skill 不证明公司业务或板块传播，也不作最终选择。


## 目标

判断价格和成交是否正在确认候选的上涨命题、市场已经反映多少、是否仍有合理上涨路径，以及行动日能否正常参与。

本 Skill 必须帮助总控区分“正在被有效识别”与“已经透支、背离或无法参与”。它可以发现具体股票线索，也可以否定量价上缺乏现实路径的候选。

`engine_status: active` 的正式入选需要本 Skill 给出至少一条 `decision_role: support` 的正向价格确认。低位、未透支、行动日可参与、场景名称或单纯缺少反证都不能替代确认。唯一例外是符合公司 Skill 新颖性与材料性判断的形成日收盘后重大新事件：它可以使用 `engine_type: fresh_event_pending`、`engine_status: conditional` 和一条 `event_price_reaction` 的 `action_condition` 作为待确认事件线索；这不是正式推荐，普通业绩重复披露、低估值、现金流、低位或无新增信息不得进入该通道。

“20 日约 20%”是总控的使用目标和事后评价标签。本 Skill 评估实现该目标的价格路径是否有依据。技术指标可以参加判断，但指标名称、单次交叉、固定阈值或历史涨幅本身都不是预测结论。

## 输入

取得总控提供的：

- `phase`：`discovery`、`validation` 或 `review`；
- `formation_date`、`action_date`、带时区的 `as_of`；
- 股票范围或待验证候选；
- 比较基准、候选原始命题和需要回答的交易问题。

形成日研究不得查询 `action_date` 及之后实际行情。只制定行动日可观察条件；未来表现必须等候选和理由冻结后再评价。

## 定向使用本地知识

只在问题相关且数据可用时调阅 `src/stock_analyzer/knowledge/research_registry.yaml` 中：

- `src_cn_t1_contrarian_2024`：区分极短期反转与中期趋势，近期强势不能自动外推；
- `src_cn_price_limit_momentum_2025`：涨停和连板不是继续上涨保证；
- `src_cn_turnover_momentum_boundary`：高换手本身不确认趋势，也不能识别交易主体；
- `src_cn_illiquidity_operability`：日收益相对成交额只用于粗粒度可操作性比较；
- `src_cn_max_overextension`：近期最大单日上涨是透支反证，不是机械淘汰线；
- `src_cn_margin_semantics`：融资变化只描述信用交易和潜在拥挤，不代表机构观点；
- `src_fama_fisher_jensen_roll_1969`、`src_brown_warner_1985`、`src_mackinlay_1997`：事件附近价格变化要扣除市场共同变化并检查事件重叠。

同时遵守条目的适用范围、前提、反证、本地验证和禁止用途。不得复制论文窗口、收益、分组或阈值。

## 技术信息的实际用法

技术指标是对 OHLCV 的数学压缩，不是新的公司、板块或资金身份事实；但“来自价量”不等于“不能参与选股”。它的用途是把肉眼难以稳定比较的趋势、路径、区间位置和波动状态变成一致观察，并在明确条件下改变候选发现、同类比较、反证或行动日判断。

默认用 `src/stock_analyzer/analysis/price_indicator_features.py` 从本地复权 OHLC 和成交额确定性计算。外部接口只用于小样本核对公式和供应商口径，不能用当前接口值覆盖历史时点。参数采用冻结的代表口径，不在看到结果后搜索最优参数。

这不是“八步漏斗”。只有两个位置有固定先后：共同变化归因在所有个股解释之前，最终综合在所有证据之后。中间各维度并列观察，不因某一维度不满足就停止，也不按满足指标数量决定结论：

- **原始路径与相对强弱**：绝对收益、相对市场、相对板块和同类、上涨天数、涨停贡献；回答究竟涨了什么、是否有个股增量、路径是否集中在少数脉冲。
- **趋势和方向**：EMA20、MACD 12/26/9、ADX14 与 `+DI/-DI`；回答趋势是否建立、增强或减弱，以及强趋势究竟向上还是向下。
- **路径效率与振荡位置**：ER20、RSI14、K/D 9/3；回答相同涨幅是否连续、振荡信号位于什么趋势语境。RSI 或 K/D 不能脱离前两项解释。
- **波动状态**：BOLL `%B`、20/2 带宽及近 5 日变化；只回答收缩、扩张、脱离和失败突破风险，不独立决定方向。
- **收盘和量能质量**：收盘位置、上影、冲高回落、成交放大天数、5/20 日方向成交与价量效率；回答成交增加是否真正推动多个收盘，不识别交易主体。
- **长期位置、剩余空间与参与性**：60/82/250 日位置、此前高点、实现波动、ATR、流动性、停牌和涨跌停；回答市场已反映多少、路径风险和行动日是否可参与。

### 主要场景与当前用法

六个信息维度始终参与；场景只是把相互有条件的事实组合成可检验的研究假设。同一股票可命中多个场景，也可以一个都不命中。场景不是互斥状态、指标投票、分数、权重、股票 Gate 或自动启停规则。

当前 11 个场景的计算定义在 `src/stock_analyzer/analysis/price_scenario_validation.py`，已有历史结果在 `docs/2026-08-19-price-scenario-skill-tuning-report.md`。它们只用于保持研究含义一致，不是每日机械选股线；以后若改变场景定义，应从改变之日开始按新版本观察，不得拿新定义重写旧记录。

历史证据不再用 `supported | refuted | insufficient` 三个标签或任意 `3%` 效应门槛决定场景能否参与。必须分开读取效果方向与大小、不确定区间、跨形成日和年度稳定性、case/control/缺失覆盖、盘中与收盘触达、MFE、MAE 和 D20 收盘。多重检验用于表达不确定性，不自动改写场景合同。

| `evidence_id` | `evidence_status_at_use` | 当前允许的用法 |
| --- | --- | --- |
| `trend_continuation` | `supported_with_boundary` | 可作正向历史关联参加发现和比较，但不得单独推荐；同时披露回撤与 D20 收盘限制。 |
| `range_cross_noise` | `supported_with_boundary` | 只能把横盘、弱趋势、弱量价语境中的上穿作受限反证，不得提高优先级。 |
| `initial_activation`、`confirmed_breakout`、`failed_breakout`、`oversold_strong_downtrend`、`reversal_attempt`、`single_day_impulse` | `provisional` | 可改变发现、支持、反证或同类比较，但必须同时引用真正用到的原始价格与成交字段，不得仅凭场景名改变选择。 |
| `healthy_pullback`、`trend_exhaustion`、`price_volume_divergence` | `observation_only` | 只作当日观察、风险问题或比较语境，不独立推荐或淘汰。 |
| BOLL 窄带后上轨突破正面组合 | `prohibited` | 已失败，不得改名或作“辅助确认”恢复。 |

已失败的 BOLL 窄带后上轨突破正面组合继续禁用，不得换名为“辅助确认”恢复。行动日停牌、无可靠报价或无法正常成交是事实约束，不由任何场景抵消。

### 已支持的窄条件和失败结果

2022-07 至 2026-07 的本地探索证据仍只支持窄语义，不生成生产阈值：单看 K/D 上穿几乎等于全样本触达率；上穿同时处在相对强、正趋势和高路径效率中明显更强。高 RSI 在强趋势/强路径中可表示趋势确认，在弱路径中不能；MACD 正向增强在顺畅路径中比杂乱路径更有意义。这些组合可以参加发现和同类比较，但必须同时给出原始相对收益、收盘/量价、剩余空间与回撤，不得升级成上述更宽场景已经通过。

BOLL 窄带后上轨突破的预设正面组合已失败，不得改名为“辅助确认”继续使用。长周期突破组合曾有较高途中触达，但回撤与回吐明显、稳健对照不足，只能作为需要共同验证的线索。

每次使用指标都要回答：“它相对已有原始事实改变了什么判断？”若删除指标名称后，解释没有原始价格、相对强弱、收盘路径和量能支撑，则该解释无效。

形成日只为实际入选股和实际存在的 `nearest_nonselection` 在当日完整 trace 中保留真正改变取舍的 1—2 条价格判断；没有合适场景时写 `raw_price`，不强迫贴标签，也不罗列 11 个场景。不再另建价格附件、数据表或新 schema。

每条 trace 价格证据写明场景或 `raw_price`、证据版本和当时权限，并用 `decision_role` 与 `decision_changed` 说明它的作用。`formation_values` 只保存真正使用的少量 5/20 日收益、相对市场/申万二级行业、收盘、成交、涨停贡献、位置或 ATR 数值，不保存整行派生数据。价格未改变取舍时可写 `decision_changed=no_change`；不得事后补造当时轨迹。

每条 trace 再使用唯一 `decision_id`，供总控的 `research_thesis.decision_ids` 引用。`raw_price` 可以承担支持、反证、比较或行动条件，但任何 `decision_role: support` 都必须至少保存：`observation_date`、一项收盘价或绝对收益数值、一项成交额或成交额比数值，以及一项相对市场或相对申万二级行业收益数值。只有标签、布尔值、价格位置、ATR、场景名称、“低位”“未透支”或“明日观察”均不得标为支持。

D20 后按照 `docs/2026-08-19-price-skill-d20-audit-method.md` 复核。场景本身的历史关联与 AI 当时是否正确使用分开评价；盘中 20% 触达、收盘触达、MFE、MAE 和 D20 收盘分开看。效果大小、区间、跨日期稳定性和覆盖共同构成证据，不用单个 `3%` 或其他数字自动裁决去留。

## 判断方法

只使用 `available_at <= as_of` 的复权日线、估值、成交额、换手、涨跌停、停牌和交易状态。分钟数据不是默认必需输入。

每日先在 DuckDB 中投影并过滤程序已生成的 `price_analysis_context`，优先读取 `scenario_case_ids`、`scenario_assignment_status`、相对市场、相对申万二级行业、量价推进、突破、涨停贡献、`target_atr_distance_20pct` 和流动性，用 SQL 缩小需要深度比较的范围。不把全部价格表送入模型，不重算 11 个场景公式，也不把 SQL 过滤结果当成候选排名。

公司 Skill 已识别具体事件且该事件 `available_at <= as_of` 时，可按需调用 `compute_event_reaction_features_v3`，用现有日线 OHLC、成交额、宽基指数和形成日有效的申万二级成员，确定性计算事件前 5 日以及事件后 1/3/5 个完整交易日的绝对收益、相对市场、相对行业、成交额比、收盘位置和上影比例。事件由 AI 选择并解释，程序不判断语义或方向；实际用于轨迹时写 `evidence_id: event_price_reaction`、`evidence_status_at_use: observation_only` 和函数返回的公式版本。只有结合实际收益、相对收益与成交推进数值后才可把 `decision_role` 写成 `support`。停牌、缺少收盘/成交、基准或行业、盘中尚未正式收盘及部分窗口必须按返回状态披露。

`awaiting_first_session` 表示事件已知但没有首个完整反应交易日。一般事件只能未决；若公司 Skill 同时给出 `first_or_repeat=first`、`new_information_level=substantive_new`、主营直接且材料性可解释，事件又在形成日收盘后且 `available_at <= as_of`，才可记录 `decision_role: action_condition`，并在 `formation_values` 保存同一 `event_id`、`event_available_at`、`reaction_start_date=action_date` 与 `reaction_window_status=awaiting_first_session`，供总控标为 `fresh_event_pending + conditional` 待确认线索。不得把行动条件补写成形成日支持或正式收益入口。该计算不落新表、不另起定时任务。

### 1. 拆分价格来源

按问题选择必要窗口，分别比较：

- 绝对收益；
- 相对市场收益；
- 相对所属板块和最接近同类的收益；
- 相对自身历史的价格位置、波动和成交变化。

当市场或板块普遍修复时，先判断短窗口绝对变化中由共同变化解释的部分；个股与市场、所属板块或最接近同类大致同步时，只写市场或板块带动的修复或跟随，不写成个股独立启动。只有在可用比较中存在清晰的个股增量时，才结合成交推进、事件时点和反证，按证据强度描述个股自身确认；基准不足时保留来源未知，不用绝对涨幅补判。弱市中绝对涨幅不大但相对强势清晰时，仍可作为个股增量证据。

### 2. 检查市场识别

判断成交变化是否伴随有效价格推进：

- 成交增加且价格持续推进，可作为市场正在识别的证据；
- 高成交但价格停滞、冲高回落或上影反复，是背离和供给压力反证；
- 低成交造成的大幅波动降低信号可信度和可操作性；
- 融资和换手变化只能描述活动与潜在拥挤，不能推断主体身份或意图。

### 3. 判断剩余路径

结合候选原始命题，说明：

- 当前价格变化发生在事实之前、同时还是之后；
- 近期上涨是初步确认、持续重估、加速，还是已经大幅消耗预期；
- 最大单日上涨、连续拉升、波动和价格位置是否增加追涨透支风险；
- 公司或板块催化是否仍在强化，足以反驳单纯的过热解释；
- 什么价格事实会使未来约 20 日显著上涨路径不再可信。

20 日负收益、前期跌幅或低历史位置只描述既有路径，不能单独证明“还没涨”、“有补涨空间”或“已经启动”。“重新活跃”、“初步确认”和“有效识别”等用语必须与前述价格来源和证据强度一致，不把它们变成固定阶段或硬阈值；高位也仍需结合因果、同类比较和透支反证判断。

### 3A. 分开获得的确认与已经付出的涨幅

每只候选都要先拆成两部分，不用总涨幅把两者混在一起：

- **获得的确认**：上涨是否分布在多个普通交易日，是否持续强于市场和同行，成交增加后是否形成多个更高收盘；
- **已经付出的涨幅**：最近 5 日和 20 日已经上涨多少，最大上涨日贡献多少，最大上涨日之后是否继续上涨，以及当前是刚突破还是已在高位停滞。

若最大上涨日同时带来 5 日涨幅、相对市场或行业强势、当日成交放大和突破近期高点，这些只能算一组“单日价格变化”，不能拆成四条支持。必须另外回答：去掉最大上涨日后其余四日是否仍上涨，以及最大上涨日之后至形成日是否继续上涨并跑赢市场。

当 `largest_positive_day_contribution_5d >= 0.50`，或已有可靠事实显示 `limit_up_return_contribution_5d >= 0.50` 时，进入单日主导判断。最大上涨日就是形成日且没有后续交易日、最大上涨日之后收益为负或相对市场转弱、去掉最大上涨日后其余四日不涨，都不能写成持续性已经确认。只有其余交易日仍上涨且最大上涨日之后继续走强，才继续与其他候选比较。没有可靠涨停证据时保持未知，不新增字段或数据源；这项判断不自动淘汰所有涨停股，也不改变 `fresh_event_pending`。

行业或公司变化明确时，可以在多个普通交易日相对同行增强、收盘逐步提高且成交增加没有变成放量不涨后较早确认，不要求先出现很大的五日涨幅。纯价格型候选没有外部原因，必须同时看到去掉最大上涨日后仍强、最大上涨日之后仍强和多个收盘提高，不能只依靠涨停或跳空。

最后只在已有自然语言判断中写出以下一个净结论，不新增枚举或 schema：

- `确认仍大于追高风险`
- `追高风险已经大于确认`
- `现有事实还无法判断`

### 4. 检查可参与性

核对停牌、涨跌停、上市阶段、成交额和正常成交限制。行动日条件必须可观察，例如：

- 是否存在正常双向成交；
- 是否出现明显脱离原命题的跳空和透支；
- 成交增加是否仍带来价格推进；
- 是否出现新公告或价格事实推翻原命题。

没有经验或证据依据时，不发明 `+2%`、`-3%` 一类精确条件。一字涨停、停牌或无法正常成交时，明确不可参与。

## 发现阶段

寻找 0 个或多个具体股票线索：独立相对强势、事件后有效确认、尚未充分反映、趋势增强与路径连续、需要共同验证的长周期突破、显著背离或透支风险。价格 Skill 可以独立发现股票；尚未形成稳定证据的场景可以改变发现问题与比较重点，但不能单独成为推荐理由。不得先按单一技术指标、金叉、触轨或超买超卖排行缩成主要候选池。

价格线索必须说明是哪个条件组合改变了判断、为什么不是市场或板块共同变化，并提出需要公司、板块或市场解释的原始问题。单一指标尾部不能直接成为最终候选。

## 验证阶段

只围绕总控给出的少量候选：

- 检查原始上涨命题是否得到相对价格和成交确认；
- 若命题依赖公司事件，区分事件前抢跑、事件后已观察反应和尚待首个完整交易日，不能把自然上涨误归因于公告；
- 先归因共同变化，再并列填写趋势、原始路径、相对强弱、收盘/量价、振荡、波动和长期位置；识别最相关的场景或原始价格判断及当前证据边界，不把它们做成顺序漏斗；
- 比较候选与最接近替代股票的价格路径；
- 说明为什么仍可能有空间，或为什么市场已经充分甚至过度反映；
- 给出最强价格反证和行动日参与、放弃条件。

## Review 阶段

`phase: review` 只复盘已有记录，不重新推荐股票。使用 snapshot 的确定性字段说明：从当时计划观察的开盘价算起实际涨跌多少，比全市场和同一行业强弱多少，期间最高涨幅、期间最深跌幅、从期间最高点又跌回来多少，成交放大时股价是否真正向上推进，是否反复冲高回落，以及推荐后的第一个交易日能否按原条件正常参与。

结论只说明原来的股价和成交支持是在增强、减弱还是已经失败。不得用单个指标下结论，不用“量价共振”“承接良好”或“筹码健康”代替事实，也不从成交推断任何交易主体。

## 输出合同

每条关键事实同时保留统一的数据质量信息。`fact_as_of` 表示行情或交易状态对应的交易日，`available_at` 表示系统何时能够取得；两者不得互换。顶层 `as_of` 仍是本轮形成日决策截止时点。`quality` 使用 `complete | partial | unreliable`，`capability_status` 使用 `supported | partial | unsupported`。复权、基准、行业归属、成交状态或历史窗口缺失，以及查询失败、当前快照不可回放和真实无记录，必须分别写入 `missing_fields` 或 `unknowns`。这些字段只解释证据边界，不计分或投票。

```yaml
phase: discovery | validation | review
objective: ""
facts: [{claim, value, provider, dataset, fact_as_of, available_at, quality, missing_fields, capability_status}]
primary_interpretation: ""
alternative_interpretations: []
supporting_evidence: []
strongest_counter_evidence: ""
unknowns: []
candidate_leads:
  - lead_type: stock | question
    name: ""
    ts_code: ""
    rationale: ""
    target_relevance: ""
    comparative_reason: ""
    remaining_path_reasoning: ""
    price_confirmation: ""
    reaction_window_status: complete | partial | awaiting_first_session | not_applicable
    close_quality_status: complete | invalid | unavailable | not_yet_observable
    stock_observation_status: complete | suspended | missing | invalid_close | not_yet_observable
    amount_observation_status: complete | missing | not_yet_observable
    benchmark_observation_status: complete | missing | not_yet_observable
    strongest_counter_evidence: ""
    action_day_observations: []
    missing_evidence: []
questions_for_other_lenses: []
evidence_sufficiency: sufficient | partial | insufficient
```

股票线索必须把量价事实与候选原始命题连接起来，并说明剩余路径、同类比较和最强反证。它是总控需要取舍的候选，不是自动买入信号。

## 边界

- 不从量价推断机构、主力、游资或账户意图；
- 不代替公司 Skill 证明业务和公告影响，不代替板块 Skill 判断共同因果；
- 不输出技术总分、指标投票、固定阈值 Gate、目标价、仓位或自动交易动作，也不因为指标数量更多就提高优先级；
- 不把单个指标或未被条件检验支持的组合改名为“辅助确认”后继续使用；
- 不把盘中瞬间触及当作可执行收益；
- 核心价格、复权、基准或交易状态不足时明确未知。
