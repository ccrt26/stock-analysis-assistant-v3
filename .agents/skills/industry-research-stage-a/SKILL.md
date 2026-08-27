---
name: industry-research-stage-a
description: Use when an industry topic must move from final demand and payer to bounded seven-view industry structure, precise product nodes, listed/non-listed company leads, local capability support, and a stage-A package for quantitative verification.
---

# A阶段：开放式产业研究

## 必须先读

1. 根 `AGENTS.md`；
2. `docs/industry-research/00_逐步执行操作手册.md`；
3. `docs/industry-research/01_全局执行规范.md`；
4. 当前运行的 `00_研究范围.yaml`、`00_运行状态.yaml`、`00_下一步操作.md`；
5. `methodology/` 中 V1—V4 与当前步骤相关部分。

## 角色门

只执行 `00_运行状态.yaml.current_step`。执行者与 `next_actor` 不一致时停止。每次完成后更新 `00_运行状态.yaml` 和 `00_下一步操作.md`，角色切换时停止。

## 第2步：ChatGPT初步开放研究

完成 V1 四张图与四种状态、V3 范围/七视图/完整性/非上市公司/未知，以及 V2 精确节点、公司发现和关系证据前半段。

必须输出：

- `01_A_ChatGPT初步研究报告.docx`
- `01_A_交给Codex.yaml`
- `01_A_证据清单.csv`

报告必须写明：范围与as_of、最终需求与付款人、四张图、七视图、精确节点、上市与非上市线索、身份/能力/认证/供货/订单/收入分层、反向替代、冲突、未知和逐实体本地任务。

禁止：估值结论、K线筛选、固定公司数量、买入名单。完成后下一步指向第3步/Codex。

## 第3步：Codex本地支持

校验交接；审计本地数据覆盖；补证券代码、曾用名、子公司、品牌和本地数据身份；从主营、公告元数据和行业/主题目录补“待核线索”；保存点时状态和数据缺口。

必须输出：

- `02_A_Codex本地支持摘要.md`
- `02_A_Codex本地支持.json`
- `02_A_数据缺口.json`
- 必要时 `02_A_冲突记录.yaml`

禁止从关键词、主题成员、公告标题、专利或认证认定供应关系；禁止运行现有最终选股。完成后下一步指向第4步/ChatGPT。

## 第4步：ChatGPT复核与A阶段定稿

检查三道地基门：产业链完整性、数据可获得性、证据可靠性。严格区分线索、身份、能力、关系和规模。

若确有决定性问题，最多输出一次 `03_A_定向补查请求.yaml`，只列有限实体/字段/冲突，交 Codex 补查后再回本步骤；不得无限循环。

通过时输出：

- `03_A_最终研究报告.docx`
- `03_A_交给B阶段.yaml`
- `03_A_证据清单.csv`

A最终包必须明确进入B的实体、精确节点、供应角色、证据等级、需核查字段、升级/失效条件、未知、冲突与review_due。用户批准后下一步指向第5步/ChatGPT。
