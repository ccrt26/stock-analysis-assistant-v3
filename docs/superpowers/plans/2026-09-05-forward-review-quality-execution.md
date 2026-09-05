# 正式推荐复盘质量修复 Implementation Plan

> **For agentic workers:** 按 `superpowers:executing-plans` 顺序执行本计划。用户已指定交给 GLM 执行，不使用多智能体开发流程。下文的范围、公式和验收是本次唯一实施合同；不另写一套设计。
>
> **审查状态：** 通过（以本次审查修订版为准）。2026-09-05，已完成唯一一次 `gpt-5.6-sol / xhigh` 独立审查，并将全部修订并入本文件。GLM直接执行本版本，不再发起第二轮设计或审查。

**Goal:** 恢复可追溯的原推荐判断，使日评保持简短、重点详评能够解释阶段路径，并让同一份详评正确进入 Markdown 和现有网页。

**Architecture:** 沿用事实仓、snapshot、每日简评账本和 V2 详评模型。只在现有 monitor 准备流程增加一个小型复盘价格上下文字典；复用已有 `current_review` 分别保存简评和详评。程序负责有明确公式的数值，AI负责解释并在保存前逐项核对依据。

**Tech Stack:** 现有 Python、Pandas、DuckDB/Parquet、Pydantic、pytest；现有 Python/HTML 网页渲染器。

**Spec:** 本文件第1—4节就是本次最终问题与设计，不另建 spec、配置系统或规则引擎。

## 1. 本轮确认的问题与对 GLM 方案的取舍

### 确认的问题

1. 详评正文被强制与简评逐字相同，日评600字符上限间接约束详评。D5/D10小结与“只有D20允许串起过程”相冲突。
2. 9/3快照62条记录中，6条replay缺完整原判断；原文件仍有数据。当前 `register_episodes` 和 `_fill_missing_original_fields` 已能补齐，不能再开发一套恢复框架。
3. 现有输入已有许多单点指标，但缺可直接使用的跨日成交、统一价格单位、原目标剩余距离和清楚的基准标签。
4. 银龙 `view_change=weakened` 的原因是原资料缺失，不能让这种记录问题被理解成公司或股价出现新恶化。
5. Markdown和网页也强制以日评覆盖详评，只改record校验无法改善最终页面。
6. 已有事实追溯和知识调阅规则，但没有在本次生成中稳定落实；缺的是具体执行和一次对照核查，不是所有纪律从未存在。

### 对 GLM 新增判断的校正

- 尚太不是应删除的重复记录：`formal:2026-08-21:001301.SZ:comparator` 对应8/24行动日和北矿；`v4-replay-2026-08-20:2026-08-20:001301.SZ:comparator` 对应8/21行动日和银龙。两条都保留，严禁按股票代码去重或跨episode借用参考价。
- 现金流47,872,105.12元 / 归母净利240,971,113.09元约19.87%，但合并现金流与归母口径并不完全一致。合并净利263,671,956.27元对应约18.16%。这些是同一半年期间的辅助比值，不直接证明利润失真或股价安全；应结合同比、应收和存货定向检查。
- 基准、起点和复权在现有计算代码中并非任意选择，主要问题是输出未充分标注、生成时混用。新增字典不能保证AI永不写错。
- 不接受“AI不得计算任何数字”的绝对禁令。允许工具按公式计算和格式换算；禁止凭空心算派生结论或不留来源的临时数字。
- 不实现中文正文数字抽取、模糊容差匹配、自然语言因果判别器或“所有错误必须被程序拒绝”。数字相同也可能股票、日期、指标含义不同，这类通用核验器成本高且不能保证正确。
- 不实行每日第二模型/子智能体复查。由同一执行者写完后对照来源检查一次；开发阶段按仓库规则完成一次指定独立审查即可。
- 不实行“数据问题永远不能改变观点”。单纯文件缺失不代表投资命题恶化；若核实原证据错误并足以改变判断，可以更正观点，但必须说明纠正的是哪项原依据，不伪称当天新利空。
- 不建立新背景卡数据库或“首次生成后永久冻结”的AI文字缓存。原trace已有历史锚，现有 `original_reason_plain_language` / `original_key_risk_plain_language` 足够展示与复用。
- 本轮不开放备选股对外展示。内部配对恢复即可，公开政策保持现状。
- 不把增加快照字段称为天然低风险。本计划整体涉及正式复盘合同，统一过一次实施前审查。

## 2. 执行提示与范围锁定

**执行提示：** 在当前股票助手仓库中，完成“恢复6条replay原判断和原配对、增加有明确口径的复盘价格上下文、分开日评与详评正文、打通Markdown及现有网页、简化复盘生成规则并补必要测试”。原推荐集合、episode身份、历史判断、既有价格指标含义、D20结算和定时任务不变。验收包含确定性数值测试、合同与渲染集成测试、一个真实银龙D10离线样稿。只在最终验证通过后用现有register命令补齐正式registry缺失字段；不重写历史snapshot、日评、报告或trace。

### 唯一允许修改的源码/规则文件

- `src/stock_analyzer/ops/forward_monitor.py`：添加小型价格上下文纯函数及接线、放开正文逐字一致、Markdown正文选择和背景说明。
- `tools/render_monitor_web.py`：保留已有页面布局，解决简评覆盖详评并允许阅读长段落。
- `ops/forward-monitor-prompt.md`：唯一完整复盘方法说明。
- `ops/forward-selection-prompt.md`：只同步其中复盘段落的正文来源；新选股部分不改。
- `.agents/skills/reviewing-stock-recommendations/SKILL.md`：同步简详分工、阶段小结、证据核对。
- `.agents/skills/orchestrating-stock-research/SKILL.md`：只同步review段的正文分工；不改发现、验证或选择。
- `.agents/skills/analyzing-price-trading/SKILL.md`、`.agents/skills/researching-company-events/SKILL.md`：仅必要的review输入/证据说明，不改其他阶段。
- `docs/architecture/forward-monitoring-v1.md`、`docs/architecture/current-v3-architecture.md`：简短同步现状，不重写架构。
- `tests/test_forward_monitor.py`、`tests/test_forward_monitor_prompt.py`、`tests/test_render_monitor_web.py`：修改受本合同影响的测试。
- 可新增且仅新增一个定向测试文件 `tests/test_forward_review_context.py`。

运行产物仅放在被忽略的 `local_archive/review_quality_acceptance/`，正式存量修改仅限 `local_archive/forward_monitor/registered-episodes.json` 的缺失字段补齐及一个备份。

**开始时已有用户修改：** `tools/render_monitor_web.py`、`tests/test_render_monitor_web.py`。必须在现有修改上做局部增量，不reset、不checkout、不stash、不拿HEAD版本覆盖。若执行时状态变化，先读diff；能局部合并就继续。

**明确不做：** 不新增报告版本/Pydantic模型/数据库表/迁移框架/新服务/新数据源/定时任务；不新建数值核验平台、证据图谱、自动中文评分或每日模型调用链；不改数据采集与事实仓时点查询机制；不扩充选股范围、不重跑选股、不删尚太任何记录；不批量重写历史；不增加概率、评级、仓位或自动交易；不重做网页；不安装依赖；不提交、推送或发布。不得修改本轮白名单之外的源码以“顺便优化”。

旧报告继续按已有读取路径可读，不建立新兼容层。已有数据哈希保持原样，本次不新增manifest或校验和文件。

## 3. 最终数据与输出设计

### 3.1 一个 `review_context` 字典，写入现有snapshot episode

先生成全部 `observations`、调用 `_attach_pair_contexts`，再确定 `daily_review_episode_ids`。`review_context` 的目标集合严格等于：当日需日评的正式推荐episode，加上它们 `pair_context.paired_episode_id` 指向且确实存在的同批配对episode；不得按股票代码寻找或跨episode借用。

从 `sessions` 中先过滤 `date <= analysis_date`，再取最后61个市场会话。用这61日一次性扩展 `_daily_price_cache`，同时继续把原 `_episode_observation` 的 `path_days` 限制在行动日至分析日最多30日，因此新增历史不得改变旧收益、D20或配对指标。不得为每个episode重新读取价格分区。

沪深300也只读取上述61个 `index_daily/trade_date=...` 分区，沿用 `available_at <= as_of` 截止，一次性过滤 `index_code == "000300.SH"` 后按日期缓存。不得调用 `_fact_rows(..., "index_daily", ...)` 扫描五年全仓，不得把网页现有的上证指数展示口径混入 `review_context`，也不得把其他指数行传入纯函数。

上述接线应在snapshot写入前完成，但不得影响attention、tracking、角色、配对或重点股票选择。`basis` 使用原episode的 `formation_date/action_date/source_as_of` 和本次snapshot的 `analysis_date/as_of`；行业名称与代码只能取该股票本次 `price_row.primary_industry_code/name`。

61日窗口以分析日结尾尤其重要：真实9月3日snapshot的 `as_of` 是9月4日上午，不能把9月4日会话带入9月3日复盘。

复用已有 `_daily_price_cache`、`_adjusted_path` 和当前截止规则；新字段只消费已截断的数据。不得修改旧路径计算、D20收益或旧字段含义。

新增一个纯函数，固定接口如下，辅助私有函数只在确有必要时局部添加：

```python
def _build_review_price_context(
    *,
    action_date: date,
    analysis_date: date,
    session_dates: list[date],
    adjusted_history: list[dict[str, Any]],
    normalization_factor: float | None,
    benchmark_daily: list[dict[str, Any]],
) -> dict[str, Any]:
    ...
```

`adjusted_history` 沿用 `_adjusted_path` 的记录结构：date、open/high/low/close（raw×当日复权因子）、amount（元）。`benchmark_daily` 仅传000300.SH的trade_date/open/close；读取层已按as_of过滤。函数不读写文件、不选股、不解释形态。

调用层在函数返回值补入 `basis`：原形成日、行动日、原 `source_as_of`、本次analysis_date/as_of；`benchmark_code=000300.SH`、`benchmark_name=沪深300`；`price_basis=raw_times_factor_div_analysis_factor`、`price_basis_date=analysis_date`、`amount_unit=CNY`；相对行业字段对应的 `primary_industry_code/name` 从本次price_context读取。不能把 `original_group_code` 的行业上涨面与另一行业的相对收益混标为同一指标。

字典只含以下内容，不扩展为通用特征库：

| 字段 | 精确定义 |
|---|---|
| `post_entry_sessions` | 行动日至分析日、最多30个市场会话；date、归一后的open/high/low/close、amount、相对此episode入口的close_return/high_return。缺报价的市场日期保留空行，不把后一个开盘替作入口。 |
| `recent_sessions` | 分析日及前4个市场会话；同样的OHLC/amount，另含close_return_1d、amount_change_1d、amount_ratio_including_today_20d。它可能含推荐前日期，必须保留日期。 |
| `benchmark_windows` | 1/3/5/20四个close-to-close窗口，每项包含start_date/end_date/return；使用市场日历的第h个前序收盘作起点，缺任一必要会话收盘时该窗口为空。它不是推荐以来收益。 |
| `benchmark_return_since_entry` | 沪深300行动日开盘至分析日收盘；与该episode股票收益起止一致。缺可靠指数开盘或窗口不全则为空，不用形成日收盘冒充。 |
| `stock_excess_since_entry` | 既有完整股票入口收益减同窗口benchmark_return_since_entry；任一不完整则为空。不新增“推荐以来行业收益”计算，本轮仍使用有明确窗口的既有relative_industry字段。 |
| `price_levels` | entry_reference_price、current_close、prior60_high、prior60_high_date、prior60_close_high、prior60_close_high_date、atr20、target_price、remaining_return_to_target、remaining_atr_to_target。 |
| `limitations` | 只记录这些新字段的具体缺口，不因非关键字段不足改变股票跟踪状态，不新增状态枚举或全局阻断。 |

公式与边界：

- 归一价格 = 已复权价格 / 分析日的可用复权因子F。入口、当前价、前高、ATR、目标价均在同一归一基准上；不得把顶层旧 `entry_open`（raw×factor）当作真实交易报价。
- analysis日F缺失：涉及人民币价位的新字段为空，已有收益指标保持原值；不得拿后一天F补齐。
- 相对入口收益仍由 `adjusted_close / adjusted_action_open - 1` 算；有除权时原始行动日开盘价与当前口径归一入口可能不同，展示说明是复权参考，不能改变原收益。
- 当日成交额 / **含当日**20个市场会话平均成交额；保留原字段相同口径。缺会话/成交额不以0补齐，也不压缩成20个有数据日。
- `amount_change_1d = amount_t / amount_prev - 1`，前值非正或缺失则空。
- prior60指**不含分析日**的此前60个市场会话；OHLC或必要日期不全则对应前高为空，不能悄悄改成“已取得日期里的前高”。并列最高值取最近一次发生日期。
- TR = max(high-low, abs(high-prev_close), abs(low-prev_close))；ATR20 = 含当日20个完整市场会话TR的简单平均。沿用现有项目20日口径，不引入ATR14或另一种平滑。
- target_price = 该episode归一入口×1.20。
- remaining_return_to_target = target_price/current_close−1；remaining_atr_to_target = (target_price−current_close)/ATR20。保留符号；已完成目标时不能渲染成“还差负数”。
- 既有 `target_atr_distance_20pct = 0.20 / atr_ratio_20d` 表示从当前价再涨20%的距离；其含义不改，新字段才表示距离原推荐目标的余程。
- 只使用date≤analysis_date且读取层available_at≤as_of的行；不因分析日收盘后补跑就修改原as_of。所有会话数使用既有交易日历。
- 不给“前高”自动附加“套牢盘”“真实抛压”标签，不用ATR距离产生成功概率。

### 3.2 简评、详评、展望的唯一分工

- `DailyFormalReviewV1.current_review` 仍是日常简评，保留600字符硬上限。没有变化通常1—3句；不强行按每日涨幅列事实。
- `ForwardEpisodeReviewV1.current_review` 是独立展开的详评，使用它已有的无最大长度字符串。无需新增字段或报告版本。
- record不再比较两份 `current_review` 是否逐字相等；继续严格比较episode、日期、current_assessment、best_supported_explanation、current_weak_or_failed_link、outlook_1_3d、outlook_reason_plain_language及D20最终结论。数量、角色、停止规则、配对完整性校验全部保留。
- `view_change` / `view_change_reason` 继续来自当日日评，不在详评另造一份。展望和两个条件仍用既有字段。
- 先综合判断、写日评草稿、选择最多8只重点、展开详评并作一次来源核对，再正式record日评和详评；保存动作仍先日评后报告。保存前发现详评改变了判断，应先同步未保存草稿，不能事后改已保存账本。
- 重点详评回答：当初主要期待什么；推荐后哪几段变化最关键；哪些原预期实现/削弱/未知；最合理解释及其局限；离原观察目标还有哪些实际障碍。问题相关时才使用公司经营和知识条目，不机械凑栏目或字数。
- 普通重点日通常2—4段；D5/D10及实质变化允许约400—800中文字，属于写作参考，不加硬长度校验。D20完整最终总结仍只在 `final_twenty_day_review.overall_review` 出现一次。D1/D3/D5/D10/D20安排和8只规则保持。
- D5/D10可以串起截至当日的阶段路径，但不能提前形成或冻结D20最终结论。
- 原背景继续使用现有两个original_*白话字段，忠实于原trace；已有同episode的可靠白话背景可以复用，无须新存储或版本。D1、D5、D10、D20详评可展示一到两句背景；其他详评只有理解当天变化确有需要时才提及。
- 原thesis不完整但有original_primary_reason、风险、market_recognition或原decision时，按已知部分继续；仅未知部分说明未保存。不能机械说“只能复盘价格”。

### 3.3 同时修正两个公开读取端

Markdown详评正文读取 `review.current_review`；全部主动推荐简表仍读ledger；观点变化仍读ledger。原背景说明不得在thesis缺失时抹掉已有概要锚。

网页 `scan_history` 的report历史项初始化为 `copy=详评正文`、`summary_copy=同一正文`；ledger历史项初始化为 `copy=简评正文`、`summary_copy=简评正文`。

同日同episode合并时，`summary_copy/headline/结构化观点/view_change/outlook` 来自ledger，`copy/正反条件` 保留report；只有report不存在时 `copy` 才回退为简评。旧report没有ledger时两者自然相同。这只是网页内存payload，不是新的持久化报告schema。

`renderReview` 的长正文只读 `copy`；概览、今日标题及用户已修改的 `_events_for` 时间线摘要读取 `summary_copy`，并以 `copy` 作为旧数据回退；不能在后续build_payload或JS又覆盖成简评。继续使用 `textContent` 或 `esc`，保留段落换行，不把AI正文当HTML执行。背景复用现有reasonFull/reasonRisk区域，仅在阶段详评按上述规则显示，不改图表、筛选、布局或导航。

### 3.4 事实纪律和知识的最小落地

删除限制深度的重复字数/固定句式微规则；保留一个总标准：

> 每个关键判断都有可追溯依据，并解释它支持什么、还不能证明什么。阶段详评应让读者理解原预期如何被后续事实检验。

允许引用：
1. 本次snapshot和原trace中明确的字段；
2. 本次由现有工具按明确公式算出的数值；
3. 公司Skill按本次snapshot已冻结的 `as_of` 定向取得的正式公司事实。

公司事实的复盘截止是本次snapshot的 `as_of`，不是原推荐的 `source_as_of`，也不是执行时当前时钟。原推荐 `source_as_of` 只用于还原当时判断，新事实用于截至本次复盘截止时点检验该判断。
百分数格式、四舍五入和元/亿元换算可以直接做。窗口、收益、ATR和现金流比值等必须由工具计算并保留口径。

公司事实只在原判断相关、阶段检查或重大变化时按需核对少量公司、相同报告期/合并范围与可比同期；不每日报全套财务，不运行全市场财务回填。现金流、利润、应收、存货各自回答什么必须说清。

知识不按“每只2—3条”配额。实际改变判断时，在已有alert `stock_change` / `company_change` / `market_change` 内部字符串追加简短记录：
`知识：条目ID；本次用途：具体哪项解释被限制/支持；不能推出：具体边界。`
不新增knowledge表或Pydantic字段，不输出置信度分数。没有实际作用就不凑条目。

同一执行者在保存前核对一次：
- 股票/episode、起止日、沪深300/行业口径是否一致；
- 每个关键数字是否能在明确字段或本次工具结果中找到；
- 是否把回落、前高、成交变化写成买方人数、账户身份或唯一原因；
- 新判断是否真的由经济事实或已核实的原证据纠正导致；
- 简评、详评、方向和条件是否一致；条件尚只部分出现时是否如实说明。

程序测试数值与结构合同；AI核对文字语义。不得新建正文数字解析器，也不得声称任何程序可以保证自然语言绝不误述。

## 4. 实施与验收顺序

### Task 0：固定执行现场

- [ ] 完整读本计划、AGENTS和当前架构；相关Skill只读本次必要部分并按各Skill要求完整读其主文件。
- [ ] 记录命令取得的HEAD和工作区状态，不在多个文件手抄SHA。

```bash
pwd
git rev-parse --show-toplevel
git rev-parse HEAD
git status --short
git diff -- tools/render_monitor_web.py tests/test_render_monitor_web.py
./.venv/bin/python -B -m stock_analyzer.ops.forward_monitor --help
./.venv/bin/python -B tools/render_monitor_web.py --help
```

上述两个CLI已由计划编写者核对。monitor没有 `--project-root` 参数，不能发明该参数。离线验证必须调用接受project_root的Python函数。

### Task 1：先写并跑失败测试，再分离简评与详评

**文件：** forward_monitor、两个monitor测试、网页渲染器和测试。

先在 `tests/test_forward_monitor.py` 复用现有 `_daily_render_case`、`_render_daily_case`、`_record_daily_review_for_snapshot` fixtures。将“正文必须相同”测试改成以下两个独立行为，不能把旧测试直接删除了事：

```python
def test_daily_and_detail_text_may_differ(tmp_path: Path) -> None:
    snapshot, daily, alert = _daily_render_case(10)
    daily["current_review"] = "日评：整理尚未结束。"
    detail = "详评：原来期待的相对强势仍需逐日检验。" * 40
    assert len(detail) > 600
    alert["episode_reviews"][0]["current_review"] = detail
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    _record_daily_review_for_snapshot(tmp_path, snapshot, daily)
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(_report_payload(snapshot, alerts=[alert])),
                       encoding="utf-8")
    result = record_forward_monitor(
        snapshot_file=snapshot_path, report_file=pending, project_root=tmp_path
    )
    assert result.status == "recorded"
    markdown = Path(result.markdown_file).read_text(encoding="utf-8")
    assert detail in markdown
    assert daily["view_change_reason"] in markdown
```

另用同fixture分别修改结构化current_assessment、outlook_1_3d，验证仍拒绝冲突；D20结论冲突单独使用 `_daily_render_case(20)`，不能在D10 fixture上伪造D20结论。正文不同不再拒绝。D20不可提前、结论冻结、8只限制等原测试保持。

网页测试必须构造同日“简评A、详评B”，确认：
`scan_history(...)[episode][0]["summary_copy"] == A`，
`["copy"] == B`，
观点变化/方向仍来自日评；
只有日评、只有旧详评两种输入仍可读；
同股票不同episode的A/B不会串用。
更新原先强制“台账覆盖正文”的断言，不改无关测试。

```bash
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor.py tests/test_render_monitor_web.py -q -k 'daily or detail or history or background or final or frozen'
```

先确认新测试因旧行为失败，再实现第3.2/3.3节；通过后继续。

### Task 2：增加有明确口径的价格上下文

**文件：** forward_monitor + 新测试 `tests/test_forward_review_context.py`。
**接口：** 严格使用第3.1节纯函数与字段，不新增持久化模型。

`tests/test_forward_review_context.py` 只测试纯函数公式、61日边界、缺口、除权和同episode入口口径。读取层相关用例放入 `tests/test_forward_monitor.py`，复用临时项目fixture测试 `prepare_forward_monitor`：as_of晚于analysis_date仍不纳入未来会话；available_at越界的股票、复权及指数行不影响结果；混合指数分区只用000300.SH；扩展cache不改变旧收益、D20、配对及 `target_atr_distance_20pct`。这些测试不得构造 `ResearchWarehouse`，只写 `tmp_path` 下的最小Parquet事实。

至少覆盖这些有确定答案的测试：

| 用例 | 必须得到的结果 |
|---|---|
| 入口7.19、当前7.90、ATR20为0.2615 | 目标8.628；剩余涨幅0.0921518987；ATR余程约2.7839388145。 |
| 20个会话前19日成交额100、今日200 | 含当日均额105，量比200/105；不能返回2。 |
| 除权样例：入口raw10/F1，当前raw6/F2 | 收益20%；按当前F归一入口5、当前6、目标6，不能生成12的目标价。 |
| 形成日收盘12、行动日开盘10、后续最高收盘11 | 最高收盘收益10%，不能混入形成日得到20%。 |
| 同代码两个episode，入口10和12 | 当前11分别+10%和−8.3333%，记录数保持2。 |
| benchmark另附000001.SH行 | 读取层只传000300.SH，原相对收益标签和新基准收益均为沪深300。 |
| 行动日无开盘、后一天有报价 | 原参考价仍空，不能以后一天重设入口。 |
| 日历中间缺报价/成交或只有不足20/60个会话 | 保留缺口，受影响窗口/均额/前高为空，其余合法事实保留。 |
| 注入analysis_date之后或available_at>as_of行 | prepare产生的新旧相关指标均不受这些行影响。 |
| 原target_atr_distance_20pct存在 | 旧值/含义不变，原目标余程使用新字段。 |

提供一个可直接放入新测试文件的核心断言，完整构造61个顺序会话与恒定TR数据，不读真实仓：

```python
from datetime import date, timedelta
import pytest
from stock_analyzer.ops.forward_monitor import _build_review_price_context

def test_review_context_original_target_and_including_today_amount():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(61)]
    rows = [
        dict(date=d, open=7.9, high=8.03075, low=7.76925,
             close=7.9, amount=100.0)
        for d in days
    ]
    rows[40]["open"] = 7.19
    rows[40]["low"] = 7.19
    rows[-1]["amount"] = 200.0
    result = _build_review_price_context(
        action_date=days[40], analysis_date=days[-1],
        session_dates=days, adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=[
            dict(trade_date=d, open=100.0, close=100.0) for d in days
        ],
    )
    levels = result["price_levels"]
    assert levels["target_price"] == pytest.approx(8.628)
    assert levels["remaining_return_to_target"] == pytest.approx(8.628 / 7.9 - 1)
    assert levels["atr20"] == pytest.approx(0.2615)
    assert levels["remaining_atr_to_target"] == pytest.approx(0.728 / 0.2615)
    assert result["recent_sessions"][-1]["amount_ratio_including_today_20d"] == pytest.approx(200 / 105)
```

上例传入的是测试自定义市场会话序列，纯函数不能自行按星期删日期。实际prepare必须传真实日历。历史支持价格可以早于行动日，收益路径必须从行动日开始。

```bash
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_review_context.py -q
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor.py -q -k 'prepare or pair or register or entry or target'
```

保持旧公式和事实字段不变，允许只增加review_context；不要为修复新测试改旧expected收益。

### Task 3：同步Prompt、Skill与必要文档

- [ ] 将第3.2—3.4节落实到白名单文件，删除与之冲突的“逐字复制”“只有D20可串起过程”“缺thesis只能评价格”等规定。
- [ ] 删掉“多加数字就可靠”的隐含要求；正式事件不需要凑数字。
- [ ] 增加D5/D10背景和阶段判断；原始时点保持原记录，包括8/21 09:10的replay，不改成8/20 18:30。
- [ ] 复盘方法只在专用Skill/monitor prompt维护，总控和selection prompt只同步接口，避免把同一规则扩写到所有Skill。
- [ ] 修改测试里与旧正文相等合同绑定的断言，继续保留事实边界、跟踪状态、角色、8只、D20和交易日纪律的断言。

```bash
rg -n '逐字复制|逐字一致|只能复盘价格|D20.*唯一|唯一.*D20|current_review|missing_original_research_thesis' \
  ops/forward-monitor-prompt.md \
  ops/forward-selection-prompt.md \
  .agents/skills/reviewing-stock-recommendations/SKILL.md \
  .agents/skills/orchestrating-stock-research/SKILL.md \
  .agents/skills/analyzing-price-trading/SKILL.md \
  .agents/skills/researching-company-events/SKILL.md \
  docs/architecture/forward-monitoring-v1.md \
  docs/architecture/current-v3-architecture.md \
  src/stock_analyzer/ops/forward_monitor.py \
  tools/render_monitor_web.py
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_monitor_prompt.py tests/test_engine_contract_knowledge_v4.py -q
```

rg是供人核对上下文；保留“D20最终结论唯一且冻结”等正确规定，不能机械把所有“唯一”删除。

### Task 4：隔离验证原判断恢复与真实D10样稿

以下命令只建离线验收目录，复制小型历史JSON；事实仓为只读用途的链接。不要运行数据采集、ResearchWarehouse初始化或修改仓库事实。不要在正式root直接执行历史prepare，因为它会覆盖同日期snapshot。

```bash
./.venv/bin/python -B - <<'PY'
from pathlib import Path
from datetime import date, datetime
import json, shutil
from stock_analyzer.ops.forward_monitor import register_episodes, prepare_forward_monitor

root = Path.cwd()
case = root / "local_archive/review_quality_acceptance/2026-09-05"
case.mkdir(parents=True, exist_ok=False)
(case / "local_warehouse").symlink_to(root / "local_warehouse", target_is_directory=True)
monitor = case / "local_archive/forward_monitor"
selection = case / "local_archive/forward_selection"
monitor.mkdir(parents=True)
selection.mkdir(parents=True)
for pattern in ("registered-episodes.json", "snapshot-????-??-??.json",
                "daily-formal-reviews-????-??-??.json", "monitor-report-????-??-??.json"):
    for source in (root / "local_archive/forward_monitor").glob(pattern):
        shutil.copy2(source, monitor / source.name)
for source in (root / "local_archive/forward_selection").glob("research-trace-????-??-??.json"):
    shutil.copy2(source, selection / source.name)
before = json.loads((monitor / "registered-episodes.json").read_text())
seed = json.loads((monitor / "snapshot-2026-09-03.json").read_text())
register_episodes(
    trace_file=root / "local_archive/forward_selection/replay-v4-2026-08-20.json",
    label="v4-replay-2026-08-20", project_root=case,
)
after = json.loads((monitor / "registered-episodes.json").read_text())
assert {e["episode_id"] for e in before["episodes"]} == {e["episode_id"] for e in after["episodes"]}
assert all(e.get("original_research_thesis") for e in after["episodes"])
prepare_forward_monitor(
    analysis_date=date(2026, 9, 3),
    as_of=datetime.fromisoformat(seed["as_of"]),
    project_root=case,
)
snapshot = json.loads((monitor / "snapshot-2026-09-03.json").read_text())
by_id = {e["episode_id"]:e for e in snapshot["episodes"]}
silver_id = "v4-replay-2026-08-20:2026-08-20:603969.SH:selected"
silver = by_id[silver_id]
assert silver["day_number"] == 10
assert silver["original_research_thesis"]
assert silver["pair_context"]["pair_status"] == "complete"
assert silver["pair_context"]["paired_episode_id"] == "v4-replay-2026-08-20:2026-08-20:001301.SZ:comparator"
assert "formal:2026-08-21:001301.SZ:comparator" in by_id
assert "v4-replay-2026-08-20:2026-08-20:001301.SZ:comparator" in by_id
assert silver["review_context"]["basis"]["benchmark_code"] == "000300.SH"
print("acceptance_root=" + str(case))
print("silver_context=" + json.dumps(silver["review_context"], ensure_ascii=False))
PY
```

若验收目录已存在，为本次换一个新的尾缀并在后续命令保持一致；这是执行细节，不需要用户确认，不覆盖或删除前次验收目录。Task 4、Task 5和网页命令的路径必须全部改成实际同一路径，禁止备份或核对时退回硬编码的 `2026-09-05`。

**样稿交付：** 在该验收目录写 `silver-d10-sample.md`，包含简评和详评两部分，并在正文外附很短的来源核对说明（字段路径/原值/使用含义/实际使用知识条目）。它是离线开发样稿，不替换9/3正式日评，不改变当时view_change枚举，不用9/4价格。新生成的样稿观点按该历史截止重新检验，明确与旧正式结论的关系，不伪称当时已发布。

验收不是只看字数：
- 原期待、关键未知和至少两个阶段的真实价格成交变化可读；
- 不再用“缺完整资料”占掉主要分析；
- 绝对收益从8/21入口算，最近窗口另标，市场名称为沪深300；
- 公司现金和利润只在当时可得且口径明确时引用；
- 知识对判断确有作用才写，不能靠引用数量装饰；
- 相同结论的简评/详评不同长度确实通过record与两类渲染测试；
- 不能因样稿上涨而宣称原原因已经被证明，不能对外展示尚太名称/表现。

不要为样稿伪造整份21条日评/8只报告。record、Markdown和网页的全链路由上述1条/多条合成fixtures验收；真实样稿用于人工检查解释质量。

网页冒烟命令，仅输出验收目录文件，不改正式index：

```bash
./.venv/bin/python -B tools/render_monitor_web.py --date 2026-09-03 --monitor-dir local_archive/review_quality_acceptance/2026-09-05/local_archive/forward_monitor --out local_archive/review_quality_acceptance/2026-09-05/monitor-smoke.html
```

冒烟使用复制的旧report，只证明旧档可读，不能作为新简详分离的视觉验收。人工检查 `silver-d10-sample.md` 的解释质量与段落完整性；Task 1网页fixture必须断言完整详评B未被简评A覆盖、HTML安全转义且换行保留。不要求打开pytest已清理的临时页面，不启动服务。

### Task 5：集中回归后，才补齐正式registry

```bash
./.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_forward_review_context.py tests/test_forward_monitor.py tests/test_forward_monitor_prompt.py tests/test_render_monitor_web.py tests/test_update_monitor_web.py tests/test_forward_selection.py tests/test_engine_contract_v4.py tests/test_engine_contract_knowledge_v4.py -q
git diff --check
git diff --stat
git status --short
```

如果失败属于本计划改动，修正后只重跑受影响测试及上述最终一轮；若证实为已有无关失败，报告并保持无关源码不动，不借机扩大任务。

只有这些验证和样稿核对通过后，执行一次现有正式注册补齐：

```bash
cp -pn local_archive/forward_monitor/registered-episodes.json local_archive/review_quality_acceptance/2026-09-05/registered-episodes.before.json
./.venv/bin/python -B -m stock_analyzer.ops.forward_monitor register --trace-file local_archive/forward_selection/replay-v4-2026-08-20.json --label v4-replay-2026-08-20
./.venv/bin/python -B - <<'PY'
from pathlib import Path
import json
root=Path.cwd()
before=json.loads((root/"local_archive/review_quality_acceptance/2026-09-05/registered-episodes.before.json").read_text())
after=json.loads((root/"local_archive/forward_monitor/registered-episodes.json").read_text())
b={e["episode_id"]:e for e in before["episodes"]}
a={e["episode_id"]:e for e in after["episodes"]}
assert a.keys()==b.keys()
allowed={"original_research_thesis","original_selection_reason",
         "original_referenced_decisions","original_nearest_alternative_episode_id",
         "data_limitations"}
for eid, old in b.items():
    for key in set(old)|set(a[eid]):
        if key in old and old[key] is not None:
            assert a[eid].get(key)==old[key], (eid,key)
        elif a[eid].get(key)!=old.get(key):
            assert key in allowed, (eid,key)
assert all(e.get("original_research_thesis") for e in a.values())
print("registry_missing_fields_filled; existing_values_and_episode_ids_unchanged")
PY
```

不要在正式目录重跑9/3 prepare或record来消除旧snapshot中的missing标签；旧档记录的是旧执行状态。下一次正常正式任务自然使用补齐后的registry及新合同。

### Task 6：交付并停止

交付：最终改动文件、相关测试结果、真实D10简评/详评样稿、registry补齐前后核对结果、任何确有依据的未决限制。明确“旧正式报告没有回写；新规则从下一次正常任务生效”。

达到上述验收后停止，不再添加仪表盘、规则版本、评分、自动复查Agent、全历史报告改写或新任务。若用户之后希望公开备选对照，作为另一个明确政策变更处理。

## 5. 审查与执行授权的衔接

本轮已按AGENTS规定完成一次 `gpt-5.6-sol / xhigh` 独立审查，结论是“通过（以修订版为准）”。审查只涉及目标一致性、完整性、可执行性、矛盾、遗漏和过度工程化，未实施任务，未启动其他子智能体。全部修订已直接并入本文件，包括：以analysis_date截断61日窗口、明确新公司事实的复盘截止、网页正文/摘要分工、纯函数与读取层测试分工及离线验收路径一致性。

GLM收到用户“执行本计划”的指令后，只执行本文件通过版本，不再发起第二轮设计/审批/多Agent流程。若执行时必须扩大本文件范围，只停止超出范围的部分并说明真实需要；不得自行扩大源码白名单或用“提高质量”另建框架。
