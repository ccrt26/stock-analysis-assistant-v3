# 三路互斥复盘 Implementation Plan

> **For agentic workers:** 使用 `superpowers:executing-plans` 执行Task 0—5。用户指定交给GLM，不使用多智能体开发，不另建spec或重写方案。
>
> **状态：** 按用户2026-09-06最新明确要求重写，本版经`gpt-5.6-sol / xhigh`单次独立审查通过（以已合并修订版为准）。上一版“常规总数8只、必评超过8才扩容”废止。当前只修改计划，不实施业务代码或回写正式档案。

**Goal:** 关键节点独立按D10风格深入复盘；剔除节点后，其余推荐每天最多8只普通详评；剩余只做简评。同一股票当天只进入一个公开类别，只生成一种正文。

**Architecture:** 沿用snapshot、每日账本、V2报告、Markdown与网页。账本保留全部需跟踪episode的结构化判断，新增一个正文类型字段；只有简评类保存简评正文，两种详评的正文只存现有report。程序校验互斥、覆盖与非节点8只上限，不选择股票或判断文风。

**Tech Stack:** 现有Python、Pydantic、pytest、Markdown和网页渲染器。

**Spec:** 第1—3节是唯一设计。用户最新两条要求优先于旧计划和尚未同步的“全部先简评、再选恰好8只”描述。

## 1. 执行提示与白名单

实现三路互斥：D1/D3/D5/D10/D20及待补D20全部节点详评，不生成简评、不占普通详评8只名额；剔除节点后按既有优先级选择0—8只普通详评，其余只简评。同股一条到节点，全股合格episode统一进节点区，但只有实际节点episode标明节点。节点沿用已确认D10阶段对账文风，问题按实际节点调整；D20当前正文只写必要当日增量，完整阶段结案只在既有最终结论公开一次。保留必要结构化跟踪状态，不给详评另配隐藏简评。prepare输出节点和非节点上限；两次record重算分组并校验覆盖、类型、普通上限，报告精确等于两种详评集合。区分新三路、旧daily与更早attention三种路径，旧档不迁移。上轮正文及网页只按同分析日、解析后的同as_of、同episode合并，详评账本null不能盖掉报告正文。Markdown三路分区且正文唯一。保留600简评硬上限，删除软长度/事实数量配额；保留文风锚、价格公式、时点、研究范围、停止条件和D20冻结。仅白名单修改及必要测试，不新增任务、数据库、报告版本、正文副本、服务、队列、评分器、条件解析器或每日第二模型。不回写正式历史，不提交、推送、发布。

允许修改：

- src/stock_analyzer/ops/forward_monitor.py：正文类型字段、正文可空条件、节点分组、prepare/record、历史正文读取、Markdown三路展示。
- tools/render_monitor_web.py：仅正文/状态合并、同日同episode去重、类型标识与缺正文显示；保留布局、图表、CSS和既有组件。
- tests/test_forward_monitor.py、tests/test_forward_monitor_prompt.py、tests/test_render_monitor_web.py：定向测试与旧档回归。
- tests/test_engine_contract_knowledge_v4.py：仅同步复盘“最多4个事实”的旧断言，不改选股知识或合同。
- ops/forward-monitor-prompt.md、.agents/skills/reviewing-stock-recommendations/SKILL.md：三路正文与生成流程的完整方法。
- ops/forward-selection-prompt.md、.agents/skills/orchestrating-stock-research/SKILL.md：只同步复盘接口和最终报告结构，不改选股。
- AGENTS.md：只同步两条复盘硬边界中“全部简评/恰好8只”和存储说明，其他边界及执行纪律不改。
- docs/architecture/current-v3-architecture.md、docs/architecture/forward-monitoring-v1.md：仅同步本轮合同、存储语义和节点依据。

不新增源码/测试文件，不拆模块，不补registry、不重做review_context，不修改自动任务。样稿只放新的local_archive/review_format_acceptance/子目录。测试用现有fixture和tmp_path，不对真实档案调用register/record/prepare，不刷新真实数据或发布网页。

## 2. 唯一业务合同

### 2.1 三组互斥，先摘节点

范围仍为snapshot原资格规则得到的daily_review_episode_ids，表示当天需更新判断的正式推荐记录，不再表示“每条必须写简评”。不纳入conditional、比较股、落选股或普通日期的evaluation_only。

按股票代码分为：

- K（节点详评）：任一合格episode的day_number为1/3/5/10/20，或属于既有required_final_review_episode_ids（补D20结案）。K全覆盖，无篇数上限。
- D（普通详评）：从全部合格股票剔除K后按实际需要选择，0≤|D|≤min(8,非节点股票数)。
- B（简评）：剩余股票。

K、D、B两两不交，合起来覆盖全部当日合格股票；report股票严格等于K∪D。总详评数=|K|+|D|，不是max(8,必评数)，也不强制填满|K|+8。

21只合格股票、5只节点，选8只普通详评，则5节点＋8普通详评＋8简评。9只节点、其余12只，仍可另选最多8只普通详评。没有普通详评需要时允许0只，不为凑数注水。

节点与重大事件重叠只写节点详评。同股多个正式episode只占一个股票名额，分别保留实际推荐日期/节点/观点；其中一个到节点，该股票统一进入K，其他合格episode在同篇作为其他推荐记录更新，不冒称它们也到节点，不再进D或B。无关比较episode不能带入。

### 2.2 非节点重要事项也不扩容

仅在非节点中按原顺序考虑：今日停止主动跟踪→观点明显变化→达标或显著回撤→重要公司事项→必要时最长未详评轮换。所有节点项从这条队列移除。

停止和重要观点变化是优先项，不是另一个不限量集合。优先项超过8只时在其中选8只，其余B把重要变化说清；不能扩为9只、阻塞日报或改挂“节点”绕过上限。AI选择需展开的问题，程序不打分或按代码排序。

### 2.3 五节点统一D10深度风格，回答各自阶段问题

沿用已确认D10的阶段对账方法和文风：原期待与担心→截至当天的关键变化→兑现/削弱/未知→更合理的解释及边界→目标余程与后续验证。不是机械凑齐栏目，更不能虚构未来阶段。

| 节点 | 当天说透的问题 |
|---|---|
| D1 | 原条件下是否可执行，首日反应怎样检验原判断，哪些尚未检验；不虚构数日持续性。 |
| D3 | 早期反应是否延续，有无反证；不把单日涨跌当长期确认。 |
| D5 | 第一周路径与D3后新增证据，原期待兑现与未兑现。 |
| D10 | 前半程对账、主要未知、目标剩余路径和障碍。 |
| D20 | 前20日结果、原理由/股票/时机评价及具体经验，按原机制结案冻结。 |

D1和D20分别为行动入口和用户定义的观察终点；D3/D5/D10为检查节奏，不声称统计最优。无新增证据可维持判断。D20完整结论仍只公开一次，使用现有final_twenty_day_review.overall_review，不改变最终结论位置。

D20仍是一篇节点详评：整篇采用阶段对账方法，但ForwardEpisodeReviewV1.current_review只写理解结案所需的当日增量和关键证据；完整D1—D20结果、原理由、选股/时机评价及经验或错误只在final_twenty_day_review.overall_review公开一次，不能在两个字段中各写一遍阶段总结。

停止的记录不因D3/D5/D10恢复普通跟踪；既有D20返回/补结案走K，不挤D。D25/D30不新增为关键节点。休市、时点、任务频率不变，不建漏跑节点队列。

### 2.4 简评、普通详评与长度

B只写当天重要增量及含义，独立可读，不重讲完整背景、价格进度或未来条件。D解释当天主要问题、证据、反证和当前判断，不强制重做节点对账。

保留简评600字符硬上限和其他现有300字符理由字段；取消60—140、150—320、180—350、400—800字、段数/句数及最多4个事实等软配额，不替换成另一套数量指标。两个用户确认的文风锚原文不改，只更新锚外适用范围。

沿用现行事实边界：成交环比回升不等于高于日常均量；连续条件仅出现一天不算完成；不按时间/涨幅线性判断目标节奏；新阈值不冒充旧预设；不无依据限定“跌回且缩量才改判”。由写作者自检，不造解析器或每日第二模型。

## 3. 最小存储和读取改动

### 3.1 每日账本保留状态，不为详评配第二篇正文

DailyFormalReviewV1新增唯一字段review_kind，并允许detail的current_review为空。具体模型代码：

```python
review_kind: Literal["brief", "regular_detail", "checkpoint_detail"] | None = None
current_review: str | None = Field(default=None, min_length=1, max_length=600)

@model_validator(mode="after")
def validate_review_body(self) -> "DailyFormalReviewV1":
    if self.review_kind in {None, "brief"}:
        if not self.current_review:
            raise ValueError("brief or legacy review requires current_review")
    elif self.current_review is not None:
        raise ValueError("detailed review must not carry a separate brief")
    return self
```

kind=None仅供读取原来无该字段的历史账本；新流程每条必须显式三选一，同股合格episode类型一致。

| 类型 | 账本current_review | report current_review | 公开入口 |
|---|---|---|---|
| checkpoint_detail | null，不创作简评 | 节点详评 | 关键节点复盘 |
| regular_detail | null，不创作简评 | 普通详评 | 今日深入复盘 |
| brief | 必填，最多600字符 | 不存在对应alert | 今日简评 |

daily-formal-reviews继续保存全部需更新episode的结构化判断、观点变化、展望原因、跟踪决定及既有D20结论，是状态账本，不再等于全部简评正文。两种详评正文只存现有monitor-report。不新增节点报告文件或版本，不抄详评进600字符字段，不用占位句伪装简评。

### 3.2 prepare确定节点与非节点候选，不预定最终篇数

daily_review_episode_ids与资格计算不变。新增snapshot的checkpoint_review_episode_ids，包含K内全部合格episode（含同股合并记录）。detailed_review_candidate_codes改为非节点候选，不包含K。

新prepare summary和PrepareSummary用checkpoint_review_stock_count、regular_detail_stock_limit替换detailed_review_stock_count。分别为|K|与min(8,非节点数)，后者为上限不是必填篇数。daily_review_episode_count仍是状态记录数。

兼容分支明确区分：①checkpoint_review_episode_ids存在（即使空列表）启用新三路，缺账本失败；②没有该字段但有daily_review_episode_ids，保留既有每日账本工作流及旧固定详评数量、最多8只校验，不能仅因不是三路就误送attention分支；③更早没有daily字段的snapshot保留attention legacy路径。历史缺账本的读取回退仍按既有规则，不补造正文。无需另加版本、CLI参数或兼容框架，不迁移旧档。record重算K，不盲信手填分类。

### 3.3 生成顺序与校验

全部记录的结构化判断草稿→摘出K→非节点中选D→其余B→各写唯一正文→同一执行者核对来源及结构化一致性→沿用先record账本再record报告。

账本覆盖全部daily IDs、kind与节点分组吻合、同股一致、普通详评≤8。报告与账本声明详评的股票和episode精确相等，K不能漏，B不能再详评。新snapshot缺账本必须失败，不能退回legacy绕过校验。

只移除V2 alerts总数max_length=8，V1保留。旧record路径显式保留最多8只检查。原身份、结构化一致性、停止条件、D20冻结、成对事实和幂等冲突不改。unreported_attention_count仍是attention未展开数，不改成简评数。

两份草稿均写完再保存，不先生成全部简评然后改类型。一处保存失败则报告失败，沿用既有重试，不发布缺正文的成功报告；不建跨文件事务、回滚系统或后台修复队列。

### 3.4 上轮观点与网页

_daily_review_history对新detail类型从同分析日、解析后同as_of、同episode的report恢复current_review到返回的内存上下文；状态/观点变化仍来自账本。每个账本日只读一次对应report，不逐episode扫档，不写回。缺报告或身份不匹配保留状态、正文未知，不借用更旧日期或同股其他episode。网页使用同样的身份核对规则。

网页scan_history仍同日同episode一条历史：新brief读账本，两种detail读report，账本null不能覆盖正文。导航标题/摘要可由已有首句提取函数从唯一正文机械生成，不是新AI简评，不能另存为简评或新增简评卡。携带review_kind作类型标签，保留页面布局。

旧无kind记录保留原“账本简评＋report详评”读取。新detail缺对应report时显示“详评正文未保存”，不能空白、补猜或倒退为昨天正文。保留HTML转义与换行。

### 3.5 Markdown与最终报告分区

市场段后依次为：

1. 关键节点复盘（K只）：全部K。每股说明“本次深入复盘原因：到达第X个交易日检查节点”；补D20写真实补结案原因。沿用详评三个小标题，D20另公开一次最终结论。
2. 今日深入复盘（D只）：仅D，不把节点混入该数。
3. 今日简评（B只）：仅B；六列表为“股票 | 当前观察日 | 当前涨跌 | 今日简评 | 未来1—3日 | 主动跟踪”，同股多episode按实际推荐日期区分。

空分区写“今日无……”一行，不复制其他区。移除新报告“全部股票简评总表＋同股再详评”的重复结构。总体跟踪计数可保留，旧档渲染仍原路径。

## 4. 实施顺序和具体命令

### Task 0：确认现场和基线

- [ ] 完整读本计划、AGENTS、当前架构、monitor prompt和复盘Skill；按技能要求读取实际用到的Skill，不另写方案。
- [ ] 保留用户diff，不恢复GitHub覆盖本地档案。

```bash
pwd
git rev-parse --show-toplevel
git rev-parse HEAD
git status --short
git diff --stat
./.venv/bin/python -B -m stock_analyzer.ops.forward_monitor --help
./.venv/bin/python -B tools/render_monitor_web.py --help
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor.py tests/test_forward_monitor_prompt.py tests/test_render_monitor_web.py tests/test_update_monitor_web.py -q
```

已有无关失败记录，不冒充本次通过，不借机改无关源码。

### Task 1：先红测试，再改模型和分组

文件：tests/test_forward_monitor.py、src/stock_analyzer/ops/forward_monitor.py。

- [ ] 加入核心集成测试，旧代码应因不支持kind/空简评/超过8只失败：

```python
def test_three_routes_five_nodes_eight_details_eight_briefs(tmp_path: Path):
    snapshot, reviews = _multi_daily_formal_snapshot(21)
    node_ids = []
    for i, (episode, review) in enumerate(zip(snapshot["episodes"], reviews)):
        kind = "checkpoint_detail" if i < 5 else "regular_detail" if i < 13 else "brief"
        review["review_kind"] = kind
        if i < 5:
            episode.update(day_number=10, checkpoint="D10")
            review.update(day_number=10, checkpoint="D10")
            node_ids.append(episode["episode_id"])
        review["current_review"] = None if i < 13 else f"简评正文{i}。"
    snapshot["checkpoint_review_episode_ids"] = node_ids
    snapshot["detailed_review_candidate_codes"] = [
        e["ts_code"] for e in snapshot["episodes"][5:]]
    snapshot["summary"].pop("detailed_review_stock_count", None)
    snapshot["summary"].update(checkpoint_review_stock_count=5, regular_detail_stock_limit=8)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    ledger_pending = tmp_path / "pending-ledger.json"
    ledger_pending.write_text(json.dumps({
        "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
        "analysis_date": snapshot["analysis_date"], "as_of": snapshot["as_of"],
        "reviews": reviews,
    }), encoding="utf-8")
    saved_ledger = record_daily_formal_reviews(
        snapshot_file=snapshot_path, review_file=ledger_pending, project_root=tmp_path)
    assert saved_ledger.review_count == 21
    alerts = []
    for i in range(13):
        alert = _daily_detail_alert(snapshot["episodes"][i], reviews[i])
        alert["episode_reviews"][0]["current_review"] = f"唯一详评正文{i}。"
        alerts.append(alert)
    pending = tmp_path / "pending-report.json"
    pending.write_text(json.dumps(_report_payload(snapshot, alerts=alerts)), encoding="utf-8")
    result = record_forward_monitor(
        snapshot_file=snapshot_path, report_file=pending, project_root=tmp_path)
    assert result.alert_count == 13
    markdown = Path(result.markdown_file).read_text(encoding="utf-8")
    assert "关键节点复盘（5只）" in markdown
    assert "今日深入复盘（8只）" in markdown
    assert "今日简评（8只）" in markdown
    for i in range(13):
        assert markdown.count(f"唯一详评正文{i}。") == 1
    for i in range(13, 21):
        assert markdown.count(f"简评正文{i}。") == 1
    stored = json.loads(Path(saved_ledger.json_file).read_text(encoding="utf-8"))
    assert sum(r["current_review"] is not None for r in stored["reviews"]) == 8
```

- [ ] 实施第3.1节字段/校验；更新test_daily_formal_review_models_define_the_v1_contract字段集合。brief 600字符通过、601拒绝、空brief拒绝；detail空正文通过、有正文拒绝；旧无kind正文可读。
- [ ] 在forward_monitor.py加入局部纯函数，不另建模块：

```python
def _checkpoint_review_scope(*, snapshot: dict[str, Any]) -> tuple[set[str], set[str]]:
    daily_ids = set(snapshot.get("daily_review_episode_ids", []))
    eligible = [e for e in snapshot.get("episodes", [])
                if e.get("episode_id") in daily_ids
                and e.get("role") == "selected"
                and _episode_selection_output_class(e) in PUBLIC_FORMAL_OUTPUT_CLASSES]
    pending = set(snapshot.get("required_final_review_episode_ids", []))
    nodes = {str(e["ts_code"]) for e in eligible
             if int(e.get("day_number", 0)) in {1, 3, 5, 10, 20}
             or e["episode_id"] in pending}
    non_nodes = {str(e["ts_code"]) for e in eligible} - nodes
    return nodes, non_nodes
```

- [ ] prepare在daily IDs及待结案IDs确定后调用，生成第3.2节字段；同时更新PrepareSummary和测试构造，不能只改JSON漏掉dataclass。
- [ ] 实际prepare调用级测试：包装此函数后调用现有_prepare，确认传入episodes/daily IDs/待结案IDs，节点IDs/非节点候选/两项summary正确；同股一条到节点时该股全部合格daily episode均进入checkpoint_review_episode_ids，而非只保存自身恰好到节点的ID。不能只用手工snapshot证明接线成功。

```bash
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor.py -q -k 'three_routes or checkpoint_review or daily_formal_review_models'
```

### Task 2：两次record和上轮正文

文件：src/stock_analyzer/ops/forward_monitor.py、tests/test_forward_monitor.py。

- [ ] 新snapshot分支下，两次record均验证daily IDs覆盖、kind/节点吻合和同股一致。
- [ ] 局部校验函数复用以下集合逻辑：by_code为已验证daily IDs按股票聚合的DailyFormalReviewV1列表，node_codes/non_node_codes来自Task 1。无需类型框架。

```python
kinds_by_code = {code: {r.review_kind for r in rows} for code, rows in by_code.items()}
if any(len(kinds) != 1 or None in kinds for kinds in kinds_by_code.values()):
    raise ValueError("new reviews require one explicit kind per stock")
kind_by_code = {code: next(iter(kinds)) for code, kinds in kinds_by_code.items()}
if {code for code, kind in kind_by_code.items() if kind == "checkpoint_detail"} != node_codes:
    raise ValueError("checkpoint reviews must exactly cover checkpoint stocks")
regular_codes = {code for code, kind in kind_by_code.items() if kind == "regular_detail"}
if regular_codes - non_node_codes or len(regular_codes) > 8:
    raise ValueError("regular details must be non-checkpoint stocks and at most eight")
expected_report_codes = node_codes | regular_codes
```

报告阶段要求reported_codes==expected_report_codes，保留每股全部episode及原结构化一致性。账本声明普通详评但无report也拒绝，brief不能带alert。

- [ ] 新流程_validate_detailed_review_priority仅对非节点看停止/重要观点变化：优先股≤8须纳入D；>8则D恰好8且从优先股中选，其余B照常披露变化。其他事项由prompt语义选择。没有优先项允许D=0，不强制轮换补满。
- [ ] V2移除alerts总数max8；拆分旧test_report_model_rejects_more_than_eight_or_duplicate_stocks：V2可解析13但拒重复，V1拒9，旧record路径仍拒>8，新record受三路约束。保留旧snapshot测试，不能把全部fixture升级掩盖旧档读取。
- [ ] _daily_review_history按同日/as_of/episode恢复返回上下文的正文，不写账本；不改_previous_episode_reviews其他历史语义。
- [ ] 明确测试以下行为：
  - 9节点＋8普通接受17详评；9节点＋9普通拒绝。
  - 0节点、0普通、全部简评接受；只有节点接受；0股票空账本/空报告接受。
  - 漏节点、节点标brief/regular、普通冒充节点、漏brief状态、brief又带alert均拒绝。
  - 节点＋事件仅一篇；非节点9个重要变化只能8详评＋1简评。
  - 同股不同episode一类一名额；其中一个节点则同股其他合格episode同篇，不改实际观察日。
  - 五节点分别必进K；D20用_final_review()，冻结且不可提前；day>20待补结案进K；evaluation_only普通节点不复活；D25/D30不新增节点。
  - 连续两日：D10仅report正文，下一日previous_daily_formal_review恢复正文和账本状态；日期/as_of/episode不匹配不能借用，缺报告正文未知。
  - 新snapshot缺账本不得走legacy；旧无kind/V1/V2可读；幂等、冲突、停止条件仍通过。

```bash
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor.py -q
```

### Task 3：Markdown三路与网页唯一正文

文件：forward_monitor.py、render_monitor_web.py及对应两个测试文件。

- [ ] 新_render_markdown按kind分K/D/B，依次输出第3.5节。复用现有每股详评块，不复制两套渲染函数。简表只B，六列表头/分隔线/空行一致。
- [ ] 简评单元格使用现有局部表达式，仅在已验证brief分支执行，不对detail的None调用splitlines：

```python
brief_text = " ".join(review.current_review.splitlines()).replace("|", r"\|")
```

- [ ] 节点明确检查原因，不从alert_type=routine_detail推断类型；三路同股不重复。
- [ ] scan_history新detail合并保留report的copy/headline/summary_copy/正反条件，状态和观点变化来自账本；导航摘要可用现有首句提取。brief读账本，legacy保留旧行为，新detail缺report显示明确提示。
- [ ] 网页测试：节点report＋账本null合并一条、正文首尾完整、kind正确；普通detail同样；brief无alert仍可读；17只报告不截断；不同as_of不合并；旧简详分离读取不变。
- [ ] Markdown测试：21只各属唯一分区；节点说明D10原因；9节点不写“今日深入复盘9只”；空分区正确；竖线换行不破表；D20完整结论一次；HTML安全转义和换行回归。

```bash
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor.py tests/test_render_monitor_web.py -q -k 'three_routes or markdown or history or detail or summary or final'
```

### Task 4：同步规则和三类样稿

- [ ] 白名单规则文件同步第2—3节；删除新流程“全体先简评”“恰好8只”“必评超8才扩容”“节点竞争8只”，保留旧档兼容说明。
- [ ] 总控/selection改为全部状态草稿→K/D/B→各写唯一正文→自检→先账本后报告；消费新prepare计数，不调用未暴露helper或发明CLI。
- [ ] AGENTS明确：每日账本保存全部结构化状态及仅简评类正文；monitor-report保存全部节点详评和最多8只普通详评；节点不重复简评。
- [ ] D10深度风格适用于五节点，按各节点问题展开。文风锚原文不改；取消软长度，不改600及事实边界。
- [ ] prompt测试覆盖互斥、普通≤8可0、节点D10风格/不简评、D20唯一冻结、无新任务/条件解析器；不只删除旧断言。
- [ ] tests/test_engine_contract_knowledge_v4.py中复盘“最多4个”正向断言改为“只使用回答中心问题所需事实、不设固定数量指标、不得凑数”，并明确“最多4个”不再出现在锚外规则中；不得改选股相关断言。

```bash
rg -n '全部.*简评|每个.*简评|恰好.?8|最多.?8|8只详细|8只重点|detailed_review_stock_count|review_kind|checkpoint_review|60—140|150—320|180—350|400—800|2—4段|最多4个' \
  AGENTS.md ops/forward-monitor-prompt.md ops/forward-selection-prompt.md \
  .agents/skills/reviewing-stock-recommendations/SKILL.md \
  .agents/skills/orchestrating-stock-research/SKILL.md \
  docs/architecture/current-v3-architecture.md docs/architecture/forward-monitoring-v1.md \
  src/stock_analyzer/ops/forward_monitor.py tools/render_monitor_web.py
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor_prompt.py tests/test_engine_contract_knowledge_v4.py -q
mkdir -p local_archive/review_format_acceptance
mktemp -d local_archive/review_format_acceptance/2026-09-06-three-routes-XXXXXX
```

逐项阅读rg，不机械删8/600/旧分支。用命令返回的新目录，以apply_patch新建three-route-samples.md，后续始终用同一实际路径：

1. 银龙9/3 D10：仅节点详评，沿用当日snapshot/原判断/真实上轮记录，不用9/4事实，不配简评。
2. 银龙9/4 D11：普通详评出口示范，只写详评；显式9/4 18:30截止，只读现有事实/函数，不冒充周日正式截止或已有正式日报。
3. 银龙9/2 D9：剩余股票简评出口示范，只写简评，不配详评。
4. 21只合成例5节点＋8普通＋8简评：由tmp_path集成测试检查完整Markdown，样稿记录结果，不伪造21只真实观点。

三份真实日期是不同日期的独立展示样稿，不宣称已重选当日真实全体名额。只用截至当日事实，真实上轮条件，不能把文风示例数字当模板。无需刷新数据、生成正式snapshot/ledger/report或重演选股，不将样稿入库。

### Task 5：最终回归，交付停止

```bash
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor.py tests/test_forward_monitor_prompt.py tests/test_forward_review_context.py tests/test_render_monitor_web.py tests/test_update_monitor_web.py tests/test_forward_selection.py tests/test_engine_contract_v4.py tests/test_engine_contract_knowledge_v4.py -q
git diff --check
git diff --stat
git status --short
git diff -- AGENTS.md src/stock_analyzer/ops/forward_monitor.py tools/render_monitor_web.py
```

- [ ] K全覆盖、D≤8、B只简评、三组互斥；detail账本没有简评正文，不以“内部需要”生成隐藏简评。
- [ ] 五节点D10深度且时点正确、D20唯一冻结、旧档可读、新detail上轮正文不丢失。
- [ ] diff仅白名单，未改事实/价格/选股/自动任务/正式历史。只修本任务导致的失败，已有无关失败报告。

交付改动清单、测试结果、三类各一份真实日期样稿、21只路由验收及限制。明确规则仅用于后续正常任务、历史未改，然后停止。不提交、推送、部署或扩展其他模块。

## 5. 本版独立审查

本版已由一个gpt-5.6-sol / xhigh审查者完成单次独立审查，结论为“通过（以修订版为准）”。三种兼容分支、同股节点prepare接线、D20正文分工、同日同as_of同episode读取，以及必要知识合同测试修订均已并入。审查者未实施或另派Agent。GLM直接按本版Task 0—5执行，不重设配额、不重复设计或另启审查；本次未实施业务代码。
