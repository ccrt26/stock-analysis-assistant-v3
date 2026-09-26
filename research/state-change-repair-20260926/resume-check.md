# 原任务刷新与恢复核对

形成日2026-09-23；行动日2026-09-24；截止2026-09-23T18:30:00+08:00。原任务nightly-rerun-2026-09-24，独立Astra研究及同版pending/交接/市场说明保留；研究来源及trace绑定核对通过。原取消state和失败monitor回执保留，state仅追加本任务xhigh覆盖。

| episode | 刷新前 | 刷新后 |
|---|---|---|
| formal:2026-08-25:002274.SZ:selected | 已冻结仍待结案 | 从日评/结案待办移除，原not_executable保留 |
| formal:2026-08-25:300473.SZ:selected | 已冻结仍待结案 | 移除，原正常观察期完成保留 |
| formal:2026-08-25:603408.SH:selected | 已冻结仍待结案 | 移除，原正常观察期完成保留 |
| formal:2026-08-26:300082.SZ:selected | 旧停止欠结案 | 保留，原9月4日live停止依据，历史三态仍未知，仅internal_only |
| formal:2026-08-26:301289.SZ:selected | 旧停止欠结案 | 保留，原9月3日live停止依据，历史三态仍未知，仅internal_only |
| formal:2026-08-26:603993.SH:selected | 旧停止欠结案 | 保留，原9月2日live停止依据，历史三态仍未知，仅internal_only |

定向移动9月23日snapshot/input-index到原任务pre-fix-monitor；本次无pending复盘草稿可搬。旧monitor提示/回执复制备份，原路径保留供原state溯源。仅调用prepare_forward_monitor重建一次，未重新准备选股。

待日评由39变为36条、34只股票，集合严格等于旧集合减去上述3条已完成episode；4条D20待办包括3条旧停止和另一条正常到期记录。全部episode和原市场/价格/条件保持；变化仅结案状态/统计、原停止与冻结来源、上一判断日期元数据，以及3条完成记录与其2个比较对象不再获得AI复盘价格上下文。未替换底层行情或原推荐。

新monitor使用原任务下新会话，未恢复旧取消monitor会话；request记载Astra xhigh、ChatGPT、fallback=false、resumed_session_id=null。研究阶段不再调用。本次停止后的核对结果如下。

## 停止时实际成果

复盘仅保存于本任务pending草稿，尚未record。36条中28条brief（按股合并为26篇简单复盘）、5条regular_detail、3条internal_only；公开正文共31股。3条旧停止的D20对象已由业务模型写入草稿，current_review/current_opportunity均为null，原停止理由保留为thesis_invalidated；不能称为已正式结案。奥克缺失原窗口末段行情，结果保留未知，没有补猜。

另1条D20为建新股份formal:2026-08-26:300107.SZ:selected，草稿结束原因为observation_complete，与原判断失效分开；同股飞凯的3条episode共用一份当前正文，原身份分别保留。

结案与范文修复后的原研究已复用。定向集中研究补充了原比较对象证据；后续同股CO-1使药石本次报价范围与等待条件发生实质修正，未增加股票、未重扫或改变时间身份。该修正尚未经过后续作者/复盘及再次同股核对，因此不能冻结。

末次确认：9月22日trace、日报、A2历史页、snapshot/index、正式复盘JSON/Markdown/账本及3份公司介绍共11份保护文件逐字未变。原research-reply和本地配置也未变。9月23日pending trace与handoff因上述获准研究纠错而改变，原版备份保留；没有宣称这两份仍不变。用户20项未提交/未跟踪文件保持，未纳入本次提交。
