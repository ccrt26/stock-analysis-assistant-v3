# 股票分析助手：本地数据底座

当前项目只维护股票研究所需的本地数据底座、知识库和读取能力。研究方法与后续建设方向以[SKILL先行架构设计](docs/superpowers/specs/2026-08-04-skill-first-stock-research-architecture-design.md)为准。

本项目不连接券商、不自动交易，也不承诺投资收益。

## 当前能力

- 从正式数据源增量获取市场、行业、主题、公司、财务、公告和交易结构事实；
- 使用业务键、时间边界、文件哈希和数据契约检查落库质量；
- 将元数据保存在 `local_warehouse/research.duckdb`；
- 将事实保存在 `local_warehouse/facts/` 的 Parquet 分区；
- 将当前三类确定性观察保存在 `local_warehouse/derived/`；
- 通过 `ResearchQuery` 按明确时点读取历史可见事实；
- 生成每日数据健康摘要；
- 读取和选择 `src/stock_analyzer/knowledge/` 中的本地知识。

截至本次清理基线，核心行情事实已保存到2026-08-03。最新可用日期应以健康检查和事实仓查询结果为准，不要依赖README中的固定日期。

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
| 次晨 | 08:00 | `data run-stage --stage next-morning --data-date auto` |

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
python -m stock_analyzer data repair-gaps --through YYYY-MM-DD
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

知识内容位于 `src/stock_analyzer/knowledge/*.yaml`。当前保留的程序能力包括：

- 注册表读取；
- 数据能力核对；
- 按研究问题选择相关知识；
- 使用边界和治理检查。

知识库不会由每日数据任务自动加载，也不会直接产生股票结论。

## 当前已知问题

2026-08-03仍有两个清理前已经存在的问题：

1. 行业目录存在重叠有效记录，导致当日 `sector_hotspot` 未生成；
2. 部分公告修订记录的发布时间早于已有版本，最近的晚间和次晨任务因此退出码为2。

核心收盘事实仍可读取。这两个问题应作为独立的数据底座修复任务处理，不能通过绕过时间校验或删除健康检查解决。

## 验证

```bash
python -m pytest -q
```

测试覆盖当前数据获取、事实仓、时点查询、派生观察、健康检查、三个任务模板和知识库读取能力。
