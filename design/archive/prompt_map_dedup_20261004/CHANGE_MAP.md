# 具体改动地图：已实现与有限验证

源码锚定提交（审查时已在本地提交；远端同步状态以交付核验为准） `39c2ee05f6a78f90b545bec9409dad850c528a11`：[源码提交](https://github.com/melonthrower/regrow/commit/39c2ee05f6a78f90b545bec9409dad850c528a11)。全部行号由该提交工作树AST核对；后续纯文档提交不改变源码。基线为7d48b3c49ea084f131368a0441af45598a26a5c2。无未实施提议，以下分别说明基线行为和已实现修改。新文件不给虚构的基线行号。

| 仓库路径、函数、当前行范围 | 基线行为 | 已实现修改 |
|---|---|---|
| [experiments/clock_manual_20260919/page_context.py::separate_map L315–L326](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/page_context.py#L315-L326) | 纠错用同对象条件丢弃整段原动态；后台地图未发 | 提取受控地图槽，原动态引用；保留其他正文及尾部 |
| [experiments/clock_manual_20260919/page_context.py::refresh L329–L390](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/page_context.py#L329-L390) | 旧地图/状态重绘 | 维护唯一地图，原任务同名引用，目标同观察同值状态省略 |
| [experiments/clock_manual_20260919/page_history.py::_handoff L150–L175](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/page_history.py#L150-L175) | 交接在地图外复述，原简化来源不足 | 核对动作/观察/结果原答后搬入事件；非同源保留 |
| [experiments/clock_manual_20260919/page_history.py::link_incoming L274–L288](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/page_history.py#L274-L288) | 已将同值结果/依据改为引用，目的/区块变化仍有重复 | 同动作同owner扩展目的/区块变化去重，并合并成单一动作历史引用 |
| [experiments/clock_manual_20260919/map_prompt.py::task_view L18–L30](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/map_prompt.py#L18-L30) | 新文件，基线无对应函数/行号 | 与原请求投影逐值相同的历史引用；完整任务卡取代同一任务定义副本 |
| [experiments/clock_manual_20260919/map_prompt.py::receipt L33–L45](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/map_prompt.py#L33-L45) | 新文件，基线无对应函数/行号 | 只去掉地图已有同值字段，原提案和独有回执保留 |
| [experiments/clock_manual_20260919/history_context.py::action_context L282–L302](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/history_context.py#L282-L302) | 长任务名重复，任务卡类型信息散落 | 任务定义一份，显式动作/类型/处理方式/覆盖任务；状态只写状态 |
| [experiments/clock_manual_20260919/region_tasks.py::render L310–L331](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/region_tasks.py#L310-L331) | 当前任务在清单重复长名 | 同owner同name引用本轮任务；异owner同名保持 |
| [experiments/clock_manual_20260919/repair_stages.py::context L186–L261](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/repair_stages.py#L186-L261) | 纠错重铺任务尝试及完整回执 | 调用共享只读引用，不改记录 |
| [experiments/clock_manual_20260919/step_repair.py::request L147–L221](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/step_repair.py#L147-L221) | 同失败对象分支删原动态 | 保留原上下文，地图放顶层一份 |
| [experiments/clock_manual_20260919/target_observation.py::render_handoff L50–L61](https://github.com/melonthrower/regrow/blob/39c2ee05f6a78f90b545bec9409dad850c528a11/experiments/clock_manual_20260919/target_observation.py#L50-L61) | 上步交接附加原始正文 | 同源事件引用，独有信息由地图承接 |
| experiments/clock_manual_20260919/遍历prompt/纠错/重复无进展.prompt L1–L6 | 允许不同位置一次尝试，未区分提案与实际执行 | 明确未发文字仍是失败尝试；同框换点/已有光标不是新依据；有据纠正仍允许 |

验收对应：

- `tests/test_prompt_map_dedup.py`（新文件）覆盖进入历史同值/异owner、状态同源/异源、跨页目标不丢。
- `tests/test_unified_map_prompt.py`（新文件）覆盖纠错唯一地图/刷新、尾部范围保留、交接来源、跨owner同名、完整任务定义及回执独有信息。另更新`tests/test_page_control_history.py`既有引用断言。
- 聚焦61项通过；一项相邻旧失败在基线复现，未计通过。命令与日志路径见本月changelog及交付verification。
- 实际正常框架保存帧最终采用v4/action、v4/update、v4/parameter、v5/repair，4HTTP/0GUI，原答经Runner绑定/登记或observe分支。v5只请求补图，harness在取图前停止，没有输入恢复或新观察证据。
- v2参数与v4纠错失败保留；原现场仍运行旧v2源并暂停遍历，3历史GUI没有被算作新版验收。无全门禁/跨应用/完整Clock结论。

设计正文：[DESIGN.md](DESIGN.md)。冻结源码与本提交的py/prompt内容一致；实际运行源与当前源分别保留于交付evidence和source，不混为同一部署。
