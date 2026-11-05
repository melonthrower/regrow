# ReGROW 最小探索任务合同与 Prompt 草案

状态：待接入草案。2026-11-05 已确认设计方向；本文件不参与运行时 Prompt 组合。当前运行 Schema 仍要求 task_type、template 等字段，必须在兼容性改造后统一切换，不能只替换运行文案。

## 一、已确认的设计

- 探索任务是一个当前区块或其控件中尚未回答的自然语言问题。任务推动认识；答案归相应 Region、Control 和实际访问关系，不在任务里保存第二套功能知识。
- 新任务提出的 operations 单项只需要 control、reason。调用已绑定当前 Region，control 是其内部控件引用；control 为空字符串表示该 Region 自身的问题。不额外引入 region 字段。
- operations.reason 是任务的原始问题文本，写清需要弄明白的事实；必要时包含调查范围与条件。它不是单纯的立题动机。它在后续进展判断中保持不变。
- 原始问题优先围绕未知功能入口的直接去向、可指定设置的参数候选/填写规则/必要条件、区块有线索但未显示的内容。其他有助于后续指令生成、操作理解或采集导航的本区块未知问题，也可以提出。
- 任务不是类型和模板的组合。新任务不输出或持久化 task_type、template、question、condition、completion_condition 等平行描述。
- task_update 仍用于回答、继续、暂缓。remaining_question 仅记录原问题未答的部分，不改写原问题。状态、来源、行动证据由框架管理。
- 旧图任务保留现有 task_type、completion_condition 和历史证据，兼容读取，不批量覆盖历史原文。

## 二、目标 Prompt 文案

以下是未来接入 src/regrow/prompts/对象/任务.prompt 等运行位置的候选文本；只有语义和字段合同同步改造并通过测试后才启用。

### task.definition

探索任务用于回答当前区块或其控件中尚未解决的具体问题，补充可复用的操作知识和访问关系。优先关注功能入口的直接去向、可用于指定任务目标的参数选项与必要条件，以及当前区块尚未显示的内容范围。其他有助于后续指令生成、操作理解或执行导航的未知问题，也可以针对所属对象提出。

每个任务绑定当前区块或其中一个控件。reason 直接写需要回答的原问题，必要时说明问题所覆盖的对象、选项或界面范围。任务进展和结束始终对照这份原问题与累计观察；已获得答案时把认识登记到对应对象，探索中发现的新独立问题另行提出。

### task.local_planning

识别当前界面时，同步整理可直接确认的区块、控件、功能和参数知识，再判断哪些关键信息值得通过进一步观察或交互补充。

优先检查功能入口的直接去向、操作可指定的选项及条件、区块中有线索但尚未看到的内容。对本轮辨认出的主要功能对象分别完成直接登记或立题判断；其他独立未知按其对任务生成和执行导航的价值决定是否探索。

### task.operations

# 新增探索问题：operations

先判断本轮允许更新的旧任务；原问题尚未回答的部分继续原任务，再考虑独立新问题。

operations 中每项只提供 control 与 reason。当前区块是任务所属 Region；control 填本区块内的控件引用，区块自身的问题填空字符串。reason 写成具体、可回答的原问题，需要范围时在原文中写清，以便后续按同一问题判断进展。

依据已有知识直接登记可以确认的功能与设置；选择仍需要观察、且会补充操作能力、参数或访问关系的具体问题。按探索价值和可达性排序，没有独立新问题时填写 []。必要的定位、准备和导航服务于原问题。

### task.update

# 判断已有任务：task_update

对照保存的原始问题、已登记知识和实际观察判断：answered 表示原问题已有足够答案；continue 表示仍有未答部分，在 remaining_question 中指出剩余内容；defer 表示存在实际障碍，并写出可判断的恢复条件。

remaining_question 只说明原问题剩余的部分，不能替换原范围。reason 说明本次判断的依据，新增的功能、参数及访问知识登记到实际对象。历史任务若保存了 completion_condition，仍按其原有条件判断，不用新定义改写旧任务。

### 调用/提出探索任务.prompt

结合当前区块、已登记知识和相关任务，先判断允许更新的旧问题，再提出尚未被已有知识或旧任务覆盖的具体新问题，最后判断本次给定范围是否考虑完整。

可以直接确认的功能知识登记到相应对象；需要进一步探索的内容以 control 与 reason 形成任务。具体回复字段和引用遵循本次提供的输出合同。

### 待退役的 Prompt 块

- task.goal_template：移除模板枚举及模板专用说明。
- task.type：移除任务类型枚举说明。
- task.completion_condition：新任务不再自行提供或由模板派生完成条件。
- task.batch_update_example：更新为直接对照原始 reason 判断的通用例子。
- task.scope、task.retry_when、task.next_action 等仍需的字段说明保留；随着实际 Schema 核对具体表述。

## 三、目标输出正例

以下只是 operations 字段的虚构例子；真实控件引用由当次上下文提供，整体回复仍包含本次合同要求的其他顶层字段。

~~~json
{
  "operations": [
    {
      "control": "c0001",
      "reason": "这个功能入口直接通往哪个区块，打开后显示什么内容？"
    },
    {
      "control": "c0002",
      "reason": "这个设置提供哪些可指定的候选选项及必要条件？查看完整的有限候选范围。"
    },
    {
      "control": "",
      "reason": "当前区块截图下缘以下至内容末尾，还有哪些尚未显示的功能入口或设置？"
    },
    {
      "control": "c0003",
      "reason": "这个尚不明确用途的控件能够执行什么操作？"
    }
  ]
}
~~~

对应的进展例子：

- 入口：已有观察确认直接到达的区块及内容，则原入口问题可以回答；目标区块内部新问题另立。
- 参数：原问题要求完整有限候选，当前只见一部分，则继续原任务。remaining_question 写仍未见的候选范围，而不修改原 reason。
- 区块内容：原问题指定的未见范围已查看，新的入口或控件按实际所属对象登记后，问题可以回答；没有新对象也可记录范围已查明。
- 其他问题：以其原始 reason 所问事实是否有可靠答案判断，允许必要多步操作，不以完整业务流程代替原问题。

## 四、接线修改清单（后续实施）

1. records/task_goals.py 与 records/task_plans.py：新 operations Schema 简化为 control、reason；停止为新任务按模板 normalize 和生成 completion_condition；保存不可变的原始 reason。
2. task_plans.matching_question：移除依赖 (control, registration_kind, completion_condition) 的相同题判定。必须避免缺少 completion_condition 后把同一控件的多个独立问题误认为相同任务。
3. records/task_settlement.py、records/object_store.py：调整 registration_kind 默认 function、类型驱动的知识产物门槛、任务标签与终点读取；不能以缺失类型默认为 function 继续运行。
4. 逐一审查 records/shared_tasks.py、records/coverage_exemption.py、records/function_scope.py、traversal/inventory_scroll.py、traversal/task_prerequisites.py，以及历史/任务上下文中使用 task_type、registration_kind 的消费者。根据对象、问题及证据确定行为，避免只删输出字段。
5. prompts/对象/任务.prompt、调用/提出探索任务.prompt、流程/调用组成.json：同步撤除已退役块和依赖；保留任务进展、清点范围、必要字段格式。
6. 检查真实请求的正例生成。call_examples.py 有 operations 样例构造函数，但须确认它实际进入当前 field_sections 输出；不要只修改未被发送的示例。
7. 兼容旧图：已保存的 completion_condition 和 task_type 在历史任务上继续按原语义读取；新任务采用 reason 原问题。不重写既有观察和动作记录。

## 五、验收重点

- 新任务立题输出只有 control、reason，Region 任务使用 control=""，整体输出仍满足运行合同。
- 同一控件允许两个不同的合理问题，但不重复建立已有未答问题。
- 有限参数候选只发现部分时继续原问题；全部范围登记后才能回答。
- 入口任务确认直接内容后结束，内部新功能另提任务。
- 区块内容问题有具体未见范围；覆盖范围后可以结算，即使没有新功能。
- 旧任务仍按原 completion_condition 处理，无静默降级。
- 检查任务提出、结果更新、任务选择、共享/覆盖豁免、恢复与历史展示的构造、校验和存储。静态测试、真实保存帧离线重放与 Luna 原生行为验收分开报告。

本提案是记录与待审核的 Prompt 目标，不表示运行中任务合同已改或原失败案例已通过。
