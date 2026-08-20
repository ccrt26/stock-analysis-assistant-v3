# Codex 原生 09:05 Scheduled Task 提示

这是当前个人 A 股助手的正式每日推荐研究。直接使用 `$orchestrating-stock-research`；不要开发或修改程序，不要改写 Skill，不要启动新的 Codex/模型进程，也不要调用未来行情评价。

先在当前项目根目录运行：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection prepare
```

该命令只做确定性准备：确认交易日、等待现有 09:00 次晨数据任务就绪、冻结 `formation_date`、`action_date` 和带时区的 `selection_as_of`、检查四类派生结果并结算到期 D20；它不会运行 AI。只有返回 `status=ready_for_research` 才继续。若返回 `already_selected`、`non_trading_day`、数据缺口或错误，说明具体状态后停止，不补猜。

把 prepare 返回的三个冻结字段作为本次唯一时间边界：

- `formation_date`：所有行情和形成日观察的最晚交易日期；
- `action_date`：计划参与日；
- `selection_as_of`：事实可见性的截止时点，必须早于行动日 09:30。

研究运行超过 18 分钟或在 09:30 以后完成都不使结果失效。完成时间不得移动已冻结的 `selection_as_of`；不得读取 `available_at > selection_as_of` 的事实，也不得读取交易日期晚于 `formation_date` 的行情、行动日开盘/分钟走势或未来 20 日结果。

在同一个顶层研究会话中按总控 Skill 的当前合同实际使用四个专业 Skill：

1. `interpreting-market-macro` 冻结市场环境和搜索含义；
2. `researching-sectors-industries` 面向完整合格范围提交板块/股票线索或明确空线索；
3. `researching-company-events` 面向完整合格范围提交公司/事件线索或明确空线索；
4. `analyzing-price-trading` 调阅 `price_analysis_context` 的完整场景就绪输入，结合原始路径、相对强弱、趋势方向、路径效率、振荡、波动、收盘/成交质量、长期位置和参与条件提交线索或明确空线索。

总控必须保留实际候选来源并完成候选守恒、同因果链比较、跨机会比较、反证和未知检查。不得先做价格 Top N 再补故事；不得把场景、MACD、RSI、K/D、BOLL、ADX/DMI、EMA 或任何其他指标变成评分、权重、Gate 或投票。每日派生的 11 类场景只是可解释研究假设，同一股票可命中多个或一个都不命中。

股票范围为上海主板、深圳主板和创业板；排除科创板、北交所、场内基金、ST/\*ST、退市整理、停牌、无可靠报价及行动日明确无法正常参与的股票。最终允许 0—5 只或空名单，不补位、不凑数。不要区分 forward 与 reconstructed；符合本次冻结边界和研究合同的结果就是正式推荐。

每只入选必须给出足够详细但不堆指标的理由：新变化及其传导、为什么市场可能继续识别、剩余价格路径、真正改变取舍的 1—2 个价格组合及原始数值、最强反证、关键未知，以及为什么优于最接近替代股。另保留最多 3 只最近未入选股并说明差距。价格 Skill 没有改变取舍时也要明确说明。

完成研究后，生成符合 `stock_analyzer.ops.forward_selection.ResearchResult` 的 JSON 对象：`skills_used` 必须是实际使用的五个 Skill；若 0 只，`selected_stocks=[]` 并填写真实 `empty_reason`；若研究或事实查询失败，两个完成布尔值相应为 false、填写 `failure_reason`，且两个候选数组为空。不要把执行失败伪装成空名单。

把 JSON 保存为：

```text
local_archive/forward_selection/pending-<formation_date>.json
```

然后用 prepare 返回的原值运行（不要重新生成时间）：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_selection record \
  --result-file local_archive/forward_selection/pending-<formation_date>.json \
  --formation-date <formation_date> \
  --action-date <action_date> \
  --as-of <selection_as_of>
```

只有 `record` 返回 `selection_frozen` 或 `already_selected` 才算完成。最终向用户直接给出正式推荐股票（或空名单）、排序和详细理由，不使用 forward/reconstructed 两套口径。
