# 实际自动测试记录

最终测试代码为 `066129e1641c4d1fc55fbb3568527a6f88e35525`；恢复入口之外的写作/审稿行为与dd33一致。

| 运行 | 结果 | 原始日志 |
|---|---|---|
| 规定基线五文件 | 113通过 | [baseline.log](baseline.log) |
| 新行为对旧实现 | 12失败，证明原行为不满足 | [three-mechanisms-before.log](three-mechanisms-before.log) |
| 初次相关 | 158通过、7失败 | [targeted-01.log](targeted-01.log) |
| 第二次相关 | 164通过、1失败 | [targeted-02.log](targeted-02.log) |
| 第三次相关 | 172通过、1失败 | [targeted-03.log](targeted-03.log) |
| 第四次相关 | 174通过 | [targeted-04.log](targeted-04.log) |
| 去除作者旧条件副通道后 | 174通过 | [targeted-final.log](targeted-final.log) |
| 首轮全量 | 1791通过、3失败、1跳过 | [full-suite-01.log](full-suite-01.log) |
| 相同失败在原始基线复现 | 3失败 | [baseline-full-failures.log](baseline-full-failures.log) |
| 初次冻结代码全量 | 1791通过、3失败、1跳过 | [full-final-02.log](full-final-02.log) |
| 最终真实文字专门验证 | 1通过 | [final-prose-path.log](final-prose-path.log) |
| 原便笺权威通道修正 | 138通过 | [authority-wiring-fix.log](authority-wiring-fix.log) |
| 原便笺修正版本相关文件 | 176通过 | [targeted-0ffe.log](targeted-0ffe.log) |
| 原便笺修正版本全量 | 1793通过、3失败、1跳过 | [full-0ffe.log](full-0ffe.log) |
| CLI警告误计复现 | 1失败、3通过 | [reader-warning-before.log](reader-warning-before.log) |
| CLI证据解析修正受影响文件 | 199通过 | [reader-warning-fix.log](reader-warning-fix.log) |
| 最终dd33规定相关文件 | 180通过 | [targeted-dd33.log](targeted-dd33.log) |
| dd33全量 | 1797通过、3失败、1跳过 | [full-dd33.log](full-dd33.log) |
| 额度恢复最终相关文件 | 188通过 | [targeted-quota.log](targeted-quota.log) |
| 恢复保留原失败断言 | 8通过、57未选中 | [quota-history-assertion.log](quota-history-assertion.log) |
| 最终066129e全量 | 1805通过、3失败、1跳过 | [full-quota.log](full-quota.log) |

[commands.jsonl](commands.jsonl)保留每次记录的真实命令、时间、耗时与原退出码；不同记录工具的time字段为完成时间，不能冒称统一采集了开始时间。全量复跑原因分别是供料代码变化、原便笺权威通道修正、CLI警告计数修正和严格额度恢复入口。未为凑全绿删测试或降低断言。

三个失败均非本轮新增：公司介绍测试的历史合成trace不满足基线已存在的18项V4字段要求；两项Prism测试读取checkout下真实交易日历，而隔离代码根没有该本地日历。对应原始基线复现日志已保存。它们仍然是失败，不能写“全量通过”。跳过项按日志原样保留，不等同通过；条件跳过是test_render_prism_web.py::test_render_html_embeds_payload_verbatim：所需sample snapshot属于git-ignored本地文件，隔离代码根没有该文件（原reason：sample snapshot stays local (git-ignored)）。

测试仅模拟外部模型边界，不能作为真实文章质量证明。另有一次早期12项通过的探索性运行，已从本任务原始可见工具回执补取[完整stdout](early-12-passed.log)、真实命令、时间与退出码；恢复来源写入commands.jsonl。没有提取隐藏推理或其他任务记录。最终188项和全量覆盖其行为。
