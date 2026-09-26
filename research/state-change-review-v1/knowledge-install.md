# 知识库实际安装与供料

本机按 `local_archive/knowledge-vault-path.txt` 指向的真实 K，安装于 `K/10_方法与范文/复盘范文/状态跟踪/`。该目录原先不存在，本次仅新建此子目录并落入三文件；没有搬迁全库或覆盖已有认可范文。

| 文件 | UTF-8 字节 | 仓库副本 |
| --- | ---: | --- |
| `00_阅读指南.md` | 3,422 | 与包文件逐字节一致 |
| `01_状态变化复盘_范文与注意事项.md` | 5,388 | 与包文件逐字节一致 |
| `02_简单复盘_范文与注意事项.md` | 3,724 | 与包文件逐字节一致 |

仓库发布副本在 `.agents/skills/reviewing-stock-recommendations/references/state-change/`。两篇范文保留 `status: teaching_example`、`example_only: true`，不视为已认可实盘，也不把示例数字写入规则。

实际调用 `build_state_change_input` 读取已存快照后，输入中的三项 `knowledge` 均包含可读全文，`source` 均指向 K 的安装目录，未从仓库与知识库拼接两套标准；Obsidian 不可读时才整体回退到仓库同版副本。未启动真实复盘会话，因此首次模型是否照该指南写作须由下一次正常任务观察。
