# Task 9 报告：存储仓库接口与 Supabase 写入边界

## RED（任务边界最小实现缺失）

执行命令：
`python3 -m pytest tests/test_repositories.py -v`

结果：
- 已收集到 `0` 个用例，出现 `1` 个错误：
  - `ImportError while importing test module 'tests/test_repositories.py'`
  - `ModuleNotFoundError: No module named 'stock_analyzer.storage.repositories'`
- 结论：按简报先行写测试，未实现仓库模块时行为符合预期。

## GREEN（实现后）

执行命令：
`python3 -m pytest tests/test_repositories.py -v`

结果：
- `1 passed in 0.05s`
- 用例：
  - `test_in_memory_repository_saves_daily_outputs`

执行命令：
`python3 -m pytest -v`

结果：
- 全量用例通过：`25 passed in 0.12s`

## 修改文件
- `src/stock_analyzer/storage/supabase_client.py`（新增）
- `src/stock_analyzer/storage/repositories.py`（新增）
- `src/stock_analyzer/storage/__init__.py`（新增）
- `tests/test_repositories.py`（新增）

## 自查结果
- 已建立 `AnalysisRepository` 接口协议，声明了四个保存入口方法：`save_recommendations`、`save_focus_states`、`save_evidence_packages`、`save_evaluation_tasks`。
- `InMemoryAnalysisRepository` 内部使用列表累积保存每类对象，测试可直接访问 `recommendations/focus_states/evidence_packages/evaluation_tasks` 验证持久化行为。
- `create_supabase_client(config)` 仅当 `config.supabase_url` 与 `config.supabase_service_role_key` 都存在时才返回 `create_client(...)`，否则抛出明确 `ValueError`，遵循“服务端边界写入”约束。
- 本任务测试仅覆盖内存仓库边界，未引入任何真实 Supabase 写入或网络调用。

## 审查修复（Important）

### 新增失败路径测试

执行命令：
`python3 -m pytest tests/test_repositories.py -v`

结果：
- `4 passed in 0.05s`
- 覆盖用例：
  - `test_in_memory_repository_saves_daily_outputs`
  - `test_create_supabase_client_requires_url_and_service_role_key[env0]`
  - `test_create_supabase_client_requires_url_and_service_role_key[env1]`
  - `test_create_supabase_client_requires_url_and_service_role_key[env2]`
- 断言在三种配置缺失场景下（两者都缺、仅缺 URL、仅缺服务端密钥）均抛出 `ValueError`，且错误文本同时包含 `SUPABASE_URL` 与 `SUPABASE_SERVICE_ROLE_KEY`。

### 兼容性修正

执行命令：
`python3 -m pytest -v`

结果：
- 全量用例通过：`28 passed in 0.13s`
- 为避免本地环境 `supabase` 为 namespace 包导致的导入错误（`ModuleNotFoundError: No module named 'supabase'` 风格），将 `create_supabase_client` 的 `create_client` 导入改为函数内延迟导入，并将返回类型改为 `Any`，在 `if TYPE_CHECKING` 中保留类型兼容性。
