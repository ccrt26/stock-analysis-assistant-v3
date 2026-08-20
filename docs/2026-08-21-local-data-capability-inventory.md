# 本地股票研究数据与实际能力盘点

**盘点日期：** 2026-08-21

**盘点性质：** 只读事实盘点；不修改选股逻辑、数据合同、派生公式、Forward 记录或五个 Skill

**证据范围：** 当前代码与五个 Skill、本地 DuckDB 元数据、实际 Parquet、已有及本次健康报告、当前配置状态、两份公告 PDF 最小网络探测

## 1. 结论先行：真实数据日期

| 口径 | 实际日期 | 判断 | 证据 |
| --- | --- | --- | --- |
| 最新完整市场数据日期 | **2026-08-20** | `equity_daily`、`adj_factor`、`daily_basic`、`stock_limit`、`index_daily` 均到该日，收盘阶段成功 | DuckDB、Parquet、`research_ingestion_runs` |
| 最新晚间事件数据日期 | **2026-08-20** | 晚间阶段完成但状态为 `limited`；公告最晚到 20:38:28，限制主要是部分财务指标同公开时点存在无法排序的上游版本 | DuckDB、健康报告 |
| 最新次晨数据日期 | **2026-08-19** | 2026-08-20 09:00 执行，状态 `limited`，限制为分钟接口权限或限流；没有 2026-08-20 对应次晨运行 | DuckDB、健康报告 |
| 最新曾具备正式研究闭环的形成日 | **2026-08-19** | 当日次晨报告曾记录核心数据与四类派生可用，并存在正式 `selection` 记录；2026-08-20 尚缺对应次晨闭环 | 健康报告、Forward 归档 |
| 当前重新回放 2026-08-19 的状态 | **不能直接把旧派生文件视为当前 ready** | 本次 `--full-history` 成功核对 29 类事实、核心完整且登记缺口为 0，但四类 2026-08-19 派生的 `input_manifest` 都因后续事实提交变为 stale；这不推翻当时曾 ready，只说明现在复现时要按原 `as_of` 重新解析输入 | 本次健康报告、代码 |

2026-08-20 的四类派生已经生成且当日晚间健康报告为 ready，但 Forward 的正式准备条件还要求形成日对应的次晨运行。因此“最新派生日”和“最新可正式研究形成日”不能混写成同一天。[证据：代码、DuckDB、健康报告]

明显落后的数据集包括：`margin_detail` 只到 2026-08-19；`minute_bar` 只到 2026-08-18，且全历史仅 3 个工具、21 个日期分区；行业和主题日线虽到 2026-08-20，但历史仅始于 2025-07-02；公告元数据只有 2025-07-14 以后；主题成员有效历史仅始于 2025-07-31。[证据：DuckDB、Parquet]

## 2. 盘点方法、规模与总体健康

- 本次实际运行：`python -m stock_analyzer data health --data-date 2026-08-19 --full-history` 的项目虚拟环境等价命令；结果为 `core_complete=true`、29 类事实、登记缺口 0。当前 shell 没有名为 `python` 的可执行文件，因此使用项目 `.venv` 解释器，没有安装依赖。[证据：命令执行、健康报告]
- 两条用户指定汇总 SQL 仅把带时区时间显式转成字符串，以绕过当前虚拟环境缺少 `pytz` 的 Python 返回值转换；表结构和聚合语义未改。[证据：DuckDB Schema、命令执行]
- 全历史物理检查没有发现缺文件、文件哈希不符、行数不符、重复业务键、Schema 缺列或核心字段覆盖失败。唯一合同异常是 `financial_indicator` 有 1 条非正修订区间；其 Parquet 物理文件仍有效。[证据：本次健康报告]
- `equity_daily` 的 `pre_close/change/pct_chg` 最低分区覆盖率为 99.9585%，高于合同 99% 要求；`adj_factor` 为 100%。[证据：本次健康报告]
- 当前 Tushare Token 状态为 **`present:env`**；未读取或输出 Token 内容。巨潮配置为 `https://www.cninfo.com.cn`、20 秒超时、最多重试 2 次。[证据：当前配置]

| 目录 | 实际总体大小 |
| --- | ---: |
| `local_warehouse/` | 13G |
| `local_archive/` | 11G |

`local_archive/` 的大头包含历史验证样本与本地研究归档，不等于每日生产事实；事实数据集大小在下表逐项给出。[证据：`du -sh`、目录检查]

## 3. 实际事实数据能力表

### 3.1 本地取得、来源、覆盖与 Schema

所有 29 个 `ResearchDatasetId` 都已有本地 Parquet；“有数据”不表示历史完整或具备严格回放。字段仅列实际 Parquet 中对研究最重要的部分，治理字段 `source_*`、`available_at`、`availability_precision`、哈希、质量和修订号各数据集均实际存在。

| dataset_id | actual_local_status | actual_source / endpoint | fetch_stage | first_partition | last_partition | rows | disk_size | important_actual_columns |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| `trade_calendar` | 本地有数据 | tushare / `trade_cal` | close + 历史 backfill | 2021 | 2026 | 1,914 | 484K | `exchange, cal_date, is_open, pretrade_date` |
| `security_master` | 本地有数据；当前型 | tushare / `stock_basic` | close + 历史 backfill | security-master | security-master | 5,887 | 1.3M | `ts_code, name, market, exchange, list_status, list_date, delist_date, valid_from/to` |
| `equity_daily` | 本地有数据 | tushare / `daily` | close | 2021-07-14 | 2026-08-20 | 6,421,947 | 1.5G | `open, high, low, close, pre_close, pct_chg, volume, amount` |
| `adj_factor` | 本地有数据 | tushare / `adj_factor` | close | 2021-07-14 | 2026-08-20 | 6,500,924 | 1.3G | `trade_date, ts_code, adj_factor` |
| `daily_basic` | 本地有数据 | tushare / `daily_basic` | close | 2021-07-14 | 2026-08-20 | 6,403,629 | 1.9G | 换手、量比、PE/PB/PS、股本、市值 |
| `stock_limit` | 本地有数据 | tushare / `stk_limit` | close | 2021-07-14 | 2026-08-20 | 8,248,377 | 1.7G | `up_limit, down_limit` |
| `index_daily` | 本地有数据 | tushare / `index_daily` | close | 2021-07-14 | 2026-08-20 | 9,712 | 19M | 指数 OHLC、涨跌幅、成交量额 |
| `industry_catalog` | 本地有数据 | tushare / `index_classify+index_basic` | 历史 backfill + evening refresh | SW2021 | SW2021 | 511 | 128K | 行业层级、代码、父级、发布状态、`valid_from/to` |
| `industry_member` | 本地有数据；有效区间历史 | tushare / `index_member_all` | 历史 backfill + evening refresh | SW2021 | SW2021 | 17,850 | 3.7M | 股票、行业层级/代码、名称、`valid_from/to, is_current` |
| `industry_daily` | 本地有数据；历史较短 | tushare / `index_daily` | evening + 历史 backfill | 2025-07-02 | 2026-08-20 | 8,618 | 6.5M | 行业指数 OHLC、涨跌幅、成交量额 |
| `theme_catalog` | 本地有数据 | tushare / `index_basic` | 历史 backfill + evening refresh | official-theme-v1 | 同左 | 272 | 76K | 发布方、主题代码/名称、基日、`valid_from/to` |
| `theme_member` | 本地有数据；历史有限 | tushare / `index_weight` | 历史 backfill + evening refresh | official-theme-v1 | 同左 | 267,102 | 51M | 主题、股票、权重、快照日、`valid_from/to` |
| `theme_daily` | 本地有数据；历史较短 | tushare / `index_daily` | evening + 历史 backfill | 2025-07-02 | 2026-08-20 | 66,442 | 22M | 主题指数 OHLC、涨跌幅、成交量额 |
| `company_profile` | 本地有数据；快照型 | tushare / `stock_company` | 历史 backfill + evening 定向刷新 | company-profile | 同左 | 13,523 | 11M | 公司名称、简介、经营范围、主营、人员、注册资本、快照日 |
| `income_statement` | 本地有数据 | tushare / `income` | 历史 backfill + evening 定向刷新 | 2021-12-31 | 2026-06-30 | 71,583 | 33M | 收入、成本、费用、营业/总/净利润、EPS、报告类型 |
| `balance_sheet` | 本地有数据 | tushare / `balancesheet` | 历史 backfill + evening 定向刷新 | 2021-12-31 | 2026-06-30 | 71,683 | 货币、应收、存货、资产、负债、权益等 |
| `cash_flow` | 本地有数据 | tushare / `cashflow` | 历史 backfill + evening 定向刷新 | 2021-12-31 | 2026-06-30 | 71,361 | 经营/投资/融资现金流、自由现金流、期初期末现金 |
| `financial_indicator` | 本地有数据；1 条修订异常 | tushare / `fina_indicator` | 历史 backfill + evening 定向刷新 | 2021-12-31 | 2026-06-30 | 72,320 | 毛利/净利率、ROE/ROA、周转、负债、现金流、同比 |
| `main_business` | 本地有数据 | tushare / `fina_mainbz` | 历史 backfill + evening 定向刷新 | 2021-12-31 | 2026-06-30 | 540,883 | 主营项目、分类、销售额、利润、成本、币种 |
| `earnings_forecast` | 本地有数据 | tushare / `forecast` | evening/next-morning + 历史 backfill | 2021-07 | 2026-08 | 20,655 | 预告类型、净利润区间、变动区间、原因、首次公告日 |
| `earnings_express` | 本地有数据 | tushare / `express` | evening/next-morning + 历史 backfill | 2022-01 | 2026-08 | 6,353 | 收入、营业/总/净利润、资产、权益、EPS/ROE、摘要 |
| `announcement` | 本地有数据；仅元数据 | cninfo / `new/hisAnnouncement/query` | evening/next-morning + 一年 backfill | 2025-07 | 2026-08 | 740,263 | ID、股票、官方时间、标题、URL、`pdf_path`、标题候选类型、硬风险候选 |
| `holder_trade` | 本地有数据 | tushare / `stk_holdertrade` | evening/next-morning + 历史 backfill | 2021-07 | 2026-08 | 67,530 | 股东、增减持、数量/比例、均价、公告日 |
| `share_float` | 本地有数据；仅有事件股票 | tushare / `share_float`、`share_float:ann_date` | evening/next-morning + 滚动 backfill | 2025-07 | 2030-07 | 1,577,279 | 公告日、解禁日、数量/比例、持有人、股份类型、上游变体处理 |
| `repurchase` | 本地有数据 | tushare / `repurchase` | evening/next-morning + 历史 backfill | 2021-07 | 2026-08 | 47,363 | 公告/结束/预计日、进度、数量、金额、价格区间 |
| `pledge` | 本地有数据；快照型 | tushare / `pledge_stat` | evening/next-morning + 季度/滚动 backfill | 2021-09 | 2026-08 | 61,210 | 截止日、质押笔数、限售/无限售质押、总股本、质押率 |
| `suspension` | 本地有数据；有记录日 | tushare / `suspend_d` | evening + 一年 backfill | 2025-07-14 | 2026-08-20 | 3,903 | 股票、日期、停牌时点、类型；空日另有 watermark |
| `margin_detail` | 本地有数据；T+1 | tushare / `margin_detail` | next-morning + 历史 backfill | 2025-07-02 | 2026-08-19 | 1,173,348 | 融资融券余额/买入/偿还、交易所 |
| `minute_bar` | 只有极少部分数据 | tushare / `pro_bar:1min` | next-morning + 可选历史 backfill | 2026-07-14 | 2026-08-18 | 6,748 | 1 分钟 OHLC、量额、工具类型；仅 3 个工具 |

### 3.2 `available_at`、回放等级、健康与真实限制

| dataset_id | availability_semantics（本地实际） | replay_level | health | usable_by_skills | real_limitations |
| --- | --- | --- | --- | --- | --- |
| `trade_calendar` | endpoint policy 推断的业务收盘 | reconstructed_conservative | 通过 | market/price | 分区含将来日历，但早期 `as_of` 只可见保守可用版本 |
| `security_master` | 全部 ingestion cutoff | ingestion_only | 通过 | market/sector/company/price | 当前取得快照，不能证明历史时点当时已知的名称/状态版本 |
| `equity_daily` | 绝大多数 exact，少量 endpoint policy | reconstructed_conservative | 通过 | market/sector/price | 可重构历史日线，非上游逐次修订原貌 |
| `adj_factor` | 绝大多数 exact，少量 endpoint policy | reconstructed_conservative | 通过 | market/sector/price | 同上；形成日必须按当时可见版本解析 |
| `daily_basic` | exact 为主，另有少量推断/ingestion | reconstructed_conservative | 通过 | market/company/price | 估值历史可算，少量旧记录精度较低 |
| `stock_limit` | exact 为主，少量 endpoint policy | reconstructed_conservative | 通过 | market/sector/price | 触及涨停不等于行动日可成交 |
| `index_daily` | exact 为主，少量 endpoint policy | reconstructed_conservative | 通过 | market/sector/price | 指数成分含义不能替代默认股票范围 |
| `industry_catalog` | actual exact `valid_from` | reconstructed_conservative | 通过、无区间重叠 | sector/market/company | SW2021 有效历史可用，但不是严格原始发布版本流 |
| `industry_member` | exact 为主，少量推断/ingestion | reconstructed_conservative | 通过、无区间重叠 | sector/company/price | 5,880 只历史股票、499 行业代码；可靠性仍受供应商历史成员能力限制 |
| `industry_daily` | endpoint policy 推断收盘 | reconstructed_conservative | 通过 | sector/market/price | 只有约 278 个交易日，不能做五年板块历史 |
| `theme_catalog` | actual exact `valid_from` | reconstructed_conservative | 通过 | sector/company | 仅 272 个当前治理主题 |
| `theme_member` | exact/推断/ingestion 混合 | reconstructed_conservative | 通过 | sector/company/price | 有效历史只到 2025-07-31 以后；不能回放更早主题成员 |
| `theme_daily` | endpoint policy 推断收盘 | reconstructed_conservative | 通过 | sector/market/price | 只有约 278 个交易日；43 个主题当前无公开成员 |
| `company_profile` | 全部 ingestion cutoff | ingestion_only | 通过 | company | 6,294 个代码的多次本地快照，不能严格回放历史主营/简介 |
| `income_statement` | date conservative 为主，少量 ingestion | reconstructed_conservative | 通过 | company | 只能保守到公告日后使用；不能倒填报告期末 |
| `balance_sheet` | date conservative 为主，少量 ingestion | reconstructed_conservative | 通过 | company | 同上 |
| `cash_flow` | date conservative 为主，少量 ingestion | reconstructed_conservative | 通过 | company | 同上 |
| `financial_indicator` | date conservative 为主，少量 ingestion | reconstructed_conservative | **物理通过；合同有 1 条非正修订区间** | company | 晚间另有若干同公开时点上游版本无法排序、未写入 |
| `main_business` | date conservative 为主，部分 ingestion | reconstructed_conservative | 通过 | company | 历史主营口径依赖供应商，部分只可按 ingestion 保守使用 |
| `earnings_forecast` | date conservative 为主 | reconstructed_conservative | 通过 | company | 标题/结构化类型仍需与原文语义核对 |
| `earnings_express` | date conservative 为主 | reconstructed_conservative | 通过 | company | 不等于正式报告 |
| `announcement` | 740,262 行 exact 官方发布时间；1 行 ingestion cutoff | strict（合同） | 通过 | company/market | strict 只覆盖元数据；正文未落地，异常 1 行须按 ingestion 保守处理 |
| `holder_trade` | 全部 date conservative | reconstructed_conservative | 通过 | company | 日精度，不是分钟级官方发布时间 |
| `share_float` | 全部 date conservative | reconstructed_conservative | 通过 | company/price | 2030-07 是已知未来解禁安排，不是未来数据泄露；仅 1,594 只事件股票 |
| `repurchase` | 全部 date conservative | reconstructed_conservative | 通过 | company | 计划、实施、完成必须分阶段解释 |
| `pledge` | 全部 ingestion cutoff | ingestion_only | 通过 | company | 3,488 只股票，最新实际截止日 2026-08-14；不能严格历史回放 |
| `suspension` | exact 为主，少量 endpoint policy | reconstructed_conservative | 通过 | market/price | 仅有记录行；真实无记录日依赖 watermark 区分 |
| `margin_detail` | exact 为主，少量 endpoint policy；T+1 | reconstructed_conservative | 通过 | price/market | 落后一交易日；只描述信用交易，不识别机构观点 |
| `minute_bar` | endpoint policy 为主，少量 exact | reconstructed_conservative | 通过但覆盖极低 | sector/price（可选） | 仅 3 个工具、6,748 行；最新次晨仍为权限/限流，不能当全市场分钟能力 |

严格回放等级来自当前合同，但上表同时报告了本地实际精度。不能因为某些行标为 `exact` 就把整个 reconstructed 数据集升级为严格回放；反过来，`announcement` 的 strict 也只证明形成日前元数据版本，不证明正文已经保存。[证据：代码、DuckDB、Parquet]

## 4. 四类派生观察的实际能力

### 4.1 全历史登记

| feature_set | first_date | latest_date | partitions | total_rows | 当前公式版本 | 2026-08-20 最新状态 |
| --- | --- | --- | ---: | ---: | --- | --- |
| `market_context` | 2025-08-15 | 2026-08-20 | 33 | 33 | `market-context-v3` | ready、`complete` |
| `sector_hotspot` | 2025-08-15 | 2026-08-20 | 33 | 22,637 | `sector-hotspot-v3` | ready、`complete_with_declared_gaps` |
| `stock_trading_context` | 2025-08-15 | 2026-08-20 | 33 | 182,119 | `stock-trading-context-v2` | ready、`complete_with_declared_gaps` |
| `price_analysis_context` | 2026-08-19 | 2026-08-20 | 2 | 11,082 | `price-analysis-context-v1` | ready、`complete_with_declared_gaps` |

“ready”取自 2026-08-20 晚间最新健康报告；本次针对 2026-08-19 的全历史重检则因后续输入变化把该旧日四类派生都标为 stale。两者分别回答“最新文件现在是否可用”和“旧形成日文件能否不重解直接复用”。[证据：健康报告、DuckDB]

### 4.2 最新 Parquet 的真实覆盖

| feature_set | 最新行数与覆盖 | 实际主要字段 | 分钟依赖 | 会变成未知的主要缺口 | Skill 可直接读取 |
| --- | --- | --- | --- | --- | --- |
| `market_context` | 1 行，`coverage_status=complete`；价格、复权、必需指数、涨跌停覆盖字段均非空 | 1/3/5/20 日等权/中位/上涨面、指数收益与缺口、成交基线、20/60 日均线/新高低、分化、波动、集中、涨跌停分布 | 不需要 | 默认指数、复权、成交或涨跌停覆盖不足会使对应市场解释未知 | market 直接读取；sector/price 作为共同变化基准 |
| `sector_hotspot` | 686 行：414 行业、272 主题；642 有成员，44 无成员；569 有声明缺口、73 limited、44 no-membership | 成员数/覆盖、1/3/5/20 日等权/中位/广度/相对收益、成交份额、前三贡献、分化、新高、官方指数对照、背离/窄参与等 | **日线核心不需要；盘中字段需要** | 686 行盘中状态全 limited，盘中指标 0 行非空；43 主题和 1 行业无公开成员；20 日相对收益仅 603 行非空 | sector 直接读取日线共同性；market/price 读取板块基准与反证 |
| `stock_trading_context` | 5,541 行；3,252 有声明缺口、2,289 limited；收益状态完整 5,489，估值状态完整 3,263 | 多窗口绝对/相对市场收益、beta/相关/波动、60/82 日位置、成交额与方向成交、高成交日路径、涨跌停后行为、PE/PB 历史分位 | 不需要 | 短历史、估值缺失、涨跌停后样本不足会局部未知；不能识别交易者身份 | price 直接读取；company 可用估值/交易反证；market 不把它聚合成身份推断 |
| `price_analysis_context` | 5,541 行；4,854 场景输入 complete、687 limited；4,922 有至少 251 个复权会话 | 1/3/5/10/20/60 日及相对市场、路径连续/收盘/上影/回落/放量/涨停贡献、60/82/250 日位置、波动/ATR/流动性、EMA/MACD/ER/ADX/DMI/RSI/KD/BOLL、量价效率、交叉/突破事件 | 不需要 | 最新默认合格范围 4,406 只中有 4,399 行，4,027 complete、372 limited、7 缺行；相对板块/同类需与 sector 数据另行比较 | price 直接读取六类信息与 11 场景输入；不含最终场景标签或选股权 |

## 5. 公告元数据、PDF 与正文读取

### 5.1 当前本地事实

| 项目 | 实际结果 |
| --- | --- |
| 公告日期范围 | 2025-07-14 00:00:00 至 2026-08-20 20:38:28（Asia/Shanghai） |
| 公告总行数 / 股票数 | 740,263 行 / 5,870 个股票代码 |
| 实际字段 | `announcement_id, ts_code, security_name, announcement_time, available_at, title, url, pdf_path, candidate_event_types, classification_version, classification_is_fact, hard_risk_candidate` 加治理字段 |
| 标题、URL、`pdf_path`、官方时间覆盖 | 均为 740,263/740,263 |
| 标题级候选类型 | 48,934 行非空；它是 `cninfo-title-v1` 标题启发式，`classification_is_fact=false`，不能当正文事实 |
| 硬风险标题候选 | 4,598 行 |
| 本地 PDF、正文或提取文本 | **0 份公告 PDF、0 份公告正文/提取文本**；目录检索到的 `.txt` 仅为维修收据 |

因此当前准确表述是：**只保存公告元数据和官方原文入口，没有公告全文库，也没有已有 PDF 缓存机制。**[证据：DuckDB、Parquet、目录检查]

### 5.2 两份公告最小可行性测试

选取 2026-08-20 两条普通近期公告（临时股东会决议、延期披露半年度报告），只在临时目录下载，测试后已删除。

| 测试 | 持久化 `www` URL | 同一 `pdf_path` 的巨潮官方静态域名 | 文件结果 | 非 OCR 文本读取 |
| --- | --- | --- | --- | --- |
| 公告 A | HTTP 404、`text/html` | HTTP 200、`application/pdf`、158,220 bytes | `%PDF-`，PDF 1.7，4 页 | `pypdf` 与 `pdfplumber` 均为非空 |
| 公告 B | HTTP 404、`text/html` | HTTP 200、`application/pdf`、117,052 bytes | `%PDF-`，PDF 1.7，1 页 | `pypdf` 与 `pdfplumber` 均为非空 |

结论：

- 当前 Codex 任务在获得外网访问权限后可以直接访问巨潮官方静态 PDF；受限 shell 的默认代理不能访问外网。数据任务已经实际访问巨潮元数据，但 Scheduled Task 没有独立执行过 PDF 探测，不能仅凭本次测试声称其 PDF 出站权限已验证。[证据：最小网络探测、ingestion 记录]
- 读取单份 PDF **不需要新增仓库程序或安装库**：Codex 捆绑运行时已有 `pdfinfo`、`pypdf 6.10.0`、`pdfplumber 0.11.9`；项目 `.venv` 本身没有后两者。[证据：本机工具检查]
- 当前最简单方式是：先用元数据核对 `available_at <= as_of`，取同一行 `pdf_path`；持久化 `www` URL 失败时改用巨潮官方静态域名；下载到临时目录，校验 HTTP、Content-Type、`%PDF-` 和页数，抽取所需正文后删除。[证据：Parquet、网络探测]
- 当前没有短期缓存或缓存失效合同。按现状最稳妥的是单次验证临时下载后删除；是否以后短期缓存应由后续调优决定，本轮不实现。
- 若 `available_at > as_of`，状态应为 `unavailable_at_cutoff`，不得读取；若 HTTP/文件校验失败，技术状态应为 `下载失败`，公司 Skill 的金额、条件、风险和材料性结论同时为 `正文未知`；若下载成功但文本为空且不做 OCR，则为 `正文未知（非 OCR 提取为空）`。仅保留公告存在、标题、来源和官方时间。

## 6. 四个 Skill 的数据可得性矩阵

| Skill 判断维度 | 所需主要字段 | 本地直接可算 | 需按需读取 | 当前不可得 | 历史可回放 | 实际限制 |
| --- | --- | --- | --- | --- | --- | --- |
| market：指数与参与宽度 | 日线/复权、6 个必需指数、涨跌停 | 是；`market_context` 已完整 | 无 | 无本地宏观原文时间序列 | 行情保守回放 | 上证综指不等于上海主板；不能从广度推出未来收益 |
| market：成交与价格推进 | 成交额、等权/中位/上涨面、新高 | 是 | 无 | 资金/账户身份 | 保守回放 | 成交放大只描述现象 |
| market：分化/波动/集中 | 横截面收益、20/60 日基线、正收益贡献 | 是 | 无 | 无 | 保守回放 | 只有分化—后续波动是当前二级条件关系，不给方向 |
| market：规模风格 | 沪深300/中证500/中证1000 | 是 | 无 | 风格将来是否延续 | 保守回放 | 只描述当前相对领先 |
| market：宏观/政策传导 | 形成日前官方原文、发布时间、公司暴露 | 否 | 仅具体候选时定向读取官方材料 | 本地没有可回放宏观/政策事实库 | 当前不能系统回放 | 不能用新闻叙事补猜 |
| sector：行业共同性 | 历史成员、行业日线、个股复权日线 | 是 | 无 | 更早完整成员版本流 | 行业成员保守回放 | 行业日线仅约 278 日 |
| sector：主题共同性 | 主题目录/成员/日线 | 部分 | 无 | 2025-07-31 前历史主题成员 | 仅近期保守回放 | 43 个主题无公开成员 |
| sector：扩散/集中/分化/同类 | 成员中位、广度、前三贡献、分化、成交份额 | 是，覆盖有成员的 642 组 | 无 | 无权重时的精确贡献 | 近期可回放 | 73 组核心输入 limited |
| sector：盘中持续性 | 分钟成员/指数 | 否（最新全部为空） | 无可靠现成补取 | 全市场/全板块分钟覆盖 | 不能 | 仅 3 个工具，接口权限/限流 |
| company：身份和主营 | 公司概况、主营分部 | 是但保守 | 候选材料性必要时读 PDF | 严格历史公司概况 | profile ingestion-only；主营保守 | 当前概况不能倒推历史 |
| company：财务传导 | 三表、指标、主营、预告、快报 | 是 | 原文语义冲突时读 PDF | 无 | 保守回放 | `financial_indicator` 有 1 条修订区间异常；公告日精度为主 |
| company：事件阶段和反证 | 公告元数据、股东交易、解禁、回购、质押、停牌 | 大部分结构化可读 | 金额/条件/阶段/风险可能改变取舍时读官方 PDF | 本地公告正文库 | 公告元数据 strict；其他多为保守/ingestion | 标题不能证明材料性；质押仅 ingestion 回放 |
| price：绝对/相对市场路径 | 复权 OHLC、基准、量额、涨跌停 | 是 | 无 | 无 | 保守回放至 2021-07-14 | 相对板块需另接 sector 结果 |
| price：趋势/效率/振荡/波动 | 251 会话复权日线 | 是；最新 4,854 行场景完整 | 无 | 无 | 可按形成日重算 | 短历史股票会 limited |
| price：长期位置和剩余路径 | 60/82/250 日位置、成交推进、涨停贡献 | 是 | 公司/板块催化需其他 Skill | 交易主体身份 | 可重算 | 位置低不等于空间大，位置高不等于透支 |
| price：流动性/参与性 | 日成交、涨跌停、停牌、T+1、融资 | 是；分钟非必需 | 行动日只制定可观察条件 | 形成日前不能读取行动日实际行情 | 日线保守回放 | 融资只到 T+1；不连接券商 |

## 7. 价格 11 个场景逐项盘点

### 7.1 是否可计算

`price_analysis_context` 实际具备 `SCENARIO_THRESHOLD_FIELDS` 全部 24 个数值字段和 4 个事件字段；本地还存在 V3 冻结的 development thresholds。使用 2026-08-20 最新 5,541 行实际执行 `assign_price_scenarios`，11 个场景全部成功返回 5,541 行 case/control 掩码。失败突破和量价背离当日 case 为 0，是“无命中”，不是“不能计算”。[证据：代码、Parquet、本地只读计算]

| scenario_id / 场景 | 所需字段摘要 | 当前本地每日计算 | 历史证据覆盖与状态 | 当前允许的选股作用 | 2026-08-20 实测 case/control | 是否每日记录 | D20 后能否复盘 |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| `trend_continuation` 既有趋势延续 | 20 日/相对收益、EMA/DMI/ER、上涨天数、收盘与量价效率、涨停贡献 | 能 | 27,663/39,437；触达差约 +2.91pp、区间全正、两年同向，但 D20 无明显改善且 MAE 略差 | **可作正向历史关联参加发现和比较**；不能单独推荐，须披露回撤/D20 限制 | 573/1,068 | 否 | 场景关联可；AI 是否正确使用不可 |
| `initial_activation` 初步激活 | 中性 20 日位置、5 日相对强、放量、MACD/DMI、收盘效率 | 能 | 3,350/5,893；触达差 -0.63pp、区间跨零 | 只改变搜索问题、验证重点或替代股比较；不能单独推荐/淘汰 | 9/52 | 否 | 同上 |
| `healthy_pullback` 上升趋势内健康回撤 | 强 20 日趋势、5 日回撤、EMA/DMI/ER/RSI、缩量、回落与量价 | 能 | 191/13,383；样本不足，触达差 -9.02pp | 健康回撤假设/风险问题；不能写成已验证买点 | 66/438 | 否 | 同上 |
| `range_cross_noise` 震荡噪声中的交叉 | MACD/KD 上穿 + 低 ADX/ER/弱 DMI/弱量价/居中收盘 | 能 | 1,418/11,835；负面关联显著、两年同向 | **可作反证；这种上穿不得提高优先级**，但不等于一定下跌 | 40/173 | 否 | 同上 |
| `confirmed_breakout` 有效突破 | 60/250 日突破、相对强、ER/DMI、收盘/量价与涨停贡献 | 能 | 5,859/598；触达差 +6.14pp，但区间跨零、MAE/D20 较差 | 可作共同验证线索和同类比较；不能单独推荐 | 40/11 | 否 | 同上 |
| `failed_breakout` 失败突破 | 突破/BOLL、放量、上影/回落、量价低效、MACD/DMI | 能 | 4/17,443；场景样本极少 | 只提出失败突破风险问题；不能机械淘汰 | 0/95 | 否 | 同上 |
| `oversold_strong_downtrend` 强下跌中的超卖 | RSI、弱 20 日绝对/相对、EMA/ADX/DMI、低收盘与负量能 | 能 | 9,815/0；无可比对照，绝对触达 17.73% 不证明抄底 | 超卖/转强待核问题；低 RSI 无独立选股权 | 5/0 | 否 | 同上 |
| `reversal_attempt` 真实反转尝试 | 弱 20 日 + 强 5 日相对、MACD/DMI/RSI、放量与正量价 | 能 | 347/18,715；样本不足，触达差 -0.87pp | 只能称反转尝试，改变验证重点/比较 | 1/27 | 否 | 同上 |
| `trend_exhaustion` 趋势衰竭 | 高 20 日/RSI/EMA、MACD 减弱、上影/回落与量价转弱 | 能 | 1,254/15,754；D20 差方向不支持预期且区间跨零 | 可提出衰竭风险问题；不能固定判衰竭或单独淘汰 | 25/123 | 否 | 同上 |
| `single_day_impulse` 单日脉冲或透支 | 强 5 日、放量、涨停贡献、上涨天数、ER/BOLL 扩张 | 能 | 283/17,623；样本不足、D20 差 -0.73pp 且区间跨零 | 报告路径集中/透支问题并作比较；不能机械淘汰 | 10/231 | 否 | 同上 |
| `price_volume_divergence` 量价背离 | 5 日上涨/放量、短长量价效率、回落/上影/收盘、MACD/DMI | 能 | 0/36,053；历史 case 为空 | 可报告放量滞涨/冲高回落事实并提出风险问题；固定模板保持未知 | 0/281 | 否 | 同上 |

当前并非把 11 个场景全部排除：既有趋势延续可以参加正向发现和比较；震荡噪声交叉可以作负面反证；其余 9 个可以改变问题、验证重点、风险核对或替代股比较，但不得单独形成推荐或淘汰。已失败的 **BOLL 窄带后上轨突破正面组合** 不属于这 11 个场景的另一个有效版本，当前明确禁止换名恢复。[证据：当前 Price Skill、价格调优报告]

当前 Price Skill 已不再用旧的 `supported/refuted/insufficient` 三标签或单一 3pp 门槛自动决定参与权；上表按当前 Skill 的效果方向、区间、年度稳定性、覆盖、MFE/MAE/D20 边界报告实际用途。[证据：当前 Price Skill]

### 7.2 当前记录能否回答场景使用问题

| 审计问题 | 当前能否回答 | 依据 |
| --- | --- | --- |
| 某股票形成日是否命中某场景 | **不能从每日记录直接回答**；可以用当日输入和冻结阈值事后重算 | `price_analysis_context` 不存场景标签 |
| 场景是支持、反证、比较还是行动条件 | 不能结构化回答 | Forward 无 `decision_role`；自由文本位置只能部分暗示 |
| 场景是否实际改变选择 | 不能 | 无 `decision_changed` |
| 使用了哪些形成日数值 | 不能稳定回答 | Forward 理由可写自由文本，但无受约束的 `formation_values` |
| 最接近替代股是谁 | **能** | Forward 已有且 32/32 股票行均填写 `nearest_comparison` |
| 场景本身是否有效 | 历史验证归档可以评价 | 有冻结阈值、场景 membership、历史结果和 D20 指标 |
| AI 是否正确使用场景 | 当前不能与场景本身分离评价 | 缺实际使用身份、版本、角色、数值和改变记录 |

## 8. Forward 记录与集中复盘能力

### 8.1 当前实际记录

`local_archive/forward_selection/` 当前约 76K，包含 Forward CSV、两份特定形成日研究 JSON 和一份 2026-08-18 价格审计说明；不是每天一份价格研究附件。[证据：目录检查]

| 项目 | 实际结果 |
| --- | --- |
| CSV 字段 | `formation_date, action_date, as_of, ts_code, name, final_fate, priority, opportunity_type, selection_reason, strongest_counterevidence, nearest_comparison, current_day, current_close_return, max_close_return_so_far, hit_20pct_close_within_20d, first_hit_day, terminal_return_20d, selection_as_of, validation_mode, max_close_return_20d` |
| 总记录 | 32 行、8 个形成日（2026-08-10 至 2026-08-19） |
| `selected` | 23 行；选择理由、最强反证、最近比较均 23/23 |
| `nearest_nonselection` | 9 行；选择理由、最强反证、最近比较均 9/9 |
| `empty_selection` | 0 行 |
| 历史兼容模式 | 空白 12 行、`reconstructed` 13 行、`selection` 7 行 |
| 已成熟形成日 | **0 个**；32 个股票行均未形成代码定义的完整 D20 结算 |
| D20 当前结算能力 | 代码会在行动日起完整 20 个交易日并具备复权开/收盘后，一次写入收盘触达、首次触达日、20 日最大收盘收益和 D20 收盘收益 |
| 每日价格附件 | **不存在**；仅一份 2026-08-18 审计说明明确写着场景和指标未留存、无法审计 |

当前 D20 结算只保存收盘路径，不保存盘中触达、MFE、MAE 或相对市场结果；历史场景验证归档有更丰富的评价口径，但它不是 Forward 每日记录。[证据：代码、CSV、归档]

### 8.2 “暂定参与 + 固定时点集中复盘”的最小字段缺口

不建设新平台、不改数据库的前提下，技术上可以把实际使用记录放在每天被 Git 忽略的紧凑研究附件中；当前 Price Skill 已允许仅对实际入选股和实际最近未入选股保留 1—2 条真正改变取舍的价格判断。Forward 已有的形成日、行动日、带时区 `as_of`、股票、最终去向、理由、最强反证和最近比较不必重复新增。[证据：当前 Price Skill、Forward Schema]

| 候选字段 | 是否已有可靠承载 | 最小处理 |
| --- | --- | --- |
| `scenario_id_or_raw_price` | 无；只能埋在自由文本 | **需要**；允许没有合适场景时写 `raw_price` |
| `scenario_version` | 派生 Parquet 有公式版本，但 Forward 不知道实际用了哪个场景/阈值版本 | **需要**；记录场景定义/阈值版本，不重写旧记录 |
| `decision_role` | `selection_reason`、`strongest_counterevidence`、`nearest_comparison` 可部分暗示，但不能区分支持/反证/比较/行动条件 | **需要** |
| `decision_changed` | 无；从最终去向不能推断价格判断是否改变了选择 | **需要**；布尔或简短枚举即可 |
| `formation_values` | 个别 JSON 有原始价格快照，Forward 不稳定、也没有场景所用技术数值 | **需要**；只保存实际用到的数值，不罗列全部指标 |
| `nearest_comparison` | **已有**，32/32 股票行已填 | 直接复用，不新增 |
| `evidence_status_at_use` | 无；现有历史结果不能证明当时 AI 采用了什么边界 | **需要**；保存当时效果方向/不确定性边界的简短状态 |

因此最小新增不是 7 个字段，而是 **6 个**：复用现有 `nearest_comparison`，补齐其余六项。这样才能在 D20 后分别问“场景在新样本中是否继续有效”和“AI 当时是否按证据边界正确使用”；少任何一类都会把两者混在一起。[证据：代码、CSV、归档、当前 Price Skill]

## 9. 最终限定结论

### 9.1 当前真实可用数据的五个最重要边界

1. **核心行情强、时点版本仍以保守回放为主。** 五年左右日线、复权、估值、涨跌停和指数已到 2026-08-20，物理质量好；但除公告元数据外没有整类 strict 历史版本流。[证据：DuckDB、Parquet、合同、健康报告]
2. **最新事实日不等于最新正式形成日。** 2026-08-20 已有收盘、晚间和派生，次晨只到 2026-08-19；后者是最新曾闭环的正式形成日，当前重放还要处理 stale input manifest。[证据：ingestion runs、健康报告、Forward]
3. **板块日线可做一年左右的指标化研究，历史主题和分钟能力明显不足。** 44 个组无成员、全部 686 个组没有可用盘中观察，分钟事实仅 3 个工具。[证据：Parquet、健康报告]
4. **公司结构化事实丰富，但正文与严格历史公司身份不足。** 公告只有元数据入口，公司概况和质押为 ingestion-only；财务指标另有 1 条修订区间异常。[证据：Parquet、健康报告、目录检查]
5. **价格 11 场景都能算，但“算得出”不等于“已验证”或“已留痕”。** 当前仅趋势延续有受限正向参与权、震荡交叉有负面反证权，其余主要改变问题；Forward 尚无成熟 D20 日期，也不记录场景实际使用。[证据：代码、Price Skill、验证报告、Forward]

### 9.2 哪些 Skill 可以直接做指标化调整

- market：指数/等权/中位/广度、成交推进、分化、波动、集中、规模风格可以直接基于 `market_context` 调整展示和问题选择；收益方向权限仍受当前证据等级限制。
- sector：有成员的行业/主题可直接使用多窗口相对收益、广度、中位、成交份额、集中和分化；不能把缺成员主题或盘中指标纳入完整判断。
- company：三表、财务指标、主营、预告/快报及结构化事件可以直接做时点化比较；材料性、合同条件和风险提示在可能改变取舍时需按需读官方 PDF。
- price：六类信息维度和 11 场景均可由现有日线事实确定性计算；当前 Skill 的参与权限必须原样保留，不得因可算而升级证据。

[证据：四类派生 Parquet、五个当前 Skill]

### 9.3 因数据不可得暂时不能做的设想

- 严格回放历史公司概况、证券名称/ST 快照、质押快照和完整主题成员；
- 在 2025-07 以前做同口径主题扩散，或用约 278 日板块日线声称五年稳定性；
- 用当前分钟数据做全市场/全板块盘中持续性；
- 直接使用本地公告正文库、自动全文检索或 OCR；当前都不存在；
- 系统回放宏观/政策原文；本地没有该事实库；
- 从量价、融资或成交推断机构、主力或账户身份；
- 用当前 Forward 区分“场景无效”与“AI 用错场景”。

[证据：合同、Parquet、目录、当前 Skill]

### 9.4 公告按需读取是否可行

**可行，但有明确现状限制。** 两份官方静态 PDF 均成功下载、校验并非 OCR 提取出非空文本；不需要新增仓库程序。持久化 `www` URL 在本次两例均为 404，需要使用同一 `pdf_path` 的官方静态域名；Scheduled Task 的 PDF 出站权限尚未独立验证，且当前没有缓存。[证据：最小网络探测、本机工具检查]

### 9.5 “暂定场景参与 + 定期集中复盘”是否技术可行

**在当前个人助手架构下可行，不需要新平台。** 现有价格派生、冻结场景阈值、Forward 时间边界和 D20 结算已经提供计算与未来观察基础；每天只需为实际入选和实际最近未入选保留很小的被忽略附件。当前最小缺口是前述 6 个场景使用字段；`nearest_comparison` 已存在，无需重复。[证据：代码、Parquet、Forward、当前 Price Skill]

### 9.6 需由 ChatGPT 读取本报告后再决定的问题

1. 对 9 个尚未形成稳定历史证据的场景，哪些只允许提问，哪些允许进入替代股比较或风险反证；
2. 趋势延续的正向触达关联与 D20/MAE 限制应如何在最终 Price Skill 中平衡；
3. 是否把官方静态域名回退和临时 PDF 读取写入后续正式工作流；
4. 是否采用每天一个紧凑、被 Git 忽略的价格使用附件，以及 6 个字段的最终命名；
5. 旧形成日派生在后续事实提交后变 stale 时，正式研究复现应采用怎样的再解析/再派生纪律；
6. 哪些板块、主题、公司设想应因历史成员、正文或宏观数据不可得而明确放弃，而不是继续扩大数据工程。

这些是后续调优取舍，不在本报告内制定最终 Skill 调优方案。
