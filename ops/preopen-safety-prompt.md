# 08:45 次晨安全提醒

这是对昨晚冻结名单的安全提醒，不是正式研究或开发任务。不得重新选股，不得增加或替换股票，不得调整昨晚顺序，不得改写推荐理由、复盘、research trace 或 Forward CSV。不得使用集合竞价或盘中价格。

在当前项目根目录运行一次：

```bash
./.venv/bin/python -m stock_analyzer.ops.preopen_safety prepare
```

完整读取返回的 JSON 及其 `output_path` 指定的结果。仅检查 `watched_stocks`，其中 `conditional_event` 必须标明不是正式推荐，不得升级成推荐。不创建新任务，不启动新 Codex 进程。

- `no_action_day`：今天休市，简短说明无需安全检查。
- `no_formal_trace`：没有找到供今天参考的昨晚正式V4轨迹，明确说明不能进行名单检查，不自行重建。
- `no_new_changes`：只回复“没有发现需要改变昨晚参与条件的新情况”。
- `changes_found`：停牌股票明确提示“暂缓参与”。只针对新增公告调用 `researching-company-events` Skill，完整读取该 Skill；对照昨晚该股原参与条件，解释是否已失效或需要谨慎，不输出新的完整股票报告。
- `data_limited`：明确哪项公告或停牌检查未完成，不得说“没有变化”。若已取得停牌或重要公告，仍说明已知影响。

信息边界只能是 `selection_as_of < available_at <= checked_at`。停牌结果只是 `checked_at` 时的当前观察，不冒充昨晚已知事实，不写入正式停牌事实分区。公告正文仅沿返回的官方来源按需读取，并核对公开时间，不扫新股票、不运行市场、板块、价格及总控的完整选股流程。

最终回复只给安全结论、受影响名单及必要限制，不追加 Git、工作区、测试或临时文件摘要。
