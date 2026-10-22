# 上下文可读性：本次实现与边界

基线 be58963。沿用现有展示入口，不增加模型调用类型、恢复分支、配置开关或校验门槛。

- control_history_context.purpose_text 只输出用途；task_inventory_context.project 分开保留历史探索判断。
- prompt_material.observation_details 在展示副本去内部来源地址及完全重复对象几何/描述；记录、坐标、图像、任务和引用不变。
- correction_feedback.present/describe 用对象名和区块表达错误，保留具体修正要求；结构诊断由 registration_diagnostics.schema_errors 展开唯一适用分支。原始诊断保存在episode，不重复灌入历史正文。
- step_repair 保留最新失败回复，纠错请求与当前诊断配对。
- control_records.extend_schema 仅允许识别登记的knowledge为空；控件prompt说明一次含义；原任务答案仍使用非空合同。
- task_settlement.register_destinations 的目标归属错误点名区块和控件，不改变判定条件。

退役：通用用途字符串自动追加跳过指令、诊断用程序路径引用被拒绝回复的展示函数。保留所有底层审计记录。

实际验证：Clock菜单a0001真实保存帧，同一任务/历史/回执，正常框架构造和登记，Luna原答未经改写。5次HTTP，0次GUI，最终原按钮任务完成并建到应用菜单的边，3个菜单项登记到菜单区块。一次错误目标归属通过具名纠错修复。动态正文3855→2708字符；固定正文24609→24682。

限制：首次3调用用尽后分独立副本续2调用，其中1次为重新接受候选触发的身份复核。空知识的新答分支未在本次模型回复出现，仅离线检查；普通提出/动作步骤完成原生预览，未增加模型调用。历史较长、准备过程与跨应用尚未新增验收。4项历史测试断言失败已在未改基线重现。现场原运行仍停在7次调用、原动作待登记；独立测试成功不等于现场已恢复。

验收证据：工作区artifacts/runs/context_readability_20261022_01；交付包to_astra/context_readability_20261022_01。具体提交与行号映射随交付包提供。

最终复核边界：0009纠错经单图补登记继承后仅附动作后图，但嵌套原材料仍提及前后两图；本轮未出现错登记，不宣称每次纠错均附完整双图。该既有图号说明不一致尚未修改。Keyboard Shortcuts身份裁剪被原Menu提示部分遮挡，未声称高质量无遮挡身份。
