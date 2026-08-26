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
- 保存每日推荐当时的完整判断，并在之后的第1—20个交易日复盘真实走势，第21—30个交易日只做后续观察。

给用户看的每日合并报告统一使用“今天的市场情况”“之前推荐股票的走势复盘”“目前还在跟踪多少只”“今天新推荐的股票”等通俗标题。报告解释原判断后来是否得到支持、上涨或下跌主要和什么有关、原行动条件是否可用，不展示内部分类名称，也不把当前价格改写成原推荐价格。

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
