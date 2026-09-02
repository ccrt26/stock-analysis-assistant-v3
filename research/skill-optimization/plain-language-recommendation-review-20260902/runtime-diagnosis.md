# 每日任务运行入口诊断

## 部署前事实

- Codex Automation：`A股助手每日研究`（ID `a`），状态为 `ACTIVE`。
- Saved Project：`/Users/ccrt/Documents/股票分析助手`，它是指向 `/Users/ccrt/股票分析助手` 的符号链接。
- Automation 提示内实际执行 `cd "/Users/ccrt/股票分析助手"`，因此每日任务的实际运行根目录是 `/Users/ccrt/股票分析助手`。
- 运行分支：`main`。
- 运行 HEAD：`52bb9c5dda22bab979fdf3936de813e1c704cb36`。
- 工作区状态：干净。
- 运行 HEAD 不包含基线提交 `36636cc9f80a1b568a6926d9395cf82f8ab58887`；相反，运行 HEAD 是该基线的祖先，落后 6 个提交。
- 每日任务会读取 `ops/forward-selection-prompt.md` 和 `ops/forward-monitor-prompt.md`，但它读取的是运行目录 `main` 上的旧版本，不是 `36636cc9f80a1b568a6926d9395cf82f8ab58887` 中已经优化过的版本。

## 旧格式的直接原因

旧格式不是因为存在第二个 LaunchAgent，也不是因为 Automation 指向了另一份独立仓库。直接原因是唯一的每日 Automation 固定进入 `/Users/ccrt/股票分析助手` 的 `main` 分支，而该分支仍停在 `52bb9c5dda22bab979fdf3936de813e1c704cb36`，没有包含此前 6 个已完成但未部署到运行分支的提交。因此任务虽然读取了正确文件名，却读到了旧提示与旧 Markdown 渲染实现，继续输出“为什么偏偏是现在”“之前研究过的股票走势复盘”“和当时最接近的备选相比”等旧格式。

## 部署后事实

待功能分支完成、测试通过并按附件要求部署后补充。
