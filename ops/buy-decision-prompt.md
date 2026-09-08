# 单股买入决策执行 Prompt（按需运行，不属于每日任务）

这一步针对用户指定、尚未买入的一只股票作买入决策研究，产出一次可追溯的本地报告。它是按需运行的研究流程，不是正式每日选股或正式复盘，不进入 Forward CSV、正式报告模型或任何冻结历史。不接券商、不下单、不决定仓位、不新增定时任务或持仓系统、不承诺收益。

## 0. 开始前必须先读

开始任何工作前，先完整读取：

```text
.agents/skills/analyzing-stock-buy-decision/SKILL.md
```

研究方法、适用边界与禁令都在该 Skill 中；本 Prompt 只规定运行顺序、材料准备、报告撰写与核对。不得依赖自动发现机制，必须显式读取。

## 1. 运行顺序

1. **写请求 JSON**。与用户确认（或按用户原话记录）：股票代码、尚未买入、研究截止时点（带时区的 `as_of`）、期望时间窗口（`horizon_sessions`，正整数；`horizon_is_hard_deadline` 默认 false）、用户是否给出参考买价及来源、是否给出可承受亏损百分比与双边交易成本。用户没有提供的字段保持 null，**不代用户填写**；`max_tolerable_loss_pct` 和 `round_trip_cost_bps` 只能来自用户。示例骨架（字段值必须按本次实际填写）：

```json
{
  "ts_code": "…",
  "position_status": "not_bought",
  "as_of": "…带时区…",
  "objective": "near_term_profit_without_fixed_target",
  "horizon_sessions": 10,
  "horizon_is_hard_deadline": false,
  "reference_entry_price": null,
  "reference_entry_source": null,
  "assumed_entry_date": null,
  "max_tolerable_loss_pct": null,
  "round_trip_cost_bps": null,
  "related_episode_ids": []
}
```

2. **运行 prepare**（新建 run 目录，已存在会报错，不覆盖）：

```bash
./.venv/bin/python -m stock_analyzer.ops.buy_decision prepare \
  --request REQUEST_JSON \
  --output-dir local_archive/buy_decisions/<新run目录>
```

`prepare` 只读事实仓，写出 `request.json` 与 `context.json`。`context.json` 含身份与范围检查、历史会话与日历口径、归一日线（含数据截止日）、中性观察（收益、60日位置、ATR、基准对比）、公告元数据、财务摘要、原推荐背景（独立子对象，仅背景）、输入清单与缺口。

3. **按 Skill 研究并补证**。读取 `context.json`；按 Skill 第 2—4 节回答"公司怎样、股票怎样、为何可能在窗口内获利、四种动作如何比较"。只对会改变结论的具体缺口读官方原文（交易所、巨潮、公司公告），逐条记录来源字段；缺口只限制它实际影响的结论。

4. **形成方案并写 analysis-input JSON**。有可执行参与方案时，每个方案给出：`plan_id`、`entry_price`、`upside_levels`、`invalidation_price`、`atr`（从 context 的中性观察取）、`round_trip_cost_bps`（用户在请求里提供过就填入），以及六个文字条件（`level_basis`、`signal_known_when`、`entry_window`、`entry_expiry`、`gap_or_no_fill_action`、`invalidation_observation`），全部按本次研究实际填写，**不得出现"由本次研究写明"等占位文本**。不同买价场景各自给失效价，不自动套同一位置。没有可执行方案时 `plans` 置空数组，并在 `interpretations` 里说明原因，不为凑方案虚构价位。`external_evidence` 按来源字段逐条填写。

5. **运行 calculate**（数值复算，不生成判断；重算允许覆盖 analysis.json，但改变事实截止时点必须建新 run）：

```bash
./.venv/bin/python -m stock_analyzer.ops.buy_decision calculate \
  --run-dir local_archive/buy_decisions/<run目录> \
  --analysis-input ANALYSIS_INPUT_JSON
```

6. **撰写报告正文**到同一 run 目录的 `report.md`。**report.md 是唯一正文，仅这一份为准**，不另存正文 JSON 副本。

7. **自读核对**：报告里的每个数字都能对上 analysis.json；条件时间与可成交价格一致；原推荐背景与新买入分开；最强反证真正影响了动作；缺口没有被写成确定事实。核对发现不一致时先改正文，不改 analysis.json 的计算结果；数字修正才显式重算。

## 2. 报告撰写要求

建议顺序（自然中文，不按字段倒 JSON，不用内部术语——发动机、行动日、D1/D10/D20、Gate、剩余ATR 等改用通俗表达）：

1. **现在的意见**：支持现在考虑、等待具体条件、暂不考虑或关键证据不足，先说最重要理由。
2. **目前发生了什么**：公司变化与股票走势分开讲，数字连着"对这次买入意味着什么"。
3. **为何可能较快获利，最可能错在哪里**：窗口内的依据与最强反证同时进入结论，反证不藏到最后。
4. **从新买价看是否值得**：首个需要观察的位置、进一步上涨条件、判断失效位置、成本与普通波动；区分价位距离和预期收益。
5. **接下来怎样处理**：一个首选方案和必要备选条件，含信号何时知道、可接受买价、跳过区间处理、有效期。
6. **买后如何判断**：上涨、停滞、转弱、回吐各自观察什么；不是自动持仓任务。
7. **资料时点与未解决问题**：正文就近给来源；结尾只留真正影响判断的限制。

可用一张简洁动作表，必要时加一张价位距离表；不用密集表格替代解释。原推荐目标价与观察期只作背景。表述不承诺照做一定获利。

## 3. 边界与核对

- 盘中报价只能是独立快照（代码、价格、报价时间、获取时间、来源）；证明不了报价时间就不能支持"立即按现价参与"；用户手价标为用户输入。
- 默认执行假设：收盘确认后次一交易日正常竞价时段参与；当日新买股份不能当日卖出；失效价不代表保证成交价。
- 观察窗口从假定买入交易日算起，买入日计为第一天；不知道买入日就条件化说明。
- 不覆盖已有 run 目录；不改 `context.json` 的 `as_of`；不改原每日选股、原推荐评价、正式复盘与冻结历史。
- 银龙旧报告中的具体价位与"3—5天"等安排只是注明来源的旧材料，不得写成通用规则或默认值。
