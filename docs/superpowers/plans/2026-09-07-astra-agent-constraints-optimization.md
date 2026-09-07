# Astra 项目约束、复盘指令与插件边界一致性优化执行 Prompt

本 Prompt 是本次实施和唯一一次独立方案审查的完整执行依据，不是新的日常股票研究入口。

## 一、目标与验收标准

消除当前程序既有合同与 AGENTS、Skill、运行 Prompt、README 和当前架构说明之间已经确认的冲突，使 Astra 在用户已授权范围内直接完成项目任务，同时保持：

- 三路互斥复盘；
- 节点详评六项对账；
- 普通详评四项覆盖；
- 简评和详评正文唯一存放；
- 时点安全、证据边界和现有研究方法。

完成效果以以下证据验收：

1. 当前入口和说明不存在仍然生效的旧复盘指令；
2. 既有程序相关回归全部通过；
3. 修改后的 Skill 元数据校验通过；
4. 真实冻结材料、批准范例和合成边界测试分别按其能力证明对应事项；
5. 项目配置按官方合同回读，并准确区分“配置已被解析”“新任务运行时已停用”和“本轮上下文已加载”；
6. “A股助手每日研究”自动任务实际改为 `gpt-6-astra`，其余配置保持不变；
7. 不声称本次文字和配置调整已经提高收益，或证明 Astra 的长期输出全面优于 Sol。

## 二、本次范围

1. 只按实际冲突修改以下当前文件：

   - `AGENTS.md`
   - `ops/forward-selection-prompt.md`
   - `ops/forward-monitor-prompt.md`
   - `.agents/skills/orchestrating-stock-research/SKILL.md`
   - `.agents/skills/reviewing-stock-recommendations/SKILL.md`
   - `README.md`
   - `docs/architecture/current-v3-architecture.md`
   - `docs/architecture/forward-monitoring-v1.md`
   - `tools/guanlan-prism/README.md`

2. 若跨文件搜索确认四个专业 Skill或当前 V4 合同仍有“同一顶层会话等于独立上下文盲审”“提交前看不到彼此结果”等不符合实际运行方式的当前指令，只将其改为：

   > 各专业 Skill 只以自己负责的事实和证据边界作答，不把其他专业 Skill 的判断当作本视角证据或背书。

   不改变研究方法、证据上限、补证次数、输出字段、发动机合同或最终取舍规则。历史文档不批量改写。

3. 项目级 Superpowers 限制只使用官方支持的本地项目配置和仓库规则：

   - 项目当前没有 `.codex/config.toml`；
   - 先确认项目处于 trusted 状态；
   - 可创建项目本地 `.codex/config.toml`；
   - 可在 `.gitignore` 中精确加入 `/.codex/config.toml`，确保含本机绝对 Skill 路径的配置不进入 Git；
   - 不忽略整个 `.codex/` 目录；
   - 不把个人绝对路径写入任何被跟踪文件。

4. 项目配置优先写入官方支持的插件开关，并通过严格配置读取确认解析值：

   ```toml
   [plugins."superpowers@openai-curated-remote"]
   enabled = false
   ```

   CLI 临时覆盖键必须使用正确的未额外套引号形式：

   ```text
   plugins.superpowers@openai-curated-remote.enabled=false
   ```

   不把错误 CLI 键的结果当作插件能力事实。

5. 若插件列表、当前桌面上下文或实际加载结果不能证明插件级停用，则在同一个被精确忽略的项目配置中，为本机已安装的 Superpowers 6.3.0 下列十四个 Skill 分别加入官方 `[[skills.config]]`：

   ```toml
   [[skills.config]]
   path = "<本机 Superpowers skills 根目录>/<skill-name>"
   enabled = false
   ```

   十四个 Skill 为：

   - `brainstorming`
   - `dispatching-parallel-agents`
   - `executing-plans`
   - `finishing-a-development-branch`
   - `receiving-code-review`
   - `requesting-code-review`
   - `subagent-driven-development`
   - `systematic-debugging`
   - `test-driven-development`
   - `using-git-worktrees`
   - `using-superpowers`
   - `verification-before-completion`
   - `writing-plans`
   - `writing-skills`

   每个 `path` 必须是本机实际存在、直接包含 `SKILL.md` 的绝对目录。逐项通过官方严格配置读取核对 `enabled=false`。当前 `skills/list` 基线本来就可能不显示远程 Superpowers，因此“列表里没有”不能单独证明本次停用生效。

6. 已在本轮上下文中加载的 Skill 不能靠写配置从当前上下文抹除。若新任务运行时停用仍无法直接证明，只报告“项目配置已被解析，需后续新任务重新加载验证”，不得写成“Superpowers 已从桌面运行时彻底移除”。

7. 若项目级配置无法被支持的配置读取正确解析，则不保留错误配置，不改全局配置，不停用或卸载托管插件，不修改缓存、sandbox、approval 或账户权限；只实施 AGENTS 中的项目工作流优先级和插件适用范围规则，并明确报告限制。

8. 全部仓库验证完成后，使用 Codex `automation_update` 更新现有“A股助手每日研究”：

   - `model` 改为 `gpt-6-astra`；
   - `reasoningEffort` 保持 `xhigh`；
   - 完整保留现有名称、Prompt、状态、项目、执行环境、计划时间和通知设置。

   “A股助手次晨安全提醒”继续使用 Sol。禁止手工修改自动任务 TOML，不创建新任务，不主动触发正式研究。

9. 只调整与本次旧指令冲突直接相关的现有测试；可以增加必要的回归断言，但不引入评分器、提示词解析器、通用规则管理框架或新的生产逻辑。

## 三、必须保留

- `formation_date`、`action_date`、带时区 `as_of`、`available_at <= as_of`、历史回放安全、18:45运行、18:30截止和休市行为。
- 一个总控加四个专业 Skill 的选股体系；复盘 Skill 只综合已正式推荐记录，不参与候选发现或选择。
- 0—5只和空名单；不评分、不补位、不增加研究证据轮次，不改变选股、条件事件或停止跟踪标准。
- 节点股全部做节点详评；非节点最多8只普通详评；其余简评；同股同日只进入一类；同股各 episode 分别对账。
- 节点详评六项全部覆盖：

  1. 原期待与担心；
  2. 截至当日的阶段路径；
  3. 已兑现、已削弱与仍未知；
  4. 当前最合理解释及其边界；
  5. 公司侧状态；
  6. 目标余程与预设验证条件。

- 普通详评四项全部覆盖：

  1. 为什么今天选它详评；
  2. 原推荐理由变强还是变弱，具体伤在哪一环；
  3. 距20%目标的余程、现实判断和主要障碍；
  4. 下一项会改变当前评价的观察点。

- 某项确实无内容时明确写“该日尚无此项可对”，不能省略或补猜。
- `daily-formal-reviews-<date>.json` 保存全部结构化判断及仅 `brief` 类正文；节点详评和普通详评正文只保存在 `monitor-report` 的 `ForwardEpisodeReviewV1.current_review`。
- AI 按既有文风基准逐篇撰写正文；禁止程序模板生成、回填或改写正式正文；历史补写继续小批量逐批自检。
- D20 完整结案只写入现有 `final_twenty_day_review.overall_review` 并只展示一次；D21—D30 不改写前20日结果。
- 历史读取兼容、数据 schema、哈希、存储、程序算法和本地页面行为。
- 产业研究 A/B/C/D 方法和 ChatGPT/Codex 交接。
- 研究补证次数和每个视角证据上限。
- 既有用户认可范例；不得为了统一措辞把范例改成模板腔。
- 不修改 `src/` 生产逻辑，不迁移或重写事实仓、正式归档、日志和已有产物。
- 不调用正式 `prepare`、`record`、`record-trace` 或 `record-daily-formal-reviews`，不联网补数，不连接券商或发布服务。
- 不删除用户未跟踪的 `tmp/`。
- 不新增定时任务、服务、数据库、报告版本、schema、校验和文件或外部副作用。
- 不安装或卸载插件，不修改账户权限，不提交或推送。

## 四、精确执行步骤

### A. 基线、唯一审查与范围控制

1. 读取修改前的 `AGENTS.md`、`docs/architecture/current-v3-architecture.md`、本 Prompt，以及计划直接涉及的当前 Prompt、Skill、README、程序合同和测试。
2. 记录 Git HEAD、分支和用户已有改动。当前已知工作区包含未跟踪的本 Prompt 和用户 `tmp/`；不得覆盖、清理或纳入任务。
3. 本 Prompt 保存为：

   ```text
   docs/superpowers/plans/2026-09-07-astra-agent-constraints-optimization.md
   ```

4. 实施前恰好启动一个 `gpt-5.6-sol`、`xhigh`、独立上下文的审查子智能体。它只读审查目标一致性、完整性、可执行性、矛盾、遗漏和过度工程化，不实施、不改文件、不启动任何子智能体，也不执行本 Prompt。
5. 审查者只返回以下之一：

   - `通过`
   - `通过（以修订版为准）`并给出完整可执行的修订 Prompt
   - `阻塞`并说明无法自行消除的真实障碍

6. 主智能体直接采用通过版本，不再启动第二次方案审查，也不在实施后要求同一审查者复审。
7. 若实际实施需要引入本 Prompt 未覆盖的高风险变更，停止该范围的实施并在最终汇报中说明，不扩大目标、不另启审查。
8. 本次审查始终依据修改前 AGENTS，不能通过先改规则绕过审查。

### B. 同步三路复盘和唯一正文规则

1. 删除或修正当前入口中的下列旧指令：

   - “先为全部记录写简评，再写详评”；
   - “所有详评合计最多8只”；
   - “日报最多8只股票”；
   - 新 snapshot 已不再提供的 `detailed_review_stock_count`；
   - “`daily-formal-reviews` 保存全部每日简评”；
   - “所有正文都从日评账本读取”；
   - 详评再次生成隐藏简评或两份公开正文；
   - 总控直接用 `DailyFormalReviewV1.current_review` 渲染详评；
   - snapshot 的所有 `daily_review_episode_ids` 都必须生成简评。

2. 历史代码兼容分支、历史报告版本和历史设计文档中的同名字段不因搜索命中而删除。程序中旧 snapshot 的兼容读取必须保留。

3. 所有当前入口统一为以下顺序：

   ```text
   全部 episode 的结构化判断草稿
   → 按股票确定节点详评 K
   → 从非节点股票中选择普通详评 D（0—8只）
   → 其余为简评 B
   → 三类分别写唯一正文
   → 核对事实来源、episode、口径和结构化结论
   → 先保存日评账本
   → 后保存详评报告
   ```

4. `DailyFormalReviewV1` 三类都必须完整填写结构化判断。正文位置固定为：

   - `brief`：账本 `DailyFormalReviewV1.current_review`；
   - `checkpoint_detail`：账本正文为空，正文写入报告；
   - `regular_detail`：账本正文为空，正文写入报告。

5. 保存前若详评写作改变了观点、主要解释、薄弱环节、方向或跟踪决定，先同步尚未保存的结构化草稿，再统一保存；不得在账本保存后另造不一致结论。

6. 简评规则：

   - 只写当日重要增量；
   - 无实质变化通常1—3句；
   - 有变化或事件日通常2—5句；
   - 600字符硬上限；
   - “一句话足够”“只用最少决定性事实”“说完即停”只约束简评和普通行文取舍，不能用于省略节点六项或普通详评四项。

7. 节点详评规则：

   - D1、D3、D5、D10、D20及待补D20全部进入节点详评；
   - 六项信息缺一不可；
   - 节点只改变侧重，不减少项目；
   - 合并成句可以成立，不要求固定标题、字数或事实数量；
   - 每项按“事实—含义—边界”说明；
   - 详评围绕当日主要问题组织，不能写成六个机械字段的朗读。

8. 普通详评规则：

   - 只从非节点股票中选择；
   - 每日0—8只；
   - 优先级和程序既有合同保持不变；
   - 四项信息缺一不可；
   - 没有实质新增但因轮换入选时，逐环检查原推荐链条；无法形成新增结论就明确说明，不硬凑行情播报。

9. D20 的六项覆盖以最终展示的该股票完整节点复盘为单位：

   - 当日 `ForwardEpisodeReviewV1.current_review` 只写当天新增判断和理解结案所需内容；
   - `final_twenty_day_review.overall_review` 完整串起前20日判断、结果、主要成功或错误和经验；
   - 状态行、当日详评、外层展望与最终结案合起来必须覆盖节点六项；
   - 同一事实不在当日正文和最终结案重复展开；
   - 完整结案只公开一次，不新增字段。

10. 上一轮详评只使用程序已经恢复的本 episode 历史正文；不建立新缓存，不借用同股其他 episode，不用旧日报自由文本作为新事实。

11. 将“说人话优先于可追溯”统一改为：

   > 事实、时点、口径和来源必须准确且可追溯；在此基础上使用普通中文表达。普通表达不能覆盖或降低事实边界。

   观点与事实分开；范例只指导表达，不替代来源证据。

### C. 精简项目执行和插件适用范围

1. 在 AGENTS 中明确：

   - 用户明确指令优先于 Skill 指南；
   - 本项目股票研究、产业研究、只读评审、开发修改和本地展示分别使用各自现有入口；
   - 多步且会产生交付物或持久变更的任务先给最小充分执行提示；
   - 已授权范围内自主完成；
   - 只有关键输入、权限或未授权重大外部影响会实质改变结果时才询问用户。

2. 高风险对象限定为：

   - 时点安全；
   - 正式选股或复盘合同；
   - 数据 schema、存储或迁移；
   - 自动任务；
   - 正式数据删除、覆盖；
   - 不可逆或重大外部动作。

   普通源文件的正常编辑不因为底层采用覆盖写入就自动成为高风险。

3. 保留高风险任务恰好一次独立方案审查。未来未被用户指定模型的审查子智能体默认继承主智能体可用的模型和推理配置；用户明确指定时遵从指定。无法启动时如实报告，不能伪称已审查。方案通过不能代替实现验证。

4. 明确项目插件边界：

   - Superpowers 不自动接管本项目入口或增加额外规划、子智能体、工作树、测试轮次和收尾流程；只有用户明确点名时才使用。
   - Sites 只适用于明确的网站建设或发布任务；当前 monitor、静态 HTML 和 Prism 是本地冻结结果展示。
   - Supabase 不属于当前项目架构，除非用户另行明确批准新设计。
   - 用户说“深入复盘”不自动触发 Deep Research。
   - 文档、表格、演示和模板 Skill 只在实际交付对应文件时使用。
   - 视觉、浏览器、GitHub 和外部 App 能力按具体任务需要调用，不增加股票研究步骤或外部副作用。

5. 项目配置只限制 Superpowers。保留其他插件、连接器和技能配置，不修改全局配置、托管插件缓存或账户权限。

### D. 更新当前架构和展示说明

1. 当前架构文档和 README 准确说明：

   - 所有需复盘的正式 episode 都生成结构化判断；
   - 三路互斥的范围和数量；
   - 节点六项与普通详评四项；
   - `record-daily-formal-reviews` 的先后顺序；
   - 简评正文与详评正文各自唯一位置；
   - `reviewing-stock-recommendations` 只做跨时间综合；
   - 四个专业 Skill 的 review 阶段只提供各自负责事实；
   - 总控只检查记录、证据与结论一致性。

2. 修正“用户日报最多8只”等已过时说明。节点详评数量不受普通详评8只上限约束。

3. 准确区分当前展示能力：

   - monitor Markdown 已实现；
   - `tools/render_monitor_web.py` 的本地静态 HTML 已实现；
   - `tools/render_prism_web.py` 调用现有 Prism `render_html()` 的本地集成已实现；
   - `tools/update_monitor_web.py` 的本地更新入口已实现；
   - 云端发布、Supabase 和交易仍不属于当前架构。

4. Prism README 区分：

   - 原始成品包和示例材料；
   - 当前仓库已经存在的真实集成入口；
   - 示例快照不是实时事实或新一轮推荐；
   - 当前应使用仓库内真实存在的渲染命令和目录。

   不生成不存在的构建、测试、安装或发布指令，不广泛改写原包历史说明。

### E. 验证、冻结材料核对与自动任务更新

1. 修改前记录已经存在的冲突，至少包括：

   - `forward-selection-prompt.md` 仍要求先为全部 episode 写简评；
   - 它仍读取新 snapshot 不再提供的 `detailed_review_stock_count`；
   - 它仍称账本保存全部每日简评、报告最多8只详评；
   - 总控 Skill 仍把所有复盘正文指向 `DailyFormalReviewV1.current_review`；
   - 复盘 Skill 输出段仍要求先写日常简评再独立展开详评；
   - 部分当前说明仍把同会话专业视角说成真正的独立盲审；
   - README 对本地 Web/Prism 集成状态或旧报告标题存在过时说明。

2. 当前七组相关测试基线为286项通过。修改后重新运行这七个文件，不沿用修改前结果：

   ```text
   tests/test_forward_monitor.py
   tests/test_forward_review_context.py
   tests/test_forward_monitor_prompt.py
   tests/test_v4_operational_prompts.py
   tests/test_render_monitor_web.py
   tests/test_render_prism_web.py
   tests/test_update_monitor_web.py
   ```

3. 对每个修改过的 Skill 使用本机现有 `quick_validate.py` 逐一校验前置元数据和目录结构。

4. 运行 `git diff --check`。

5. 测试调整只反映最终合同：

   - 保留程序三路互斥、节点全覆盖、普通详评不超过8只、正文位置、D20冻结和历史兼容的既有断言；
   - 将仍断言旧 Prompt 文案、失效字段或双正文路径的测试改为新合同；
   - 必要时增加“旧字段不再出现在当前入口”“详评账本正文为空”“节点数不占普通详评名额”的回归；
   - 不为自然语言语义增加关键词 Gate、评分器或通用 Prompt 解析器。

6. 冻结材料验收必须分层：

   - 对实际存在的真实冻结记录，只读核对它能够证明的节点、普通详评或简评分类、正文位置、来源和事实边界；
   - 对批准范例，核对节点六项、普通详评四项和表达标准是否保留；
   - 对真实样本当前缺失的 D20最终结论和同股多 episode 详评，使用既有合成测试验证程序边界，并明确说明没有真实案例回放证据；
   - 2026-09-04部分历史正文含“套牢盘”或把单日回落当因果证明等旧表达，只能作为本次规则需要排除的反例，不能作为新语义质量合格证据；
   - 不追溯改写任何正式归档；
   - 不把关键词测试通过写成语义质量证明。

7. 搜索当前有效入口中的以下旧内容并逐项人工判断：

   - `detailed_review_stock_count`
   - 全部记录先写简评
   - 详评总数最多8只
   - 所有正文从账本读取
   - 详评同时保存简评正文
   - 提交前不读取彼此结论
   - 说人话优先于可追溯

   历史兼容代码和历史文档命中不要求删除。

8. 配置验证按以下层级分别记录：

   - TOML 语法和严格配置读取是否成功；
   - 插件键是否回读为 `enabled=false`；
   - 十四个 `skills.config` 是否逐项回读为 `enabled=false`；
   - `.codex/config.toml` 是否被精确忽略；
   - 当前插件列表是否仍显示远程插件；
   - 当前或新加载任务是否能够证明 Skill 已停用。

   只能按实际达到的层级报告。当前上下文已经列出的 Skill 不能写成已被本轮配置移除。

9. 仓库验收全部完成后：

   - 读取现有“A股助手每日研究”完整自动任务配置；
   - 使用 `automation_update` 只将模型改为 `gpt-6-astra`；
   - 保持 `reasoningEffort=xhigh`；
   - 回读并逐字段比较名称、Prompt、状态、项目、执行环境、计划时间和通知设置；
   - 确认“A股助手次晨安全提醒”仍为 Sol；
   - 若更新或回读失败，保留原任务配置并报告失败，不手工写 TOML 兜底。

10. 最终汇报必须清楚列出：

   - 唯一一次方案审查结论；
   - 实际修改文件和每类冲突的最终效果；
   - 七组测试、Skill 校验和 `git diff --check` 的结果；
   - 真实冻结材料、批准范例与合成测试分别证明了什么；
   - 历史正文未追溯改写；
   - 每日研究自动任务的实际模型和保持不变的字段；
   - Superpowers 达到的是配置解析、逐 Skill 项目限制还是已验证的新任务运行时停用；
   - 尚未取得的证据和剩余限制；
   - 已实施和未实施事项。

不得声称无人值守生产质量已得到长期验证。
