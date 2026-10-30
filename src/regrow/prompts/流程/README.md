# 调用组成

`调用组成.json` 的 `calls` 保存 **17 类调用**。每类的 `template` 只说明本步目的，`field_sections` 选择实际输出需要的含义、概念及局部格式。

| 要改什么 | 维护位置 |
|---|---|
| 全局遍历目标 | `shared_context.role` 指向的共享角色 |
| 本步要做什么 | `calls.<role>.template`；导航用 `purpose_by_work_kind` |
| 字段含义、正例 | 四个 `对象/*.prompt` 文件的稳定块 ID |
| 需要哪些概念 | `concepts` 与语义块的 `requires`；只引用必要定义 |
| 字段组与相邻格式 | `outputs` 的 `block/fields/details`；格式从实际 schema 对应子树生成 |
| 是否加载细节 | `when_paths/when_any_paths/when_required_paths/when_values`；使用完整字段路径 |
| 工作模式或修订方式 | `work_kinds/block_by_work_kind/when_request/unless_request` |
| 动作分支 | `actions`；动作表以实际平台及允许动作生成 |
| 当前专用补充 | `supplement_paths` 仅保留构造器已提供的内容；普通纠错用 `source_field_requirements` 按开放字段保留诊断说明 |
| user 材料展示 | 原 `question/groups/sections/materials`；事实仍由原 builder 提供 |

`field_sections.py` 负责选块、依赖去重和局部格式；`output.py` 负责原合同、当前平台与来源补充；`run_context.py` 在 system 中加入一次角色、范围及适用环境限制。`object_modules` 仅列语义来源文件，旧规则选择与 Markdown 章节重排已经退出。

根字段未分组会报错。格式不会生成新的业务能力；关闭字段不会保留无关教学，跨字段条件仍保留，已关闭枚举分支的不可达条件不重复显示。原格式重答保持原合同；普通纠错的完整/局部 proposal 分别说明，共享关系使用专用合同。

现有工作台完整预览与正常发送仍共用 `model_transport.prepare_request`。本批是离线代码与呈现验证，尚无本版 Luna 原生行为验收。
