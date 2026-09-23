CLI命令版本为0.155.0；实际会话session_meta报告0.155.0-alpha.9.2，额度恢复前后新会话一致。使用本机HTTP假端点捕获请求后立即返回400，不向任何模型供应商转发；业务模型请求0次。捕获的tools为空数组。关闭列表与stock_ai.READER_DISABLED_FEATURES一致，strict-config、ignore-user-config、project_doc_max_bytes=0及禁用Skill同时生效。检查实际developer输入没有skills、memory、app-context、user_instructions标记；不公开系统提示原文。CLI预期exit=1（假端点拒绝），这不是一次成功模型运行。正式reader还必须取得每次实际Astra xhigh及上下文证据。


环境变量化的[离线探针](../scripts/reader_capability_probe.py)已经实际重跑，结果见[dd33捕获](reader-offline-capabilities-dd33.json)；两次实际stdout摘要见[历次探针](capability-probe-attempts.json)。本机假端点的/models返回404、/responses返回400均为预期，没有供应商转发。真实reader声明的工具集合不由业务rollout直接回报（offered_tools=null）；工具可用性证据来自同一CLI禁用配置的请求捕获，另逐次核对实际配置与活动。首次真实请求7的CLI警告误计与修正另有[完整记录](reader-warning-correction.md)，不能把那次原执行核验失败隐藏。
