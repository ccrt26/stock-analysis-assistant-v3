# M0/M1 轻量对照：程序与手工研究边界

**当前状态：**程序修复与无模型输入预检阶段；`research_enabled=false`。旧 2026-09-24 Sol/xhigh M0 保留为不合格诊断，M1 未运行。本轮 `live_pair_verified=false`。未自动启用、未生产采用；正式 nightly、推荐、复盘、公司介绍和 WEB 不读本试验。

## 固定身份

共用原程序基线 `d3985297ba17aa1f62496c259924f9aeb24c3814`；M0 方法 `a1fcef2f1c6e3a99b47d4a5186fec91179f8e64c`；M1 V3 候选方法 `c84238a686cc0809172ecd2e28e8cbf7880fc398`。两套冻结 Skill 与方法包保持原样。未来每边一个独立 Codex 研究上下文，运行时强制 `gpt-6-astra` / `xhigh`、不回退；本轮 Sol 只承担程序开发。模型是否实际按请求运行，未来须从该次 CLI rollout 的 turn_context 核实，配置与提示词不等于运行证据。

## 输入与短决定

`prepare` 按带时区 `as_of` 找最后交易形成日和下一参与日，冻结四类原派生、完整合格证券范围、公司全市场时点索引、一次性字段图和相关来源分区版本。`company_discovery.parquet` 按当时可见的公告、四类财务及公司资料存原值；`discover --view company` 可分页查询，不用价格候选代码。标题不是正文；覆盖摘要是本地可检索情况，不声称全市场公告完整。`facts` 可一次传多个 `--code`、`--category`，默认精简输出并用 `next_offset` 续页。公司事实读完整截止，周末可配周五已冻结价格派生；相关分区覆盖或文件哈希改变则拒绝继续。

未来真实短决定需含 sector/company/price 的 `discovery_summary`，把已查有候选、已查无合适候选、未执行或资料不足区分。每只实际候选保留原去留和必要证据；若 M1 用保持解释，可加观察参照、来源和后续已完成交易的 `confirmation_reference`。合格资格写在各边 `qualification.json`；旧无 V2 资格或旧 Sol 身份不能因有 `result.json` 而升格。预算失败非零退出、保留日志、不转写为空名单。

## 本轮可运行命令

从本分支工作树运行，设置 `PYTHONPATH="$PWD/src:$PWD"`。`CFG` 是本机私有 `LOCAL_ARCHIVE_DIR/selection_trials/confirmation-cost-v3/experiment.json`；`CATALOG` 取准备命令返回目录中的 `inputs/catalog.json`。

```bash
python tools/selection_parallel.py status --config "$CFG"
python tools/selection_parallel.py prepare --config "$CFG" --as-of '2026-09-23T18:30:00+08:00' --mode replay_smoke --replay-id 2026-09-24-input-v2
python tools/selection_parallel.py discover --catalog "$CATALOG" --view company --limit 50 --offset 0
python tools/selection_parallel.py facts --catalog "$CATALOG" --code 000001.SZ --code 000002.SZ --category company --category price --offset 0
python tools/selection_parallel.py outcomes --config "$CFG" --through YYYY-MM-DD
python tools/selection_parallel.py batch --config "$CFG" --number 1 --through YYYY-MM-DD
```

`prepare`、`discover`、`facts`、`outcomes`、`batch`、`status` 不调用模型。`batch` 需要预定十日范围与到达的评价截止，未冻结日历时会拒绝。`select`、`daily`、`review-batch` 是未来研究入口，在当前开关下启动前拒绝；不运行探针。新 replay-id 使用 `smoke/<replay-id>/` 单层目录，`run.json` 另记真实参与日。相同交易日多身份时 `select` 必须显式 `--replay-id`。共同输入、代码提交、Prompt、方法、模型或预算改变时新建配对身份；只在条件完全未变且用户已批准后续未完成一边。

## 限额与结果

私有配置初始每边 `max_tool_commands=24`、`max_wall_seconds=900`、`max_input_tokens=750000`、`max_output_tokens=20000`。工具数与时长由本次独立子进程组的流式执行器观察和停止；安装版 CLI 在历史事件中仅 `turn.completed` 报 token，因此输入/输出 token 当前只能事后验收，缓存输入包含在总输入，推理输出包含在输出，不重复相加。这不是账户周额度或账单保证。达到可观察限额标 `budget_exceeded`，不自动补跑。批次研究未来同样受显式限额。

入选结果沿原程序的行动日开盘×复权因子参考入口及第5/10/20日/20%收盘触达口径；落选与未决近邻单列 `candidate-outcomes.csv`，不计入推荐绩效分母。`summary.json` 只计显式合格前瞻决定，配对须双方同日合格；回放与诊断另列。端点与完整路径分开，未成熟不算失败，参考价格路径不等于成交或净收益。`comparison.csv`、`metrics.json`、`readiness.json` 按固定十日和指定评价截止版本化，原结果及 catalog 精确定位；`report.md` 只有未来人工批次研究成功后才会出现。

未来要真实配对，先由用户审查本轮回执并另行启动 Astra/xhigh 会话。按最终提交创建新 replay-id，核对同版输入和预算，才可有序运行 M0、M1；不能把旧 Sol M0 接到新 M1。一次配对仍不足以声称方法更准或生产采用。

见[数据地图](data-map.md)和根 README 总体图。
