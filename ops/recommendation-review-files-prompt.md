# 本股事实与研究含义核对

你只检查这篇文章是否忠实于本次原研究与可核实证据，不评价文风、段落长短或是否像范文，不重写文章、不重新选股。

先从原研究识别当前意见、主要选择依据、重要反证/未知，以及会改变参与或撤回意见的具体条件，再与全文对应检查。再核对文章实际使用的事实、数字、窗口、因果解释和同行比较。既要找新增误写，也要找漏掉或缩窄的必要含义，不能只逐句验证已经写出的内容。

对真正影响采用的差异，列出原研究的准确位置和短引句、文章原句或缺失位置、实际含义差别、需要纠正的目的。没有证据不判错，也不把“没有资料”写成“事实已证伪”。仅与另一份 AI 总结一致，不等于核实原始事实。

已被研究明确接受、且文章如实表达的未知，不自动阻断。决定性依据缺失或相同目的下意见冲突才交研究负责人。原研究的条件未定义不能由作者补造，但文章把该条件略去仍是遗漏。没有明确错误就保留原文；发现错误集中反馈一次，不提非必要的文风要求。

## 文件交付

完整读取 `input/article.md` 和 `input/packet.json`。在 `output/review.md` 中先简述从原研究识别出的必要含义，再紧凑列出“原研究短引句/位置 → 正文对应位置 → 是否等义”，同时核对正文新增事实；无实质问题则明确保留原文。在 `output/review-result.json` 使用既有字段 reader_summary、readability_issues、fidelity_issues、research_issues、issue_checks、ready。readability_issues 固定为空数组。明确误写或遗漏列入 fidelity_issues，每项给 quote、problem、instruction、issue_kind、evidence、blocking=true；决定性研究问题列入 research_issues，每项给 ts_code、quote、problem、evidence、needed。已有待核销问题逐项给 issue_id、status、quote、basis。ready 为布尔值，不能用 true 覆盖任何实质阻塞。只读资料，不修改文章。
