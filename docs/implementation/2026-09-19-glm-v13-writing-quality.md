# V1.3 写作质量优化实施摘要（脱敏）

日期：2026-09-19｜分支：fix/recommendation-authoring-20260918｜生成版本：ff308b7（此前核查基线 61b3199，V1.2 生成版本 64a8acd）
性质：经用户授权的有限写作质量优化。全文替换作者 Prompt、审稿 Prompt 与通用写作教学（不再是旧文追加）；AUTHOR/REVIEW 合同升 v3（CLARIFICATION 保持 v2）。不修改 build_article_packet、数据字段、审稿枚举、complete()、选股 Skill、复盘、D20、schema、WEB、launchd、长期模型路由或知识库原件。

## 替换文本的实质变化

- 作者合同 v3：读者任务先行（按什么价格、参与还是等待、为何接受最大代价、什么变化改变看法）；先辨认研究主张与取舍再组织正文；价格障碍与目标的关系属于参与理由，不藏进结尾；首稿与修改轮拥有同等编辑权（重排/合并/删除重复及不影响判断的正确数字）；以事实自然表达局限，不背免责声明；无每数一次/字数/段数/价格段落等机械规则。
- 审稿合同 v3：复述含“为何接受代价/为何等待”且不得由包代补；按意思判冗余，影响读者理解的重复可 blocking（expression 可阻塞，需两处真实原句定位）；压缩后的顺口说法同样核对对象/单位/窗口/基准；加“不是预测”不使前面的无依据预测变正确；issue_checks 对删并修复引用当前保留的核心解释，不要求补回被删冗余。
- 教学 v3：以两篇认可范文的论证动作为教学（解释证据如何改变取舍），明确不复制其结论、价位、段数；编辑不是逐句加补丁；交付前只看正文不看自我声明。

## 修改轮旧冲突的消除

V1.2 合同中“修改轮只按审稿问题修改表达与解释，保留原文正确的事实、数字与条件”与编辑权条款互相牵制；v3 全文替换后该措辞已不存在（grep 核对为 0），新标准是“留下的陈述准确、决定性内容不丢失”，不是无条件保留数字。

## 测试与核验结果

- 07 结构测试：修复前仅合同常量断言失败（v2），其余 6 项既有保护通过；替换后 7/7 通过。
- 相关 11 个测试文件 634 项全部通过；V1.2 外部五反例 5/5 通过；旧文本断言零调整（test_v4_operational_prompts 只断言教学文件存在；其余使用合成 Prompt）。
- 全量 1615 通过/1 跳过/2 失败（prism 两用例，与 V1.2 基线同例同因：worktree 缺 local_warehouse 交易日历）。
- 真实审稿挑战（GLM-5.3-flash，provider=glm、fallback=False、provider_order=["glm"]，作者/审稿隔离新会话）：旧六例 6/6 通过；新八例 7/8 通过——W01 窗口偷换、W02 相对强弱写成绝对、W03 成交额写成成交量、W05 严重语义重复（expression+blocking）、W06 取舍解释缺失、W07 必要重复与合理未知不误杀、W08 真实研究缺口交研究，均按预期识别。
- **W04（ATR 夹带天数推断）未通过**：审稿 ready=true、意见数组全空，且其复述认可了违规句（“需要多天上涨才可能走到”）。每例仅一次完整调用序列，未重跑试探，未改夹具/expected/模型。
- 按执行单停止条件停于复核点后，**用户明确豁免 W04 残余风险并授权启动六篇**（决定记录于 evidence/commands.jsonl `user-decision-w04-waiver`）。六篇固定回放（飞凯×3、中天/中材/海星各1，输入由 06 脚本固定、packet 逐字节一致）全部 ready 且执行核验 verified=True，四组退出码全为 0。
- 六篇运行亮点：中材被审稿抓出 2 条 metric_basis 阻塞（滚动窗口口径误写为当日占比；38.49% 分母错挂“五日涨幅”），作者按指示修订后复审通过——审稿端语义筛查在真实文章上兑现；海星经 4 条澄清（含 1 条 resolved_added 补件）后修订通过。飞凯三篇独立重复均单轮过审。
- W04 类句子横向核对：六篇中 4 篇含波幅/目标距离句，全部正确表述为尺度换算并否认天数/概率，无由波动推时间的推断——作者端未兑现该残余风险；审稿端缺口作为已知项如实保留。
- 逐篇阅读复核与飞凯 repeat-1 逐字原文见复核包 04/05 文件；本轮终态停在待 ChatGPT/用户阅读复核，生产未启用。

## 接入证据

- 生产与试写共用同一入口：trial.run→run_article_cycle 使用 tools/recommendation_pipeline.py 的 author_prompt/review_prompt，其读取 CODE_ROOT 的 ops/ 两份 v3 全文；writing_material.teaching 由 prepare 阶段读取 CODE_ROOT 的 selection-writing-calibration.md（input-binding.json 哈希绑定）。tests/test_recommendation_v13_contract.py 断言真实函数的合同常量与 payload 结构；test_recommendation_authoring 的缓存/循环测试在替换文本下全部通过，证明没有第二套试验专用 Prompt。

## 生产与边界

- production-before/after 零差异（关键文件哈希、main 54e27c9、无新增正式 state、知识库四件原件哈希不变）。
- 异常报告（非本轮造成）：ai-nightly 自当日 09:54—17:54 之间不在 launchd gui domain（其余 5 任务正常）；本轮无任何 launchctl 操作，未代为恢复。
- 未满足项：W04 审稿识别为唯一阻断项；六篇阅读复核未执行；prism 环境失败非本轮事项。停在待 ChatGPT/用户复核。
