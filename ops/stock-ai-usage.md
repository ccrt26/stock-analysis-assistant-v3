# 股票助手 AI 模型切换与定时任务使用说明

两个正式 AI 任务（18:45 晚间研究、08:45 次晨安全提醒）由 macOS launchd 启动
`tools/stock_ai.py`。18:45 夜间默认 **Astra high → GLM → DeepSeek**；08:45 次晨保持 **GLM → DeepSeek**。仅模型额度不足或供应商确实不可用时接替。

- **Astra**：`gpt-6-astra`、`high`，本机 Codex CLI 和现有 ChatGPT 登录；显式限制 ChatGPT 认证，不用 API Key、不启用 fast/priority、不改全局 Codex 配置。
- **GLM**：`bigmodel/glm-5.3-flash`，ZCode CLI、BigModel 个人套餐，原思考 max。
- **DeepSeek**：`deepseek/deepseek-flash`，ZCode CLI、官方 API，原默认思考。

三路均不可用时保留产物如实停止；不自动重置额度。
研究方法、Skill、归档合同与展示不变。

## 日常命令（项目根目录执行）

```bash
./.venv/bin/python tools/stock_ai.py status                 # 现在用哪个、最近结果
./.venv/bin/python tools/stock_ai.py use deepseek --task nightly # 以后仅夜间优先 DeepSeek
./.venv/bin/python tools/stock_ai.py use glm --task nightly  # 以后仅夜间优先 GLM
./.venv/bin/python tools/stock_ai.py use auto --task nightly # 恢复夜间 Astra→GLM→DeepSeek
./.venv/bin/python tools/stock_ai.py tonight deepseek       # 只今晚用 DeepSeek
./.venv/bin/python tools/stock_ai.py tonight astra          # 今晚使用 Astra high
./.venv/bin/python tools/stock_ai.py tonight clear          # 清除今晚覆盖
./.venv/bin/python tools/stock_ai.py run nightly --provider glm   # 人工跑/补跑晚间研究
./.venv/bin/python tools/stock_ai.py run nightly --rerun-date YYYY-MM-DD  # 按原行动日补跑
./.venv/bin/python tools/stock_ai.py run preopen --provider deepseek  # 人工跑次晨提醒
./.venv/bin/python tools/stock_ai.py run nightly --dry-run  # 只看计划，不执行
./.venv/bin/python tools/stock_ai.py install                # 预览定时任务安装
./.venv/bin/python tools/stock_ai.py install --apply        # 实际安装/更新两个 AI LaunchAgent
./.venv/bin/python tools/stock_ai.py uninstall              # 移除两个 AI LaunchAgent
./.venv/bin/python tools/stock_ai.py verify --provider astra # 一路模型的小型真实测试（astra/glm/deepseek）
```

`status` 只读；`use`、`tonight` 只改本地配置（`.stock-ai.local.json`），均不请求模型 API。
`tonight` 只绑定当天自然日晚间任务，次日自动失效；`use` 不打断已启动的任务；
`--provider` 只影响本次调用，不持久化。优先级为本次 `--provider` → 当日 `tonight` → `use ... --task nightly/preopen` → 旧全局 `use` 偏好 → 分任务默认。显式首选之后按该任务固定默认次序补齐；例如夜间 `--provider glm` 为 GLM → Astra → DeepSeek。分任务 `auto` 明确恢复该任务默认，不被旧全局偏好覆盖；夜间 `auto` 同时清除今晚覆盖，保留影响次晨的旧全局设置。未指定 `--task` 的 `use glm/deepseek/auto` 仍操作旧全局偏好；已有分任务设置优先。Astra 仅允许夜间，次晨不增加 Astra 路线。晚间研究**不设总时限与模型时限**：
执行到完成或明确失败；只有本次模型终端请求证实的额度、认证、型号、限流或模型连接故障才接替；
本地/数据/归档问题如实失败，不靠换模型掩盖。模型目录覆盖自动写入
`~/.zcode/cli/config.json`（DeepSeek 1M 上下文修正），不动模型选择与凭据。

## 语音说法 → 本地命令

在能执行本机命令的助手里说：

| 用户说法 | 执行命令 |
|---|---|
| “以后夜间用深度求索” | `use deepseek --task nightly` |
| “以后夜间用 GLM” | `use glm --task nightly` |
| “今晚用 DeepSeek” | `tonight deepseek` |
| “今晚切回 GLM” | `tonight glm` |
| “恢复夜间默认” | `use auto --task nightly` |
| “现在用哪个 AI” | `status` |

执行后应复述实际保存的设置，例如：“已设置：今晚优先 DeepSeek，失败后按 Astra、GLM
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
  失败记录含日期、阶段、各条路线的实际尝试与原因、已完成产物和日志路径，
  无需自己翻技术文件。
- 每阶段原始事件、错误和最终回复保存到本阶段日志；ZCode 原重试日志继续追加保存。
  state/索引中的 attempts 保存退出码与日志路径。显示文字可以缩短，接替判断使用
  本次模型终端请求依据；工具输出里的 HTTP 403/429 不构成模型故障，取消/超时仍不接替。
- `verify` 的验证记录区分两个层面：`configured_model` 是本次调用显式配置的模型，
  `evidence_model` 来自对应执行器的实际请求/会话协议；Codex 另核对 high、ChatGPT 传输端点与完整会话输入。两者一致才算
  通过。没有证据时不标注“已验证”。

## 结果位置

- 最终完整回复：`local_archive/ai_tasks/nightly/<日期>/final-reply.md`（次晨同理）。
- 结果索引与每次尝试原因：`local_archive/ai_tasks/index.jsonl` 与 `state/`。
- 执行日志（JSONL/JSON 事件、Prompt、prepare 日志）：`logs/ai_tasks/`。
- 正式报告归档与网页展示沿用原有位置（`local_archive/forward_selection/`、
  `local_archive/forward_monitor/` 与本地 A2 页面）。网页同步继续沿用现有晚间收尾与恢复调用；主用是 `style-preview/prism-a2.html`，日期页是 `prism-a2-report-<date>.html`。旧 `prism.html` 与 `prism-report-*` 为停更备用，不再同步。

## 正文显示与完整完成

整份日报仍须严格归档、CSV 和全部合并分区核对通过。仅合并文字失败时，已独立核对的推荐分区允许同步显示，任务仍记“合并报告待修复”，不重跑模型、不归档半份日报。completed 复核也会调用渲染器，让认可稿或模板更新生效；相同网页由渲染器保持不写入。历史补缺与停止原因说明见 `ops/web-display-maintenance.md`。

## 推荐正文的执行与恢复

新研究由同一个晚间任务按顺序完成（article-v1 分工）：选股研究会话形成 pending、市场说明和 selection-handoff.json → 程序按原截止备齐时点事实并组织单股研究包 → 逐股启动全新作者会话完整成稿 → 独立审稿会话核对读者理解与研究一致性，表达问题返回作者有限次修改，研究问题返回研究负责人定向返修后重建材料回到作者 → 独立复盘会话按原合同完成当日复盘 → 汇合核对、正文与理由一起冻结 → 程序原样装配四个分区交付，不调用模型总结。未冻结阶段按实际输入身份复用：输入（Prompt、事实、范文、模型配置）不变才复用旧结果，研究返修后受影响旧稿自动重建。已有采用稿继续原恢复方式，不补称经过新审核。名单真正为空时不启动逐股作者，复盘照常按原合同执行。手动完整执行见每日 Prompt 的分工说明。

人工验收试写（不动正式记录）用 `tools/recommendation_trial.py prepare|run`：prepare 只读源 trace 与事实、固定输入快照；run 调用与生产相同的作者循环真实写文章，`--no-fallback` 锁定单一供应商路线，产物只写指定试验目录。该入口不提供正式 prepare/record/freeze/发布能力；`check-review` 用合成挑战做真实审稿回归，`export` 汇总复核包。

持续维护触发规则：今后修改作者/审稿Prompt、材料投影、疑点处理（resolver）或模型/执行器配置时，先跑相关合成回归，再经同一试写入口回放固定样本，最后用未参加调优的新记录抽查；问题留档并能按阶段恢复。这仅积累稳定性证据，不证明长期零错误，收益准确率另走既有方法研究。

阶段输入、输出、会话、实际型号、耗时及具体问题保存在本轮 `local_archive/ai_tasks/nightly/.../recommendation/`，任务状态的 `recommendation_stages` 保存阶段索引。`accepted-recommendation.json` 含采用正文及准确对应的待冻结 trace，仅用于同源交付与中断恢复，不是新的正式事实库。正常继续使用现有 `nightly --rerun-date`；程序复用已完成阶段，不重新选股。若明确提示 CSV/trace/采用稿冲突，保留产物核对具体差异，不能删除正式记录后重跑。

所有阶段沿本轮有效路线，同任务 state 保存已失效供应商，研究/写审/返研/公司介绍和恢复均跳过；下次独立夜间任务重新 Astra 优先。CLI 缺失、权限、事实、研究质量、JSON 合同、PDF 和归档问题不接替。完整同源交接已保存而终端回传失败时先核对已有产物，只补缺失；冻结后不重新选股。公司介绍在第一次本地展示后补缺项，单独记录结果。连续几晚的成品质量要看实际文章和修正记录；程序验收通过不代表语义每天零错误。


## 官方原件与通用事实

少量候选验证可先调用 `python -m stock_analyzer.ops.recommendation_context --code 代码 --formation-date 日期 --as-of 带时区截止 --category financial --output 临时文件`；类别支持 financial/company/price/industry，`--period` 保留特定期间，`--sector-date` 按原截止读取行业跨日序列。期间摘要只说明本地可得，不等于公司是否披露。正文引用近邻及其他期间时保留对应事实，不能只留下价格。

同份已知公告用 `python -m stock_analyzer.ops.official_evidence --announcement 元数据.json --as-of 带时区截止 --output-dir 临时目录`，可提供 `--existing-receipt` 或已核验同公告的 `--alternative-url`。优先复用同版原件，下载只在取证函数内使用明确直连。旧公司介绍 `fetch-evidence` 与 receipt 回读合同仍兼容。失败记录 HTTP 状态和诊断，不把错误页当 PDF，也不把取证失败变成模型接替理由。

## 本次推荐文件方式（候选）

仅授权运行时使用 run nightly --provider astra --no-fallback --recommendation-authoring-profile astra-files-v1。profile 与禁备用只作用本次，不修改长期配置；恢复沿用 state 保存策略，显式冲突拒绝。新推荐研究及写审为 Astra xhigh，正式复盘保持 Astra high。preopen 不接受这两个参数。正式启用须另行批准，细节见 docs/architecture/normal-recommendation-files.md。

## 待复核候选：首次手动运行与供应商恢复

本节是候选操作说明，**仅复核通过并另行批准后才能执行**。用户主动暂停的定时任务保持暂停；手动运行不等于恢复 launchd。

首次已获批准的手动夜间任务显式使用：

```sh
./.venv/bin/python tools/stock_ai.py run nightly --provider astra --no-fallback --recommendation-authoring-profile astra-files-v1
```

日期由实际 prepare 决定，不把隔离验收的历史 rerun-date 当作今天。该策略仅绑定本任务，不要求修改长期供应商顺序或生产本地配置。研究/交接/作者/审稿/同股核对 xhigh，独立正式复盘及公司介绍 high；需核对实际会话证据，配置值不能证明已执行。新 profile 在同股当前意见核对完成前保留复盘待核对稿，未决不装配完整日报。

真实额度不足时保留原阶段、失败和预算。用户明确确认 Astra 已恢复后，按**原任务同一身份、同一 profile、同一策略**在上面的已有 run 命令加 `--retry-unavailable-provider astra`；原任务使用 rerun-date 时保留其原值，不能另造业务日期。参数只解除已核实的本任务供应商故障 marker，先备份并追加审计，不清空 state、不重选、不删除有效文章。完成/取消、日期或策略不符、数据/合同/业务阻断均不能由它解除。再次供应商失败仍停止；不自动检测额度是否重置。

旧 `--scheduled` 命令不带 `--no-fallback` 时不等价于本次首轮策略。以后是否恢复调度及其策略需单独授权；本节不提供自动恢复动作。
