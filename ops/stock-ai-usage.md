# 股票助手 AI 模型切换与定时任务使用说明

两个正式 AI 任务（18:45 晚间研究、08:45 次晨安全提醒）由 macOS launchd 启动
`tools/stock_ai.py`，自动链路为 GLM → DeepSeek（仅额度不足或不可用时接替），经本机
ZCode CLI 无交互执行原有运行 Prompt：

- **GLM**：`bigmodel/glm-5.3-flash`，BigModel 个人套餐，思考档 max；
- **DeepSeek**：`deepseek/deepseek-flash`（官方 API 名，对应 DeepSeek-V4.1-Flash，1M 上下文），默认思考模式；
- **Astra**：不参与自动任务。GLM 与 DeepSeek 都失败时，工具只如实报失败；
  由你在 Codex App 中手动让 Astra 补跑（晚间读取 `ops/forward-selection-prompt.md`，
  次晨读取 `ops/preopen-safety-prompt.md`，沿用原 prepare 边界）。

研究方法、Skill、归档合同与展示不变。

## 日常命令（项目根目录执行）

```bash
./.venv/bin/python tools/stock_ai.py status                 # 现在用哪个、最近结果
./.venv/bin/python tools/stock_ai.py use deepseek           # 以后默认 DeepSeek
./.venv/bin/python tools/stock_ai.py use glm                # 以后默认 GLM
./.venv/bin/python tools/stock_ai.py use auto               # 恢复默认 GLM→DeepSeek
./.venv/bin/python tools/stock_ai.py tonight deepseek       # 只今晚用 DeepSeek
./.venv/bin/python tools/stock_ai.py tonight glm            # 今晚切回 GLM
./.venv/bin/python tools/stock_ai.py tonight clear          # 清除今晚覆盖
./.venv/bin/python tools/stock_ai.py run nightly --provider glm   # 人工跑/补跑晚间研究
./.venv/bin/python tools/stock_ai.py run nightly --rerun-date YYYY-MM-DD  # 按原行动日补跑
./.venv/bin/python tools/stock_ai.py run preopen --provider deepseek  # 人工跑次晨提醒
./.venv/bin/python tools/stock_ai.py run nightly --dry-run  # 只看计划，不执行
./.venv/bin/python tools/stock_ai.py install                # 预览定时任务安装
./.venv/bin/python tools/stock_ai.py install --apply        # 实际安装/更新两个 AI LaunchAgent
./.venv/bin/python tools/stock_ai.py uninstall              # 移除两个 AI LaunchAgent
./.venv/bin/python tools/stock_ai.py verify --provider glm  # 一路模型的小型真实测试（glm/deepseek）
```

`status` 只读；`use`、`tonight` 只改本地配置（`.stock-ai.local.json`），均不请求模型 API。
`tonight` 只绑定当天自然日晚间任务，次日自动失效；`use` 不打断已启动的任务；
`--provider` 只影响本次调用，不持久化。晚间研究**不设总时限与模型时限**：
执行到完成或明确失败；只有 GLM 额度不足或确实不可用才自动接替 DeepSeek；
本地/数据/归档问题如实失败，不靠换模型掩盖。模型目录覆盖自动写入
`~/.zcode/cli/config.json`（DeepSeek 1M 上下文修正），不动模型选择与凭据。

## 语音说法 → 本地命令

在能执行本机命令的助手里说：

| 用户说法 | 执行命令 |
|---|---|
| “以后用深度求索跑股票任务” | `use deepseek` |
| “以后用 GLM” | `use glm` |
| “今晚用 DeepSeek” | `tonight deepseek` |
| “今晚切回 GLM” | `tonight glm` |
| “恢复默认” | `use auto` |
| “现在用哪个 AI” | `status` |

执行后应复述实际保存的设置，例如：“已设置：今晚优先 DeepSeek，失败后按 GLM
接替；长期默认不变。”模型名或日期不明确时，先问清再执行，不猜测。

## 定时与迁移状态

- 新计划：`com.ccrt.stock-analysis-assistant.ai-nightly`（18:45）、
  `com.ccrt.stock-analysis-assistant.ai-preopen`（08:45），`RunAtLoad=false`、
  `KeepAlive=false`，安装不触发研究；日志在 `logs/ai_tasks/`。
- 旧 Codex App 原生 automation（`a`、`a-2`）已于 2026-09-12 经应用接口删除，
  两项均返回 `deleteStatus=deleted`；历史对话保留，不能根据历史对话仍显示就判断调度存在。
- 如以后明确决定恢复旧方式，须先停止这两个 Mac AI 计划，再通过 Codex 应用接口
  重建对应调度。当前不恢复；不编辑已删除任务的配置文件来假装重新启用。
- 通知方式（2026-09-12 起）：已取消 ZCode 对话通知，统一使用 macOS 原生通知。
  整项任务失败、部分完成需处理、取消、错过交易日检查窗口或因占用未执行时，
  先把失败原因与已有成果写入 `local_archive/ai_tasks/`，再经 `osascript`
  提交一条系统通知（提交成功只代表系统已接受，不代表已读）；正常完成、
  正常休市、正常无需变化不弹通知。任何通知都不调用 GLM、DeepSeek、Astra
  或 ZCode 对话接口。
- 查看最近一次失败：运行 `status`，或直接让助手"查看最近一次失败原因"——
  失败记录含日期、阶段、两条路线的实际尝试与原因、已完成产物和日志路径，
  无需自己翻技术文件。
- 每路完整错误输出追加保存到对应 `events-<provider>.stderr.log`，包含每次退出码；
  state/索引中的 attempts 保存退出码与日志路径。显示文字可以缩短，接替判断使用
  本次完整错误依据，取消/超时仍不接替。
- `verify` 的验证记录区分两个层面：`configured_model` 是本次调用显式配置的模型，
  `evidence_model` 来自 ZCode 会话请求记录（rollout）的实际主请求字段；两者一致才算
  通过。没有证据时不标注“已验证”。

## 结果位置

- 最终完整回复：`local_archive/ai_tasks/nightly/<日期>/final-reply.md`（次晨同理）。
- 结果索引与每次尝试原因：`local_archive/ai_tasks/index.jsonl` 与 `state/`。
- 执行日志（JSONL/JSON 事件、Prompt、prepare 日志）：`logs/ai_tasks/`。
- 正式报告归档与网页展示沿用原有位置（`local_archive/forward_selection/`、
  `local_archive/forward_monitor/` 与本地 Prism 页面）。
