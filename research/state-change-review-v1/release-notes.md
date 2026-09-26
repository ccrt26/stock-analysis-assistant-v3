# 部署与限制

实施基于本机及远端相同的 `9dcc0e9eba297cbca8b702ec7b86ab0dd5912bdd`，保留该版本已有的推荐成稿修复。新策略只绑定新建夜间任务；旧无策略档案和旧已开始任务继续 legacy 语义。生产安装后，以本目录后续部署记录及 `git rev-parse main` 核对实际代码版本。

本轮 18 个精确离线假模型节点通过，真实业务模型会话 0 次。没有执行历史 50 股回放、A/B、model verify、nightly 冒烟、生产页面生成或晚间任务启动。测试证明保存与确定性展示接线，首次真实复盘写作、实际调用量、耗时及投资判断质量必须在下一次正常运行后观察。

Obsidian 三份教学资料已经按本机知识库指针安装并被单快照供料函数选中。教学场景是虚构，未被标成用户认可实盘。当前未启用的 LaunchAgent 维持未启用、未加载状态；既有 Astra/profile/禁备用命令不变，仅生产本机配置增加 `monitor_review_policy=state-change-v1`。

## 实际生产更新

受测并合入的实现提交为 `fbbee9c`（完整 SHA 可用 `git rev-parse fbbee9c` 读取），从原 main `9dcc0e9` 快进合入。工作分支 `fix/state-change-review-v1` 已推送。生产代码目录已在 main 上；此文件所在的后续提交仅记录部署事实，不更改受测程序。

实际 `.stock-ai.local.json` 已增加 `monitor_review_policy=state-change-v1`；设置前后 `recommendation_authoring_profile=astra-files-v1`，其余配置值逐项相同。夜间 LaunchAgent 安装命令仍为 `run nightly --scheduled --provider astra --no-fallback --recommendation-authoring-profile astra-files-v1`，未加载、未启动，原禁用状态未改变。用户原有未提交文件均保留，本次没有生成生产 HTML 或覆盖旧文章。下一次正常新任务会按本机配置绑定新策略；已开始旧任务保持旧策略。

部署后复核当前 A2 页面源码时，发现同股列表原先固定采用最早记录。随后把新策略的列表代表改为最新仍跟踪的 episode；没有活跃记录时取最新已结束 episode，并按保存的结束原因展示。适配仅在下次生成 state-change-v1 页面时应用，未修改用户尚未提交的 A2 页面源码，也未在本轮生成生产 HTML。修订沿用相同 18 个精确离线节点，仍全部通过。
