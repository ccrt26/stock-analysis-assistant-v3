# 推荐文章 reader-first：完整复核入口

**QUALITY_NOT_ESTABLISHED：新reader仍放过用户明确指出难读的C2，B4还出现事实漏检。** 三机制已实现，但固定对照仍反复出现条件表达不清，不能把事实核对通过或供料缩减等同于好文章。内容质量等待用户与ChatGPT复核，部署状态为 **NOT_DEPLOYED**。

固定计划共19项：4次说明整理、8篇A/B写作对照、4篇C组原文审查和3个H留出；H组每篇初稿后最多一次集中修订，全部阶段请求累计上限64。

最终19项中9完成、10失败、0项仍为not_run；失败包含8篇已写出但未通过的A/B稿、N-H3整理和H3入口。15个固定正文目标中14个有全文，H2另保留1份修订，共15份实际文章版本；H3未写出文章。53/64次业务请求（50次执行完成、2次中断、1次额度失败）；原9项额度所致not_run历史均保留。完成控制试验不等于内容通过，C2实际漏放。

H1初稿通过双审；H2初稿有两项遗漏、一次修订后通过；H3停在澄清合同冲突，后续采用/页面/浏览器步骤未运行。生产37项目标核对保持，夜间仍禁用且未加载。详细计数和生产核对见[结论](conclusion.md)、[全部试验CSV](results.csv)、[实际请求台账](requests.json)及[统计](run-statistics.json)为准；失败、中断和原not_run收据均保留，各trial的history可直接阅读。

## 建议复核顺序

1. [执行单全文](execution-spec.md)、[独立方案审查记录](independent-plan-review.md)与[采用的通过版](execution-plan.md)，再看[实际基线](baseline.md)。
2. [三个机制及每个改动文件映射](changes.md)、[测试全部结果](tests/README.md)、[实际阶段顺序和输入边界](integration/stage-order.json)。
3. 阅读下表全部文章和审稿，不只看通过稿；[逐篇内容观察](content-observations.md)是待复核意见，不代替原文。
4. [隔离日常入口范围](integration/replay-scope.md)、[H3完整执行](trials/H3/README.md)、[日常入口及页面证据](integration/README.md)。
5. [版本、命令与脱敏边界](delivery.md)、[最终结论与运行影响](conclusion.md)。

## 实际代码版本

- baseline：`61f0ebbd719845e44aae3fb5449f0b74b15bf1ad`。
- 最终 tested code：`066129e1641c4d1fc55fbb3568527a6f88e35525`。
- 早期真实请求分别使用`17ad21b`、`0ffeae1`、`dd33e77`，每一请求实际SHA见台账；不把旧运行冒称最终版本重跑。写作提示与正式试验材料未按试验优劣调参。
- 066129e只新增用户授权后的严格额度恢复及验收工具；原B2失败保留，原session续接，作者与reader不重跑。详见[额度恢复](integration/quota-recovery.md)。最后证据提交的远端HEAD在交付回执中实查提供。
- [全部分支差异](https://github.com/ccrt26/stock-analysis-assistant-v3/compare/61f0ebbd719845e44aae3fb5449f0b74b15bf1ad...fix/recommendation-reader-first-20260922)。

## 全部固定对照与留出

每个“完整执行”入口列出实际请求、全输入、可见交付、审稿及失败历史。文章链接不是择优副本；H初稿与至多一次修订同时保留在阶段目录。

| 试验 | 含义 | 全文 | 全部阶段与意见 |
|---|---|---|---|
| A1 | 第一轮旧供料 | [文章](trials/A1/article.md) | [完整执行](trials/A1/README.md) |
| A2 | 第一轮当前供料 | [文章](trials/A2/article.md) | [完整执行](trials/A2/README.md) |
| A3 | 第二轮当前供料 | [文章](trials/A3/article.md) | [完整执行](trials/A3/README.md) |
| A4 | 第二轮旧供料 | [文章](trials/A4/article.md) | [完整执行](trials/A4/README.md) |
| B1 | 第一轮旧修订供料 | [文章](trials/B1/article.md) | [完整执行](trials/B1/README.md) |
| B2 | 第一轮当前修订供料 | [文章](trials/B2/article.md) | [完整执行](trials/B2/README.md) |
| B3 | 第二轮当前修订供料 | [文章](trials/B3/article.md) | [完整执行](trials/B3/README.md) |
| B4 | 第二轮旧修订供料 | [文章](trials/B4/article.md) | [完整执行](trials/B4/README.md) |
| C1 | 用户认可原文及其原研究 | [原文](cases/C1/source/article.md) | [新旧审稿](trials/C1/README.md) |
| C2 | 用户指出难读的历史WEB全文 | [原文](cases/C2/source/article.md) | [新旧审稿](trials/C2/README.md) |
| C3 | 真实长文，认可标签未确认 | [原文](cases/C3/source/article.md) | [新旧审稿](trials/C3/README.md) |
| C4 | 合成AND→OR挑战，仅一处改动 | [挑战文](cases/C4/source/article.md) | [新旧审稿](trials/C4/README.md) |
| H1 | 诺瓦星云留出 | [全部稿件与状态](trials/H1/README.md) | 同入口含初稿及修订 |
| H2 | 德冠新材留出 | [全部稿件与状态](trials/H2/README.md) | 同入口含初稿及修订 |
| H3 | 延江股份留出及正常入口回放 | [全部稿件与状态](trials/H3/README.md) | 同入口含未决处理和真实保存结果 |

四个真实说明整理阶段：[N-D1](trials/N-D1/README.md)、[N-H1](trials/N-H1/README.md)、[N-H2](trials/N-H2/README.md)、[N-H3](trials/N-H3/README.md)。N-H3原未决没有删掉，见[原交接](trials/N-H3/stages/research-handoff-files-1/output/handoff.json)。[C组用户标签依据](baseline-label-evidence.md)与[C4精确差异](cases/C4/source/change.diff)不进入被测reader输入。

## 需要重点复核的真实位置

- [A1](trials/A1/article.md)的“新的重大不利公告”与[A2](trials/A2/article.md)的“新的重大不利公告或变化”：当前供料保留了更广的原研究取消条件；它不是可以为了短文删掉的内容。
- [C2新reader](trials/C2/stages/reader-files-1/output/review-result.json)称“增加了理解，不构成需要删除的重复”并通过，但[用户原标签](baseline-label-evidence.md)明确指出该稿啰嗦、反复、难读；这是本轮阅读审查未达预期的直接证据。
- [B4事实审稿](trials/B4/stages/review-300398-SZ-files-1/output/review.md)把权威研究的“重大不利变化”缩写成“重大不利公告”并给出通过，正文确实漏掉更广触发；这是事实审查稳定性的具体反例。
- [H2初次事实审查](trials/H2/stages/review-001378-SZ-files-1/output/review-result.json)发现原研究的“失去涨停后接受区则撤回”没有传入当前说明及初稿。完整权威核对在本例救回必要含义，但清理本身仍有遗漏；D1说明也仍有过程性文字。
- [H3澄清结果](trials/H3/stages/articles/300658.SZ/research-clarification-files-1/output/resolution.json)将同一问题同时列入retained_unknown与unresolved，入口因此失败。N-H3的原研究问题和所有失败保留，页面未验收。

实际reader能力证据见[离线请求捕获及真实运行配置](integration/reader-capability-proof.md)。只有文章/阅读标准先行这一接口已经有实际证据；它是否能稳定符合用户的阅读标准，仍要看全部固定样本。未部署、未开启正式夜间任务，生产WEB状态以[生产核对](integration/production-after.json)为准。
