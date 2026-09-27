# M0/M1 轻量对照：手工试验说明

**状态：**命令是本分支新增的手工试验接口；合成定向测试已通过，真实 M0/M1 配对验收在首边停止，第二边未运行。当前私有配置标为 `blocked_smoke_pending_method_input_decision`，研究命令拒绝继续。未启用定时试验，未采用为正式选股方法。正式 `tools/stock_ai.py`、正式归档与 WEB 不读取本试验结果。源码不携带本机事实、模型输出或路径。

## 身份与输入

共用程序从 `d3985297ba17aa1f62496c259924f9aeb24c3814` 起开发；M0 冻结于 `a1fcef2f1c6e3a99b47d4a5186fec91179f8e64c`，M1 冻结于 `c84238a686cc0809172ecd2e28e8cbf7880fc398`。H 是正式历史，只读参考，不能充当同模型 M0。两个方法各有一个仓库外上下文和方法包；各用 `codex exec --model gpt-6-sol -c 'model_reasoning_effort="xhigh"' --sandbox read-only`，每边一次新会话，无替补。五个 Skill 在会话内履行不同研究职责。

`init` 验证并冻结方法文件；`prepare` 根据带时区的 `as_of` 找最后形成交易日和下一参与交易日，保存完整中性派生、可选范围、事实分区版本与派生来源。`facts` 只读同一 catalog；模型可以分别发现候选，实际读取小切片由宿主复核并存回本日 `inputs/reads/`。来源版本变化会停止配对。当前 `replay_smoke` 与前瞻 `daily/` 分开放；首次前瞻准备才冻结30个预定参与日，连续每10日一批。

## 命令与恢复

以下均从本分支工作树运行，并让 `PYTHONPATH` 包含本工作树的 `src` 与根目录。`CFG` 是本机私有 `LOCAL_ARCHIVE_DIR/selection_trials/confirmation-cost-v3/experiment.json`，其中显式写实际源码、仓、归档、上下文和 Python 路径。公开仓不提供个人路径配置；文件须先按本机路径建立。`init` 会检查配置中固定提交、模型、推理强度及隔离目录。

```bash
python tools/selection_parallel.py init --config "$CFG"
python tools/selection_parallel.py prepare --config "$CFG" --as-of '2026-09-23T18:30:00+08:00' --mode replay_smoke
python tools/selection_parallel.py facts --catalog "$CATALOG" --code 000001.SZ --category price
python tools/selection_parallel.py select --config "$CFG" --action-date 2026-09-24 --method M0
python tools/selection_parallel.py select --config "$CFG" --action-date 2026-09-24 --method M1
python tools/selection_parallel.py outcomes --config "$CFG" --through 2026-09-24
python tools/selection_parallel.py status --config "$CFG"
python tools/selection_parallel.py daily --config "$CFG" --date auto
python tools/selection_parallel.py batch --config "$CFG" --number 1 --through YYYY-MM-DD
python tools/selection_parallel.py review-batch --config "$CFG" --number 1 --through YYYY-MM-DD
python tools/selection_data_inventory.py --source-root "$SOURCE_ROOT" --output-dir "$MAINTENANCE_DIR"
```

上面的历史日期只示范 `replay_smoke` 接口，不应每天重跑；当前阻断状态下 `prepare`、`select` 与 `daily` 会拒绝新研究，只有 `status`、独立结果计算和盘点等无需新研究的命令可用。日常人工命令是 `daily --date auto`；上海时间18:30前只报告尚未到截止，明日不开市只更新既有结果。若已冻结一边，重复 `select` 直接复用；中断后对未完成的方法调用相同 `select`，不得换截止或来源。真实来源版本已变时停下并按试验 `maintenance/questions-for-chatgpt.md` 交回。`outcomes` 可独立调用，不依赖当晚有新研究。`review-batch` 仅在用户明确调用时启动一次集中研究，不自动改方法。

## 指标和状态

参与日开盘为标准参考入口，复权收盘到第5/10/20个原日历交易日的回报由原 `export_skill_optimization_dataset.py` 计算。第20日约20%收盘触达沿用原口径。端点值与全路径完整性分列；缺中间日不补零、不顺延。最低点相对入口的跌幅与最大收盘回撤分别列；沪深300用同入口开盘和对应收盘。参与条件是否真实可执行没有成交和盘中顺序时标未知；参考价格路径不等于实际成交或净收益。空名单、未跑、失败、条件事件、未成熟和缺路径各自保留。

批次范围按预定日历，不按入选股票数或好坏重排。`outcomes.csv` 配有 `summary.json`、同股首条和不重叠窗口辅助 CSV；`comparison.csv` 保留全部候选及零入选/失败日，`metrics.json` 分列完成、配对、空名单与第5/10/20日各自分母、中位数、相对基准及路径指标。辅助视图不声称统计独立。`report.md` 只有人工触发批次研究后才存在。第一版停止收新样本于第30个预定参与日，既有样本的20日结果仍可继续更新。旧正式 WEB 的五日方法复盘属于 `skill_optimization`，与这里的十日批次分开。

详见 [数据地图](data-map.md) 和根 README 的正式/试验流程图。
