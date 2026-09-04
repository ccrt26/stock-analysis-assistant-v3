# 股票分析助手：本地数据底座与五 Skill 研究架构

当前项目维护股票研究所需的本地数据底座、本地研究知识、确定性读取/计算能力，以及一个总控加四个专业研究 Skill。请先阅读[当前 V3 架构与实现状态](docs/architecture/current-v3-architecture.md)。2026-08-04 的[SKILL 先行架构设计](docs/superpowers/specs/2026-08-04-skill-first-stock-research-architecture-design.md)保留为历史过渡文档，不再单独代表当前实现。

本项目不连接券商、不自动交易，也不承诺投资收益。

## 让 ChatGPT Web 理解本项目

将 ChatGPT Web 连接到本 GitHub 仓库或直接提供仓库链接后，建议要求它按顺序阅读：

1. `AGENTS.md`；
2. `docs/architecture/current-v3-architecture.md`；
3. `.agents/skills/orchestrating-stock-research/SKILL.md`；
4. 与问题相关的市场、板块、公司和价格专业 Skill。

GitHub 不包含被忽略的 `local_warehouse/`、`local_archive/`、`logs/`、`.env*` 或其他本地运行数据。ChatGPT Web 可以理解架构和审查代码，但不能仅凭仓库假设自己已经取得真实本地事实。

可直接使用以下开场语：

> 请先阅读 `AGENTS.md`、`docs/architecture/current-v3-architecture.md` 和股票研究总控 Skill，再按需要阅读四个专业 Skill。请区分已实现的数据底座、Skill 研究流程和未实现的自动化能力，不要恢复旧 V3 的评分、Gate、报告发布或交易路径，也不要假设 GitHub 包含本地事实仓。

## 当前能力

- 从正式数据源增量获取市场、行业、主题、公司、财务、公告和交易结构事实；
- 使用业务键、时间边界、文件哈希和数据契约检查落库质量；
- 将元数据保存在 `local_warehouse/research.duckdb`；
- 将事实保存在 `local_warehouse/facts/` 的 Parquet 分区；
- 将当前三类确定性观察保存在 `local_warehouse/derived/`；
- 通过 `ResearchQuery` 按明确时点读取历史可见事实；
- 生成每日数据健康摘要；
- 由五个 Skill 按当前研究问题调阅 `src/stock_analyzer/knowledge/` 中的本地知识。
- 通过 `.agents/skills/` 中的五个 Skill 组织市场、板块、公司、价格和最终比较研究；
- 保存每日推荐当时的完整判断，并在之后的第1—20个交易日复盘真实走势；同一股票可以合并展示，但每次推荐或比较都读取自己的上一轮复盘并分别评价。正式推荐到第20个交易日后会优先完成最终复盘，漏跑时持续提醒到成功保存；比较对象不形成荐股最终结论。第21—30个交易日只更新后续走势观察。

给用户看的每日合并报告统一使用“今天的市场情况”“之前研究过的股票走势复盘”“目前还在跟踪多少只”“今天新推荐的股票”等通俗标题。推荐日期使用原计划观察日；同一股票当天共同的市场、行业、公司和个股变化只展示一次，每条记录分别说明原判断和实际路径。第20天固定结论与第21—30天当前走势分开显示。报告不直接展示冻结记录中的内部说法，也不把当前价格改写成原推荐价格。推荐股和当时备选股只有在真实记录能够可靠对应、观察窗口一致且两边价格路径完整时才比较。

GitHub 不保存真实行情事实。最新可用日期应以本地健康检查和事实仓查询结果为准，不要依赖 README 中的固定日期。

## 本地目录

```text
local_warehouse/
├── research.duckdb
├── facts/
└── derived/

local_archive/
└── data_health/

logs/
└── research-data/
```

这些目录及 `.env.local` 都被Git忽略，不应提交、移动或清空。

## 三个数据任务

项目保留三个 `launchd` 模板：

| 阶段 | 时间 | 命令 |
| --- | --- | --- |
| 收盘 | 18:30 | `data run-stage --stage close --data-date auto` |
| 晚间 | 21:30 | `data run-stage --stage evening --data-date auto` |
| 次晨 | 09:00 | `data run-stage --stage next-morning --data-date auto` |

模板位于 `ops/launchd/`。任务只更新本地事实、派生观察和健康摘要。

## 安装与配置

需要Python 3.11或更新版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev,data]"
```

取数需要Tushare Token。程序按以下顺序读取：

1. 环境变量 `TUSHARE_TOKEN`；
2. `TUSHARE_TOKEN_PATH` 指定的文件；
3. 当前用户的 `~/.tushare_token`。

定时任务会在本地 shell 中读取 `.env.local`。不得把Token或密钥提交到Git。

可选配置：

- `PROJECT_ROOT`
- `LOCAL_WAREHOUSE_DIR`
- `LOCAL_ARCHIVE_DIR`
- `CNINFO_BASE_URL`
- `CNINFO_TIMEOUT_SECONDS`
- `CNINFO_MAX_RETRIES`

## 当前CLI

```bash
python -m stock_analyzer data backfill --through YYYY-MM-DD
python -m stock_analyzer data run-stage --stage close --data-date auto
python -m stock_analyzer data derive --data-date YYYY-MM-DD
python -m stock_analyzer data health --data-date YYYY-MM-DD
```

查看参数：

```bash
python -m stock_analyzer data --help
python -m stock_analyzer data run-stage --help
```

`run-stage`会访问外部数据源并写入事实仓。仅检查命令能否加载时应使用 `--help`，不要启动真实任务。

### 数据缺口与人工复核

完整复核应使用交易日历推导应有日期，而不是只看最后一个文件：

```bash
python -m stock_analyzer data health --data-date YYYY-MM-DD --full-history
```

健康报告中的状态含义：

- `complete`：事实存在且来源合同、文件哈希、行数和字段检查通过。
- `legitimate_empty`：官方接口成功返回空，且该数据集允许当天无记录。
- `waiting_upstream`：官方数据尚处于正常等待窗口。
- `permission_denied`：正确官方接口明确拒绝当前 Token。
- `provider_conflict`：同一业务键和公开时点有多个载荷，不能猜选版本；查询会在解决前屏蔽该键。
- `unsupported_optional`：分钟等可选能力受权限或频率限制，不冒充核心日线完整。
- `failed`：来源、解析、校验或写入失败，可重试。
- `unclassified_missing`：应该有但没有且原因未查明，必须继续调查。

申万官方行业日线仍只认 `sw_daily`，通用 `index_daily` 不作为申万行情来源。当前 Token 未购买 `sw_daily` 所需积分，因此活跃研究链路使用独立的 `industry_daily_proxy`：按交易日有效的申万 2021 一级行业成分，用前一交易日 `free_share × close` 加权当日个股收益。代理只提供收益和覆盖率，不生成或冒充官方点位、开高低收与成交量额；主题指数仍使用官方 `index_daily`。健康检查要求最近 250 个交易日的代理分区完整且成分覆盖率不低于 80%。

财务指标业务键保持 `(ts_code, report_period, report_type)`。只有同一 `ts_code + end_date + ann_date` 返回多个不同载荷时，程序才用相同条件追加一次 `fina_indicator` 查询并显式请求官方 `update_flag`；恰好一个版本为 `1` 时采用该版本，但只从本次查询的实际观测时点起可用。这里不是按数值大小排序；没有唯一 `1` 时继续保留 `provider_conflict`。`update_flag` 不进入业务哈希和最终事实。

一次性 2026-09-02 缺口修复工具必须显式选择模式；`--execute` 会先在 `local_archive/data_repairs/` 备份数据库和目标 Parquet，再生成 250 日行业代理、精确重试冲突财务键并重算受影响派生日期：

```bash
python tools/repair_research_data_gaps.py --dry-run
python tools/repair_research_data_gaps.py --execute
```

三个写任务在初始化 DuckDB 前共用同一全局锁。`close` 只按收盘阶段的失败或等待决定非零退出；`evening` 与 `next-morning` 还检查各自应产出的研究观察。可选分钟受限会进入健康报告，但不会单独令核心日线任务失败。

## 人工补跑早晨研究

当天早晨的研究没有启动或失败时，可以在稍后安全补跑：

```bash
python -m stock_analyzer.ops.forward_selection prepare \
  --rerun-date YYYY-MM-DD
```

日期填写原计划推荐日期。程序会自动找到前一个交易日，并把研究截止时间固定为原计划推荐日上海时间 09:05；不会把实际补跑时间、当天盘中行情或当前价格当成早晨条件。无参数 `prepare` 仍只允许在 09:05—09:30 使用。

市场情况和价格分析是正式研究的最低条件，任何一项不可用都会停止推荐。行业研究、个股交易背景或行动日前公告补采缺失时，可以继续受限研究，但返回结果会明确列出本次不能使用的内容；不会拿名称、概念或当前行情补猜。完整步骤以 `ops/forward-selection-prompt.md` 为准。

数据命令也按同一边界返回状态：市场情况或价格分析不可用时退出码为 2；只有可选研究内容缺失、核心研究仍可用时退出码为 0，并显示“核心研究可用，部分研究通道受限”和具体限制。

## 事实查询

Python代码可以使用：

- `stock_analyzer.storage.research_query.ResearchQuery`
- `stock_analyzer.storage.research_warehouse.ResearchWarehouse`
- `stock_analyzer.data.research_contracts.ResearchDatasetId`

也可以使用DuckDB只读连接 `local_warehouse/research.duckdb`，再根据 `research_fact_partitions.relative_path` 查询对应Parquet文件。

## 知识库

知识内容位于 `src/stock_analyzer/knowledge/*.yaml`。五个 Skill 先确定当前问题，再直接调阅相关条目；知识不由每日数据任务加载，不经过程序化评分或 Gate，也不直接产生股票结论。

## 历史问题状态

清理基线曾发现行业目录有效记录重叠和公告修订时间倒序问题；这些历史数据已一次性修复，当前运行链不再保留专用迁移程序。运行时状态仍必须以 `data health`、任务退出码和事实仓清单为准，不能通过绕过时间校验或删除健康检查掩盖新问题。

## 验证

```bash
python -m pytest -q
```

测试覆盖当前数据获取、事实仓、时点查询、派生观察、健康检查、三个数据任务、每日推荐和选出后的走势复盘边界。
