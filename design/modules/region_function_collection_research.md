# Region 功能生成与采集证据

当前接口见 [采集合同](visual_collection.md)。`region_function_research.region_function_inventory`、`function_collection_research.design_region_instruction/RegionGuidedCollector`、`collection_graph`、`collection_visual_guard` 和 `collection_writer` 构成同一维护路径。逐步图原样保留功能与未确认范围，采集只读图，独立输出；图路线是建议，当前图、任务对象和实际业务结果决定执行。

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
