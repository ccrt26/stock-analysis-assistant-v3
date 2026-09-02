---
name: reviewing-stock-recommendations
description: Use only after a stock was explicitly recommended, to compare the dated original thesis with actual price, sector, company and market developments and explain progress toward the 20-trading-day 20% observation target.
---

# 正式推荐复盘

## 唯一职责

本 Skill 不发现候选、不选择股票、不改变历史推荐，也不是第六个选股视角。

它只接收：

- 明确正式推荐的记录；
- 推荐日期和当时完整理由；
- 推荐后的价格与成交事实；
- 市场、行业、公司和价格四个 Skill 的 review 结果；
- 已有 `ForwardEpisodeReviewV1` 字段。

它负责把这些事实合成一份用户能理解的复盘。

## 每次必须回答

1. 这只股票在具体哪一天开盘前被推荐；
2. 当时最重要的判断是什么；
3. 当时期待随后看到什么；
4. 到今天观察了多少个交易日；
5. 当前收盘涨跌、期间最高、期间最深下跌；
6. 距离20%观察目标还有多少个百分点；
7. 后来的事实为什么支持或反对当时判断；
8. 哪一项预期实现了，哪一项没有实现；
9. 现在应评价为继续成立、明显减弱、已经不成立或暂时无法判断；
10. 接下来哪件具体事情会改变结论。

## 分析原则

- 股票上涨不自动证明当初理由正确；必须比较市场、同行和原预期。
- 股票下跌也不自动证明公司事实错误；要指出失败发生在哪一层。
- 不按每天1%的线性速度评价。
- 停牌期间不虚构价格进展；先说停牌前走到哪里，再说新公告怎样改变公司背景，最后说明复牌后需要验证什么。
- 一条无关月报、公告标题或局部数据缺失不能决定整只股票的结论。
- 能用已有价格、行业和公司事实分析时，不得把整段结论写成“资料不足”。
- 不使用“冻结时点、冻结结论、原逻辑、传播链、正常双向成交”等用户难以理解的词。
- 必须使用具体推荐日期，并以正式推荐记录的 `action_date` 为准。
- 不新增定时任务，不新增报告模型或 schema。

## 输出

继续填写现有 `ForwardEpisodeReviewV1`，不增加schema。

`original_reason_plain_language`：
写成“该股票在YYYY年M月D日开盘前被推荐，当时主要因为……”。

`current_review`：
必须包含“当时预期 → 实际变化 → 为什么支持或反对 → 当前结论”。

其他枚举只供内部记录，不直接显示给用户。
