# 真实基线

生产 main、远端 main 与隔离工作树起点：`61f0ebbd719845e44aae3fb5449f0b74b15bf1ad`，已经实际查询远端。未回退。旧作者工作树 `3b1bcc9` 无未提交改动且落后，不用作基线。

生产工作目录与用户给出的 Documents 入口为同一个符号链接目标。原 main 未提交的数据财务修复、研究健康检查、架构说明及 A2 显示编辑均留原处；本轮分支不夹带这些改动，不切换运行版本。生产 launchd 指向原 main，nightly 18:45 已 disabled且未加载，未发现当前 stock_ai 业务进程。WEB 服务指向生产归档；本轮不写该位置。

Python：沿用生产已安装的 Python 3.12.14 / pytest 9.1.1，无依赖升级。基线五文件测试 [baseline.log](tests/baseline.log)：113 passed；命令与退出码见 [commands.jsonl](tests/commands.jsonl)。首次默认 exec 沙箱因项目符号链接报 UnsupportedOperation，未执行任何命令；后续显式最小授权运行成功，此环境异常不算业务试验。

现行代码证据：`complete` 在独立复盘之后先 `_author_articles`，再 `check_current_opinions`；`stage_spec` 给 author/review同时提供 packet、handoff、答复和范文。已有有限修订、阶段恢复、owner定向处理、D20保护、same_stock_material与原样保存/装配均复用。

样本按实际身份与原件关系核对。飞凯复杂新版：300398.SZ / formation=2026-09-18 / action=2026-09-21 / as_of=2026-09-20T18:30:00+08:00 / reference=38.35。未拿9月17日37.12元稿替代新版研究。其最终研究包/负责人处理/WEB相关全文存在，样本完整性仍逐项核对；留出仅据元数据选取，不用正文调提示。
