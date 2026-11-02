# 遍历补登记与纠错续接拟改动表

状态：全部为拟修改，尚未实现或验证。现有源码锚点固定到已导出的[31c8fae0](https://github.com/melonthrower/regrow/tree/31c8fae0bd2991c4d3e9bb8d1101bc68f9ec412d)，不是本地dirty状态整体提交。`framework_open_issues_20261102_01/source-comparison.json`已有当前源码与对应冻结源一致的证据，本轮复用该审计；行号由当前AST核对。源码变化后需发新版本，不能沿用此表。

|问题|文件与现有锚点|当前行为|拟改动与接受例|
|---|---|---|---|
|补登记合同丢失|`src/regrow/recognition/region_identity.py:40–48`，prepare；`src/regrow/traversal/discovery_step.py:49–300`，commit，重点131/254；`src/regrow/recognition/discovery_completion.py:145–214`，supplement|内部去schema请求进入持久补登记批次，后续读取崩溃|保留原合同来源与内部派生请求的用途边界；Characters0100原断点正常补登记，新批次保留完整合同，0重放GUI|
|重观察丢目标|`src/regrow/traversal/step_repair.py:189–199`，reopen_blocked；`src/regrow/traversal/discovery_step.py:22–47`，await_discovery；`src/regrow/recognition/locator.py:54–171`，prepare|重观察使pending目标superseded，目标owner退出必要候选|只在原未执行任务续接支路保留身份召回义务；Gedit正文owner继续进入当前有效候选；真正恢复不串用旧提案|
|旧几何不可沿用|`src/regrow/traversal/target_registration.py:22–38`，context；`:51–92`，registered；`:141–168`，advance|现有目标关联还会读取原提案与原帧|新帧续接不得借旧坐标确认当前对象；保持原任务、按当前识别重新关联后新选动作。修改前检查此相邻路径，不能只把status改回pending|
|纠错表示冲突|`src/regrow/prompts/correction_feedback.py:7–35`，organize；`:87–207`，describe；`src/regrow/traversal/correction_prompts.py:20–59`，original_reply|内部诊断和扁平草稿直接进入可读请求|经同一模型格式转换呈现具名具体问题和嵌套稿；Gedit0128整份请求的说明、草稿、schema一致|
|名称/结构转换与父引用|`src/regrow/recognition/named_references.py:143–180`，encode_objects；`:183–241`，prepare；`:253–270`，render；`:295–392`，decode；`src/regrow/prompts/对象/区块.prompt:194–196`，region.parent|通用render替换名称，不等于结构转换；parent仅解析当次/基准行，未解析名称落入内部整数校验|复用既有编码职责；按提案明确父引用范围；缺父引用用具体对象错误，不静默写null、不伪造父观察|
|相邻纠错合同|`src/regrow/runtime/reply_correction.py:49–59`，request；`:62–127`，call；`src/regrow/traversal/step_repair.py:210–328`，request|格式重答与业务/专门纠错走不同入口|保留各入口实际合同，避免重复编码和破坏专门修订外层；必要聚焦检查及原生Gedit案例|

已实现、已验证：仅本提案的资料核对与文字审阅；不是上述行为修复。既有普通目标补登记实机15HTTP/4GUI、原入口收口限定验证等仍各按原证据范围成立，不覆盖这里的失败支路。

新文件：`design/proposals/traversal_continuation_20261102/DESIGN.md`与本文，均为新文档。第一批不预设新框架模块、CLI开关、账本或字段；若实现中确需改变已对齐含义，先回到具体例子讨论。
