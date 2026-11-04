# Region 功能生成与采集证据

当前接口见 [采集合同](visual_collection.md)。`region_function_research.region_function_inventory`、`function_collection_research.design_region_instruction/RegionGuidedCollector`、`collection_graph`、`collection_visual_guard` 和 `collection_writer` 构成同一维护路径。逐步图原样保留功能与未确认范围，采集只读图，独立输出；图路线是建议，当前图、任务对象和实际业务结果决定执行。

## 2026-11-02 指令记录与Seed准备

当前生成结果以source_refs保留每项子目标的知识依据，以setup描述本条指令所需初始素材及要打开的文件。生成只补充这两项及历史状态/采集初态的区别，不要求遍历替未来任务准备具体环境。范围及执行入口见采集合同。真实GIMP图生成“准备图片裁剪为800×1000”，原始回复经正常校验保存；独立设备按原答生成/投放图片，正常截图检查确认已打开1080×1440原图、尚未裁剪。source_refs对应裁剪工具、尺寸输入框和图像工作区。累计4HTTP（含1次接口schema拒绝），0正式GUI；两次图片准备原件均保留，第二轮退出默认示例启动并绑定窗口。15项辅助检查通过；文件/初态链有限通过，完整裁剪采集未验证。

前一轮“画笔间距20.0，保持历史Hardness050预设”的生成虽然结构校验通过，但用户指出历史状态不能当作采集初态；该原答不作为跨环境生成语义通过证据。原件仍保留，本轮生成的setup明确由采集环境建立新对象。证据见artifacts/runs/instruction_seed_bridge_20261102_01。

## 2026-11-02 生成材料整理（本地候选，有限验证）

`StepwiseCollectionGraph.inventory()` 使用 `generation_material()` 选取区块说明、功能、支持对象、控件用法、参数和条件，不再发送探索 tasks、task_refs、调用来源和知识修订序号。历史功能的对象、完成效果与未确认内容沿 `function_updates.description()` 合入正文，参数观察内容保留而来源记录留在原图。没有 functions 的区块仍可凭控件知识进入目录。

本次不改生成 Prompt/输出 schema、Collector 的完整区块记忆、遍历源码或源图。按目标引用筛选采集知识仍未实现。复用真实 GIMP 冻结图，7 区块52控件保持，19 项探索待办退出生成请求，序列化材料从28149缩至9613字符。11项聚焦检查通过；正常生成 CLI 以原始 Luna 回复保存“画笔间距20.0且保持当前预设”的目标，1HTTP/0GUI。自由数值20.0为模型提出，未实机验证；此证据不代表采集、Seed或跨应用闭环。完整请求/回复及评审位于 `artifacts/runs/generation_material_20261102_01/`。

## 既有证据与未解决边界

- 2026-09-09 桌面/Android 秒表及条件闹钟已有局部实机正例；含两次真实不同初态的条件分支，不是匹配初态的正式比较。完整数据与旧接线说明保存在 [历史记录](../archive/2026-10-02-framework-wiring-fix/region_function_collection_research_before_wiring.md)。
- 2026-09-14 VLC 小试 12HTTP/7GUI：中间误判展开列表为设置完成，最终核对正确拒绝，SFT 为 0。阶段完成与失败恢复不能由终验存在而视作已解决。
- 2026-09-22 Settings 两轮各 10HTTP/4GUI，各拦截一个错点并完成延迟设置；当时通过独立 pilot 显式接 guard，未验普通 CLI 消费逐步图。它证明有限定位/回执链，不证明跨应用鲁棒性。

旧 `--region-ledger`、模型切换和 State/recipe 辅助 API 的说明不是当前入口用法。旧 progressive-feed 研究提议及其未实现部分保留在归档，未作为当前采集能力。

## 2026-10-02 普通入口接线

生成与采集共用 `load_collection_graph`，正常生成结果必需固定摘要；指针、Region 记录或消费图片变化都拒绝执行。逐步视觉 guard 在普通采集入口构造，图像和既有 matcher 固定到本次输出；Writer 使用单次目录，保留旧运行。实际执行仍为原 Collector 与 Writer，没有单独试点执行器或采集模式开关。

定向离线检查已覆盖生成→校验→guard→Collector→Writer、来源缺失/变化拒绝、观察关系边界及真实匹配器双框投影。模型和现场验证另记，不将模拟环境结果作实机结论。

实际验证：冻结Clock图42个Region、178个双框观察、221个消费依赖，源与副本摘要一致。正常CLI生成1条London查询目标（1HTTP）；首轮3HTTP/1GUI后因原答input_text缺点位拒绝，输入未执行。提示补齐输入等动作的必要点位与name/ref区别后，同一指令在新独立AVD重跑8HTTP/2GUI，另wait只取新图；输入、候选显示及终验均通过，Writer保留3个语义步骤和2个实际primitive。两次定位都因旧模板无准入资格走当前图Luna确认，不是实际模板匹配正例。种子已有London，未选择/添加候选；图摘要不变、所属实例已关闭。

使用正常本地模型配置（本次实际gpt-6-luna、medium），试验传输/环境包装仅保存并限制30HTTP/12GUI，未修改请求内容、模型回复或Collector控制流。采集累计12HTTP/3GUI；此前本地缺配置引用、偶数端口循环、初始应用包名误作应用键的准备失败均保留，未发生其余GUI投递。证据在 `artifacts/runs/framework_wiring_collection_20261002_01/`，外部包见 `to_astra/framework_wiring_fix_20261002_01/`。这是一项研究小试，不覆盖任意参数、真实模板正匹配、条件任务、长期稳定性或训练验收。
