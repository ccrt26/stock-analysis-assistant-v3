# 隔离日常入口：实际失败与生产保持证据

**入口确已执行，但整链未完成；页面/浏览器验收为not_run。** H3在研究澄清合同校验处停止，没有本轮采用稿或正常页面。浏览器能力可用，未生成替代页面或截图；不能以自动测试代替实际整链成功。

## 实际到达的位置

- [范围与历史复用](replay-scope.md)：2026-09-21形成、9月22日行动的延江股份；复用已存选股研究与112个历史episode的当日复盘交付，实际调用候选`complete`。没有重跑五Skill全市场研究。
- [研究级同股检查](../trials/H3/stages/current-research-check.json)：真实`pairs=[]`、`expected_pairs=[]`，检查通过且`execution=null`，没有为了凑步骤调用模型。这个样本不能证明真实同股冲突已经整链实跑。
- [唯一澄清请求及全部材料](../trials/H3/README.md)：请求53为Astra xhigh，完整交付后进入合同校验；不是额度中断。
- [实际resolution.json](../trials/H3/stages/articles/300658.SZ/research-clarification-files-1/output/resolution.json)将`H-300658.SZ01`既写为非阻塞`retained_unknown`，又列入`unresolved`。文字主张保留同比未知、不改变原判断，但同一ID同时出现于两个互斥列表，现有校验拒绝。
- [失败回执](../trials/H3/run.json)记录“同一问题同时给出已解决与未决”。原输出、模型可见回复、输入与协议全部保留；没有手改回执、重抽澄清、删除问题或另换留出样本。

| 后续步骤 | 实际状态与证据 |
|---|---|
| H3作者、reader、fidelity及有限修订 | 未运行：澄清结果未满足合同 |
| 最终真实文章与复盘文字核对 | 未运行：没有本轮推荐正文 |
| 采用、正式保存、日报装配、正常渲染 | 未运行：`complete`抛错，未到达`finish_nightly_success` |
| 冻结研究采用稿比对 | [not_run](frozen-research-check.json)：没有采用稿；命令退出0不表示该验收通过 |
| 正常“研究说明”页面及正文同一性 | [not_run，命令退出2](browser.json) |
| 浏览器中的D20、普通复盘、节点显示 | 未运行：没有本轮正常页面；相关自动测试另见[测试记录](../tests/README.md) |

[运行前检查](pre-daily-no-adoption.json)确认隔离根没有旧采用稿和旧正常页面可冒充成功；[浏览器工具检查](browser-tooling-check.json)仅证明Chromium可启动，不是页面验收。[158个源码文件核对](isolated-code-check.json)确认隔离入口实际使用066129e代码。[请求阶段审计](stage-order.json)覆盖全部53次实际请求及reader→fidelity的同稿、先后与供料边界。

实际隔离任务的[失败状态](daily/ai_tasks/state/nightly-replay.json)、[原pending研究](daily/forward_selection/pending-trace-2026-09-21.json)和[当日复盘交付](daily/forward_monitor/pending-report-2026-09-21.json)均为本轮有界脱敏副本。公开目录不沿用被Git忽略的local_archive目录名，没有强制加入生产归档或修改忽略规则。

## 生产与工具检查

[生产前](production-before.json)与[生产后](production-after.json)的小范围核对覆盖37个正式CSV、归档、索引、配置、plist与页面目标：内容、大小及mtime均保持；生产仍为main/61f0ebbd719845e44aae3fb5449f0b74b15bf1ad。夜间任务仍`disabled=true`、`loaded=false`。这不是对整个事实仓的遍历声明。[任务进程检查](production-processes.json)另列准确范围。

最初验收脚本只识别`=> true`，误将本机实际`=> disabled`记为false；[原错误回执](production-after-first-parser.json)、[原因和修正](production-query-correction.json)及两次命令日志均保留。修正的是只读证据工具，未改变任务状态。

[实际命令](actual-commands.sh)、[验收命令时间/退出码/日志](qa-commands.jsonl)均可读。业务代码和Prompt未在066129e之后改变；之后增加/修正了脱敏、链接、统计及验收辅助脚本。它们已在实际材料上执行和语法检查；浏览器脚本中需要成功页面的分支本轮没有运行，不能声称已经验证。

`NOT_DEPLOYED`。无生产保存、页面覆盖、任务启用或运行版本切换。后续仅等待用户与ChatGPT复核。
