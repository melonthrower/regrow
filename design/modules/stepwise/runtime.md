# 运行、环境与进度

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

选择源码与运行，维护传输、预算、冻结副本和进度。

## 多应用只读浏览器投影

`python tools/stepwise_dashboard.py <config.json>` 接入同一冻结源码的多个已有run。配置包含 `source`、`source_hash`、`repository`，以及 `apps[{key,label,run,sessions,limits}]`；`sessions`下为原生 `session-*/session.json` 和 `round-*/budget.json`，`limits`为本批累计上限，配置保存在对应实验目录。可用 `port` 固定本地端口，未提供时自动分配；启动打印本地浏览器地址。

Python入口负责读取，配套HTML负责布局。复用 `progress.snapshot`、`region_graph.project/asset`；只监听本地地址，拒绝POST，没有启动、暂停或GUI控制入口。区块图和进度必须来自同一提交快照；刷新冲突暂留旧数据并明确重试。运行中未结算轮次的原预算纳入计数一次，不按页面刷新重新计账。`root-review.json`只用于显示已检查小步、暂缓或保留问题继续，不改变调度；`accepted=false, continue=true`与质量接受分开。调用/操作按本批累计上限显示，不把一次原生处理称作40调用批次。

左侧为最近框架真实观察及时间，非连续投屏；右侧将当前可交互包含结构与所有历史区块按归属展开，来路不当包含父级。无控件绑定的任务仍显示在区块下，任务清点不完整单列。切换应用立即清空上一应用的显示，新应用断流不能沿用旧应用数据；同一应用断流明确保留上次数据。图片裁图为登记时身份证据。刷新不调用Luna、不取设备新图、不修改原run。

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

## 连续批次与剩余预算
原生auto会话一次连续推进，人工仅会话结束后审查区块、任务、逐动作调用和异常。每小步最多6次HTTP调用和6条GUI命令，正常调用与纠错合计，但run_session把min(6,剩余额度)交给run_step，不要求尾段还剩6 HTTP/GUI；实际命令数仍由发送入口强制计账。GUI完整命令序列不足则不开始该动作；HTTP不足或修订额度耗尽保留pending。空闲知识登记同样使用HTTP余量，GUI为0。浏览器root-review只展示整批审查，不是调度门槛；“已检查批次”按会话计，旧单小步会话亦仍按其保存会话计。

HTTP不足2次时，已消费调用的小步以ready_next_round续接本会话余量；未消费调用的新小步以budget_limit停止，避免空尾段循环。待登记证据保留，不能据此重投已执行GUI。


## 收尾后重新调度
auto在scope_idle/region_complete后执行一次有界、0GUI的finalize_knowledge，再回到原run_step。若该步仍为空闲即停止，不能仅因pending、knowledge_complete或新快照重复整理；正常动作/发现/清点等推进后，后续空闲可再次整理。每段知识阶段单独保存knowledge、knowledge-0002等目录，HTTP只并入当前session一次。暂停、预算、异常、review_pending和其他受阻结果保留原停止边界。跨会话预算仍由已有续接入口从旧账扣除，不因新session重置本批100额度。
