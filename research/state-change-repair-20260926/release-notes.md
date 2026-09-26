# 部署、版本与未发布状态

## 代码

| 项目 | 版本 |
|---|---|
| 初始基准 | ecb0eb6e3b3b9e9ca7b225cd3a0abd59954e52fe |
| 12项完整精确集合通过并首次部署 | 30686af8583c9dfb332a559ede542f19ba5e5c2d |
| omission别名适配，原T10定向通过 | 1b114c2ac78a30a957972cd59fc186d864d4d2a8 |
| 阻塞澄清双数组原样恢复，原T10定向通过 | c5d18af827ce0d6c1fb1b3f00b5be60e62e6ee5f |
| resolved别名适配，原T10定向通过；末次业务生产代码 | a464891bdcf0029915a2012bca088be921ab924c |

以上各提交均经工作分支推送、main快进合入、生产生效及远端ls-remote核对。真实生产根与受测工作区为同一本机最新有效目录；原20项用户修改/未跟踪内容保持，SHA不表示干净checkout。没有reset、clean、强推、升级依赖或修改调度。

本轮最后追加提交只含research/state-change-repair-20260926中的交付文档，生产HEAD与origin/main随之同步；具体最终SHA以该目录的提交及最终回执为准。相对a464891没有新增源码差异，不重复跑测试或业务。

## 业务和页面

- 四次原入口执行均退出2：前三次分别是omission、阻塞双数组、resolved解析阻断，已最小修复并通过原输出恢复；最后一次为真实CO-1未决与负责人合同阻断。
- 最后停止于2026-09-26 21:56:14，无运行中的本任务业务进程。完整失败回执、state、原问题及修改前后研究草稿均保留本地。
- 9月23日无正式trace、正式ledger/report、最终日报、公司介绍或A2历史页；本地A2仍显示9月22日。未运行后续日期，自动调度开关未改。
- 因未决业务不能发布，本轮没有执行publish_prism_a2.sh，没有9月23日站点提交或构建。
- 既有站点仓库仍为[aab89bbe16a830455692cc42878fd3cd2f2eff2c](https://github.com/ccrt26/prism/commit/aab89bbe16a830455692cc42878fd3cd2f2eff2c)，属于原9月22日发布，保留其未跟踪.DS_Store。
- 历史候选公网入口[Prism](https://prism.dafeirou1hao.top/)此前普通HTTP访问返回403，网页工具亦不可访问。未绕过浏览器限制或改安全设置；公网9月23日未核实，且本轮根本未发布，不能用旧构建成功替代。

## 恢复边界

原入口仍是tools/stock_ai.py run nightly --rerun-date 2026-09-24 --provider astra --no-fallback --recommendation-authoring-profile astra-files-v1。当前直接重按该命令不能解决CO-1；需要先处理负责人未决项合同及实际双方意见，不能删除unresolved或重置调用预算。本轮未对这一新范围作修改或追加业务调用。
