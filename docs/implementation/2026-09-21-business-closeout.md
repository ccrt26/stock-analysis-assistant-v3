# 正常流程四项收尾（候选，未部署）

仅在原候选分支收尾推荐表达、同股当前意见、A2来源显示和人工运行/恢复策略。正式流程为用户主动暂停，本轮不部署、不修改生产配置或知识库、不启动/恢复正式任务。

`astra-files-v1` 的新未冻结任务使用 `same-day-current-opinion-v1` 任务回执。复盘先保存原 pending ledger/report 和 snapshot；两者通过原 record 验证器时仅记“已分析”。验证器复用原函数，在一次性临时目录运行，不改金融 schema 或正式记录。推荐作者与独立审稿完成后，总控核对 confirmed 推荐与所有当前机会 episode 的交集、原句、用途、参考价及具体条件。标签或周期不能自动放行。

未决合并回各原负责人一次；研究同步 pending/交接/作者输入，复盘只能改受影响本日对象与唯一正文。作者编辑同一篇，审稿收到同版问题处理；必要时复核一致性一次。问题仍在则保留成果，不采用、不 record、不 freeze、不装配。核对回执绑定日期、研究/交接、双方正文、条件及快照来源；实际模型证据也必须通过。空交集记录真实空集，无模型请求。

同版采用快照在金融写入前保存，之后原 ledger record → report record → trace/CSV freeze → 日报装配。中断按同版补缺，所有已写文件不同则拒绝覆盖；这是幂等恢复，不是跨文件原子事务。新任务 accepted/checkpoint/completed 均不得绕过核对；旧已冻结任务沿原恢复合同，不补审旧历史，不算本轮新验收。

来源显示只改 `tools/guanlan-prism/concept-a/a2/overview.js`，由 `tools/guanlan-prism/tools/build_preview_a2.py` 原模板注入。多次引用指向单条定义，文章实例隔离 DOM ID；多行定义不吞相邻正文；代码中的类似语法保持；缺定义和冲突显示说明；沿用 HTML 转义与 http/https URL 白名单。不改归档 Markdown、事实和条件。

首轮人工策略是 `--provider astra --no-fallback --recommendation-authoring-profile astra-files-v1`。研究、交接、作者、审稿及一致性为 Astra xhigh；复盘与公司介绍为 Astra high。实际请求证据和配置分开记录。未加 no-fallback 的旧 scheduled 命令不等价，本轮不改 plist。

`--retry-unavailable-provider astra` 只在用户明确确认供应商恢复后使用：原锁内匹配已有日期身份/策略、非完成非取消且供应商终端失败；先备份旧 state、追加原 marker 审计，再解除该路当前不可用标记。保留 attempts、已完成阶段与预算，不能解除业务、数据、合同或锁阻断；再次供应商失败停止，不探测额度、不请求备用。

验收仅固定历史同一业务日独立副本；原完成记录作为来源，不复制 completed/accepted 冒充新成功。具体测试数量、真实调用、生成版本、最终版本及未通过项随本轮复核报告交付。研究结论与证券正文由角色实际输出，开发者不代写。

本轮产物只提交用户和 ChatGPT 复核。部署和首个正式手动运行均为后续动作：**仅复核通过并另行批准后才能执行**。不得用本轮隔离验收声称首次正式运行成功。
