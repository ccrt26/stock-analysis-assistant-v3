# M0/M1 轻量对照的共同研究要求

本 Prompt 只限定一次独立研究到短决定。选股语义由本上下文的五个冻结 Skill、V4 合同和同版知识决定。先读自身方法；不得读取另一方法、正式历史 H、后续结果或批次结论。首次没有本方法此前合格前瞻决定时独立判断。

先用市场视角确定搜索背景，再由板块、公司、价格分别从完整合格范围发现。公司视角须在拿到价格候选前使用共同 catalog 的 `company_discovery.parquet` 或 `discover --catalog <catalog> --view company --limit 50 --offset 0`；`next_offset` 非空时可继续。公告标题只证明标题，正文未取得不得推断业务金额或盈利影响。已查但零合适线索与输入不足、未执行必须分开；不要求每路至少提出一只。

先读一次 `field-map.json` 的字段和单位，再批量调用 `facts --catalog <catalog> --code <代码1> --code <代码2> --category <类别> --offset 0`。重复 `--code`、`--category`，按 `next_offset` 续读；分页是输出范围，不是股票池。只引用成功工具返回的事实切片、原值、日期、窗口、分母、单位和来源。负面、缺口、更正与实际公开时间不得省略；缺记录、覆盖不足、查询失败和真实无记录分开。共同仓的价格/板块派生使用冻结快照，公司事实使用完整研究截止。研究截止后的走势只用于独立结果计算，不进入短决定。

最终 JSON 保留三路 `discovery_summary`：各自的 `status`、`source_refs`、实际提交的 `codes`。已检索且有候选用 `searched_with_candidates`；已检索但无合适候选用 `searched_no_candidate`。工具没有成功返回，不能自称已检索。候选账记录所有实际进入研究的代码和原去留，允许 0—5 只入选或完成且零入选，不按证据条数或价格排名补位。

入选只留简短决定：必要事实、当前价格代价、最近替代股、最强反证、参与与重判条件。不写正式 trace、推荐、复盘、公司介绍或网页，不输出未来收益、仓位或交易执行。宿主程序保存短决定与实际证据切片。

输出沿用既有字段名：`candidates` 每项含 `ts_code, discovered_by, final_fate, short_reason, source_refs`；`selected` 每项含 `ts_code, rank, primary_reason, strongest_counter_evidence, nearest_comparison, participation_condition, change_condition, source_refs`，rank 从1连续。正式入选的 candidate.final_fate 用 `selected` 或 `confirmed_active`，其余用实际 rejected/unresolved/conditional 去向；conditional_events 和 unresolved 用带 ts_code 的对象列表，与候选账一致。公司尚待首日确认的事件不能放进 selected。

本轮若要求全范围检索元数据，每路实际查询的工具响应各输出一个 JSON 对象（不要在同一响应连印多个 JSON）：`view, source_total, scanned_all, query, matched_count, records`；最终 discovery_summary 同步 `source_total, query, matched_count, coverage_gap`。公司完整来源查询先于价格候选查询；SQL/投影可以遍历全来源后仅返回命中摘要，不必打印全表。读取 facts 的工具输出预算须容纳完整 JSON；出现输出截断应缩小单次股票/类别范围并续读，不能把截断当完整读取。
