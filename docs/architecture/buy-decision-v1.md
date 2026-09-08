# 单股买入决策能力 V1（buy-decision-v1）

**更新日期：** 2026-09-08
**状态：** 已实现并本地试跑；按需运行，不属于每日任务

## 1. 一句话说明

用户指定一只**尚未买入**的 A 股，程序只读事实仓准备一次研究的紧凑材料并对 AI 提出的价位方案作数值复算；AI 按 `.agents/skills/analyzing-stock-buy-decision/SKILL.md` 的方法作出参与、等待或放弃的判断并撰写唯一正文 `report.md`。Python 管事实、时间、数值与来源记录；判断与正文由 AI 完成。

## 2. 边界

- 不修改五个选股 Skill 合同、原推荐 20% 评价、正式复盘、Forward CSV、冻结历史；不加打分、权重、固定盈亏比门槛或新 Gate。
- 不接券商、不下单、不决定仓位、不建持仓或账户系统、不新增定时任务/推送/数据库/服务端；不承诺收益。
- 原推荐（`registered-episodes.json` 及历史快照）只读引用为背景，其目标价、20% 标签、剩余观察天数不得作为新买入门槛或卖出条件。
- 三起点分离：原推荐（背景）／本次拟买入（独立计算）／真实持仓（不创建）。

## 3. 组成

```text
.agents/skills/analyzing-stock-buy-decision/SKILL.md   研究方法与边界
ops/buy-decision-prompt.md                             运行顺序与报告撰写
src/stock_analyzer/analysis/buy_decision_features.py   纯计算：距离/窗口/ATR/归一
src/stock_analyzer/ops/buy_decision.py                 prepare / calculate 子命令
tests/test_buy_decision_features.py                    纯计算测试
tests/test_buy_decision.py                             只读入口 + prepare/calculate 测试
tests/test_buy_decision_prompt.py                      Skill/Prompt 语义校验
tests/fixtures/buy_decision_calibration.md             六例合成校准（人工阅读核对）
```

## 4. 共享存储的唯一改动：显式只读入口

`ResearchWarehouse(root, read_only=True)`：不创建目录/锁文件/索引、不写 catalog、不迁移、不恢复中断写入；发现未恢复 journal（`.fact-promotions/*.json`）或备份（`*.parquet.previous`）时抛 `FactRecoveryError` 交由原维护流程处理，只读研究自身不修数据；写方法抛 `PermissionError`（在取文件锁之前拒绝）。`ResearchWarehouse(root)` 默认写模式行为完全不变。`materialize_snapshot` 全链（含冲突过滤）本就使用只读连接或内存 duckdb，帧与 `input_manifest` 一次生成、互相对应。

交易日历有两路口径：as_of 快照内的可见会话（价格事实窗口）与原始分区会话表（未来会话推演；未来日历行的 `available_at` 是各自日期收盘后，经 as_of 过滤读不到，原始读法沿用 `forward_selection.LocalForwardData.trading_dates` 先例，仅用于会话存在性，不作为价格事实）。

## 5. 接口合同

```bash
python -m stock_analyzer.ops.buy_decision prepare \
  --request REQUEST_JSON --output-dir NEW_RUN_DIR \
  [--warehouse-root PATH] [--project-root PATH]

python -m stock_analyzer.ops.buy_decision calculate \
  --run-dir RUN_DIR --analysis-input ANALYSIS_INPUT_JSON
```

- 请求合同：`ts_code`（V1 范围：沪市主板 600/601/603/605、深市主板 000/001/002/003、创业板 300/301）、`position_status` 必须 `not_bought`、`as_of` 带时区、`horizon_sessions` 正整数、参考买价与来源成对、亏损容忍度与成本仅用户可填。
- `prepare` 写 `request.json` + `context.json`（身份与范围、双路日历、归一日线与截止日、中性观察、公告元数据、财务摘要、原推荐背景独立子对象、`input_manifest`、缺口）。不覆盖已存在 run 目录。
- `calculate` 校验每个方案的价位与六个文字条件（占位文本拒绝），逐方案调 `compute_buy_geometry`（无回退：方案没给 ATR/成本就输出 null），复算观察窗口，写 `analysis.json`（输入原样保留）。`plans=[]` 合法。
- 纯计算：`compute_buy_geometry`（价距、净收益近似、ATR 距离、`below_entry` 标注；不输出买卖结论）、`holding_window_end`（买入日计第一天；非交易日起点/日历不足报错）、`atr20_from_sessions`（20 会话真实波幅简单平均，与既有两处实现同定义）、`normalize_price_history`（原始价×当日因子÷基准日因子）。

## 6. 文件产物

```text
local_archive/buy_decisions/<run_id>/request.json     请求原样
local_archive/buy_decisions/<run_id>/context.json     只读材料与缺口
local_archive/buy_decisions/<run_id>/analysis.json    方案复算结果
local_archive/buy_decisions/<run_id>/report.md        唯一报告正文（AI 撰写）
```

同一报告的数字修正可显式重算 `analysis.json`；改变事实截止时点必须建新 run。目录已被 `.gitignore` 覆盖，不入库。

## 7. 已知边界与缺口语义

盘中报价在 V1 只能是独立快照（代码、价格、报价时间、获取时间、来源）；证明不了报价时间就不能支持"立即按现价参与"。默认执行假设为收盘确认后次一交易日正常竞价时段（保守简化，不接盘后固定价格交易）。缺口只限制它实际影响的结论，区分未查询/取数失败/覆盖不足/存在但无正文/版本无法确认/确实无记录。

## 8. 测试

```bash
./.venv/bin/python -m pytest -q \
  tests/test_buy_decision_features.py \
  tests/test_buy_decision.py \
  tests/test_buy_decision_prompt.py
```

只读入口测试全部使用临时仓库；既有仓库测试继续覆盖默认写模式。六例合成校准是人工阅读核对材料，不是收益统计证据。
