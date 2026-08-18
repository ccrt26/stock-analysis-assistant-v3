# Forward 自动化运行收口

## 1. 本轮目标

本轮目标是把已经存在的每日 Forward 自动化真正收口为这台 Mac 上可以无人值守运行的个人任务：

```text
09:00 次晨数据任务
↓
数据准备完成
↓
09:30前调用本机 Codex + 当前五个 Skill
↓
冻结上一交易日对应的0—5只 Forward 结果
↓
真实运行记录保存在本地运行目录
↓
历史股票只有完整走满D20后才一次性结算
↓
用户不需要每天手工发命令
```

本轮不改变选股逻辑。

## 2. 本轮需要解决的问题

当前 `cdf7e56` 已知的实际问题：

1. Forward launchd 模板没有像现有数据任务一样加载 `.env.local`；
2. 当前 09:10 只检查一次，如果 09:00 数据任务稍晚完成，当天 Forward 就会直接漏掉；
3. 每日真实运行结果现在写入 Git 跟踪的 `docs/forward-selection-log.csv`，会导致仓库每天产生运行数据修改；
4. GitHub 中存在 launchd 模板，但还需要确认这台 Mac 上真正安装、加载并可以运行；
5. 必须实际验证本机 `codex exec` 非交互调用可用，而不是只证明代码存在。

## 3. 非目标

本轮不做：

- 不修改五个 Skill；
- 不修改选股逻辑；
- 不继续历史回测；
- 不增加评分器；
- 不增加新的选股程序；
- 不复制 Skill 到 Python；
- 不增加数据库；
- 不增加服务端；
- 不增加队列；
- 不增加状态机；
- 不增加 Web 页面；
- 不增加新的 Agent；
- 不增加自动调优；
- 不增加自动报告平台；
- 不增加复杂审计体系；
- 不为了追求代码行数而大规模重构 `cdf7e56`。

## 4. 验收标准

### A. 代码层

- [PASS] 五个 Skill 没有修改；`git diff -- .agents/skills` 为空。
- [PASS] 没有新增程序化选股规则；Python 只负责等待、调用、校验、冻结和结算。
- [PASS] Forward 仍通过 `codex exec` 调用五个 Skill；正式 prompt 与结构化输出合同保持使用当前五个 Skill。
- [PASS] `.env.local` 在 launchd 环境中加载；安装配置与现有数据任务使用相同的 `set -a / source / set +a`。
- [PASS] runtime CSV 改到 `local_archive`；实际路径为 `local_archive/forward_selection/forward-selection-log.csv`。
- [PASS] docs 历史 CSV 没有被每日运行继续使用；只在本地文件首次不存在时作为初始化源。
- [PASS] D20 仍是一次性结算；相关测试验证完整20日后计算且重复运行不再结算。
- [PASS] 没有新增平台型组件；没有新增模块、数据库、服务或状态机。

### B. 时间与数据层

- [PASS] Forward 约 09:05 启动；`launchctl print` 显示工作日09:05。
- [PASS] 09:00 数据暂未完成会简单等待；测试验证每30秒检查并在 ready 后继续。
- [PASS] 最晚约 09:15 仍未 ready 则当天放弃；测试验证返回 `data_not_ready` 且不调用 Codex。
- [PASS] 09:30 以后绝不写 forward；研究完成和最终写入前均检查开盘时间，越界测试不落盘。
- [PASS] 非交易日不产生；现有非交易日测试保持通过。
- [PASS] 同 formation_date 不重复；已有 forward 决策的幂等测试保持通过。
- [PASS] 只使用 selection_as_of 之前的信息；正式 prompt 保留 `available_at <= selection_as_of`，实际时间在数据 ready 后、调用 Codex 前冻结。

### C. 本机运行层

- [PASS] plist 已经实际安装到当前 Mac；文件位于当前用户 `Library/LaunchAgents`。
- [PASS] launchctl 能够看到 Forward 任务；label 已注册，安全触发 `runs = 1`、`last exit code = 0`。
- [PASS] Codex CLI 能够被实际找到；实际路径为 ChatGPT 应用内 Codex，版本 `0.148.0-alpha.15`。
- [PASS] Codex 非交互 smoke 成功；结构化返回 `status=ok` 并列出实际读取的两个仓库文件。
- [PASS] read-only sandbox 成功；smoke 明确运行在 `sandbox: read-only`。
- [PASS] 当前非正式时段执行 runner 不会产生假的 forward；21:08 launchd 实际返回 `outside_selection_window`，新增行数为0。
- [PASS] `local_archive/forward_selection` 目录能够正常写入；本地 CSV 已完成首次初始化。

### D. 数据结果层

- [PASS] 现有历史记录成功保留；初始化后 docs 与本地 CSV 的 SHA-256 同为 `56414c2975e442ab9545743efe8156ceff40adf2bb70b16c901c64a711b9ee9f`。
- [PASS] 2026-08-17 reconstructed 状态没有被改变；整文件一致，相关记录仍为 `reconstructed`。
- [PASS] D20 结算计算保持原口径；行动日复权开盘为入口，D1—D20复权收盘一次计算命中、首次命中、最大和终点收益。
- [PASS] 不再每天更新 D1—D19；不足完整20个交易日时测试验证记录完全不变。

## 实际验收结果

上述 A—D 项全部 PASS。直接相关测试与仓库完整测试均通过（`374 passed`）；Forward LaunchAgent 已按工作日09:05注册，数据未 ready 时只等待至约09:15，正式写入仍必须早于09:30。Codex 只读非交互 smoke 和 launchd 非正式窗口安全运行均成功。本轮没有修改任何 Skill。
