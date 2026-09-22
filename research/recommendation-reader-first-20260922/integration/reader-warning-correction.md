# 首次真实reader的执行证据误计

请求7（A1）真实CLI会话的可见事件包含`item.completed / error`，文本为：`Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable features.code_mode_host and install codex-code-mode-host.` 原证据计数把所有非agent_message/reasoning的item视作工具活动，误计1次；原协议没有任何工具调用。关闭能力的配置与离线tools=[]证明没有变化。

最小修正仅将CLI的error消息排除在工具计数之外；真实协议调用和未知item类型仍然阻塞。新增四个场景，修正前1失败3通过，修正后受影响199项通过。原阅读输出为ready=false，指出“未持续向下跌破36.97元”时段不清，不因这次解析修正改成通过。

原失败回执、状态和请求7原证据保留。`scripts/recover_reader_receipt.py`只对原会话、原输入和原可见JSON重新验证、归档，不调用模型、不改审稿判断。A1只补尚未运行的事实核对。原作者与reader均复用真实交付，不重抽。

为停止后续阶段受同一误计影响，在请求8（A2作者）进行中中断固定runner。这个中断也保留在总台账；只允许原会话续写，续写实际请求另计。未修改样本、作者/审稿Prompt、阅读标准或研究含义。先前两个代码版本及所有实际结果留存，计划升为v1.2-parser-only；同一64次总上限不清零。
