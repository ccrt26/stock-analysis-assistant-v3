# 本地研究知识库阅读索引

本页只帮助 ChatGPT 找到仓库中已经存在的研究资料，不新增规则、不复制数据库。

## 建议先读

1. [五 Skill 短期上涨发动机定向优化报告](2026-08-21-a-share-short-term-upside-engine-tuning-report.md)
2. [短期上涨发动机第二次收口报告](2026-08-21-short-term-engine-gap-closure-report.md)
3. [今日四只股票结果与详细复盘](2026-08-21-daily-selection-review.md)
4. [方正科技五个 Skill 的完整逻辑](2026-08-21-founder-technology-five-skill-analysis.md)
5. [A股短期定价与公司业绩讨论](2026-08-21-a-share-earnings-and-short-term-pricing.md)
6. [当前 V3 架构](architecture/current-v3-architecture.md)

## 五个研究 Skill

- [总控研究](../.agents/skills/orchestrating-stock-research/SKILL.md)
- [市场环境](../.agents/skills/interpreting-market-macro/SKILL.md)
- [板块与行业](../.agents/skills/researching-sectors-industries/SKILL.md)
- [公司与事件](../.agents/skills/researching-company-events/SKILL.md)
- [价格与交易](../.agents/skills/analyzing-price-trading/SKILL.md)

## 知识库文件

- [research_registry.yaml](../src/stock_analyzer/knowledge/research_registry.yaml)：官方规则、论文来源、知识条目、允许用途和禁止外推边界。
- [supplement_validation_results.yaml](../src/stock_analyzer/knowledge/supplement_validation_results.yaml)：动量、换手、盈利、现金质量等本地验证摘要。
- [market_skill_validation_results.yaml](../src/stock_analyzer/knowledge/market_skill_validation_results.yaml)：市场宽度、成交、分化和趋势状态验证结果。
- [direct_validation_results.yaml](../src/stock_analyzer/knowledge/direct_validation_results.yaml)：可直接复算的方法验证。
- [targeted_gap_validation_results.yaml](../src/stock_analyzer/knowledge/targeted_gap_validation_results.yaml)：针对资料缺口的验证摘要。
- [market_skill_evidence.yaml](../src/stock_analyzer/knowledge/market_skill_evidence.yaml)：市场 Skill 当前可使用的证据登记。
- [market_skill_hypotheses.yaml](../src/stock_analyzer/knowledge/market_skill_hypotheses.yaml)：市场假设及验证边界。
- [price_scenario_thresholds_v3.json](../src/stock_analyzer/knowledge/price_scenario_thresholds_v3.json)：价格场景研究阈值及用途限制。
- [rules.seed.yaml](../src/stock_analyzer/knowledge/rules.seed.yaml)：少量基础研究规则种子。

这些文件和五个 Skill 原本已经由 Git 跟踪；本次新增索引，让 ChatGPT 可以直接找到并按顺序阅读。

## 没有上传的内容

本地行情事实仓、正式运行归档、缓存、日志和凭据不属于可公开知识文档，因此没有上传。论文只登记来源、方法和本地验证摘要，不上传论文全文。
