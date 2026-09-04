# A股每日简评、8只详评、观察节点与主动跟踪——Codex执行指令 V4.0

> 历史记录：本文保留当时方案与事实，不作为当前运行入口或调度依据。当前时序以 `docs/architecture/current-v3-architecture.md` 和 `ops/forward-selection-prompt.md` 为准。

> **直接执行本文件，不要改写成另一份泛化方案。**
>
> 本轮只建设和优化股票推荐后的复盘分析与正式记录：
>
> 1. 每个仍在主动跟踪中的正式推荐，每个已收盘交易日都有一条简短AI复盘；
> 2. 每天从仍需复盘的正式推荐中选择8只做详细复盘；不足8只时全部详细复盘；
> 3. D1、D3、D5、D10、D20是阶段性观察节点，不再决定当天有没有复盘；
> 4. 原推荐已经被事实否定，或者原推荐无法按计划参与时，停止每日AI复盘；
> 5. 停止主动跟踪后不删除历史，仍低成本保留确定性价格到D20，并形成最终结论；
> 6. 补齐2026年8月20日以来全部正式推荐在各自观察期内的逐交易日复盘记录；
> 7. 推荐记录、每日简评、8只详评和D20结论都必须完整归档，供今后任何查看或分析方式读取。
>
> 这是个人A股助手，不是平台。不得增加数据库、后端服务、评分器、概率模型、第二套定时任务、权限、消息队列或复杂审批流程。

---

# 一、仓库、基线与分支

## 仓库

```text
https://github.com/ccrt26/stock-analysis-assistant-v3
```

## 唯一基线

```text
分支：main
提交：8304cd68885e19e253419e6369ff7dc7837b3b83
```

## 新功能分支

```text
codex/daily-simple-eight-detailed-reviews-20260903
```

## 创建独立worktree

在实际项目根目录执行：

```bash
git fetch origin --prune

test "$(git rev-parse origin/main)" = \
  "8304cd68885e19e253419e6369ff7dc7837b3b83"

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
BASE_HEAD="$(git rev-parse origin/main)"
WORKTREE="$PROJECT_ROOT/.worktrees/daily-simple-eight-detailed-reviews-20260903"

git worktree add \
  "$WORKTREE" \
  -b codex/daily-simple-eight-detailed-reviews-20260903 \
  "$BASE_HEAD"

cd "$WORKTREE"

test "$(git rev-parse HEAD)" = "$BASE_HEAD"
test "$(git branch --show-current)" = \
  "codex/daily-simple-eight-detailed-reviews-20260903"
test -z "$(git status --short)"
```

将本文件原样保存到：

```text
docs/2026-09-03-daily-simple-eight-detailed-reviews-prompt.md
```

主项目目录已有的无关未跟踪文件不得删除、覆盖或提交。禁止执行`git clean`。

---

# 二、最终复盘结构

## 第一层：所有主动正式推荐每天简评

每个已收盘交易日，对每条仍在主动跟踪中的正式推荐，生成一条简短AI复盘。

简评只回答：

1. 当前是否仍在推荐时的预期范围内；
2. 当前走势更像向上、横盘、向下，还是暂时无法评价；
3. 与上一交易日相比，最重要的变化是什么；
4. 推荐时最重要的判断是否仍成立；
5. 未来1—3个交易日更可能怎样，为什么；
6. 继续主动跟踪，还是停止主动跟踪。

普通无变化日约60—140个中文字。

不得每天重复：

- 公司简介；
- 完整推荐理由；
- 全部市场、行业、公司和价格数据；
- 当前、最高、最低和回撤的完整清单；
- 大段免责声明；
- 同一段固定模板。

## 第二层：每天8只详细复盘

详细复盘与全部简评同时存在。

```text
当天仍需复盘的不同正式推荐股票不少于8只
→ 必须选择8只详细复盘

当天仍需复盘的不同正式推荐股票少于8只
→ 全部详细复盘
```

同一股票存在多条正式推荐记录时：

- 每条episode分别有简评；
- 用户详细报告中同一股票只出现一次；
- 详细分析必须区分各次推荐日期和各自结论，不能混成一条记录。

## 第三层：D20最终结论

每条正式推荐无论是否提前停止主动跟踪，都必须在D20形成最终复盘。

D20之后默认完成，不再每日复盘；已有明确延长记录的，按原规则到D25和D30。

---

# 三、每天8只详细复盘怎样选择

不打分，不设置权重，不按涨幅简单排序。

## 优先顺序

1. 今天决定停止主动跟踪的股票；
2. 到D20、必须形成最终结论的股票；
3. 观点发生实质变化的股票：
   - 原来成立，现在开始减弱；
   - 原来减弱，现在恢复；
   - 原来减弱，现在被否定；
   - 主要涨跌解释发生改变；
4. 第一次达到20%、从推荐后高点明显回落、突破位置发生变化；
5. 重要公司事项确实改变原推荐判断；
6. D10、D5、D3、D1阶段性观察节点；
7. 剩余名额按“距离上一次详细复盘最久”轮换补足。

## 轮换原则

轮换只用于补足8只，目的在于避免同一批股票长期占用详细复盘。

不得按照：

- 股票代码；
- 今日涨幅；
- 原推荐顺序；
- 所属行业；
- 发动机类型；

机械轮换。

## 超过8只高优先事项

若同一天高优先股票超过8只：

1. 停止主动跟踪；
2. D20；
3. 判断失效或明显改变；
4. 达标、重大回撤或重要公司变化；
5. 其他阶段节点；

依次选择8只。

没有进入详细区的股票仍必须有当天简评和正式记录。

---

# 四、观察日到底是什么

## 1. 计算方式

从正式推荐的`action_date`开始，按交易所实际开市日计数：

```text
D1  = action_date当天
D3  = 从action_date起第3个交易日
D5  = 从action_date起第5个交易日
D10 = 从action_date起第10个交易日
D20 = 从action_date起第20个交易日
```

不是自然日。

## 2. 产出时间

观察节点评价的是对应交易日**收盘后的结果**。

例如：

- 股票在9月3日开盘前被正式推荐；
- 9月3日是D1；
- D1复盘使用9月3日收盘数据；
- 通常在下一个交易日09:05任务中生成并交付。

不得在D1开盘前假装已经知道D1表现。

## 3. 每天都有简评后的意义

D1、D3、D5、D10、D20不再表示“只有这些天才复盘”。

它们表示：

> 当天普通简评之外，还必须完成一个阶段性问题。

---

# 五、各观察节点的具体产出

## D1：第一天实际反应

### 要回答

- 是否有可靠推荐参考价；
- 原推荐是否能够按计划参与；
- 首日收盘相对参考价向上、横盘还是向下；
- 首日表现是否立即出现与原推荐最重要判断相反的情况；
- 首日走势主要可由市场、行业还是股票自身解释。

### 产出

- 一条D1简评；
- `current_path`；
- 可执行性判断；
- 未来1—3日方向及理由；
- 主动跟踪决定；
- 极端高开低走、停牌、无法参与或原判断立即受损时，优先进入8只详评。

### 不能做

- 不能凭一天判断20日推荐成功或失败；
- 不能因普通首日下跌直接停止跟踪。

---

## D3：最初判断是否开始兑现

三个交易日可以初步区分：

- 一天冲高还是连续表现；
- 是否继续跑赢大盘或同行；
- 成交增加后是否形成多个较高收盘；
- 原推荐所依赖的行业、公司或价格变化是否仍存在。

### 产出

- 一条D3简评；
- 早期结论：
  - 仍在预期内；
  - 开始减弱；
  - 暂时无法判断；
- 当前向上、横盘或向下；
- 未来1—3日方向及理由；
- 主动跟踪决定；
- 作为8只详评的优先候选。

D3不是最终结论。

---

## D5：第一个完整交易周检查

这是第一次阶段小结。

### 必须回答

- 第一周最终涨跌；
- 期间最高收盘、盘中最高、最深下跌和从高点回落；
- 上涨是否分布在多个交易日；
- 是否仍跑赢市场和同行；
- 推荐时最重要的理由是否初步实现；
- 当前是继续向上、进入横盘整理，还是开始向下；
- 20%目标是否仍有现实可能；
- 是否继续主动跟踪。

### 产出

- D5简评；
- 第一周小结；
- `current_assessment`；
- `current_path`；
- `outlook_1_3d`及理由；
- 主动跟踪决定；
- 优先进入当天8只详评。

不得用“5天应该涨5%”判断好坏。

---

## D10：观察期中点检查

D10不是看有没有涨10%，而是判断剩余观察期是否仍值得继续。

### 必须回答

- 前半程是持续推进、横盘消耗时间，还是已经走弱；
- 当前与推荐后最高点的关系；
- 原推荐最强的一项依据是否仍成立；
- 当前最弱或已经失败的一项是什么；
- 股票是否仍强于市场或同行；
- 20%目标：
  - 仍有现实可能；
  - 需要重新加速；
  - 已明显困难；
  - 已不再是合理期待；
- 是否继续主动跟踪。

### 产出

- D10简评；
- 中期小结；
- 对剩余D11—D20的基准判断；
- 主动跟踪决定；
- 优先进入当天8只详评。

D10仍不是最终复盘，不因距离20%较远机械判错。

---

## D20：最终复盘

D20必须形成完整结论，不得只写短评。

### 确定性结果

- 是否以收盘达到20%；
- 第一次达到日期；
- D20收盘涨跌；
- 期间最高收盘涨幅；
- 盘中最高涨幅；
- 期间最深下跌；
- 最大收盘回撤；
- 从最高点到D20的回吐。

### 分析结论

- 推荐理由最终是否成立；
- 方向是否选对；
- 具体股票是否选对；
- 推荐时机是否合理；
- 最大成功是什么；
- 最大错误是什么；
- 若曾停止主动跟踪，该决定是否合理；
- 对以后选股的一条具体经验。

### 正式产出

- D20每日复盘记录；
- `FrozenTwentyDayReviewV1`；
- 详细复盘；
- 默认`complete_observation`；
- 冻结最终结论。

第21—30日不得改写D20结论。

---

## D25和D30

只适用于已经按现有规则明确延长到30个交易日的记录。

### D25

- 延长后是否出现真正的新变化；
- D20结论是否仍适用；
- 只更新D20以后走势，不改写D20。

### D30

- 延长观察结束；
- 保存D20以后新增表现；
- D20结论保持原样；
- 正式完成。

不得把所有股票默认延长到30日。

---

# 六、什么时候停止主动跟踪

## 1. 允许停止：原推荐被事实否定

必须满足：

```text
current_assessment=contradicted
tracking_decision=stop_active_tracking
```

日评必须说清：

- 推荐时最重要的判断是什么；
- 后来的哪项事实与它相反；
- 为什么这不是一天的普通波动；
- 为什么继续每日AI复盘已没有实际价值。

### 例子

- 推荐依赖突破后站稳，但多个交易日持续跌回突破位下方，并明显落后市场或同行；
- 推荐依赖行业多数股票共同转强，但行业变化消失，股票自身也没有独立强势；
- 推荐依赖公司新变化获得价格响应，但随后价格和成交持续表现相反；
- 纯价格型推荐依赖多日上涨，但成交增加持续对应更低收盘。

## 2. 允许停止：原推荐无法执行

例如：

- 推荐日没有可靠参考价；
- 行动日停牌，不能按原条件参与。

第一次说明清楚后：

```text
current_weak_or_failed_link=execution
tracking_decision=stop_active_tracking
```

## 3. 不能单独停止

- 一个交易日下跌；
- 当前只是`weakening`；
- 横盘几天；
- 一份行业数据暂时缺失；
- 一份例行公告；
- 尚未达到20%；
- 大盘普通回落；
- AI短期判断偏下，但原推荐尚未被事实否定。

## 4. 达到20%

达到20%不提前停止，继续到D20，检查能否守住以及是否明显回吐。

## 5. 同一股票以后再次被推荐

必须产生新的episode。

旧episode不恢复、不覆盖。

---

# 七、停止主动跟踪以后怎样处理

## 主动阶段

- 每天AI简评；
- 可能进入8只详评；
- 保存全部观点变化。

## 停止主动跟踪后

- 次日起不再生成普通每日AI简评；
- 不再占8只详评名额；
- 历史推荐和历史复盘不删除；
- 程序继续记录确定性价格到D20；
- D20重新进入复盘对象并形成最终结论。

## D20完成后

- 状态改为完成；
- 不再每日复盘；
- 历史永久保留。

这不是新建第二套股票池，只是每条正式推荐记录的生命周期状态。

---

# 八、需要保存的正式记录

## 1. 正式推荐记录

继续使用：

```text
local_archive/forward_selection/
research-trace-<formation_date>.json
```

它继续是正式推荐判断的唯一来源。

不得新建第二份推荐数据库。

## 2. 每日确定性观察

继续使用：

```text
local_archive/forward_monitor/
snapshot-<analysis_date>.json
```

保存程序计算的：

- 推荐日期与观察日；
- 参考价格；
- 当前、最高、最低和回撤；
- 相对市场、相对行业；
- 成交、收盘和突破情况；
- 公告和数据限制；
- D20确定性指标。

## 3. 全部每日简评

新增：

```text
local_archive/forward_monitor/
daily-formal-reviews-<analysis_date>.json
```

这是正式复盘记录，不是临时报告。

## 4. 每天8只详细复盘

继续使用：

```text
local_archive/forward_monitor/
monitor-report-<analysis_date>.json
monitor-report-<analysis_date>.md
```

`monitor-report`不再代表当天全部复盘，只代表8只详评。

---

# 九、每日简评数据合同

在：

```text
src/stock_analyzer/ops/forward_monitor.py
```

增加：

```python
DAILY_FORMAL_REVIEWS_VERSION = "daily-formal-reviews-v1"
```

## `DailyFormalReviewV1`

```python
class DailyFormalReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    episode_id: str = Field(min_length=1)

    day_number: int = Field(ge=1, le=30)

    checkpoint: Literal[
        "D1",
        "D3",
        "D5",
        "D10",
        "D20",
        "D25",
        "D30",
    ] | None = None

    current_assessment: Literal[
        "not_yet_tested",
        "partly_supported",
        "supported",
        "weakening",
        "contradicted",
        "insufficient_evidence",
    ]

    current_path: Literal[
        "up",
        "sideways",
        "down",
        "not_evaluable",
    ]

    best_supported_explanation: Literal[
        "market_common_move",
        "industry_common_move",
        "company_change",
        "stock_specific_move",
        "mixed",
        "unknown",
    ]

    current_weak_or_failed_link: Literal[
        "none",
        "market_conditions",
        "new_information",
        "industry_follow_through",
        "price_and_volume_confirmation",
        "remaining_room",
        "company_risk",
        "timing",
        "execution",
        "stock_selection",
        "unknown",
    ]

    current_review: str = Field(min_length=1, max_length=600)

    view_change: Literal[
        "first_review",
        "unchanged",
        "strengthened",
        "weakened",
        "invalidated",
    ]

    view_change_reason: str = Field(
        min_length=1,
        max_length=300,
    )

    outlook_1_3d: Literal[
        "event_pending",
        "strengthening",
        "continuation_possible",
        "range_or_wait",
        "weakening",
        "overheated",
        "invalidated",
    ]

    outlook_reason_plain_language: str = Field(
        min_length=1,
        max_length=300,
    )

    tracking_decision: Literal[
        "keep_active_tracking",
        "stop_active_tracking",
        "complete_observation",
        "historical_not_applied",
    ]

    tracking_decision_reason: str = Field(
        min_length=1,
        max_length=300,
    )

    review_origin: Literal[
        "live",
        "copied_live_archive",
        "backfill",
    ]

    final_twenty_day_review: FrozenTwentyDayReviewV1 | None = None
```

## `DailyFormalReviewLedgerV1`

```python
class DailyFormalReviewLedgerV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ledger_version: Literal["daily-formal-reviews-v1"]

    analysis_date: date

    as_of: datetime

    reviews: list[DailyFormalReviewV1]
```

不增加：

- 页面字段；
- 样式字段；
- 颜色；
- 卡片名称；
- 排序展示字段；
- 图表配置；
- 股票评分；
- 预测概率。

---

# 十、每天哪些记录需要简评

在snapshot中为每个正式episode派生：

```text
tracking_status
tracking_exit_date
tracking_exit_reason
previous_daily_formal_review
last_detailed_review_date
days_since_last_detailed_review
```

## `tracking_status`

```text
active
evaluation_only
completed
```

### active

每天生成AI简评。

### evaluation_only

已停止每日AI简评，但继续记录价格；D20重新复盘一次。

### completed

D20或明确延长观察结束，不再复盘。

## snapshot顶层增加

```text
daily_review_episode_ids
evaluation_only_episode_ids
detailed_review_candidate_codes
```

## `daily_review_episode_ids`

包含：

- `confirmed_active`；
- `legacy_v1_not_rewritten`；
- `tracking_status=active`；
- D1—D20；
- evaluation_only在D20需要最终复盘的记录；
- 明确延长且到D25或D30的记录。

排除：

- `conditional_event`；
- comparator；
- rejected；
- unresolved；
- evaluation_only普通日期；
- completed。

## summary增加

```text
active_tracking_count
evaluation_only_count
completed_formal_count
daily_review_episode_count
detailed_review_stock_count
```

保留现有summary字段以兼容历史报告。

---

# 十一、记录全部每日简评

在现有CLI增加：

```bash
./.venv/bin/python -m stock_analyzer.ops.forward_monitor \
  record-daily-formal-reviews \
  --snapshot-file <snapshot> \
  --review-file <pending-daily-review>
```

输入：

```text
pending-daily-formal-reviews-<date>.json
```

成功后保存：

```text
daily-formal-reviews-<date>.json
```

## 校验

1. 日期和`as_of`与snapshot一致；
2. review ID与`daily_review_episode_ids`完全一致；
3. 每个episode恰好一次；
4. conditional、比较股和落选股不得进入；
5. live记录不得使用`historical_not_applied`；
6. copied和backfill必须使用`historical_not_applied`；
7. `stop_active_tracking`只允许：
   - `current_assessment=contradicted`；或
   - `current_weak_or_failed_link=execution`且`entry_open`为空；
8. `weakening`不能单独停止；
9. `complete_observation`只允许D20或现有明确延长观察终点；
10. D1—D19不能填写最终结论；
11. D20必须填写最终结论；
12. D21—D30不得改写已经冻结的D20结论；
13. 已存在相同文件返回`already_recorded`；
14. 已存在不同内容返回`review_conflict`，不覆盖；
15. 成功后删除pending文件；
16. 不增加内容哈希。

---

# 十二、全部简评的生成方法

修改：

```text
.agents/skills/reviewing-stock-recommendations/SKILL.md
ops/forward-monitor-prompt.md
```

## 输入

每条简评读取：

- 当前snapshot；
- 原推荐trace；
- 最近一份本episode的每日简评；
- 当天市场结果；
- 当前已有行业、公司和价格事实。

## 普通日的资源原则

- 市场Skill每天只运行一次；
- 没有新公司事项时，不重复读取公告正文；
- 不重新写公司简介；
- 不做全量公司深度研究；
- 主要根据snapshot、原推荐判断和上一交易日简评更新观点。

## `current_review`

必须用普通中文回答：

- 今天是否仍在原推荐预期内；
- 当前向上、横盘、向下或无法评价；
- 与上一交易日相比，真正改变了什么；
- 原推荐最重要的一项判断是否仍成立；
- 当前为什么继续或停止主动跟踪。

## `outlook`

先给方向，再说明为什么。

不得只写：

```text
若上涨则向上，若下跌则向下。
```

## `view_change`

以最近一份每日简评为准。

只换措辞不算观点变化。

## 无变化日

一段短评即可。

示例：

> 海油工程今天仍在原来的判断范围内。收盘和前一交易日接近，相对油服同行的优势也没有明显变化，原先“行业偏强、个股略有领先”的判断还在，但没有新的加速迹象。未来几个交易日更可能横盘偏上，继续主动跟踪。

---

# 十三、8只详细复盘的实现

## 1. 复用现有模型

继续使用：

```text
DailyForwardMonitorReportV2
ForwardMonitorAlertV2
ForwardEpisodeReviewV1
```

`alerts`最多8只的限制保留。

## 2. 允许普通轮换详评

当前report只允许attention股票。

做最小调整：

- 允许active正式股票因轮换进入详细复盘；
- `alert_type`增加一个兼容值：

```text
routine_detail
```

含义：

> 今天没有重大异常，但按轮换进入详细复盘。

不新增第二套attention池。

## 3. 报告数量

```text
detailed_review_stock_count
=
min(8, 当天需要简评的不同正式推荐股票数)
```

新report必须恰好包含该数量。

## 4. 高优先与轮换

snapshot为AI提供：

```text
attention_reasons
view_change
checkpoint
last_detailed_review_date
days_since_last_detailed_review
```

AI按第三节顺序选择最终8只。

程序只验证：

- 数量正确；
- D20、今日停止、关键观点变化等强制事项没有被遗漏；
- 所有详细股票都属于当天正式简评对象；
- 同一股票只出现一次。

程序不建立分数和权重。

## 5. 简评与详评不能矛盾

同一episode同时出现在两处时，以下必须一致：

```text
current_assessment
best_supported_explanation
current_weak_or_failed_link
outlook_1_3d
outlook_reason_plain_language
final_twenty_day_review
```

详细分析可以更长，但不能改成另一套结论。

---

# 十四、每日用户报告

修改：

```text
ops/forward-selection-prompt.md
ops/forward-monitor-prompt.md
```

## 1. 全部主动推荐简表

```markdown
## 所有主动推荐的今日结论

| 股票 | 推荐后第几日 | 当前涨跌 | 当前走势 | 是否仍在预期内 | 未来1—3日 | 主动跟踪 |
```

要求：

- 每个active正式推荐一行；
- 当前走势只写向上、横盘、向下或无法评价；
- 是否仍在预期内使用普通中文；
- 主动跟踪写“继续”或“今日停止”；
- 不显示conditional、比较股和evaluation_only；
- 表格中的结论不得只写“部分支持”“仍需观察”。

## 2. 8只详细复盘

```markdown
## 今天重点复盘的8只股票
```

不足8只时按实际数量改标题。

每只继续采用当前完整详评结构：

```text
推荐日期和当时判断
到今天走到哪里
我的分析
接下来更可能怎样
```

普通无变化股票不在详细区重复展开。

## 3. 三类数量

```text
主动跟踪：X只
仅保留评价：Y条
已完成：Z条
```

## 4. 今日正式推荐

继续使用现有详细分段格式。

不得展示：

- conditional事件线索；
- 最近未选；
- 比较股；
- Git状态；
- 工作区和临时文件说明。

---

# 十五、历史补录：2026年8月20日以来

## 1. 范围

全部：

```text
action_date >= 2026-08-20
confirmed_active
legacy_v1_not_rewritten
```

排除：

```text
conditional_event
comparator
rejected
nearest_nonselection
```

从各自action_date到：

- D20；
- 或执行时最新可靠交易日；
- 已明确延长的按原规则到D30。

## 2. 已有正式复盘

从同日：

```text
monitor-report-<date>.json
```

原样复制已有判断：

```text
review_origin=copied_live_archive
tracking_decision=historical_not_applied
```

不得润色、改写或补充后来事实。

## 3. 缺失日期

只使用：

- 同日snapshot；
- 同日`as_of`以前的事实；
- 原推荐trace；
- 前一交易日已经完成的历史日评；

生成：

```text
review_origin=backfill
tracking_decision=historical_not_applied
```

不得读取后续交易日来解释当前日期。

## 4. 历史补录不追溯退出

补录只补观点记录，不虚构过去的主动跟踪决定。

完成历史补录后，以最新可靠交易日做一次live复盘，正式决定当前主动跟踪状态。

## 5. 不补历史8只详评

已有历史monitor report保持不变。

本轮不回头为每个旧日期另造8只详评，避免事后重新选择重点。

从新制度正式启用的第一个live交易日起，每天执行8只详评。

## 6. 覆盖记录

创建：

```text
research/skill-optimization/daily-simple-eight-detailed-reviews-20260903/
  backfill-coverage.csv
  backfill-summary.md
```

CSV字段：

```text
episode_id
ts_code
name
action_date
review_date
day_number
checkpoint
review_origin
current_assessment
current_path
view_change
outlook_1_3d
tracking_decision
source_snapshot
source_monitor_report_if_any
```

总结必须回答：

- 正式episode数量；
- 理论应有日评数量；
- 实际日评数量；
- copied数量；
- backfill数量；
- 缺失数量和原因；
- 是否有任一应复盘日期为空；
- 是否使用未来数据；
- 是否覆盖历史monitor report。

不得提交本地绝对路径。

---

# 十六、允许修改范围

```text
AGENTS.md

src/stock_analyzer/ops/forward_monitor.py

.agents/skills/reviewing-stock-recommendations/SKILL.md

ops/forward-monitor-prompt.md
ops/forward-selection-prompt.md

tests/test_forward_monitor.py
tests/test_forward_monitor_prompt.py
tests/test_v4_operational_prompts.py

docs/2026-09-03-daily-simple-eight-detailed-reviews-prompt.md

research/skill-optimization/daily-simple-eight-detailed-reviews-20260903/
```

只有现有CLI测试因新增命令需要同步时，才允许修改紧邻的CLI测试文件。

---

# 十七、禁止修改范围

```text
src/stock_analyzer/ops/forward_selection.py

五个选股Skill：
.agents/skills/orchestrating-stock-research/
.agents/skills/interpreting-market-macro/
.agents/skills/researching-sectors-industries/
.agents/skills/researching-company-events/
.agents/skills/analyzing-price-trading/

docs/architecture/a-share-short-horizon-engine-contract-v4.md

tools/

数据采集来源
数据库schema
七种engine_type
四种engine_status
11个价格场景
20%目标
D20确定性指标公式
入口价格口径
Automation数量与运行时间
```

不得：

- 新建数据库；
- 新建服务；
- 新建第二个定时任务；
- 新增评分、权重或概率；
- 用固定涨跌阈值自动停止跟踪；
- 删除历史正式推荐；
- 覆盖历史monitor report；
- 使用未来数据补写过去；
- 将conditional改成正式推荐；
- 修改液冷研究分支；
- 为普通文本增加哈希。

---

# 十八、执行纪律

本轮涉及正式复盘合同、每日正式归档和主动跟踪状态。

按`AGENTS.md`：

- 实施前恰好进行一次`gpt-5.6-sol`、`xhigh`独立审查；
- 审查只检查：
  - 每日简评与8只详评是否分清；
  - 观察节点产出是否合理；
  - 停止主动跟踪是否过早；
  - 停止后是否仍保留D20评价；
  - 历史补录是否避免后见之明；
  - 新记录是否为最小必要结构；
  - 是否过度工程化；
- 审查不实施，不调用其他子智能体；
- 主智能体采用一次审查意见后连续完成；
- 此后不再启动子智能体。

---

# 十九、Task 1：真实现状诊断

创建：

```text
research/skill-optimization/daily-simple-eight-detailed-reviews-20260903/
  current-state-diagnosis.md
```

根据当前仓库确认：

1. 当前Prompt明确要求AI只研究发生变化的股票；
2. 当前`alerts`最多8只；
3. 非重点正式推荐每天没有AI日评；
4. 当前没有主动跟踪、仅保留评价和已完成三种持久状态；
5. 当前D1/D3/D5/D10/D20只是attention检查点；
6. 当前历史正式推荐和确定性价格记录已经具备；
7. 当前缺口是每日观点记录，而不是行情或推荐记录不足。

不得把诊断写成展示工具需求分析。

---

# 二十、Task 2：测试驱动实现每日简评记录

先在：

```text
tests/test_forward_monitor.py
```

增加失败测试，再实现：

- 模型解析；
- snapshot ID范围；
- record命令；
- 幂等与冲突；
- D20；
- tracking状态；
- 历史兼容。

每个功能遵循：

```text
写失败测试
→ 确认失败
→ 最小实现
→ 定向测试通过
```

不要一次写完后再补测试。

---

# 二十一、Task 3：测试驱动实现8只详评

增加测试：

1. active股票数为12时，详评恰好8只；
2. active股票数为5时，详评5只；
3. 今日停止和D20优先；
4. 观点变化优先；
5. 轮换补足；
6. 同一股票只显示一次；
7. 详评与简评结论一致；
8. 不按涨幅和代码机械选择。

再做最小实现。

---

# 二十二、Task 4：更新Skill和Prompt

必须完整落实：

- 所有active每天简评；
- 普通日短写；
- 观察节点阶段性产出；
- 8只选择规则；
- 停止主动跟踪规则；
- D20继续保留；
- 简评与详评一致；
- 用户报告两层结构。

不得再次新增一套相近但冲突的输出合同。

修改完后搜索：

```bash
git grep -n \
  -e "AI只研究今天确实发生变化的股票" \
  -e "不得把全部股票交给 AI" \
  -- \
  ops/forward-monitor-prompt.md \
  .agents/skills/reviewing-stock-recommendations/SKILL.md
```

这些旧规则必须被替换，而不能与新规则同时存在。

---

# 二十三、Task 5：实际历史补录

这不是只写工具。

必须实际执行2026年8月20日至最新可靠交易日的补录，并生成：

```text
backfill-coverage.csv
backfill-summary.md
```

已有正式复盘必须原样复制。

缺失日逐日按当时可见事实生成。

不得因工作量大而只补样例。

---

# 二十四、Task 6：最新live验收

补录完成后，以最新可靠收盘交易日正式运行一次：

1. 全部active episode都有简评；
2. 选出8只详评；
3. 每条live简评作出tracking决定；
4. 停止主动跟踪的股票次日不再进入普通日评；
5. 保存正式文件。

创建：

```text
research/skill-optimization/daily-simple-eight-detailed-reviews-20260903/
  checkpoint-definition.md
  expected-daily-user-report.md
```

`checkpoint-definition.md`用普通中文说明D1、D3、D5、D10、D20的定义和产出。

---

# 二十五、测试要求

## 每日简评

至少覆盖：

1. 每个active正式episode每天恰好一条；
2. conditional、比较股和落选股不能进入；
3. `current_path`合法；
4. 无变化日也有短评；
5. 历史补录来源清楚；
6. 文件幂等且冲突不覆盖；
7. D20最终结论；
8. D21—D30不改写D20。

## 主动跟踪

至少覆盖：

1. keep次日继续；
2. stop次日不再简评；
3. weakening不能单独stop；
4. contradicted可以stop；
5. execution无法执行可以stop；
6. stop后价格仍计算到D20；
7. stop后D20仍复盘；
8. 达到20%不自动stop；
9. 新episode独立；
10. 三类计数正确。

## 8只详评

至少覆盖：

1. active不少于8时恰好8只；
2. active不足8时全部；
3. 今日停止和D20优先；
4. 观点变化优先；
5. 观察节点优先；
6. 轮换补足；
7. 同一股票只出现一次；
8. 与简评结论一致。

## 观察节点

至少覆盖：

1. D1为action_date当天；
2. D3/D5/D10/D20按交易日计数；
3. D1可执行性产出；
4. D5第一周小结；
5. D10中期小结；
6. D20最终结论；
7. D25/D30只对延长记录有效。

## 用户报告

至少覆盖：

1. 全部active简表无遗漏；
2. 8只详细区；
3. 当前走势可读；
4. 今日停止清楚；
5. 三类数量分开；
6. 不显示conditional、比较股和事件线索。

运行：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_forward_monitor.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_v4_operational_prompts.py

./.venv/bin/python -m pytest -q

git diff --check
```

不得删除旧测试换取通过。

---

# 二十六、人工验收

至少检查：

- 一只明确向上；
- 一只横盘；
- 一只向下；
- 一只`weakening`但继续主动跟踪；
- 一只`contradicted`并停止；
- 一只无法执行并停止；
- 一个D1；
- 一个D3；
- 一个D5；
- 一个D10；
- 一个D20，或明确说明当前尚无成熟D20。

确认：

- 简评不是长报告；
- 8只详评有真正分析；
- 普通日没有重复公司简介；
- 停止决定不是因为单日涨跌；
- 历史补录没有使用未来事实；
- 推荐、简评、详评和D20均有正式记录。

---

# 二十七、仓库规则的最小更新

在`AGENTS.md`只增加：

```markdown
- 每个仍在主动跟踪中的正式推荐，在每个已收盘交易日生成一条简短AI复盘；当当天需复盘的不同正式推荐股票不少于8只时，另选8只做详细复盘，不足8只时全部详细复盘。D1、D3、D5、D10、D20是阶段性检查节点，不决定是否生成日评。
- `research-trace`保存正式推荐，`daily-formal-reviews-<date>.json`保存全部每日简评，`monitor-report`保存8只重点详评。原推荐被事实否定或无法执行后，可停止每日AI复盘；历史不删除，程序继续保存确定性价格到D20并形成最终结论。
```

不重写其他规则。

---

# 二十八、提交、合并与清理

## 建议一个功能提交

```bash
git add \
  AGENTS.md \
  docs/2026-09-03-daily-simple-eight-detailed-reviews-prompt.md \
  src/stock_analyzer/ops/forward_monitor.py \
  .agents/skills/reviewing-stock-recommendations/SKILL.md \
  ops/forward-monitor-prompt.md \
  ops/forward-selection-prompt.md \
  tests/test_forward_monitor.py \
  tests/test_forward_monitor_prompt.py \
  tests/test_v4_operational_prompts.py \
  research/skill-optimization/daily-simple-eight-detailed-reviews-20260903

git commit -m \
  "feat: review every active recommendation and detail eight daily"
```

## 推送

```bash
git push -u origin codex/daily-simple-eight-detailed-reviews-20260903
FEATURE_HEAD="$(git rev-parse HEAD)"
```

## 快进合并main

```bash
cd "$PROJECT_ROOT"

git switch main
git fetch origin --prune
git pull --ff-only origin main

git merge --ff-only "$FEATURE_HEAD"

./.venv/bin/python -m pytest -q
git diff --check

git push origin main
```

主项目目录的无关未跟踪文件不得提交或删除。只要不与本轮路径冲突，不得因此放弃快进合并。

核对：

```bash
test "$(git rev-parse main)" = "$FEATURE_HEAD"
test "$(git rev-parse origin/main)" = "$FEATURE_HEAD"
```

## 删除功能分支

```bash
git fetch origin --prune

git merge-base --is-ancestor \
  origin/codex/daily-simple-eight-detailed-reviews-20260903 \
  origin/main

git push origin --delete \
  codex/daily-simple-eight-detailed-reviews-20260903

git worktree remove \
  "$PROJECT_ROOT/.worktrees/daily-simple-eight-detailed-reviews-20260903"

git branch -d \
  codex/daily-simple-eight-detailed-reviews-20260903

git fetch origin --prune
```

不得强制删除。

保留：

```text
main
research/ai-liquid-cooling-2026h2
```

---

# 二十九、最终验收标准

## 每日简评

- [ ] 每个active正式推荐每天一条；
- [ ] 当前向上、横盘、向下或无法评价明确；
- [ ] 是否仍在原预期内明确；
- [ ] 与上一交易日变化明确；
- [ ] 未来方向和理由明确；
- [ ] 主动跟踪决定明确；
- [ ] 无变化日短写。

## 8只详评

- [ ] active不少于8时恰好8只；
- [ ] active不足8时全部；
- [ ] 今日停止、D20和观点变化优先；
- [ ] 观察节点优先；
- [ ] 轮换补足；
- [ ] 同一股票只出现一次；
- [ ] 详评与简评不矛盾。

## 观察节点

- [ ] D1定义和产出清楚；
- [ ] D3定义和产出清楚；
- [ ] D5有第一周小结；
- [ ] D10有中期小结；
- [ ] D20有最终结论；
- [ ] D25/D30只用于延长；
- [ ] 每天都有简评，观察节点只负责加深。

## 主动跟踪

- [ ] contradicted可停止；
- [ ] 无法执行可停止；
- [ ] weakening不自动停止；
- [ ] 单日下跌不自动停止；
- [ ] 停止后不再每日AI；
- [ ] 停止后价格仍记录到D20；
- [ ] D20仍形成最终评价；
- [ ] 历史不删除。

## 历史与记录

- [ ] 8月20日以来应复盘日期无空白；
- [ ] 已有复盘原样复制；
- [ ] 缺失日期按当日事实补录；
- [ ] 不使用未来数据；
- [ ] 历史补录不追溯改变主动跟踪；
- [ ] 推荐、简评、详评和D20分别有正式记录。

## 工程范围

- [ ] 不修改五个选股Skill；
- [ ] 不修改七种发动机、四种状态和11个价格场景；
- [ ] 不修改20%目标、D20指标公式和入口价格；
- [ ] 不新增数据库、服务、定时任务、评分或概率；
- [ ] 不修改`tools/`；
- [ ] 完整测试通过；
- [ ] main本地与远端一致；
- [ ] 功能分支删除；
- [ ] 液冷研究分支不变。

---

# 三十、Codex最终汇报格式

```markdown
已完成：每日简评、8只详评、观察节点与主动跟踪

## GitHub
- 基线：`8304cd68885e19e253419e6369ff7dc7837b3b83`
- main最终提交：`<HEAD>`
- 对比链接：<URL>
- 当前现状诊断：<URL>
- 观察节点说明：<URL>
- 历史补录总结：<URL>
- 历史覆盖清单：<URL>
- 用户日报样例：<URL>

## 每日简评
- 正式推荐episode数：<数量>
- 最新active数量：<数量>
- evaluation_only数量：<数量>
- completed数量：<数量>
- 每日简评总数：<数量>
- 主动期间是否存在无简评日期：是/否
- 普通无变化日是否短写：是/否

## 8只详评
- 最新交易日详评股票数：<数量>
- active不少于8时是否恰好8只：是/否
- 今日停止和D20是否优先：是/否
- 观点变化是否优先：是/否
- 是否通过最长未详评轮换补足：是/否
- 与简评结论是否一致：是/否

## 观察节点
- D1：<定义和产出>
- D3：<定义和产出>
- D5：<定义和产出>
- D10：<定义和产出>
- D20：<定义和产出>
- D25/D30：<适用范围>

## 主动跟踪
- 最新停止主动跟踪：<数量>
- 因原判断被否定：<数量>
- 因无法执行：<数量>
- weakening是否自动停止：否
- 停止后是否继续价格到D20：是
- D20是否仍形成最终结论：是

## 8月20日以来补录
- 覆盖日期：<起止>
- 应有简评：<数量>
- 实际简评：<数量>
- copied_live_archive：<数量>
- backfill：<数量>
- 缺口：<数量及原因>
- 是否使用未来数据：否
- 是否追溯修改历史主动跟踪：否
- 是否覆盖既有monitor report：否

## 工程范围
- 五个选股Skill修改：0
- 新数据库：0
- 新服务：0
- 新定时任务：0
- 评分或概率：0
- tools修改：0

## 验证
- 基线定向测试：<结果>
- 修改后定向测试：<结果>
- 完整测试：<结果>
- `git diff --check`：<结果>
- main本地/远端一致：是/否
- 功能分支已删除：是/否
- 无关未跟踪文件是否未触碰：是/否
```
