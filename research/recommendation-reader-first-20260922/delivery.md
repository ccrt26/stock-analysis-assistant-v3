# 复现、交付及边界

本轮只有`fix/recommendation-reader-first-20260922`一个工作分支。实际基线`61f0ebbd719845e44aae3fb5449f0b74b15bf1ad`；首次冻结代码`17ad21b5d0a5afff5d5813d95f689631625c5278`；来源接线修正代码`0ffeae19d8829505e685fbb4da63161142b122dd`；CLI警告计数修正代码`dd33e77bb2e9dae28a62c49d133d5554240669e3`；用户要求恢复额度中断后的最终测试代码`066129e1641c4d1fc55fbb3568527a6f88e35525`。最终远端HEAD将在推送后实查，由最终回执给出；后续证据提交不改变此次已冻结业务提示。

## 实际入口

解释器沿用已验证的Python3.12.14环境，不升级。`$CODE_ROOT`为候选代码独立目录，`$WORK_ROOT`为隔离实验目录，`$PRODUCTION_ROOT`仅作为准备阶段只读来源，`$EVIDENCE_ROOT`为本轮research复核目录。命令中的这些占位符需由复核者在其有权限的本地原件环境设置。

```bash
PYTHONPATH=src:tools "$PYTHON" -m pytest -q tests/test_recommendation_reader_first.py tests/test_recommendation_files_profile.py tests/test_normal_recommendation_files.py tests/test_pipeline_repair_acceptance.py tests/test_current_opportunity_review.py tests/test_d20_web_readiness.py tests/test_same_day_consistency.py
PYTHONPATH=src:tools "$PYTHON" -m pytest -q
"$PYTHON" research/recommendation-reader-first-20260922/scripts/prepare_samples.py --production "$PRODUCTION_ROOT" --output "$WORK_ROOT/sources"
PYTHONPATH=src:tools "$PYTHON" research/recommendation-reader-first-20260922/scripts/prepare_daily_root.py --production "$PRODUCTION_ROOT" --sources "$WORK_ROOT/sources" --root "$WORK_ROOT/daily-root"
PYTHONPATH=src:tools "$PYTHON" -u research/recommendation-reader-first-20260922/scripts/run_trials.py --work "$WORK_ROOT" --code "$CODE_ROOT"
```

这些模型命令是实际执行记录，不是邀请再跑一遍择优。完整顺序与两次确定性修复续跑、一次额度恢复见`integration/actual-commands.sh`；请求7的确定性协议重解析见`integration/reader-warning-correction.md`。runner要求既存冻结experiment-plan和对应代码SHA，终态trial拒绝重复。C4单点变更见cases/C4/source/change.diff。每一次真正调用在requests.json先保留号码，再记录终态、耗时、实际模型和用量。未使用的可选修订不是失败重试。模型金额费用没有可靠来源，写未提供。

H3从历史研究/复盘交付开始运行`complete`和`finish_nightly_success`；不是重新扫描全市场。独立数据根仅复制必要对象的事实子集（112个历史episode/候选代码、422个事实分区约31.6MB）以及95个保持原统计范围的派生分区；没有复制整个事实仓。子集元数据按既有校验更新，原始值、available_at及修订链不改写；公开provenance明确它不是原分区字节副本。数据库和整个事实仓不上传。

## 脱敏

只做路径占位、凭据/请求头去除及既有公开会话协议过滤。保留股票、日期、价格、条件、全文和所有模型的可见交付。不给隐藏推理、系统提示全文或私人任务全集。CLI公开rollout保留实际工具输入/返回及可见回复；不存在的内容不补造。

公开文件中的原有绑定哈希用于定位脱敏前实际输入；含路径的公开副本经机械替换后字节可能不同，不声称公开脱敏文件与私人原件哈希相同。作者/阅读/事实实际输入按阶段保存。标签证据在case台账，reader本身只收到文章及阅读标准。

## 部署与旧任务

`NOT_DEPLOYED`。不切换正式运行版本、不合并main、不更新生产页面、不启用夜间任务。旧正在运行/中断的文件任务留在原版本完成，或保持停止等待人工处理；不能把旧accepted或旧全材料审稿贴成新合同通过。部署及恢复夜间任务须由用户后续明确决定。回退仅需继续使用原生产版本，本轮未迁移生产数据。

额度中断原请求24和B2/后续not_run收据全保留。恢复时输入/会话不变，前面完成的作者和reader不重跑，后续请求从25累计。见[integration/quota-recovery.md](integration/quota-recovery.md)。H3原研究未决通过现有正常处理接线，见[integration/h3-unresolved-transfer.md](integration/h3-unresolved-transfer.md)。

隔离日常根还需要相同提交的代码文件：可在新隔离根中用 `git archive "$TESTED_CODE_SHA" src tools ops .agents | tar -x -C "$WORK_ROOT/daily-root"` 复制受控源码。这个命令是复现说明；本次现有隔离根的实际验证见[integration/isolated-code-check.json](integration/isolated-code-check.json)，158个文件与066129e逐字节相同。`prepare_daily_root.py`负责有范围的数据副本，不应被误解为单独完成代码根准备。

## 最终实际交付范围

真实业务代码、Prompt和自动测试冻结在066129e；最后材料提交还包含脱敏导出、实际链接/统计、生产状态解析及浏览器验收辅助脚本。实际材料导出、阶段顺序审计和脚本语法检查通过，命令与退出码见integration/qa-commands.jsonl；浏览器成功页面分支因H3未采用而未运行，不以语法检查替代。

全部53次请求及19项trial终态已保留；H3失败后没有追加请求，未用完的11次上限不是待继续重试额度。C组4份固定原文、A/B全部8篇、H1初稿、H2初稿及修订均直接可读。H3缺稿、无采用正文/正常页面/截图，原因和准确未运行阶段见integration/README.md；不创建空文件伪装交付。

公开历史复盘材料是本次日常回放实际需要的单日有界交付，并非整个生产归档或全市场行情。受限原件全文、完整事实仓及私人原协议留本地；公开必要事实、来源及实际供料，远端复核不能因此独立重建所有供应商数据获取步骤。

最终公开副本核对见[integration/delivery-audit.json](integration/delivery-audit.json)：15份实际文章逐字保留、JSON/CSV及索引链接有效、066129e之后业务代码/Prompt/自动测试未变。[最终脱敏检查](integration/privacy-check-final.json)未发现所列凭据、私人账户字段、真实本机路径或非公开协议事件；它是明确范围的机械检查，不宣称能证明所有供应商原件真实性。

暂存检查发现嵌套local_archive名称同样受仓库忽略规则保护，故仅将公开副本的目录改为integration/daily/forward_selection、forward_monitor和ai_tasks；原实验路径及内容不变，未修改.gitignore，未强制加入归档。原始文章、模型输出、统一diff与pytest日志的末尾空行/空白照存；Git全材料空白检查的非零结果单列，业务代码及辅助脚本格式检查通过。生成CSV统一为LF，未改字段内容。
