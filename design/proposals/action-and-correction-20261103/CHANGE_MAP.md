# 具体改动表（方案，尚未实现）

定位基线是冻结source-v8及其已导出源码提交 [fceb3b74da9a86c3202de71f86d12c0ab80a09d6](https://github.com/melonthrower/regrow/tree/fceb3b74da9a86c3202de71f86d12c0ab80a09d6)。下列行号从对应冻结源复核；这不是本轮实现提交。活动工作树有既有未提交/暂存内容，不可整体当成本轮改动导出。

|仓库相对路径、函数和锚点|当前行为|拟改与验收|
|---|---|---|
|src/regrow/traversal/action_binding.py，_bind_action_target，L60–67|名称唯一即绑定已有ID；不证明实际落点|保留此身份关联职责，不把matched解释成成功；不按位置强改ID|
|src/regrow/recognition/action_target_review.py，conflict，L89–112|点位无其他旧候选时return None|加入原目标当前有可靠外观线索却未覆盖拟操作点的疑点；复用原核对调用，保留无定位不等于不可操作与裁剪非点击范围|
|同文件request/accept，L123–161|提供原上下文/疑点，返回原动作合同，保存同帧同动作确认|保留机制/预算/原任务；新疑点说明候选见DESIGN.md，先审后改，不加输出字段|
|src/regrow/runtime/action_executor.py，ActionExecutor.execute，L44–86|投递前检查画面/窗口并调用conflict|继续共用核对逻辑，不另加一套执行器判断；用真实投递前图验收触发，不重放旧GUI|
|src/regrow/recognition/named_references.py，labels，L47–75|派生名称和全局唯一owner|保留单一ID及共享引用含义；纠错呈现需补本次明确动作归属，不能全局唯一化或取第一个父区块|
|同文件encode_objects，L143–180；prepare两处使用，L229–242|完整纠错草稿与局部修订都需唯一owner|两个呈现入口统一采用原稿/本次有效合同的明确关系；原107案例不崩溃、不复制控件、不迁移归属|
|src/regrow/prompts/调用/操作目标核对.prompt，L1–2|已要求当前图核对对象/位置|暂不改正文；候选只补新增疑点的动态说明，且需先获用户确认|
|src/regrow/prompts/异常处理/异常识别.prompt，L1–8|目标应用前景归属决定external_app|本轮不改；系统辅助流程的定义、任务归属和输出影响另行对齐后给完整候选|

必要相邻合同：合法点位不误挡；输入控件外观裁剪不成为全部点击范围；明确原稿区块不被覆盖；共享控件ID/知识只有一份；已发请求与历史失败合同保留。验证使用原生构造器和完整真实上下文、未经编辑的Luna回复及正常纠错/登记。未做生成/采集或benchmark验收。

新文件：本设计和此改动表为新增审阅产物；没有新增框架源码文件，不虚构其旧行号。历史错误知识清理由原生snapshot发布保留旧证据，不能改写原动作或把未接受107草稿称作已发布事实。

V3补充已定位的调用链：named_references.decode L357–360对纯知识修订不带region_index，保留；traversal/correction_prompts.py original_reply L20–55已有source与original_request，不新增传递字段。实际补点限定named_references.prepare中两处编码之前派生本次显示映射，输入直接来自已保存的原动作source及binding，映射不改持久归属。原门禁复现见baseline-diagnosis.json，仅诊断原代码，尚无新行为验收。
