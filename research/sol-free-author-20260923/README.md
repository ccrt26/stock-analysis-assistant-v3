# 两篇自由成稿试点（2026-09-23）

这是两份截至 **2026-09-20 18:30 +08:00** 的历史研究表达试写；原行情形成日为 9 月 18 日，原参与日为 9 月 21 日。正文不是 9 月 23 日的新买入建议。每股只进行了一次独立写作和一次独立事实核对，首稿与核对的可见文字原样保存；仅将临时文件链接目标改为本目录对应文件。

| 股票 | 实际首稿 | 一次事实核对 | 本次结果 |
| --- | --- | --- | --- |
| 飞凯材料 300398.SZ | [正文](300398.SZ/article.md) | [核对](300398.SZ/fact-check.md) | 未发现明确误写；原研究未定义“持续向下跌破36.97元”的时长和盘中回到区间的判法。 |
| 德冠新材 001378.SZ | [正文](001378.SZ/article.md) | [核对](001378.SZ/fact-check.md) | 未发现可证实的误写；原研究未定义“持续跌破23.18元”与“回款继续恶化”的执行口径；本阶段材料不足以独立复核国恩比较的原始值。 |

飞凯稿把当日参与范围和参与后撤回条件区分得较清楚，但末段条件较密。德冠稿交代了涨停前后的普通日承接和较高参与成本，结尾的条件也需要读者慢一些看。这只是外层阅读观察，作品是否值得采用仍由用户和 ChatGPT 判断。

## 研究原件和输入

- 两股使用同一历史身份及同版完整研究包，分别见 [飞凯研究原件](300398.SZ/research.json)、[德冠研究原件](001378.SZ/research.json)。它们是固定证据提交 [89590074518ddccf8bde7c43c5749ae725ed98dd](https://github.com/ccrt26/stock-analysis-assistant-v3/commit/89590074518ddccf8bde7c43c5749ae725ed98dd) 中 [D1/source/packet.json](https://github.com/ccrt26/stock-analysis-assistant-v3/blob/89590074518ddccf8bde7c43c5749ae725ed98dd/research/recommendation-reader-first-20260922/cases/D1/source/packet.json) 和 [H2/source/packet.json](https://github.com/ccrt26/stock-analysis-assistant-v3/blob/89590074518ddccf8bde7c43c5749ae725ed98dd/research/recommendation-reader-first-20260922/cases/H2/source/packet.json) 的直接副本。相较本地包，只脱敏了 authoring_note.source_refs 中的本机根路径，研究判断没有改写。
- 字段和原始计算位置见 [飞凯来源图](300398.SZ/source-map.md)、[德冠来源图](001378.SZ/source-map.md)，各股 `evidence/` 存放所用计算文件中本股对象的直接摘录。两位作者使用相同的 [中国巨石](examples/01-中国巨石.md) 与 [国际复材](examples/02-国际复材.md) 认可范文。事实核对会话没有收到范文。
- 实际短提示为 [作者](prompts/author.md) 和 [事实核对](prompts/fact-check.md)；[执行单](execution.md) 只由外层读取，没有交给作者或核对者。[调用脚本](run_sol_stage.sh) 是实际使用版本。
- 会话原文里的临时文件链接目标已映射为本目录同名文件，链接显示文字、文章正文和核对结论未改。原始 CLI 交付仍留本机；未另造公开出处。

## 运行记录与范围

[四次会话记录](runs.tsv)列出开始、结束、耗时、会话 ID、请求和本地会话记录报告的模型与档位，以及 CLI 可提供的 token 用量。四次均成功退出，累计耗时 **587 秒（9 分 47 秒）**。外层任务及四次业务会话的本地 `turn_context` 均报告 **gpt-6-sol / xhigh**；登录检查报告 ChatGPT 登录。脚本未设置 Fast，并忽略用户全局配置；客户端未单独报告实际服务速度档位，因此不把请求的 Standard 冒充独立测量。原始 CLI 事件和会话日志保留本机，未上传隐藏推理或认证文件。

本轮没有修改生产代码、原推荐、定时任务或正式流程；没有运行 pytest、全仓回归、WEB 渲染或浏览器验收。研究试点未部署，也未接入日常任务。发现的原研究歧义和证据缺口没有在本轮补造或通过重写首稿掩盖。
