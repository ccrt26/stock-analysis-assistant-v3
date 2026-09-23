# 延江股份阶段输入索引

身份：300658.SZ 延江股份，形成日 2026-09-21，参与日 2026-09-22，研究截止 2026-09-21 18:30 +08:00。作者和核对者各自使用独立 `gpt-6-astra / xhigh` 文件会话。实际阶段提示分别在 [author-prompt.md](author-prompt.md) 与 [fact-check-prompt.md](fact-check-prompt.md)。

两者共同读取同一份权威 `input/packet.json`，公开复核副本在 [author-packet.json](../../evidence/author-packet.json)。该包由同版 [context-trace.json](../../evidence/context-trace.json) 与 [selection-handoff.json](../../evidence/selection-handoff.json) 确定性提取，包含最终选择意见、风险接受、反证、未知、实际财务及行情口径、原参与和撤回条件，且保留 `decision_trace` 中 `300658.SZ-price-risk-condition` 的全部 `formation_values`。原市场说明见 [research-reply.md](../../evidence/research-reply.md)。公开副本只替换本机路径，原运行中的 trace 绑定仍按未替换的原件验证。

作者还读取两篇在本次研究截止前已获认可、且非本股的范文全文及批注：中国巨石 `600176.SH`（形成日 2026-09-11）与国际复材 `301526.SZ`（形成日 2026-09-15）。原范文保存在既有知识库，不在本轮重复提交；它们只教表达，不作为延江事实来源。事实核对者没有收到范文或写作指南，只读取同版 `packet.json` 与实际 `input/article.md`。旧执行单、历史失败清单、上一轮审稿记录均未进入这两次输入。

研究中的关键原句位置：`final_selection.selected_stocks[0].selection_reason` 给出推荐力度、比较与风险取舍；`candidate_ledger[ts_code=300658.SZ].research_thesis` 给出业务、经营风险及重要未知；`decision_trace[decision_id=300658.SZ-price-risk-condition].formation_values` 保留价格区间、撤回动作、除息后比较；同版 `selection-handoff.json → stocks[300658.SZ]` 记录完整自然语言条件和可交易性。它们是核对时必须对应的含义，不是要求作者逐项照抄字段名。
