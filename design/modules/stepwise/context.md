# 地图与上下文

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

把已有图、动作和任务记录组织成各步骤输入；不创建执行事实。

## 输入、输出与边界

已提交图、当前观察与任务 → 当前树、来源关系、相关历史和实际发送正文。同一事实保持来源，历史不自动代表当前可操作。

主要接口：`page_context.build / attach / refresh；page_history；prompt_delivery.desktop_parts`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

正常发送由 `RecoveryRun.call` 在平台、范围与截图说明组装后调用 `history_disclosure.project`，统一排版普通与纠错上下文。动作事实由 `task_action_context.build → history_context.action_context → findings` 提供；保留 `known_findings` 证据字段。已移除无人调用的同名转接函数与旧的更新专用排版函数，相关保真断言归入现行发送投影测试。

## 源码与提示入口

- [page_context.py](../../../experiments/clock_manual_20260919/page_context.py)
- [page_history.py](../../../experiments/clock_manual_20260919/page_history.py)
- [map_prompt.py](../../../experiments/clock_manual_20260919/map_prompt.py)
- [history_context.py](../../../experiments/clock_manual_20260919/history_context.py)
- [history_disclosure.py](../../../experiments/clock_manual_20260919/history_disclosure.py)
- [task_action_context.py](../../../experiments/clock_manual_20260919/task_action_context.py)
- [task_attempt_context.py](../../../experiments/clock_manual_20260919/task_attempt_context.py)
- [target_observation.py](../../../experiments/clock_manual_20260919/target_observation.py)
- [prompt_delivery.py](../../../experiments/clock_manual_20260919/prompt_delivery.py)
- [render_region_context.py](../../../experiments/clock_manual_20260919/render_region_context.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [探索树阅读.prompt](../../../experiments/clock_manual_20260919/遍历prompt/历史上下文/探索树阅读.prompt)

历史正文主要由上述Python模块动态投影；同目录的其他早期提示不能因位置相邻就并入请求，按提示入口索引核对实际组装引用。

## 验证与未完成事项

地图投影和普通/纠错共用历史已有实现及有限保存帧验证；当前可见控件误报仍是开放问题。地图可读不等于身份正确。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#context)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。
