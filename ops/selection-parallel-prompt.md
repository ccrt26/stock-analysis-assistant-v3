# M0/M1 轻量对照的共同研究要求

本 Prompt 只限定一次独立研究到短决定。选股语义由本方法冻结文件（compact 执行视图或一次提供的冻结正文）、V4 合同和同版知识决定。已提供的正文不重复用工具读取；不读取另一方法、正式历史 H、后续结果或批次结论。

先用市场视角确定搜索背景，再由板块、公司、价格分别从完整合格范围发现。公司视角须在拿到价格候选前完成独立发现：用 `discover --request`（compact）或 `discover --view company`（legacy 分页）查询共同 catalog 的 company 视图/索引；请求先覆盖完整来源再分页，`next_offset` 非空可续页。公告标题只证明标题，正文未取得不得推断业务金额或盈利影响。已查但零合适线索与输入不足、未执行必须分开；不要求每路至少提出一只。

字段、单位、表名与来源总数已在 field-map 或 runtime-index 一次给出，不再探查 schema 或打印目录结构。个股事实用 `facts --profile decision`（compact，按完整行分页、投影保留窗口/行业层级/分母/负面/限制/缺口，`--part` 按上一页 `next_part` 续读）或 legacy `facts --offset`。历史逐日 OHLC、无关财务列默认不重复打印，但按字段/日期可精确回读。负面、缺口、更正与实际公开时间不得省略；缺记录、覆盖不足、查询失败和真实无记录分开。共同仓的价格/板块派生使用冻结快照，公司事实使用完整研究截止。研究截止后的走势只用于独立结果计算，不进入短决定。

知识按 ID 定向读取（`knowledge --context <本方法上下文> --id <ID>`），启动材料已含必要条目；不打印整个 registry 或验证面板。官方原件用 `evidence --catalog <catalog> --context <本方法上下文> --request <请求文件>`：先 locate 取真实页段定位，再 read 完整页段；决定去留的条款必须实际读到，不能把下载或 receipt 存在当已读。引用沿用 `official:<evidence_id>`。

最终 JSON 保留三路 `discovery_summary`：各自的 `status`、`source_refs`、实际提交的 `codes`。已检索且有候选用 `searched_with_candidates`；已检索但无合适候选用 `searched_no_candidate`。工具没有成功返回，不能自称已检索。候选账记录所有实际进入研究的代码和原去留，允许 0—5 只入选或完成且零入选，不按证据条数或价格排名补位。

入选只留简短决定：必要事实、当前价格代价、最近替代股、最强反证、参与与重判条件。不写正式 trace、推荐、复盘、公司介绍或网页，不输出未来收益、仓位或交易执行。宿主程序保存短决定与实际证据切片。

输出沿用既有字段名：`candidates` 每项含 `ts_code, discovered_by, final_fate, short_reason, source_refs`；`selected` 每项含 `ts_code, rank, primary_reason, strongest_counter_evidence, nearest_comparison, participation_condition, change_condition, source_refs`，rank 从1连续。正式入选的 candidate.final_fate 用 `selected` 或 `confirmed_active`，其余用实际 rejected/unresolved/conditional 去向；conditional_events 和 unresolved 用带 ts_code 的对象列表，与候选账一致。公司尚待首日确认的事件不能放进 selected。

全范围检索元数据由程序回执给出：`discover --request` 的每路响应含 `view, source_total, searched_total, matched_count, returned_count, next_offset, coverage_gap`；最终 discovery_summary 同步 `source_total, query, matched_count, coverage_gap`，数值取自回执，不手填。公司完整来源查询先于价格候选查询。价格可从完整 universe 左连接价格表遍历全 U，缺口明确列出；不允许先取小样再筛选。整条 stdout 按预算装页：同请求多查询共享预算，未返回行的查询响应给出可执行的 `next_offset` 续读；超长行按固定分片计划以 `oversized_rows` 存根表示，`next_offset` 已越过本页表示的全部行，行内容经 `--part <part_id>#N` 逐段续读，非法片段号会被拒绝。

事实读取的工具输出按页返回完整 JSON，每页为最终打印的 stdout 尺寸所限；`next_part`/`next_offset` 非空时续读，不把截断当完整读取，不因分页遗漏负面或缺口。原文读取保持最初请求范围：`next_part.next_request` 原样放入新请求，仅 `start_offset` 前进，`cursor.exhausted` 只在整个原范围返回后为真；`returned_spans` 携带原文绝对偏移与本页响应偏移（不再重复正文），采用 `official_evidence` 的 `adopted_pages_and_clauses` 可附 `source_char_start/source_char_end` 精确位置，缺省时程序只在引文唯一时推导。同一次工具可依次完成多路查询并输出一个 JSON（如 `{"discoveries":[...各路回执...]}`）。预算不足时如实失败，不删除必要核实步骤来宣称完成；可用 `--usage-file` 附带剩余预算摘要。中断恢复复用已保存查询与输出，不重复已失效路线。
