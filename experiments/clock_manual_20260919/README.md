# Clock 人工引导探索 · 2026-09-19 起

- [PIPELINE_DESIGN.md](PIPELINE_DESIGN.md)：统一设计入口，按存储、历史、发现、动作、更新、异常检测/分派组织，逐项标注实现和验证状态。
- [HISTORY_DISCLOSURE.md](HISTORY_DISCLOSURE.md)：各步骤历史缩短的当前入口、信息保留边界与验证证据。
- [遍历prompt/](遍历prompt/README.md)：按功能拆分的固定指令与输出schema。
- [REBUILD_DIRECTION.md](REBUILD_DIRECTION.md)：重组实施与验证记录；后续当前设计集中到统一文档。
- [LUNA_RECORDING.md](LUNA_RECORDING.md)：Luna原始输出与Region证据布局，早期停点属于历史。
- [FLOW_BASELINE.md](FLOW_BASELINE.md)：原框架源码副本、阶段驱动器及早期重放。

当前停点：同一run累计10模型调用、2探索动作、1恢复动作。call0009由Luna选择系统返回，a0003执行一次，call0010正常更新确认回到Clock主界面（菜单未展开）。恢复episode已登记为recovered，未触发重启；原菜单工作区块保留，当前可交互是Clock主体与底部导航。普通探索未自动继续，现场继续前需重新截图。

工作目录 /data/shenghonghui/projects/GUI-ReWalk；设备emulator-5690。records/保存人工比较与报告，luna_runs/保存真实请求/回复、截图、动作、图快照及运行元数据；两者不混为模型结果。旧记录不覆盖，运行证据不提交Git。这里是重组实验，不是旧正式框架已完成迁移的声明。

2026-09-20：发现/更新登记与历史读取已统一为名称直达、观察追加的Region结构。控件ID仅作后台引用，给Luna的上下文不含ID。当前记录从knowledge_current.json进入；region_records为旧历史。实际查看[最新菜单记录](luna_runs/clock_region_20260919_01/knowledge_snapshots/a0002-0008-6720f5021216/regions/r0003/region.json)、[框架生成上下文](records/015_region_knowledge_20260920_01/context/dynamic.prompt)和[验证报告](records/015_region_knowledge_20260920_01/REPORT.md)。副本stepwise目录已同步维护源码并用于实际登记；原主框架未改。

最新精简入口：[菜单JSON](luna_runs/clock_region_20260919_01/knowledge_snapshots/a0002-0008-d2131ccb19c3/regions/r0003/region.json)、[上下文](records/016_region_slim_20260920_01/context/dynamic.prompt)、[来源及验证](records/016_region_slim_20260920_01/REPORT.md)。不再保存bbox/icon_bbox或区块history/exploration，按控件图匹配当前所附帧；进度从实际动作推导。0007/0008属于同一次a0002的复核，不增加探索步。

异常恢复实现及实机结果见[报告](records/017_external_recovery_20260920_01/REPORT.md)。唯一恢复prompt在遍历prompt/异常处理/返回目标应用.prompt；副本stepwise/recover_external.py为本次执行入口。

### 当前终端启动入口

运行 `./experiments/clock_manual_20260919/启动遍历.sh`，在窗口展开“选择应用 · 继续 / 新开遍历”。继续保留历史并重新观察；新开保留应用数据，单独建图。窗口包含阶段、任务、阻塞原因和动作结果。程序尝试打开系统浏览器；远程无图形桌面时需在客户端打开打印的地址（默认本机39595端口）。当前Codex转发窗口为 http://localhost:63995/ 。实现与验证边界见PIPELINE_DESIGN.md §13。
