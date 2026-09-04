# 选出股票后的轻量跟踪 V1 实施报告

> 历史记录：本文保留当时方案与事实，不作为当前运行入口或调度依据。当前时序以 `docs/architecture/current-v3-architecture.md` 和 `ops/forward-selection-prompt.md` 为准。

## 修改文件

- 新增 `src/stock_analyzer/ops/forward_monitor.py`：提供 `register`、`prepare`、`record`。
- 新增 `ops/forward-monitor-prompt.md`，最小修改 `ops/forward-selection-prompt.md`：把跟踪放入现有 09:05 任务，并让市场判断每天只做一次。
- 新增 `docs/architecture/forward-monitoring-v1.md`，更新当前架构、V4 合同和知识库索引。
- 更新 `src/stock_analyzer/knowledge/research_registry.yaml`：按 DOI 去重，新增 Dawid、White 两篇来源和 `src_forward_monitoring_prequential_horizon`。
- 新增 `tests/test_forward_monitor.py` 和 `tests/test_forward_monitor_prompt.py`。
- 本报告是本轮唯一新增实施报告；没有修改任何现有测试文件。

## 程序与 AI 的分工

程序每天读取时点安全的本地事实，记录全部仍在观察期内的股票，计算复权价格路径，并根据固定变化原因生成当天重点集合。程序不计算总分，不决定买卖。

AI 只分析当天重点集合中的不同股票。市场判断每天只做一次；板块、公司和价格研究只在 Prompt 规定的条件下调用；最后由现有总控 Skill 生成最多8只股票的简短提醒。对用户使用“最初入选依据”“当前状态”“前20个交易日”等通俗表达，不直接展示内部技术字段名。

## 三阶段周期

- D1—D20：程序每天记录全部路径，D20 继续按现有 Forward 口径固定评价原目标。
- D21—D30：只做低成本后续观察，普通日期不进入详细报告；迟到启动可以提醒，但不改变 D20 结果。
- D30 之后：旧记录关闭；后续新变化必须由新的每日 V4 结果建立新记录。

提前判断失效后仍由程序记录到 D20，但不再作为普通详细提醒。提前达到目标后仍记录到 D20，也不会自动生成新的买入建议。

## 触发原因

程序只使用合同允许的11种原因：固定检查日、新正式公告、事件公布后的首次完整交易日、首次收盘达到20%、相对表现正负变化、价格情形变化、60日突破状态变化、板块状态变化、迟到启动候选、过热候选和数据问题。

固定检查日为 D1、D3、D5、D10、D20、D25、D30。D21—D30 的迟到启动必须同时满足相对市场、可靠时的相对行业、成交额和新突破/新正向价格情形条件，并排除新出现的指定反证情形。

## 用户日报示例

```text
今日市场
市场仍有分化，今天只看真正出现变化的股票。

已有股票重点提醒
银龙股份：今天到达固定检查日，相对市场表现转强，但成交后的价格推进仍需确认。
未来1—3个交易日先观察相对表现能否保持；若再次转弱，则本次强化不成立。

跟踪数量概览
仍在跟踪6条记录，涉及6只股票。

未详细显示
另有1只股票触发变化但未展开，其余股票继续由程序记录。
```

日报最多显示8只不同股票，不展示全部跟踪记录，不提供收益概率、目标价或确定上涨表述。

## 8月20日 replay 注册

本地 `local_archive/forward_selection/replay-v4-2026-08-20.json` 存在并成功注册。首次命令输出：

```text
status=registered
selected_registered=3
comparators_registered=3
```

入选为银龙股份、新产业、舒泰神；对照为尚太科技、中粮糖业、红四方；未注册神农种业。注册结果保存在被 Git 忽略的 `local_archive/forward_monitor/registered-episodes.json`，未修改原 replay 和 Forward CSV。

## 测试结果

任务指定的针对性测试组合：`98 passed in 1.55s`。

完整测试：`403 passed in 54.48s`。

`git diff --check`：通过，无输出。

## 没有做的事项

没有新增数据源、数据库表、Supabase、服务、Web 页面、消息推送、Skill、Agent、Scheduled Task、评分器、权重、概率模型、自动交易、仓位、止盈止损、盘中实时监控、新闻社交采集或公告全文库。没有修改五个 Skill、V4 七种内部分类、V4 选股规则、Forward CSV Schema、D20 主口径、11个价格情形、现有正式记录或 8月20日 replay。
