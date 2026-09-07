# 观澜 · 光场 PRISM：当前仓库接入

本目录保存已接入股票助手的前端成品源码。当前入口是仓库根目录的 `tools/render_prism_web.py`：复用 `tools/render_monitor_web.py` 的冻结数据，再调用本目录 `tools/build.py` 中的 `render_html()`，生成独立单文件离线页面。

## 从真实归档生成页面

在股票助手仓库根目录运行：

```bash
./.venv/bin/python tools/render_prism_web.py --help
./.venv/bin/python tools/render_prism_web.py
```

默认读取最新已有 snapshot 和对应已保存报告，输出到归档目录下的 `prism-report-<date>.html`。可以用 `--date YYYY-MM-DD` 选择已有归档日期，用 `--out` 指定输出文件，用 `--monitor-dir` 指定验证副本目录。命令会生成页面；只检查参数时使用 `--help`。

Prism 不覆盖原有 monitor HTML 或 `index.html`，也不增加定时任务。`tools/update_monitor_web.py` 仍是既有 monitor 页面本地更新入口，不能把它描述为已经自动更新全部 Prism 页面。

## 数据与正文边界

- 页面呈现已经冻结的事实和 AI 正文，不新增荐股、不修改理由、不接入实时行情。
- 节点详评、普通详评、简评按源 `review_kind` 展示；详评正文来自报告，简评正文来自账本。同股不同推荐日期保留独立记录。
- 原文中即使存在措辞或判断问题，也不由前端静默改写；应该在研究流程中核对来源与判断。
- 程序排版与数据内联不等于程序创作复盘正文；本地页面生成不代表云端发布授权。

## 当前源码

| 路径 | 用途 |
|---|---|
| `src/shell.html` | 页面外壳 |
| `src/base.css`、`src/prism.css` | 基础布局与视觉，按此顺序加载 |
| `src/app.js` | 页面、筛选、图表和交互 |
| `src/core.js` | 确定性展示计算 |
| `src/effects.js` | 独立装饰动效 |
| `tools/build.py` | 接收适配数据并生成 HTML |
| `docs/03-数据接口与口径.md` | 原包数据接口及示例口径说明，实际输入由仓库适配器提供 |

修改源码后，通过仓库 `tools/render_prism_web.py` 重新生成页面，不只修改生成产物。

## 验证

在仓库根目录运行现有相关测试：

```bash
./.venv/bin/python -m pytest tests/test_render_prism_web.py tests/test_render_monitor_web.py tests/test_update_monitor_web.py -q
```

这些测试检查数据适配、正文来源、三类展示和本地更新边界；通过它们不等于已经完成浏览器视觉或所有平台交互验收。实际页面调整按任务需要使用浏览器验证。

## 原始交付资料

本目录 `docs/` 保留原前端成品包的设计、接入和验收说明。原包中“交给 GLM5.3”、示例快照、固定日期、截图和解压目录命令属于历史交付背景，不是当前任务指令或当前事实。当前集成已完成，不需要重新交接给指定模型；仓库不保证原包的 `data/snapshot.json`、`dist/`、`previews/`、`tests/` 等交付产物全部存在，应使用上面的真实仓库入口。

页面不附带字体文件，也不依赖 CDN、在线图片、图标或图表服务。
