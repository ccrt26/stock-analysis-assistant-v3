# Task 10 报告：静态报告生成

## RED
- 运行命令：`python3 -m pytest /Users/ccrt/股票分析助手/.worktrees/codex/v3-mvp/tests/test_report_generation.py -v`
- 结果：导入失败（`ModuleNotFoundError: No module named 'stock_analyzer.reports'`），符合“先写测试，后实现”要求。

## GREEN
- 运行命令：`python3 -m pytest /Users/ccrt/股票分析助手/.worktrees/codex/v3-mvp/tests/test_report_generation.py -v`
- 结果：`1 passed in 0.03s`
- 运行命令：`python3 -m pytest -v`
- 结果：`29 passed in 0.14s`

## 变更文件
- `src/stock_analyzer/reports/__init__.py`
- `src/stock_analyzer/reports/generator.py`
- `src/stock_analyzer/reports/templates/index.html.j2`
- `src/stock_analyzer/reports/templates/stock.html.j2`
- `tests/test_report_generation.py`

## 自查结果
- `render_reports` 会写入固定入口 `index.html` 到 `output_dir`。
- 同步写入 `output_dir/data/latest.json`，包含 `recommendations` 与 `focus_states`。
- 生成内容是中文页面，且测试覆盖了敏感字段不外泄（`SUPABASE_SERVICE_ROLE_KEY`、`TUSHARE_TOKEN`）以及推荐名称字段注入。
- 为兼容当前本地 Python3.9 环境缺失 `jinja2` 的情况，函数采用运行时降级：
  - 有 `jinja2` 时使用模板引擎渲染；
  - 无 `jinja2` 时使用等价的本地安全回退渲染；
  - 不影响现有功能约束与测试结论。
