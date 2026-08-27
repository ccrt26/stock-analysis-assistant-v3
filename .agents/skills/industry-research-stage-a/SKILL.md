---
name: industry-research-stage-a
description: Use when a topic must be scoped by ChatGPT, researched through final demand, payer, four maps and seven views, supported by Codex local capability/entity checks, and finalized by ChatGPT before quantitative verification.
---

# A阶段：开放式产业研究 V3.0

## 角色顺序

启动范围由 ChatGPT起草、用户批准、Codex落库。正式A阶段为：ChatGPT A1 → Codex A2 → ChatGPT A3。Codex不得要求用户填写产业范围技术字段。

## 启动步骤：ChatGPT研究范围草案

第一次默认使用V3确定的液冷端到端可行性试点。ChatGPT输出 `00_研究启动说明.docx`、`00_研究范围.yaml`、`00_下一步操作.md`；用户只批准。Codex随后原样落库、创建分支、commit并push，不做研究。

## A1：ChatGPT产业结构与初步线索

完成最终需求与付款人、V1四张图和四种状态、V3七视图与替代/自制/未知、精确节点词典、第一轮上市/非上市线索和逐项本地支持请求。

输出：
- `01_A1_产业结构与初步线索报告.docx`
- `01_A1_本地支持请求.yaml`
- `01_A1_证据清单.csv`
- 更新 `00_下一步操作.md`

禁止本地财务/估值结论、固定公司数量和买入名单。

## A2：Codex本地支持

先原样保存A1文件，再校验范围、节点、实体和证据ID；补曾用名、子公司、品牌、证券代码和本地身份；审计本地数据覆盖；节点词典扫描只可补待核线索。

输出：
- `02_A2_本地支持摘要.md`
- `02_A2_本地支持.json`
- `02_A2_数据缺口.json`
- 必要时 `02_A2_冲突记录.yaml`

必须commit+push。禁止从关键词、主题成员、公告标题、专利或认证认定供应关系。

## A3：ChatGPT完成A阶段

复核上市/非上市关系；严格区分身份、能力、认证、供货、订单、重复交付、收入、利润和现金；检查替代、客户自制、二供、潜在进入者、冲突和未知；验收产业链完整性、数据可获得性、证据可靠性三道地基门。

输出：
- `03_A_开放式产业研究最终报告.docx`
- `03_A_交给B阶段.yaml`
- `03_A_证据清单.csv`
- 更新 `00_下一步操作.md`

最多一次有限定向补查。最终包必须写清进入B的实体、节点、供应角色、证据等级、字段、升级/失效条件和review_due。
