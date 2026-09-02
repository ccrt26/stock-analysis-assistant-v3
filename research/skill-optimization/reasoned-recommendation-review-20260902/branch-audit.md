# 远端分支与哈希边界审计

## 审计基线

- 审计时 `origin/main`：`94955b91e1108948eef4df7b653c08c98e052b66`。
- 判断方法：逐个运行 `git merge-base --is-ancestor origin/<branch> origin/main`。
- 处理原则：只有完整进入 `main` 的旧开发分支才可在本轮功能进入 `main` 后普通删除；任何检查失败或引用变化的分支都保留。

## 远端分支

| 分支名 | 分支 HEAD | 是否已进入 main | 处理决定 |
|---|---|---|---|
| `chatgpt/final-engine-contract-v4` | `8a1c29dccb2dcc8c6a02e44ce7f01aac58f0330e` | 是 | 本轮功能进入 `main` 后重新检查，仍为祖先才删除远端引用 |
| `chatgpt/v4-operational-prompt-cleanup` | `bd40e930cc451230442c60087e1671f43365fbb6` | 是 | 本轮功能进入 `main` 后重新检查，仍为祖先才删除远端引用 |
| `codex/detailed-recommendation-explanation-20260901` | `36636cc9f80a1b568a6926d9395cf82f8ab58887` | 是 | 本轮功能进入 `main` 后重新检查，仍为祖先才删除远端引用 |
| `codex/five-skill-selection-logic-optimization-20260901` | `05e1788f8457f00eccbafd0b55a276a6acf18fc9` | 是 | 本轮功能进入 `main` 后重新检查，仍为祖先才删除远端引用 |
| `codex/plain-language-recommendation-review-20260902` | `94955b91e1108948eef4df7b653c08c98e052b66` | 是 | 本轮功能进入 `main` 后重新检查，仍为祖先才删除远端引用 |
| `codex/skill-optimization-dataset-20260831` | `e03677c6b57b0288adf3c24caffa3f31c6ddbfac` | 是 | 本轮功能进入 `main` 后重新检查，仍为祖先才删除远端引用 |
| `feat/industry-research-workflow-v2` | `70b9f7838551a2e61a2c10cb7698e74c35303a7c` | 是 | 本轮功能进入 `main` 后重新检查，仍为祖先才删除远端引用 |
| `fix/liquid-cooling-data-gap-v1` | `5525c7d37b9bccf3423d75fc9c0a9ac8ed0f0cc3` | 是 | 本轮功能进入 `main` 后重新检查，仍为祖先才删除远端引用 |
| `main` | `94955b91e1108948eef4df7b653c08c98e052b66` | 是 | 保留，最终必须与本轮功能提交一致 |
| `research/ai-liquid-cooling-2026h2` | `388e93632a184190b989bc454af0402128955be4` | 否 | 独立研究进行中，无条件保留；不合并、不删除、不改写 |

本轮功能分支 `codex/reasoned-recommendation-review-20260902` 在本次审计时尚未推送。它在完整测试通过并快进进入 `main` 后，仍须重新执行祖先检查，成功后才删除远端引用。

## 哈希现状与处理边界

### Git 提交 SHA

用于固定本次准确基线、比较改动以及确认功能分支、本地 `main`、远端 `main` 和实际运行目录版本一致。本轮只在开始、合并和最终核验时通过 Git 命令读取，不为普通文档另外生成校验和。

### 数据仓库内部哈希

`content_hash`、`file_sha256`、`business_key_hash`、`payload_hash` 和 `input_manifest_hash` 已用于事实与派生数据去重、修订识别、文件一致性、输入对应和中断恢复。它们属于数据层核心能力，本轮不删除、不改造。

### 冻结数据包校验和

现有 `manifest.json`、`checksums.sha256` 及验证样本中的 SHA 用于冻结一组多文件研究数据或验证输入，继续保留。本轮不修改现有冻结样本，也不为 Prompt、Skill、日报、复盘、说明文档或分支收口新增哈希文件。
