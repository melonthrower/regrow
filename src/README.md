# 当前逐步框架

业务实现只有三部分：`regrow/recognition` 识别对象，`regrow/traversal` 推进任务，`regrow/records` 保存并查询已接受记录。提示和平台/模型在 `regrow/prompts`、`regrow/runtime`；展示与启动在 `regrow/tools`。

从 `regrow/traversal/run_task_step.py` 的 `_run_step` 读主循环。它先处理未登记动作，再按需观察/提出任务，选择与执行一步，然后登记结果。

`python src step --help` 查看单步入口。复制整个 src 为冻结目录后，命令为 `python <冻结目录> session ...`，目录中必须同时包含 `__main__.py` 和 regrow 包。

记录读写/事务/发布只有 `regrow/records/snapshots.py` 一份实现；正常输出校验和纠错使用相同登记路径。旧 StepwiseFlow 状态机及其转发 API 不在当前源码中。
