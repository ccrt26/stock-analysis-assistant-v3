# 本地财务冲突与健康核查

核查先识别当前仓库、数据发布节奏及任务触发时间。`research.duckdb` 是当前仓库；派生登记看 `research_derived_partitions`，阶段记录看 `research_ingestion_runs`。旧 `research_derived_runs` 和旧数据库 `warehouse.duckdb` 的 `formal_*` 不作为当前缺口。每日分钟采集已停用；官方行业日线与独立代理是不同数据集，不直接拼接。

融资融券是T+1事实。健康检查的 `evaluated_at` 只决定哪些业务日已到期，真实 `generated_at` 保留生成时间；指定日物理分区、最新应到日、等待发布日期分别展示。历史评估不声称回放当时采集状态。18:32定时点之前没有当晚执行记录不是任务故障。

## 定向修复三表冲突

先使用只读检查，保存结果供审查；重试目标只能来自已审清单。命令以项目根目录为工作目录，目录名称由实际本次维护指定。

```sh
mkdir -p local_archive/data_repairs/statement-repair
.venv/bin/python -B tools/repair_statement_conflicts.py --inspect \
  > local_archive/data_repairs/statement-repair/reviewed-targets.json
.venv/bin/python -B tools/repair_statement_conflicts.py --apply \
  --targets local_archive/data_repairs/statement-repair/reviewed-targets.json \
  --output-dir local_archive/data_repairs/statement-repair
```

`--inspect`自身不创建目录、锁或请求上游。重定向文件是人工保存盘点结果。凭据沿用现有配置，必要时在不打印内容的子shell加载`.env.local`。

`--apply`只请求income/balancesheet/cashflow，并按完整业务键过滤。不同内容只有唯一官方最新标志才裁决；内容相同不因标志不同产生版本冲突。事实先原子保存并重读核对，再解除对应冲突，裁决从本次观察起生效。来源失败保留未决，程序或存储异常停止后续写入。工具不启动研究或复盘、不重算派生、不改自动任务、不覆盖正式健康报告。

每次apply在现有任务锁内生成独立运行子目录；备份阶段再取得现有事实锁。先核对仓库版本且无WAL、待恢复日志及previous文件，复制整个数据库和目标分区、校验备份，再打开可写仓库。备份、前后快照、结果及单独健康报告都在运行目录中。不能运行旧的广范围修复脚本替代此入口。

发生中断时保留已有成功结果，检查`result.json`与剩余清单；用原已审目标清单再次执行，只处理仍未决目标。不能为了使数量归零而人工标记完成。若要恢复整个数据库，必须持任务锁并确认备份后没有其他写入；否则禁止用旧数据库覆盖，需另做范围内恢复。
