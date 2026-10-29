# 当前代码地图

源码根为 `src/regrow/`。下列行号来自当前源码 AST；原文件去向见 [迁移表](../../THREE_PART_MIGRATION.json)。

| 职责 | 唯一实现 | 行号 |
|---|---|---|
| 主循环；先结算，再按需工作 | [traversal/run_task_step.py](../../../src/regrow/traversal/run_task_step.py) `_run_step` | 31–199 |
| 发现请求和身份候选 | [recognition/locator.py](../../../src/regrow/recognition/locator.py) `prepare` | 57–174 |
| 共享视觉匹配与相对位置 | [recognition/matching.py](../../../src/regrow/recognition/matching.py) `match_controls` | 147–150 |
| 识别调用与补观察协调 | [traversal/observation.py](../../../src/regrow/traversal/observation.py) `Locator` | 101–118 |
| 选择本轮工作 | [traversal/traversal_scheduler.py](../../../src/regrow/traversal/traversal_scheduler.py) `select_work` | 78–148 |
| 完整动作请求 | [traversal/action_proposer.py](../../../src/regrow/traversal/action_proposer.py) `request_from_run` | 61–143 |
| 来源核验及实际投递 | [runtime/action_executor.py](../../../src/regrow/runtime/action_executor.py) `ActionExecutor` | 39–119 |
| 从实际动作构造更新请求 | [traversal/result_updater.py](../../../src/regrow/traversal/result_updater.py) `build_attempt_update` | 112–185 |
| 结果协调与登记 | [traversal/register_update.py](../../../src/regrow/traversal/register_update.py) `commit_update` | 31–239 |
| 唯一正常快照保存发布 | [records/snapshots.py](../../../src/regrow/records/snapshots.py) `commit` | 42–60 |
| 加载当前记录 | [records/snapshots.py](../../../src/regrow/records/snapshots.py) `load` | 62–69 |
| 只读任务覆盖 | [records/tasks.py](../../../src/regrow/records/tasks.py) `coverage` | 372–401 |
| 对象变化与稳定编号 | [records/observations.py](../../../src/regrow/records/observations.py) `materialize_regions` | 20–78 |
| 原回复/纠错的有效来源 | [records/calls.py](../../../src/regrow/records/calls.py) `submission` | 6–26 |
| 投递前与登记共用来源核验 | [records/action_evidence.py](../../../src/regrow/records/action_evidence.py) `action_source_observation` | 136–158 |
| 统一提示配置 | [prompts/compose.py](../../../src/regrow/prompts/compose.py) `catalog` | 5–9 |
| 字段与平台输出合同 | [prompts/output.py](../../../src/regrow/prompts/output.py) `prepare` | 177–247 |
