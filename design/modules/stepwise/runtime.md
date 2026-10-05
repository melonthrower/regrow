# 运行、环境与进度

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

选择源码与运行，维护传输、预算、冻结副本和进度。

## 输入、输出与边界

运行配置、源码引用、设备/模型 → 完整run目录和阶段驱动。预算保留在框架账本，不塞入Luna prompt。

主要接口：`launch_traversal；run_source；run_progress_session；desktop_transport.DesktopRun`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

公共发送顺序在 `model_transport.ModelTransport.call`：平台 → 前置条件 → 环境范围 → 运行范围 → 截图尺寸 → 历史投影 → schema必填兼容 → 进度/预算检查 → 请求落盘与计数 → 发送及保存原答。桌面先经 `DesktopRun.call/prepare_request`，Android与恢复共用这一个发送实现。

正常会话通过所选源码的新子进程运行；不支持在一个动作进程中混用两份源码。冻结器按顶层Python文件收集源码，新增职责文件沿同一规则进入新冻结源。旧run不随整理自动部署。`render_region_context`中的两份.snapshot.py仅是入口审计摘录，不是自足运行源码；复现使用run_manifest指定的冻结源。

## 源码与提示入口

- [model_transport.py](../../../experiments/clock_manual_20260919/model_transport.py)

- [launch_traversal.py](../../../experiments/clock_manual_20260919/launch_traversal.py)
- [app_launcher.py](../../../experiments/clock_manual_20260919/app_launcher.py)
- [run_source.py](../../../experiments/clock_manual_20260919/run_source.py)
- [run_progress_session.py](../../../experiments/clock_manual_20260919/run_progress_session.py)
- [debug_loop.py](../../../experiments/clock_manual_20260919/debug_loop.py)
- [debug_candidate.py](../../../experiments/clock_manual_20260919/debug_candidate.py)
- [debug_progress.py](../../../experiments/clock_manual_20260919/debug_progress.py)
- [desktop_transport.py](../../../experiments/clock_manual_20260919/desktop_transport.py)
- [desktop_capture.py](../../../experiments/clock_manual_20260919/desktop_capture.py)
- [desktop_lifecycle.py](../../../experiments/clock_manual_20260919/desktop_lifecycle.py)
- [browser_hub.py](../../../experiments/clock_manual_20260919/browser_hub.py)
- [progress.py](../../../experiments/clock_manual_20260919/progress.py)
- [progress_details.py](../../../experiments/clock_manual_20260919/progress_details.py)
- [progress_window.py](../../../experiments/clock_manual_20260919/progress_window.py)
- [exploration_summary.py](../../../experiments/clock_manual_20260919/exploration_summary.py)
- [exploration_loop.py](../../../experiments/clock_manual_20260919/exploration_loop.py)
- [call_model_once.py](../../../experiments/clock_manual_20260919/call_model_once.py)
- [assemble.py](../../../experiments/clock_manual_20260919/assemble.py)
- [replay_stepwise_baseline.py](../../../experiments/clock_manual_20260919/replay_stepwise_baseline.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [平台](../../../experiments/clock_manual_20260919/遍历prompt/平台)
- [通用](../../../experiments/clock_manual_20260919/遍历prompt/通用)

## 验证与未完成事项

浏览器入口仍为启动遍历.sh；assemble和replay_stepwise_baseline为离线诊断，不是第二条默认实机路径。恢复现场前读SERVER_HANDOFF并核对run_manifest源码。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#runtime)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。

## 空闲后知识阶段
正常会话在GUI无可执行工作后调用finalize_knowledge，HTTP并入session账本，GUI预算为0。没有后台线程、独立队列或CLI开关；网络中断记录interrupted，不伪报knowledge_complete。新冻结源统一使用本批三步与恢复规则，旧冻结源不热替换。
