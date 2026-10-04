# 逐步遍历器

[全部代码职责与位置](../../design/modules/stepwise/CODE_MAP.md)：按流程找入口，再按共享能力找唯一实现；改动前沿输入、校验、登记和下一步核对。

[开发入口](../../DEVELOPMENT.md) · [模块与设计](../../design/modules/stepwise/README.md) · [测试导航](../../tests/STEPWISE_INDEX.md) · [提示入口](遍历prompt/README.md)

当前逐步遍历研究的源码目录；名称保留历史Clock实验日期，不限制应用范围。与其他框架实现分开定位，不能凭同名文件互相替代。

常规浏览器启动仍使用 `./experiments/clock_manual_20260919/启动遍历.sh`，阶段执行由原launch/run_task_step链承担。环境与当前停止点查[SERVER_HANDOFF](../../design/SERVER_HANDOFF.md)，不要沿用README中的旧设备、端口或调用计数恢复现场。

- 源码按模块页查找，不创建平行实现。
- 固定prompt/schema留在 `遍历prompt/`；最终请求还含程序投影的上下文。
- 运行读取 `knowledge_current.json` 指向的提交快照；calls、action_attempts和旧快照均为证据。
- checkout与run冻结源可能不同，实际调用以run_manifest指定源码为准。
- [旧设计入口](PIPELINE_DESIGN.md)保留导航，原长文已归档。
