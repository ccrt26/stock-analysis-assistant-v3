# 同股意见交接修复与 9 月 23 日续跑

## 固定范围与原件结论

审计基线：aa28ef42620466d53f7c647493ad6cf090fe3a79。
任务 nightly-rerun-2026-09-24：形成日 2026-09-23，行动日 2026-09-24，截止 2026-09-23T18:30:00+08:00。
实施按本次 GPT-6 Sol xhigh；业务保持 Astra xhigh / ChatGPT / astra-files-v1 / state-change-v1 / no-fallback。

原 CO-1 与 selection 答复的必要原文保存在测试夹具 tests/fixtures/recommendation_authoring/owner_handoff_co1.json，均来自本任务原件。
原 selection 已决定修正报价范围，原未决是 monitor 当前参与意见及作者正文待处理；
同版交接明确标记 selection_resolved_monitor_and_author_pending，绑定当前研究。
不是 selection 自身研究未知。代码不按这段中文关键词推断，也不删除历史 unresolved。

## 改动对应

- validate_owner_answer：同 ID 可跨 resolutions/unresolved，仍保留未决；同数组重复、错身份、漏项拒绝。
- 原交付恢复：核对原输入、实际 request、session 协议中的 user/final、模型与档位；不以今天 Prompt 是否相同判定重跑。
- owner_handoff_status：只有同 issue / code / episode、同版明确职责、真实 monitor 答复及本日字段引句才能闭合前方待办。selection 自身未知、monitor 自身未决不能关闭。
- resolve_current_opinion_owners：保留原答复及 before-owners，调用缺失 monitor 一次；缓存也从原交付核对。只允许受影响 episode 的当前意见和正文改变，保护历史与 D20。
- complete：已打开协调先恢复负责人，再进入作者及第二次同股核对。
- 作者衔接：原研究问题仍保留；派生已处理交接供作者使用，不再次触发研究。传递完整原稿（包括标题），保持已有一次修订预算和逐股缓存。
- run_stage：只将当前 monitor 负责人纳入本任务文件配置的 Astra xhigh，不改全局路由。
- 同股核对 Prompt：核对真实交接及当前正文，不因历史 unresolved 原句仍在而自动否决，也不能自动判 ready。

不改 D20、三态方法、已安装范文、普通作者 Prompt、选股 Skill、WEB 布局、调度或全局路由。

## 测试与离线核对

先收集后执行 tests/test_owner_handoff_resume.py，12 项，无参数化额外展开。
原代码在完成夹具后复现 12 failed；最终 12 passed in 4.82s。
中间失败包括测试假数据校正，以及真实完整原稿标题衔接问题；仅反复执行此集合，未跑全仓或旧集合。
修复验收真实业务模型会话 0。

| 节点 | 验证 |
|---|---|
| T01 | 原 CO-1 中途答复，重复/错身份/漏项拒绝 |
| T02 | 原 selection 输入、输出、回执保留，仅调用缺失 monitor |
| T03 | 真实回复闭合当前待办，历史未决不删除 |
| T04 | 自身未知、错范围、错引句、错 episode、无依据、monitor 未决不关闭 |
| T05 | complete 先负责人，普通作者、研究、首次核对不得抢跑 |
| T06 | monitor 完成后恢复零调用，坏输入/缓存拒绝 |
| T07 | 三篇已有正文，仅修改受影响一篇，其余两篇复用 |
| T08 | 原第二次核对与修订预算；耗尽不得增加调用 |
| T09 | 同股另一 episode 保护；36 条保存、3 条仅内部 D20 保留 |
| T10 | 当前真实引句、语义结果与 ready 一致，未通过不保存 |
| T11 | 假模型接真实 record/freeze/CSV/日报、公司介绍补缺复用及页面读取 |
| T12 | monitor 实际配置 xhigh/禁备用；原行动日入口 |

真实原件离线预检：当前 pending 合同、36 条/34 股、3 条 internal_only 有效；
原 selection 请求与协议通过；首个缺失阶段为 current-opinion-owner-monitor；
原始检查已用 1/2；药石 initial=1、expression=0、clarification=0；
艾德 expression=1/clarification=1，瑜欣 expression=1/clarification=2；
既有 18 个业务会话与所有回执保留，22 个用户已有未提交文件未变。

## 正式续跑

修复已通过离线验收。真实业务、最终日报及发布结果在完成后追加本目录；
本节不是业务完成声明，不以草稿代替最终日报。
