# Timer任务推进变更地图 v1

**提议，未实现。** 代码基准为已导出的[`9c71783db10918ced219cb28669944dd7c3956b6`](https://github.com/melonthrower/regrow/tree/9c71783db10918ced219cb28669944dd7c3956b6)，下列仓库相对路径、函数和行锚均据该提交核对。该提交的遍历行为未因交接文档改变；真实受阻运行仍冻结978f537。配套[设计](TIMER_TASK_PROGRESS_DESIGN.md)。源代码变化后应出新地图，不沿用旧行号。

以下路径前缀均为`experiments/clock_manual_20260919/`。

| 路径、行锚与函数 | 当前行为 | 拟改动与直接接受例 |
| --- | --- | --- |
| `task_settlement.py:150` `set_next_action`；`:80` `completion_target` | 把next_action写成completion_action，动作选择与结算随后使用该覆盖目标 | 普通下一步建议不覆盖任务目标；保留建议的历史来源，动作选择参考当前图。0064之后目标仍为c0034输入，不变成c0037删除；身份拆分/滚动的独立合法修正不可被一并删除。 |
| `task_settlement.py:175` `settle_task`；`:63` `require_registration` | 按覆盖目标匹配后要求原任务产物，缺少时blocked | 准备效果只登记动作，原参数任务保持待推进；a0023返回设置页不以缺输入结果暂挂。真正目标动作的参数/入口/效果登记要求继续执行。 |
| `action_proposer.py:6` `render_work` | 使用completion_target构造任务目标，已有preparation_allowed | 始终披露原任务目标与当前准备进展；a0023之后正常选择输入字段，而非重复删除。无新增动作规划器。 |
| `result_updater.py:24` `build_update_request`；`遍历prompt/任务/任务动作登记.prompt:9,14` | next_action一方面用于改绑定，另一方面用于继续任务 | 统一为下一步推进建议，更新仍登记当前效果；准备不冒充原知识、缺参数也不等于准备失败。schema说明、提示、校验与历史投影需一起核对，禁止仅改文案。 |
| `discovery_step.py:82` `commit`（旧缺口处理`:167`） | 未被当次batch处理或未按旧名再次确认的候选继续保留 | 沿明确候选来源和已确认身份关系处理旧缺口；名称变化不强迫重复发现。仅名称/旧位置类似不能解除；保留原缺口历史。 |
| `region_tasks.py:53` `apply_plan`；`task_record_repair.py:5` `apply`；`traversal_scope.py:14` `record_only` | 普通清点沿用blocked；现有记录修订不能直接采用后来证据结清这类旧疑问；record_only现用于范围复核 | 在既有修订入口表达采用哪条新证据回答哪个旧问题，复用历史保留方式，不能冒用外跳排除policy。解决“图标用途”不伪造hover成功；仍缺参数的任务不得因同控件有点击记录而完成。具体最小字段接线需在实施时核对原生请求。 |
| `step_repair.py:147` `request`（字段枚举`:155`）；`repair_stages.py:303` `edit_record`（任务路由`:345`） | 修订请求枚举和路由只接已有任务修订操作，底层扩大能力不会自动使正常请求可达 | 把必要进度修订接到同一schema、完整证据上下文、路由和发布入口。以已经blocked且有a0022/a0023历史的原输入任务作接受例：保留任务定义及真实动作，明确解除错误目标覆盖/阻塞、恢复待推进；不能利用旧task_control能力任意改挂或直接写done。 |
| `task_prerequisites.py:26` `enroll`（门禁`:42`） | 先置任务blocked，再以同控件任意blocked阻止准备，可能命中任务自身 | 前置未满足不能禁止满足它的准备；hover无提示不禁用start点击。仅沿明确已登记的崩溃/禁止等限制阻止其他用途，不解析原因文字猜测范围；当前可操作性仍由原动作路径确认。覆盖自身blocked、其他用途blocked与真实限制的正反例。 |

这两份设计文件为新文件，无既有行号。实现时更新相应任务、更新、身份/发现、调度模块合同及月度日志；共享协议确实改变时才同步CURRENT_FRAMEWORK/Region对齐说明。

验证范围：聚焦目标/准备结算、条件用途与发现缺口测试仅为辅助；接受依赖完整真实记录生成的原生Luna请求/原答，经正常校验修订登记后检查实际目标、任务、知识及图片。保存帧0GUI与后续实机执行分开报告。当前尚未执行这些接受案例；本文不把建议登记为已实现能力。
