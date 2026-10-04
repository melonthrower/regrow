# 纠错与异常恢复

[模块总览](README.md) · [测试索引](../../../tests/STEPWISE_INDEX.md)

处理失败提案、记录修订、暂挂和应用异常。

## 输入、输出与边界

失败原答、诊断、当前任务与证据 → 修正/补观察/记录修订或暂停。已执行动作先结算，不因登记失败重做GUI。

主要接口：`step_repair.Runner / request；repair_stages；recover_loop`。详细现行合同见[原模块文档](../stepwise_debug_loop.md)；本页负责开发定位与职责边界，实验流水不在这里复制。

## 源码与提示入口

- [step_repair.py](../../../experiments/clock_manual_20260919/step_repair.py)
- [repair_stages.py](../../../experiments/clock_manual_20260919/repair_stages.py)
- [correction_prompts.py](../../../experiments/clock_manual_20260919/correction_prompts.py)
- [correction_crop_feedback.py](../../../experiments/clock_manual_20260919/correction_crop_feedback.py)
- [model_reply_parse.py](../../../experiments/clock_manual_20260919/model_reply_parse.py)
- [recovery.py](../../../experiments/clock_manual_20260919/recovery.py)
- [recover_external.py](../../../experiments/clock_manual_20260919/recover_external.py)
- [recover_loop.py](../../../experiments/clock_manual_20260919/recover_loop.py)
- [recovery_stall.py](../../../experiments/clock_manual_20260919/recovery_stall.py)
- [branch_switch.py](../../../experiments/clock_manual_20260919/branch_switch.py)
- [suspended_updates.py](../../../experiments/clock_manual_20260919/suspended_updates.py)
- [ownership_review.py](../../../experiments/clock_manual_20260919/ownership_review.py)
- [action_owner_correction.py](../../../experiments/clock_manual_20260919/action_owner_correction.py)
- [control_observation_repair.py](../../../experiments/clock_manual_20260919/control_observation_repair.py)
- [task_record_repair.py](../../../experiments/clock_manual_20260919/task_record_repair.py)
- [shared_control_review.py](../../../experiments/clock_manual_20260919/shared_control_review.py)

固定提示/schema入口（最终请求还会按步骤组合）：

- [纠错](../../../experiments/clock_manual_20260919/遍历prompt/纠错)
- [异常处理](../../../experiments/clock_manual_20260919/遍历prompt/异常处理)
- [监督](../../../experiments/clock_manual_20260919/遍历prompt/监督)

## 验证与未完成事项

原纠错/恢复链已存在，格式通过不证明身份或导航成功。重复失败、错误登记或任务跑偏需暂停讨论；缺证据时不堆叠新重试。

聚焦测试从[测试索引](../../../tests/STEPWISE_INDEX.md#repair)选择；涉及共享接口时补相邻模块测试。索引不是全通过声明，也不自动要求全部执行。
