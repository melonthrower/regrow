# 2026-11-02 当前源码与实机验证

正式 `src/` 已同步为本轮实际运行的完整冻结源码，摘要 `bd3ea9a16951091332ab5317b4e86a263f7f15dbce6e0b83f4b2a96dcf43c8b5`；不再需要从旧 reviews/tested-source 手工挑选补丁。

Settings/Gedit 原设备、原图实机小试新增15次模型调用、4次GUI操作，4次均有真实回执、后图和登记。Settings 的 Night Light 入口任务完成；Gedit 正文目标恢复关联并继续原业务任务，该业务任务仍 pending。Gedit 对已有缩进证据判断偏保守而重复准备文本，作为未解决质量问题保留。未新增模型角色，未重放旧动作。

这是限定研究源码同步：此前4次保存帧模型验证及9项辅助检查另计；失败补充/暂挂/恢复分支仍主要由辅助检查覆盖，非全框架发布或全应用验收。运行记录、截图、请求回复、凭据及机器配置不在本提交中。

[本轮设计和验证范围](reviews/target-registration-live-20261102/DESIGN.md) · [正式源码变更图](reviews/target-registration-live-20261102/CHANGE_MAP.md) · [版本元数据](SOURCE_VERSION.json)

# regrow

当前 GUI 遍历研究代码快照。保留主框架、逐步遍历器、独立 prompt、测试及当前设计文档；不含运行截图/账本、模型凭据或虚拟机镜像。

- [开发入口：按问题找代码、设计与测试](DEVELOPMENT.md)
- [逐步遍历器](experiments/clock_manual_20260919/README.md)
- [当前框架与模块索引](design/CURRENT_FRAMEWORK.md)
- [原项目说明](README.upstream.md)
- [本次快照说明](SNAPSHOT.md)

这是研究中的工作区快照，不是经过全框架回归的发布版本。外部 OSWorld/Android 环境和模型认证需自行配置，不在代码包内。
