# V3 Golden Research Samples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This project explicitly prefers inline execution and does not require subagents.

**Goal:** 建立四个严格时点、证据可追溯、能回答用户四个验收问题的黄金研究样本，为后续研究合同和技术实现提供不可降低的行为基准。

**Architecture:** 本阶段不修改运行代码，不生成新名单。仓库只保存本计划；全部证据清单、研究过程、合格/不合格对照、验收记录和哈希清单写入 U 盘 `golden-samples` 专用目录。每个案例先冻结形成日与可见证据，再由当前任务逐股研究，最后进行跨案例防模板化比较。

**Tech Stack:** Markdown、JSON、SHA-256、现有本地事实库和 U 盘不可变产物、形成日前官方公告/年报、现有知识库、Codex 受证据约束分析。

**Status Authority:** 本计划不声明当前生产能力；生产能力现状唯一以 `docs/operations/production-capability-matrix.md` 为准。

## Global Constraints

- 最高级合同：`docs/superpowers/specs/2026-07-19-v3-repair-governance-master-design.md`。
- 研究层设计：`docs/superpowers/specs/2026-07-19-v3-evidence-to-judgment-repair-design.md`。
- 不修改 V01—V03、2026-07-17 形成批次和任何既有 U 盘不可变产物。
- 不使用形成日之后的行情、公告、财务或未来结果形成当时结论。
- 历史实践样本只评价研究行为，不因已经知道的后续涨跌改写当时结论。
- 所有新增运行产物只写 `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/golden-samples/golden_sample_version=v3-golden-sample-01/`。
- 不激活旧生产任务，不写 Supabase，不发布，不自动交易，不扩展生命周期、卖出、止损、仓位或交易成本。
- 不修改任何 Python 代码或测试；本阶段的“测试”是严格时点、证据身份、推理完整性和真实读者验收。

---

## File Map

仓库新增：

- `docs/superpowers/plans/2026-07-19-v3-golden-samples.md`：本阶段唯一实施计划。

U 盘新增：

- `golden-samples/golden_sample_version=v3-golden-sample-01/README.md`：样本范围、用途、边界和用户四问入口。
- `golden-samples/golden_sample_version=v3-golden-sample-01/manifest.json`：版本、案例身份、文件哈希和来源身份。
- `golden-samples/golden_sample_version=v3-golden-sample-01/cross-case-comparison.md`：四案例差异、禁止套用项和研究合同候选规则。
- `golden-samples/golden_sample_version=v3-golden-sample-01/cases/formation_date=2026-07-17/301257.SZ/evidence-ledger.md`：普蕊斯形成日前证据账本。
- `golden-samples/golden_sample_version=v3-golden-sample-01/cases/formation_date=2026-07-17/301257.SZ/original-failure-analysis.md`：旧报告为什么不合格。
- `golden-samples/golden_sample_version=v3-golden-sample-01/cases/formation_date=2026-07-17/301257.SZ/gold-report.md`：普蕊斯合格研究样稿。
- `golden-samples/golden_sample_version=v3-golden-sample-01/cases/formation_date=2026-07-17/301257.SZ/acceptance.md`：四问及证据/推理验收。
- `golden-samples/golden_sample_version=v3-golden-sample-01/cases/formation_date=2026-07-17/002603.SZ/`：以岭药业同构的四份文件。
- `golden-samples/golden_sample_version=v3-golden-sample-01/cases/formation_date=2026-07-10/002317.SZ/`：众生药业同构的四份文件；只使用 2026-07-10 收盘前证据。
- `golden-samples/golden_sample_version=v3-golden-sample-01/cases/formation_date=2026-07-17/603757.SH/`：大元泵业同构的四份文件，用于验证降级或拒绝能力。

---

### Task 1: Freeze Case Identities and Fail-First Acceptance

**Files:**
- Create: U 盘根目录 `README.md`
- Create: 四个案例的 `original-failure-analysis.md`

**Interfaces:**
- Consumes: 已确认修复总合同、现有 V03 档案、2026-07-17 形成报告、2026-07-10 历史实践分析。
- Produces: 四个固定案例身份和逐案例失败清单，供后续研究与验收引用。

- [ ] **Step 1: Freeze the four case identities**

固定且不得替换：

```text
301257.SZ | 普蕊斯   | formation_date=2026-07-17 | current-failure case
002603.SZ | 以岭药业 | formation_date=2026-07-17 | same-date contrast case
002317.SZ | 众生药业 | formation_date=2026-07-10 | historical research-behavior case
603757.SH | 大元泵业 | formation_date=2026-07-17 | downgrade/reject case
```

- [ ] **Step 2: Write fail-first reader questions before new research**

每个 `original-failure-analysis.md` 必须逐项记录旧材料是否能够回答：

```text
Q1 公司做什么、靠什么赚钱？
Q2 为什么是现在、为什么是它？
Q3 最强反证会怎样改变判断？
Q4 未来什么算兑现、什么算失败？
```

每个失败项必须引用旧材料原句或明确指出“旧材料不存在此回答”，不能只写“可读性不好”。

- [ ] **Step 3: Verify no research conclusion was written early**

Run:

```bash
GOLDEN_SAMPLE_ROOT=/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/golden-samples/golden_sample_version=v3-golden-sample-01
rg -n '最终结论|研究通过|qualified|可以买|目标价' "$GOLDEN_SAMPLE_ROOT"/cases/*/*/original-failure-analysis.md
```

Expected: 只允许引用旧报告中的现有措辞；不得出现新研究结论或目标价。

---

### Task 2: Build Strict-Cutoff Evidence Ledgers

**Files:**
- Create: 四个案例的 `evidence-ledger.md`

**Interfaces:**
- Consumes: 形成日不可变产物、本地事实库、现有知识库、形成日前官方一手资料。
- Produces: 后续 `gold-report.md` 唯一允许引用的事实和知识清单。

- [ ] **Step 1: Record local immutable identities**

每个账本顶部必须包含：

```text
ts_code
stock_name
formation_date
cutoff_at=formation_date 23:59:59+08:00
source_path
source_sha256
```

- [ ] **Step 2: Separate evidence into five sections**

```text
A. 公司与业务事实
B. 财务、现金流和估值事实
C. 行业、事件与公司催化
D. 价格、相对强弱和成交事实
E. 关键未知与不可使用信息
```

每条证据必须记录来源、发布时间/数据截止、事实、用于回答的问题和边界。

- [ ] **Step 3: Use knowledge in question-first order**

先写研究问题，再记录知识选择：

```text
research_question
knowledge_id_or_source
why_applicable
how_it_changes_analysis
not_supported
```

若知识没有改变任何判断，标记 `decorative_only=true`，不得在正文声称已经使用。

- [ ] **Step 4: Verify cutoff and source quality**

Run:

```bash
GOLDEN_SAMPLE_ROOT=/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/golden-samples/golden_sample_version=v3-golden-sample-01
rg -n '发布时间|数据截止|source_sha256|关键未知|not_supported' "$GOLDEN_SAMPLE_ROOT"/cases/*/*/evidence-ledger.md
```

Expected: 每个案例五类证据齐全；缺失项明确记录为未知，不以模型记忆补足。

---

### Task 3: Produce the 普蕊斯 and 以岭药业 Gold Reports

**Files:**
- Create: `cases/formation_date=2026-07-17/301257.SZ/gold-report.md`
- Create: `cases/formation_date=2026-07-17/301257.SZ/acceptance.md`
- Create: `cases/formation_date=2026-07-17/002603.SZ/gold-report.md`
- Create: `cases/formation_date=2026-07-17/002603.SZ/acceptance.md`

**Interfaces:**
- Consumes: 两只股票各自的 `evidence-ledger.md`；不得读取另一只股票账本形成公司事实。
- Produces: 同一形成日、同属医药链但不能互换文字的两份合格样稿。

- [ ] **Step 1: Write the conclusion before the appendix**

每份样稿按固定问题顺序，而不是按数据库字段顺序：

```text
1. 当前研究结论及一句话理由
2. 一分钟看懂公司
3. 为什么是现在
4. 完整机会链：变化 → 业务 → 财务/预期 → 价格
5. 为什么是它：同类比较或无法比较的明确缺口
6. 最强支持证据
7. 最强反证及其影响
8. 未来 10—30 日基准/增强/失败路径
9. 当前未知
10. 事实与来源附录
```

- [ ] **Step 2: Choose conclusion from evidence, not from action confirmation**

只允许：

```text
研究通过 | 仅观察 | 证据不足 | 逻辑矛盾
```

三项确认可以支持“价格已启动”，不得作为“研究通过”的唯一理由。两只股票不要求得出相同状态，也不预设哪只必须通过。

- [ ] **Step 3: Run the four-question reader acceptance**

`acceptance.md` 必须用不超过两句话分别回答 Q1—Q4，并列出回答在 `gold-report.md` 的章节位置。任何一题不能回答，样稿退回重写。

- [ ] **Step 4: Run the anti-template comparison**

人工核对：交换“普蕊斯”和“以岭药业”名称后，业务、机会来源、传导、反证或未来验证至少四处立即不成立。少于四处，判定报告仍然模板化。

---

### Task 4: Produce the Historical Behavior and Rejection Gold Reports

**Files:**
- Create: `cases/formation_date=2026-07-10/002317.SZ/gold-report.md`
- Create: `cases/formation_date=2026-07-10/002317.SZ/acceptance.md`
- Create: `cases/formation_date=2026-07-17/603757.SH/gold-report.md`
- Create: `cases/formation_date=2026-07-17/603757.SH/acceptance.md`

**Interfaces:**
- Consumes: 各自 `evidence-ledger.md`；众生药业不得读取 2026-07-10 收盘后的复盘结果；大元泵业不得因需要拒绝样本而预设拒绝结论。
- Produces: 一份保留历史实践研究优点的样稿，以及一份证明系统能够降级/拒绝但不机械否决的样稿。

- [ ] **Step 1: Reconstruct 众生药业 without future leakage**

只保留历史分析中形成日前可见的市场主线、公司业务、公告、价格和知识使用；删除 2026-07-11 以后表现及复盘评价。报告必须区分“创新药转型事实”“医药主线”“价格确认”三条证据，不得把它们合并为泛医药叙事。

- [ ] **Step 2: Research 大元泵业 without forcing rejection**

从公司业务、财务变化、形成日价格异动、可能催化和关键未知出发。若缺少公司级机会命题，输出“仅观察”或“证据不足”；若证据支持机会，也允许形成研究通过。样本价值在于展示拒绝能力，而不是预设结论。

- [ ] **Step 3: Run cutoff contamination checks**

Run:

```bash
GOLDEN_SAMPLE_ROOT=/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/golden-samples/golden_sample_version=v3-golden-sample-01
rg -n '2026-07-1[1-9]|后续上涨|后来|命中|达到目标' "$GOLDEN_SAMPLE_ROOT"/cases/formation_date=2026-07-10/002317.SZ/{evidence-ledger,gold-report}.md
```

Expected: 不出现 2026-07-10 之后事实；如文本讨论禁止边界，必须明确标记为 `not_used_in_conclusion`。

- [ ] **Step 4: Run the four-question reader acceptance**

两份 `acceptance.md` 均回答 Q1—Q4；若结论为证据不足，Q2 应回答“为什么现在不能形成公司级判断”，Q4 应回答“补足什么证据才可升级”。

---

### Task 5: Cross-Case Contract Extraction and Immutable Manifest

**Files:**
- Create: U 盘根目录 `cross-case-comparison.md`
- Create: U 盘根目录 `manifest.json`
- Modify: U 盘根目录 `README.md`

**Interfaces:**
- Consumes: 四个案例的证据账本、失败分析、黄金报告和验收记录。
- Produces: 第三道门“研究合同”的输入，但本任务不提前编写通用运行 schema 或代码。

- [ ] **Step 1: Compare what must remain common and what must vary**

`cross-case-comparison.md` 必须分开：

```text
所有行业共同必答的问题
医药服务、药品制造、泵制造各自不同的传导变量
可复用的证据规则
绝对不能复用的结论句
允许拒绝的条件
旧报告最容易复发的错误
```

- [ ] **Step 2: Verify the four reader acceptances**

Run:

```bash
GOLDEN_SAMPLE_ROOT=/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/golden-samples/golden_sample_version=v3-golden-sample-01
for f in "$GOLDEN_SAMPLE_ROOT"/cases/*/*/acceptance.md; do rg -q '^## Q1' "$f" && rg -q '^## Q2' "$f" && rg -q '^## Q3' "$f" && rg -q '^## Q4' "$f"; done
```

Expected: exit 0，四个案例均包含 Q1—Q4。

- [ ] **Step 3: Create immutable hashes**

`manifest.json` 必须包含固定版本 `v3-golden-sample-01`、由
`date -u '+%Y-%m-%dT%H:%M:%SZ'` 取得的 RFC 3339 生成时间，以及
`301257.SZ@2026-07-17`、`002603.SZ@2026-07-17`、
`002317.SZ@2026-07-10`、`603757.SH@2026-07-17` 四个案例。每个案例的
`files` 对象必须逐一列出 `evidence-ledger.md`、
`original-failure-analysis.md`、`gold-report.md` 和 `acceptance.md` 的相对路径与
`shasum -a 256` 实际输出，不允许示例哈希或缺省文件。

- [ ] **Step 4: Final boundary verification**

Run:

```bash
git status --short
GOLDEN_SAMPLE_ROOT=/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/golden-samples/golden_sample_version=v3-golden-sample-01
find "$GOLDEN_SAMPLE_ROOT" -type f ! -name '._*' | sort
```

Expected: 仓库除本计划外无新增运行产物；U 盘只新增本版本黄金样本文件；旧 V01—V03 和形成批次未修改。

- [ ] **Step 5: Verify repository boundary**

```bash
git status --short
git log -1 --oneline -- docs/superpowers/plans/2026-07-19-v3-golden-samples.md
```

Expected: 本计划已经作为单文件提交保存；U 盘运行产物未加入 Git，仓库没有本阶段其他改动。

---

## Completion Gate

本计划完成只表示第二道门材料已经准备好，不授权进入研究合同或代码实现。完成后由用户阅读四份 `gold-report.md`，重点检查：

1. 是否看懂公司做什么、靠什么赚钱；
2. 是否知道为什么是现在、为什么是它；
3. 是否知道反证怎样改变判断；
4. 是否知道未来什么算兑现或失败。

用户确认后，才能进入第三道门：把黄金样本抽象为正式研究合同。
