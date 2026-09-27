# 股票分析助手本地数据地图

实际路径由 `AppConfig` 的 `PROJECT_ROOT`、`LOCAL_WAREHOUSE_DIR`、`LOCAL_ARCHIVE_DIR` 解析。源码工作树可能没有事实仓；不要从工作树缺文件推断本机没有数据。GitHub 只包含源码和说明。

| 位置（相对实际根） | 内容 | 生产/消费 | 保存边界 |
| --- | --- | --- | --- |
| `local_warehouse/research.duckdb` | 事实与派生登记、修订、运行元数据 | 数据任务写，时点查询读 | 基础事实元数据，保留 |
| `local_warehouse/facts/` | 行情、复权、日历、成员、财务、公告等 Parquet | 采集写，正式研究与试验只读 | 基础事实，保留；可再下载不等于可删 |
| `local_warehouse/derived/` | 全市场市场/板块/个股/价格观察 | 确定性派生写，研究读 | 可再生但依赖原版本；局部重建核对前保留 |
| `local_archive/forward_selection/` | 正式推荐、trace、来源 | 正式任务与 WEB | 正式记录，原样保留 |
| `local_archive/forward_monitor/` | 正式复盘和原20日结案 | 正式任务与 WEB | 正式记录，原样保留 |
| `local_archive/company_introductions/` | 正式推荐附属公司介绍 | 正式任务与 WEB | 正式记录，原样保留 |
| `local_archive/skill_optimization/` | 原人工方法研究 | 旧 WEB 五日范围方法复盘 | 研究证据，保留；不与新试验混写 |
| `local_archive/selection_trials/confirmation-cost-v3/` | M0/M1方法、共用输入、独立短决定、原输出、后续结果、批次 | 仅手工试验与集中研究 | 当时输入、决定和批次版本保留；不写正式账本 |
| `local_archive/data_repairs/`、`repairs/`、`change_backups/` | 修复备份与证据 | 恢复与审计 | 不按“重复”名称清理 |
| `local_archive/ai_tasks/`、验证资料 | 模型原始材料和研究证据 | 正式任务恢复、审计 | 需核对产消关系，不能概括为临时文件 |
| `local_archive/publish/`、`logs/` | 展示回退、运行日志 | WEB 回退与故障定位 | 用途未核清前保留 |
| `local_warehouse/.staging/`、`.backfill_staging/` | 可能的中断恢复暂存 | 仓库恢复路径 | 未核清引用与恢复依赖前保留 |

试验 `daily/<参与日>/inputs/` 保存当时共同中性观察、完整证券范围、原分区版本和实际读取的关键小切片；`M0/`、`M1/` 各自保存原始短输出和采用结果；`outcomes/<评价截止>/rNNN/` 由程序计算并附分母及重复股辅助视图；`batches/batch-NNN/<评价截止>/rNNN/` 包含十日全量材料，人工运行后才有 `report.md`。`smoke/` 是回放链路验收，不计入前瞻十日批次。模型工作上下文在仓库之外，可由冻结方法包重建，不是第二份权威归档。

私有 `maintenance/inventory.csv` 按实际文件列大小、类别和已知产消关系；`cleanup-proposal.csv` 只列重建和引用均核实的精确候选。本版未验证任何真实文件可安全清理，因此建议列表为空，**没有执行删除**。未知项、修复备份、正式记录和原证据继续保留。程序不提供删除参数。
