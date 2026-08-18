这是当前个人 A 股助手的正式每日 Forward 研究。不要开发程序，不要修改任何文件，不要调优或改写任何 Skill，也不要调用未来行情评价。

先完整阅读并遵守：

- `AGENTS.md`
- `docs/architecture/current-v3-architecture.md`
- `.agents/skills/orchestrating-stock-research/SKILL.md`
- `.agents/skills/interpreting-market-macro/SKILL.md`
- `.agents/skills/researching-sectors-industries/SKILL.md`
- `.agents/skills/researching-company-events/SKILL.md`
- `.agents/skills/analyzing-price-trading/SKILL.md`

本次冻结边界：

- task_type：daily_selection
- formation_date：{formation_date}
- action_date：{action_date}
- selection_as_of：{selection_as_of}
- 股票范围：上海主板、深圳主板和创业板；排除科创板、北交所、场内基金、ST/*ST、退市整理、停牌、无可靠报价及行动日明确无法正常参与的股票。

只使用本地事实仓中 `available_at <= {selection_as_of}` 的事实。允许使用 formation_date 完整收盘行情、当日晚间已公开并入库的信息，以及 action_date 09:00 前已公开并入库的隔夜或延迟信息。不得查询或使用 action_date 09:30 后行情、任何开盘后分钟走势、selection_as_of 之后才公开的信息或未来20日结果。

严格按当前五个 Skill 正常完成：市场环境、四视角候选发现、候选链归并、三类 opportunity_type、同类型比较、共同验证、跨类型比较和最终0—5只取舍。公司故事不自动优于板块或独立价格机会；高位突破和低位激活并列；最终名单不是候选 Top N，不补位、不凑数，允许空名单。不得把这些规则翻译成评分、权重或 Gate。

每只入选必须保留 priority、opportunity_type、核心入选理由、最强反证，以及为什么优于最接近的同类型或跨类型替代股。另保留最多3只 nearest_nonselection，并说明为什么没进以及与最后一只入选股相比差在哪里。

在内部完成总控 Skill 要求的完整候选链和最终比较，但最终只返回调用方输出 schema 要求的紧凑 JSON。`skills_used` 必须列出实际使用的五个 Skill。若最终0只，`selected_stocks` 返回空数组，并在 `empty_reason` 明确说明当天空名单原因。不得输出 Markdown 或 schema 以外字段。
