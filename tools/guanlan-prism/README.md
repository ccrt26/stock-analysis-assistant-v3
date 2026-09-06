# 观澜 · 光场 PRISM V2

**这是一套已经能运行的前端成品，不是一份需要重新设计的方案。**

本版继承用户认可的「观澜 AFTERCLOSE」功能与信息布局，升级配色、玻璃面板、光场、边缘反射、文字层级与交互动效。原行情数组、参考价、推荐理由、复盘正文均保留。交付日期：2026-09-06。

## 先看成品

打开 `dist/guanlan-prism.html`。它是单文件版，CSS、JavaScript、图标、数据都已经包含在里面，不需要安装软件包、启动后端或调用模型。

修改源码时打开根目录 `index.html`。它与单文件版来自同一套源码，但 CSS 和 JavaScript 分开加载。整个目录一起保留，不要只拿走 index.html。

页面右上角的星光按钮控制装饰动效；太阳按钮切换明暗；搜索支持 ⌘/Ctrl K。系统开启“减少动态效果”时，光场会静止，星光按钮会说明这一状态。这不影响主动点击“回放观察过程”。

## 交给 GLM5.3

**把整个压缩包提供给 GLM5.3，并要求先读根目录 `GLM5.3_执行指令.md`。不要只提供截图。**

需要它做的是“移植现成前端 + 对接原有数据”，不是“参考此设计重新写一版”。HTML 结构、两份 CSS 的加载顺序、Canvas 效果、SVG 图表、交互代码都已经给齐。

## 目录导航

| 路径 | 用途 |
|---|---|
| `dist/guanlan-prism.html` | 直接体验的单文件成品，也是视觉与交互基准 |
| `index.html` | 拆分源码的预览入口，由构建脚本生成 |
| `src/shell.html` | 页面外壳：品牌、导航、顶栏、弹窗、内容容器 |
| `src/base.css` | 继承的布局与组件基础；不要省略 |
| `src/prism.css` | V2 完整视觉、响应式与动效样式；必须在 base.css 后加载 |
| `src/app.js` | 页面生成、导航、搜索、筛选、收藏、图表、时间轴与导出 |
| `src/core.js` | 确定性展示计算；不产生新选股或研究结论 |
| `src/effects.js` | 独立光场与鼠标高光，不读取股票数据 |
| `data/snapshot.json` | 原示例快照，35 条独立观察记录 |
| `assets/brand.svg` | 独立的品牌矢量原稿；运行版已内联同样图形 |
| `tools/build.py` | 标准库构建脚本，也提供 `render_html()` 接入函数 |
| `docs/` | 视觉、交互、数据、接入、验收与改动说明 |
| `previews/` | 本代码在浏览器中实际渲染的多页面效果图 |
| `tests/` | 可运行检查、截图脚本与本次执行结果 |

## 源码修改后重新构建

需要 Python 3.11 或更高版本；运行成品 HTML 不需要 Python。

```bash
# 在解压后的 guanlan-prism-v2 目录中运行
python3 tools/build.py
```

这会同步重建 `dist/guanlan-prism.html` 和 `index.html`。**只修改 src 中的源文件，不要只改 dist，否则下一次构建会把改动覆盖。**

接入兼容的真实快照时：

```bash
python3 tools/build.py --data /实际路径/新快照.json --out /实际路径/新的观察报告.html
```

`--data` 模式默认使用输入记录的顺序作为展示顺序，不把本例中的固定股票当成新一轮推荐。它不修改输入文件，也不修改包内原快照。字段合同见 `docs/03-数据接口与口径.md`。

## 检查与截图

仅测试需要 Node（运行内置 node:test）和 Python Playwright；运行页面不需要 Node、不需要 npm install。

```bash
python3 -m pip install -r requirements-test.txt
python3 -m playwright install chromium
python3 tests/run_all.py
python3 tests/capture.py
```

测试默认寻找 `chromium` 可执行文件；找不到时使用 Playwright 的 Chromium。也可以通过 `CHROMIUM_PATH` 指定现有浏览器路径。

在本机检查真正的文件打开与跨刷新存储：

```bash
python3 tests/prism_browser_test.py --file
```

本次受管理浏览器阻止 `file://` 导航，因此交付前使用“将完整 HTML 装入 Chromium 页面”的方式验证渲染与交互，**未把本机双击、跨刷新存储或 Safari 测试写成已经完成**。详细证据与限制见 `docs/05-验收与已知限制.md`。

## 本版范围

这是展示层，不是新的荐股系统。没有访问你的本地事实仓、没有接入新的实时行情、没有修改 GitHub 仓库。行情快照截至 2026-09-04，原快照截止为 2026-09-06 18:30（上海时间）。视图里的涨跌不是账户收益。原文与数组有不一致时，图表用数组，正文保留原文。

本包不附带任何字体文件，也没有 CDN、在线图片、在线图标或在线图表库依赖。
