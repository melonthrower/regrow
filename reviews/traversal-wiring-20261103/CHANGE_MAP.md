# 接线修复具体改动表

源码固定到 [48120178](https://github.com/melonthrower/regrow/tree/481201785d0645a57865646b5f2c970c08f56463)。已实现；保存帧、实机与未接受语义分别见DESIGN和运行报告。以下为该源码的实际行号；with_contract、reobserve、body为本批新增函数，不存在旧行号。

|文件／函数|实际改动|
|---|---|
|`src/regrow/traversal/discovery_step.py`：[await_discovery L22–49](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/traversal/discovery_step.py#L22-L49)；[commit L51–305](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/traversal/discovery_step.py#L51-L305)|内部解析与补登记合同分开；旧批次按原调用恢复；仅指定未投递纠错支路保留目标。|
|`src/regrow/recognition/discovery_completion.py`：[with_contract L145–159](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/recognition/discovery_completion.py#L145-L159)|新增原合同恢复；核对原观察范围和截图，不用新模板猜旧合同。|
|`src/regrow/recognition/locator.py`：[request_from_run L173–200](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/recognition/locator.py#L173-L200)|正常请求入口为旧缺合同批次读取实际合同。|
|`src/regrow/traversal/step_repair.py`：[reopen_blocked L189–201](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/traversal/step_repair.py#L189-L201)|未投递动作/发现重观察显式请求保留原目标；不改变已执行动作续登记。|
|`src/regrow/traversal/target_registration.py`：[reobserve L51–63](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/traversal/target_registration.py#L51-L63)；[registered L66–112](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/traversal/target_registration.py#L66-L112)|保留原任务/目标身份线索；新帧不使用旧点击点关联新对象。|
|`src/regrow/recognition/named_references.py`：[prepare L183–260](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/recognition/named_references.py#L183-L260)；[decode L314–416](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/recognition/named_references.py#L314-L416)|按原合同呈现嵌套纠错草稿；父引用无法解析给出具名错误，含义不变。|
|`src/regrow/prompts/correction_feedback.py`：[organize L7–32](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/prompts/correction_feedback.py#L7-L32)；[body L35–42](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/prompts/correction_feedback.py#L35-L42)|保留结构化纠错材料，复用一个正文组织入口；Prompt源文件不改。|
|`src/regrow/runtime/reply_correction.py`：[call L62–129](https://github.com/melonthrower/regrow/blob/481201785d0645a57865646b5f2c970c08f56463/src/regrow/runtime/reply_correction.py#L62-L129)|保存original的精确内部视图视作同请求，保留next和计数；不同问题仍拒绝。|

接受例：Characters旧0100断点的补登记合同与发布；Gedit原0127错误的具名重答、纠错重观察后的正文目标；Settings旧0137格式重答和a0014结果续登记。共5新HTTP/0GUI，未编辑原答。
未接受：历史父关系、Characters当前区块判断、候选完整收集、VM恢复及全应用完成。单独实跑另记。
