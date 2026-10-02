# 框架接线修复实施清单

执行方式：root 按 executing-plans 实施和测试；陌生读者只审阅。用户已批准四项诊断方向并要求完成修复。

目标：保留语义完成判定、运行所选源码、普通入口消费冻结逐步图并完成单功能采集，更新维护测试和文档。
技术：现有 Python / pytest / Luna / RegionGuidedCollector / CollectionWriter；不增加依赖、CLI模式或遍历副本实现。
设计：`to_astra/framework_wiring_fix_20261002_01/DESIGN.md`。
基线：`artifacts/tmp_tests/framework_wiring_fix_20261002_01/`；240项既有状态；精确命令/结果均存该目录。真实验证保存到单独 records/ 或 artifacts/runs/ 子目录。

- [x] A：先写跨 settle_task→advance 的 pending、blocked、done 测试，确认当前失败；移除路由与历史入口自动结算；更新旧交接测试，验证正常结果和历史核对仍可收尾。
- [x] B：先写运行源码选择/显式坏路径测试；增加 `run_source.py::session_command(run, output, mode)`，供 RoundRunner 与 Supervisor 使用；维护启动入口与服务身份一致；验证真实子进程路径及回复解析来源。
- [x] C：更新5项失配夹具与失效采集CLI测试，保持功能整理、对象绑定和同帧滚动边界门禁；运行直接邻接测试。
- [x] D：增加采集侧冻结图加载/投影，普通生成和采集入口共用；保留 functions/未知范围/真实边/快照及 matcher 版本；复用视觉 guard、Collector、Writer，验证源图不变与结果落盘。
- [ ] E：审阅实际变更、生成请求和截图；修复实质意见并复审，再用正常框架真实 Luna 保存帧验证任务完成正反例；运行单功能独立采集小试，保留实际结果。
- [ ] F：更新模块合同、全局入口/已知风险、研究证据边界及本月日志；整理独立审阅阶段、设计/地图/ZIP；在批准源码导出基线上只提交任务差异并同步私有 regrow，报告哈希与剩余工作区状态。

重点：语义对象与后台ID可能不一致；目的区块可为多个；旧任务不因后续新任务清点失去 pending；缺源码不能静默回退；冻结 pointer/records/图片和 matcher 均属于来源版本；无响应调查 done 不等于产品功能成功。

本文件是开工实施计划的历史快照；最后的模型/现场验证、交付检查点及完成状态以2026-10月日志和交付REPORT为准，避免在历史计划中预写未发生的提交结果。
