# 状态变化复盘 v1

新建晚间任务把 `monitor_review_policy=state-change-v1` 绑定进 run_policy；snapshot、日评账本和报告保存相同策略。旧任务及旧档案继续按旧 Prompt 和记录语义读取。

三态属于每次正式推荐 episode：`follow` 表示原上涨依据仍在；`wait` 表示出现相关疑点但尚未否定，须写等待条件；`ended` 表示原判断失效或观察期完成，另记结束原因。缺资料保留上次实际判断日期或空值，不据此改态。同股当前事实与参与意见共用，原依据、条件、状态及 D20 结果分别保存。

状态不变或首次登记使用简单复盘；真实 `follow↔wait`、`follow/wait→ended` 使用状态变化复盘，一股一份正文，不设名额。节点保存原事实和简短判断，D20 固定结案留内部，不另生成公开长文。已结束 episode 普通日不再让 AI 重判，欠 D20 时仅补内部结果。

供料索引按股共用当前市场、行业、行情与公告，逐 episode 保留原依据、风险和条件；从 Obsidian 状态跟踪三份资料中选同一套，只有不可读时才用仓库同版副本。业务执行见活动复盘 Skill 与 `ops/forward-monitor-prompt.md`，旧任务见 legacy Prompt。
