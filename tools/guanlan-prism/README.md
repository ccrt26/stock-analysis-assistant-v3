# 观澜 · A2 主用展示

A2 是日常主用的本地收盘研究页面。保留已确认的黑白界面、量价图表、总览、全部观察、观点时间线、星图和浏览器收藏；个股详情可阅读走势、完整复盘、当初的推荐理由及推荐时点公司资料。

## 入口与更新

- 主用：`http://127.0.0.1:8940/style-preview/prism-a2.html`。路径沿用，不因转正更换书签。
- 备用：`http://127.0.0.1:8940/prism.html`。只保留停更内容，页面标明最后数据日期。
- 新日期页：`local_archive/forward_monitor/prism-a2-report-<date>.html`。
- 旧 `prism-report-*` 不重建、不删除。旧 `src/` 与 `tools/build.py` 保留作备用源码参考，不是日常同步入口。

在仓库根目录，逐字使用已完成研究的三个时间字段：

```bash
./.venv/bin/python tools/render_prism_web.py \
  --date <formation_date> --action-date <action_date> --as-of <selection_as_of>
```

现有晚间任务在研究归档后执行同一命令，公司介绍补齐后按原规则再次同步；不新增任务。`tools/build_preview_a2.py` 的命令入口也转交同一同步命令，不再支持从备用 HTML 制作新版。可用 `--no-publish --out <临时路径.html>` 生成验收文件；备用、旧日期页和固定入口不能作为 `--out` 目标。

程序直接复用正式归档的共享数据整理与归档完整性检查。个股及指数补充日线只取报告日之前、且报告截止前已可见的本地事实；与冻结收盘冲突时失败。全部资源及补充数据内嵌在 HTML，不请求实时行情，也不依赖外部 JSON。每个页面原子替换，失败保留旧首页，旧日期补跑不会覆盖较新首页。备用页不参与同步和就绪判断。

## 阅读口径

完整复盘与原推荐原文保留，不由模型改写；标题首段只展示一次。当前参与意见与 20 日固定结案分别展示。选择历史日期时图表截断至该日，显示该日实际保存的复盘；没有正文就说明没有，不把最近一篇冒充当天结论。这是按当前冻结数据回看，不是重新获取原时点快照。

公司资料按该次推荐身份展示，所选日期不改变其研究截止；注明实际编写时间、来源与资料限制。缺项如实提示。收藏继续使用原 A2 浏览器存储，随网页更新保留，仅在本浏览器有效。

## 源码与验证

- `concept-a/overview-a2-shell.html`：主用壳层、导航及星图。
- `concept-a/a2/`：量价数据适配、图表、交互及样式。
- `tools/build_preview_a2.py`：A2 纯渲染、补充日线及兼容命令入口。
- 仓库 `tools/render_prism_web.py`：唯一正式同步入口。

在仓库根目录运行：

```bash
./.venv/bin/python -m pytest -q tests/test_render_prism_web.py tests/test_prism_a2_preview.py tests/test_stock_ai.py tests/test_forward_monitor_prompt.py
./.venv/bin/python tests/check_prism_a2_browser.py --url http://127.0.0.1:8940/style-preview/prism-a2.html --out /tmp/prism-a2-check
```

浏览器检查需要已安装 Playwright Chromium。单元测试使用临时目录和独立样例，不读取或写入正式归档。真实页面检查核对内嵌快照及补充价量，并检查详情阅读和桌面/手机交互。实施方案见仓库 `docs/implementation/2026-09-13-prism-a2-primary.md`。
