# A股短周期上涨发动机 V4 最终合同

本合同是个人股票助手的短周期研究唯一定义。它不建立评分器、模型、平台或自动交易，只固定五个 Skill 的分工和每日留痕，避免把“公司材料完整”再次误写成“未来约20日上涨路径最强”。

## 1. 固定研究链

```text
新信息或新需求
→ 市场传播、板块传播或股票自身需求
→ 相对市场和行业的价格成交确认
→ 剩余路径是否仍未耗尽
→ 基本面锚和公司风险是否支持
```

## 2. 七种发动机和四种状态

从 `formation_date >= 2026-08-21` 起，新提交的正式轨迹必须是 `daily-research-trace-v4`；旧v1/v2/v3只作为历史记录读取，不得用于新的正式提交。

`engine_type`：`fresh_event_pending | event_repricing_confirmed | sector_broad_diffusion | sector_leader_cluster | independent_demand_acceleration | anchor_only | unresolved`。

`engine_status`：`active | conditional | inactive | unresolved`。

四种已确认发动机使用 `active`；`fresh_event_pending` 只能是 `conditional`；`anchor_only` 只能是 `inactive`；`unresolved` 只能是 `unresolved`。

## 3. 一条正式推荐通道和一条事件线索通道

正式推荐通道只适用于四种 `active` 发动机。价格支持必须有观察日期、绝对价格或收益、成交、相对市场或行业收益，以及至少一个独立路径质量字段。

事件线索通道只适用于 `fresh_event_pending`：公开时间必须满足 `formation_date 15:00（含） <= event_available_at < action_date 09:30` 且不晚于 `as_of`。形成日收盘后、中间非交易日、行动日开盘前分别使用 `after_close`、`nontrading_day`、`preopen`，不接受 `intraday_unresolved`。事件还必须是首次、`substantive_new`、主营直接相关、材料性可解释、尚无首个完整交易日，并保存同一事件的公司支持、行动条件、公告前相对表现和抢跑/透支事实。它不是已确认正式推荐。

### 消费端派生分类

冻结 trace 不增加字段、不迁移也不回写。程序和研究导出只在消费端派生 `selection_output_class`：

- `confirmed_active`：V4 `final_fate=selected`，四种已确认发动机之一，`engine_status=active` 且 `market_recognition.status=confirmed`；
- `conditional_event`：V4 `final_fate=selected`，`engine_type=fresh_event_pending`、`engine_status=conditional` 且 `market_recognition.status=pending`；
- `legacy_v1_not_rewritten`：缺少 V4 thesis 的旧正式记录，只读保留，不事后确认；
- `not_formal_candidate`：rejected、unresolved、nearest 或 comparator。

`selection_output_class` 只允许出现在 monitor snapshot、研究 CSV 或渲染时的派生对象，不写回 trace、Forward CSV 或数据库。`final_fate=selected` 不再直接等同正式推荐。

原 conditional trace 永不原地晋升。首个完整交易日只把原行动条件记为 `met | not_met | unknown`；无论条件是否满足，原记录都不进入正式推荐数量、正式 D1—D20、正式 D20 结论或正式收益汇总，也不得用行动日开盘、当日最低价、后续最高价或盘中价格倒推可靠入口。若之后某个正常形成日已经具备价格确认，总控可独立形成新的 `event_repricing_confirmed + active` trace；新记录拥有自己的入口和评价，旧记录身份不变。

## 4. 市场传播

`market_propagation_mode`：`broad_sustained_participation | one_day_repair | sector_rotation | concentrated_speculation | weak_or_fragmented | unclear`。

V1透明解释条件：

- `broad_sustained_participation`：3日和5日等权收益、中位数均为正，上涨面均高于50%，成交没有明显低于20日基线，新高没有与价格推进明显背离；
- `one_day_repair`：1日等权收益、中位数为正且上涨面不低于65%，但3日或5日收益/上涨面未同步，成交未高于20日基线；
- `sector_rotation`：市场不属于持续广泛参与，同时至少两个板块被板块Skill确认存在广泛扩散或领导集群，且5日成交份额增加；
- `concentrated_speculation`：正收益贡献集中度高于自身20日80%分位，且市场中位数不为正或上涨面低于50%；
- `weak_or_fragmented`：3日和5日分布均弱，且没有可确认的广泛参与或板块传播；
- `unclear`：数据不足或模式冲突。

高分化风险只写入 `market_risk_overlays: [high_dispersion_risk]`。传播模式改变搜索重点，不直接选股、决定仓位或否决。

## 5. 板块发动机

`sector_broad_diffusion` 要求3/5日板块相对收益和成员中位数为正、上涨面均高于50%、5日成交份额增加、前三强正收益贡献低于80%，候选只能是 `leader_confirmed` 或 `core_diffusion_member`。

`sector_leader_cluster` 至少要求 `max(3, ceil(有效成员数×5%))` 只真实相关成员同步增强。每个记录成员都必须同时具有正的3日/5日相对市场收益和不低于75%的板块内5日百分位；5日成交份额增加，单一股票正收益贡献不高于60%，候选自身板块内百分位不低于75%。只有 `leader_confirmed` 和 `core_diffusion_member` 可以正式入选；不能用“补涨”升级落后成员。

## 6. 披露链

同一事项按 `预告 → 预告修正 → 快报 → 正式报告 → 更正` 核对。`new_information_level`：`substantive_new | incremental_detail | confirmation_only | repeat_or_no_new_information | not_applicable | unknown`。正式报告更完整不等于新增催化；没有分析师一致预期历史时不写“超市场预期”。

## 7. 事件反应和复盘

新合同使用 `compute_event_reaction_features_v3`，记录 `preopen | after_close | intraday_unresolved | nontrading_day`，拒绝盘前尚未完成的同日日线，使用形成日有效申万二级成员，并计算事件后1/3/5日相对表现、成交、收盘质量和窗口最高点到末日收盘回撤。

四种 `confirmed_active` 发动机分别复盘行动日可执行率、D1/D3/D5/D10/D20、相对市场、相对行业、20日收盘20%触达、最大上涨、MFE、MAE、D20收盘和 selected/nearest 成对结果。`conditional_event` 只保留不依赖参与假设的首日绝对、相对、成交和收盘事实，入口依赖字段保持为空。旧轨迹保持 legacy，不倒填新类型。

## 8. 选出后的固定时间边界

V4 结果冻结后，程序按每条研究记录继续保存必要事实，但不改写当时的内部分类、理由和比较：

- `confirmed_active` 的 D1—D20 是固定主评价期；D20 仍按现有 Forward 定义结算。
- `conditional_event` 的 `formal_return_started=false`，正式收益字段和正式 D20 结论保持为空；其首日事实只评价原条件，不创造参与收益。
- D21—D30 只是被动后续观察。迟到启动可以提醒，但必须写明“不改变原20个交易日结果”，也不修改 D20 命中结果。
- D30 后旧记录关闭。此后的新事件或新变化必须由新的每日 V4 结果形成新记录。
- 提前判断失效后仍由程序被动记录到 D20，但退出普通详细提醒。
- 提前达到目标后仍记录到 D20，不自动产生新的买入建议。

## 9. 每次运行的数据能力边界

新生成的 V4 轨迹必须保存 `runtime_capabilities`，包括 `market_research_available`、`price_research_available`、`industry_research_available`、`theme_research_available`、`stock_context_available`、`announcement_status`、`announcement_exchanges` 和本次限制。历史 V4 轨迹继续可读，不倒填该字段；新的 `record-trace` 必须收到它，并拒绝比 `prepare` 更宽的能力声明。

市场观察和价格分析是正式研究最低条件，任一不可用时停止。行业、主题、个股背景和公告是彼此独立的可选通道：一项缺失只禁用对应证据，不得阻断其他可用研究路径。`complete_core_date` 只作数据诊断，不是正式研究 Gate。

公告状态只有 `cninfo_complete | exchange_complete | exchange_partial | announcement_unavailable`。`exchange_partial` 时，`fresh_event_pending` 只允许用于 `announcement_exchanges` 中完整覆盖的交易所；未覆盖交易所不得把查询失败解释为没有公告。`announcement_unavailable` 时不得形成行动日前新公告候选。所有公告仍必须满足 `available_at <= as_of`。

跟踪程序不增加第六个 Skill，不计算总分，也不改变本合同七种 `engine_type`、四种 `engine_status`、一条正式推荐通道、一条事件线索通道和11个既有价格场景。
