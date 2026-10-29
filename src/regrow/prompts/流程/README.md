# 调用组成

[调用组成.json](调用组成.json) 的 `calls` 保存16类调用的主模板、原有问题与材料槽，以及实际需要保留的专用补充路径。

| 修改内容 | 位置 |
|---|---|
| 某步怎样判断与回答 | `calls.<role>.template` 指向的 `调用/*.prompt` |
| 本步主问题、user材料标题及顺序 | `calls.<role>.question/groups/sections/materials` |
| 本次已有专用限制是否保留 | `calls.<role>.supplement_paths`；只保留构造器确实提供的段落，不自动加载整份补充目录 |
| 观察的局部/定位范围补充 | `calls.observation.mode_parts`；由本轮实际mode选择 |
| 角色、环境限制 | `shared_context`，运行范围仍来自run清单 |
| 输出字段和动作 | 本次schema、`platforms`及平台动作正文；`output.py`填入合同，`response_example.py`生成字段说明与格式例 |

所有正式发送和工作台完整预览共用 `output.prepare`。模板中的明确占位符按本次合同展开，fixed_parts保留来源；不再执行旧object_modules的字段选块/依赖/章节重排。旧02/03流程文件不再由calls的flow入口读取。

纠错不重写失败调用的原合同；共享行为核对须从其实际专用请求识别，不能仅因外层role=step_correction就装普通纠错模板。两种身份核对也不继承普通记录修订权限。

本地接入及验证状态见上级README、修改指引和 `artifacts/runs/prompt_template_integration_20261025_01/`。历史冻结源/真实请求原件不随编辑更新。
