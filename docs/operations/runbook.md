# 统一研究数据运维手册

> **当前状态（2026-07-16）：** 只有本地数据更新任务在运行。旧的自动选股、报告生成、激活、部署和发布任务均已停用。在用户认可新的分析框架和报告样式前，不得恢复这些报告任务。

这份手册只说明当前统一事实库的更新、检查和故障处理。历史正式报告链路不是当前运维对象。

## 数据保留窗口

| 用途 | 默认长度 | 业务原因 |
| --- | ---: | --- |
| 逐股短期分析 | 82 个交易日 | 足够观察近期趋势、波动、成交和相对强弱 |
| 市场、行业和概念 | 250 个交易日 | 识别风格轮动、热点持续性和拥挤变化 |
| 财务报表 | 12 个季度加 5 个年度 | 比较盈利质量和周期变化 |
| 公告元数据 | 1 年 | 支持当前事件和风险检查 |
| 停复牌 | 1 年 | 支持近期可交易性检查 |
| 融资融券 | 250 个交易日 | 观察中期变化，不证明资金身份 |
| 分钟线 | 20 个交易日，仅候选股与宽基指数 | 验证盘中路径，避免全市场无限扩张 |

已经完整保存且体量可控的日线、复权、估值基础和宽基指数可作为长周期备查库保留 5 年，但日常分析不默认读取 5 年，日常任务也不重复下载 5 年。

## 每日数据时间表

| 时间 | 固定阶段 | 作用 | launchd 标签 |
| --- | --- | --- | --- |
| 18:30 | `close` | 收盘行情、复权、每日估值、涨跌停价和宽基指数 | `com.ccrt.stock-analysis-assistant.research-data-close` |
| 21:30 | `evening` | 公告、板块、概念、公司行动和晚间资料落地后，生成当日市场、板块和个股研究观察 | `com.ccrt.stock-analysis-assistant.research-data-evening` |
| 次日 08:00 | `next-morning` | 融资融券、晚到修订和定点缺口重试；只有上游事实发生变化时才重新计算研究观察 | `com.ccrt.stock-analysis-assistant.research-data-next-morning` |

三个任务使用三个独立标签和固定阶段，不根据实际启动时间猜测阶段。如果 macOS 延迟到次日才执行，程序按阶段截止时间和官方交易日历选择应归属的交易日，不会把次日误当成当日收盘数据。

收盘阶段只保存原始事实，不提前生成资料尚未到齐的板块观察。晚间和次晨计算不连接新的 API，只读已验证并落地的统一事实库。任何一类观察失败，整个定时阶段都会明确报错，不会打印成功。

## 手工运行与检查

手工运行单个数据阶段：

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data run-stage \
  --stage close --data-date auto
PYTHONPATH=src .venv/bin/python -m stock_analyzer data run-stage \
  --stage evening --data-date auto
PYTHONPATH=src .venv/bin/python -m stock_analyzer data run-stage \
  --stage next-morning --data-date auto
```

检查指定交易日：

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data health \
  --data-date YYYY-MM-DD --full-history
```

只用本地已有事实手工复算三类研究观察（不访问 API）：

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data derive \
  --data-date YYYY-MM-DD
```

健康报告会把“收盘核心事实是否完整”和“三类研究观察是否可用”分开展示。研究观察还会核对公式版本、文件指纹、行数和原始输入清单；`complete_with_declared_gaps` 只表示“可以使用，但有明确限制”，不会被说成没有缺口。

### 历史时间语义与严格查询

正式时间合同、29 个数据集审计和 2026-07-16 迁移记录见 [`2026-07-16-v3-historical-time-semantics-repair.md`](2026-07-16-v3-historical-time-semantics-repair.md)。运维必须遵守：

- `available_at` 表示分析最早允许使用的时间；`ingested_at` 表示本地实际收到的时间，两者都必须保留。
- 确定性市场事实只有首版可按官方业务时点保守重建；后来修订使用来源更新时间或本次入库时间。
- 公告、财报、预告、快报和可修订公司事实必须有逐行披露依据；缺失时使用可审计的入库下界或 fail closed。
- 当前证券主表、公司概况和无发布时间的质押快照不能倒填到历史。
- 严格查询只通过 `available_at <= as_of` 放行；禁止增加按 `trade_date` 绕过的运维参数。

历史时间审计（只读）：

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data audit-time-semantics \
  --output local_archive/audits/YYYY-MM-DD-research-time.json
```

历史时间迁移不是日常任务。固定迁移 `2026-07-16-historical-time-semantics-v1` 已完成并通过幂等复核；除非正式设计批准新的迁移编号，不得重复发明规则或手工改写 Parquet/DuckDB。

### 日线字段与收益口径

- `equity_daily.pre_close/change/pct_chg` 是 Tushare `daily` 的供应商事实，和原始 OHLC、成交量、成交额一起构成稳定物理契约。每个日分区必须存在这些列，三个字段的逐分区非空覆盖率不得低于 99%；缺列或低于阈值时，即使旧清单写着 `passed`，健康检查也必须失败，续传回填也必须重取该分区。
- 供应商 `pct_chg` 不等于本地跨日可比收益。市场、热点和个股研究观察使用 `close * adj_factor` 生成本地复权价格，并在结果中记录 `equity_return_price_basis=close_times_adj_factor`。原始事实不被复权值覆盖或混写。
- 当前正式公式版本是 `market-context-v2`、`sector-hotspot-v3`、`stock-trading-context-v2`。三类输入清单都必须包含与股票日线相同窗口的 `adj_factor` 分区；复权因子修订会使输入清单变更并触发重算。

### 财务事实键与可比查询

- `financial_indicator` 的正式业务键是 `(ts_code, report_period, report_type)`。该端点不提供 `update_flag`，仓库修订依赖 `available_at`、`payload_hash`、`revision_no` 和 `research_fact_revisions`；不得为了和报表端点表面一致而补造 `update_flag`。
- `income_statement`、`balance_sheet` 和 `cash_flow` 的正式业务键是 `(ts_code, report_period, report_type, statement_type)`。不同 `comp_type`、`end_type` 或报表类型是需要保留的正式事实变体，不得按 `(ts_code, report_period)` 粗暴删除。
- 需要一行可比报表时，使用 `ResearchQuery.comparable_financials_as_of`。它先按 `as_of` 解析修订，再按报告期应有的 `end_type`、`update_flag`、合并报表优先级、`available_at` 和稳定的 `statement_type` 依次选择；该规则只生成查询视图，不修改事实层。

只修补已记录的精确缺口：

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data repair-gaps \
  --through YYYY-MM-DD
```

缺口重试必须保留原缺口编号和股票代码。不得因一只股票的财务资料失败而重跑全市场。

## 已知能力边界

- 当前官方账号不提供可用的历史分钟数据；这是来源能力限制，不是无限重试的临时错误。
- 部分官方主题指数不公开成分股；相关热点结论必须标注覆盖限制。
- 新股或尚未披露定期报告的公司可以缺少核心财务记录；只按具体代码定向追补。
- 日线量价、所谓“主力资金流”和不完整分钟数据都不能证明机构账户正在买入或卖出。

## 限售股解禁事实

同一股票、解禁日、股东和股份类型只保留一条当前事实。数据源返回多个版本时，优先用最新已知总股本核对解禁数量和比例；无法核对时保留降级标记和所有候选版本哈希，不将多版本相加。

存量数据的统一化命令是：

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data normalize-share-float \
  --through YYYY-MM-DD
```

## 旧存储迁移与灾备审计

`STORE-004` 宽表 JSON 迁移是历史存储事件，不是日常任务。以下命令保留用于审计或灾备演练；它们都是非删除命令，清单生成命令 **does not delete** 任何文件。

```bash
stock-analyzer formal-warehouse-inventory \
  --source-root local_warehouse/formal_evidence \
  --output local_archive/manifests/formal-warehouse-inventory.json

stock-analyzer formal-warehouse-migrate \
  --source-root local_warehouse/formal_evidence \
  --warehouse-root local_warehouse \
  --migration-id formal-json-to-duckdb-parquet-20260712 \
  --output local_archive/manifests/formal-warehouse-migration.json

stock-analyzer formal-warehouse-audit \
  --warehouse-root local_warehouse --strict-hashes \
  --output local_archive/manifests/formal-warehouse-audit.json

stock-analyzer formal-warehouse-deletion-manifest \
  --source-root local_warehouse/formal_evidence \
  --warehouse-root local_warehouse \
  --migration-id formal-json-to-duckdb-parquet-20260712 \
  --output local_archive/manifests/formal-warehouse-deletion-manifest.json
```

旧多版本市场 Parquet 的股票日线已通过业务键和内容哈希等值校验。其他 Phase 3 旧快照是经批准退役的旧设计数据，删除前只验证了新事实区的替代覆盖，没有完成逐值等价审计。这一历史限制必须保留在退役附录和能力矩阵中，不得声称已经证明全部旧数据与新数据逐值相同。

## 安全要求

- 不得打印、复制、提交或记录 `.env.local`、Tushare token 或其他凭据。
- 数据任务不得连接经纪商、下单或自动交易。
- 旧报告调度、自动发布和报告激活已停用；必须在新分析框架和报告样式获得用户明确认可后，另行设计和验收。
