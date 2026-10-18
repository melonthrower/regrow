# 在这里修改各步Prompt怎样组成

入口：[调用组成.json](调用组成.json)。配置每次构造时读取，无第二份Python常量清单。`title/builder/说明`供维护者定位，不发送Luna；其他被使用的项见下表。固定片段以原`.prompt`路径保留，旧请求的原规则版本与原始材料不追改。

| 想改什么 | 修改位置 | 哪条真实路径读取 |
|---|---|---|
| 哪一步装哪些固定规则 | `calls.<role>.parts`；动作/更新的`flow`指向[02](02_动作选择.json)/[03](03_结果核对.json) | `prompt_rules.parts` → locator/任务/动作/更新/总结/恢复入口 |
| 发现全局/局部用哪段 | `calls.observation.mode_parts` | locator传已知mode，prompt_rules选择 |
| 原工作主问题和边界 | `work.<kind>.question/guidance`；`question_from`引用同一角色问题 | work_context → step_questions |
| 本步分问题、对应材料槽、对应输出 | `calls.<role>.groups` | step_questions；一行配置同时维护三者 |
| 补发现、旧任务复核等分组 | `calls.<role>.variants`、`messages`中对应句子 | step_questions的已有事实条件；不让框架猜截图结论 |
| 普通动作正文各段顺序和取材槽 | `calls.action_selection.sections/materials`，末尾问题在`calls.action_selection.question` | action_material；未分配的实际材料仍保留在remaining |
| 桌面/Android/环境规则 | `platforms`中的路径和角色范围 | prompt_delivery → 正常发送层及原步骤纠错 |
| 导航、前置、局部清点补充模块 | `supplements` | 原导航/前置/局部补充入口在需要时读取 |
| 输出填写引导及字段规则组合 | `output.action_text/declaration_intro/identity_declaration/crop_declaration/parts/glossary/fragments/groups` | output_contract；schema仍由原合同产生并本地校验 |
| 正反例、概念和具体操作含义 | 上述清单引用的`.prompt`原文件 | 原fixed_parts与最终system；本轮没有删掉或改写正文 |

角色键：`observation`发现，`task_proposal`提出任务，`action_selection`下一步，`observation_update`结果更新，`function_registration`总结，`recovery`恢复；其余候选选择/比较、归属复核、补观察及任务复核在同一calls表保留原问题分组。普通纠错的问题也在calls.step_correction；错误码与专门修复能力仍由correction_prompts/step_repair判定，不能靠编辑提示开出新权限。

`output.groups`目前是四个固定分类名（术语定义、本步目的与判断、输出要求、示例），可调整顺序，不可直接改名或删除；改分类需同步渲染器。动作sections的key是固定内容块，可编辑title和排列顺序，remaining负责保留未分组的实际材料。role/kind是现有调用标识，不能仅在配置里改名。

材料槽名称指向builder已经提供的真实字段。改名或新增槽需要同步材料生产；未知字段会保留在补充材料，不自动成为新事实。配置中的`all/any`保持原字段能力筛选，`$task_assessment/$control_output`仅是内部已知能力，不是让Luna填写的新字段。本轮没有借迁移完成“按职责重写所有提示”的工作。

注意三条边界：平台只有具备动作能力的角色拿整套动作表；输出schema会按本轮任务/平台特化，文件只是基础；保存的纠错/续接请求保留当次固定规则，编辑新配置不会覆盖原历史证据。

修改入口后的最小证明是：在隔离副本编辑问题/材料槽/规则组合，确认它进入最终请求；再比较正常完整记录的前后正文、图片和归属。不能把格式检查当作Luna语义验收。本批证据见项目`artifacts/runs/prompt_entry_unification_20261015_01`，聚焦检查和修改前副本在对应tmp_tests目录。

普通动作合并表：平台prompt用`action | 操作含义`表维护每个动作的一份说明；本次schema提供必填字段，prompt_delivery.action_contract生成三列表。common_fields指向共用target/reason/坐标说明；普通动作内不再另送这份说明。保存的“片段-动作合同”按原版本读取，历史旧手册不会被当前文字替换。complete是任务结算回复，不加入GUI执行器动作集合；task_update与其他阶段的原字段合同仍由原代码校验。
