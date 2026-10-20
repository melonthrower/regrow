# regrow 当前本地研究快照（2026-10-20）

- [Astra接手说明](design/OBJECT_PROMPT_HANDOFF_20261020.md)
- [活动源码](src/regrow) · [开发入口](DEVELOPMENT.md)
- [Prompt调用审查目录](design/prompt_objects_review/调用审查目录.md) · [四对象审查入口](design/prompt_objects_review/README.md)
- [本快照说明与验证边界](design/TRAVERSAL_SNAPSHOT_20261020.md)

本分支保存当前本地框架，四对象Prompt已接入正常调用，唯一正文在[src/regrow/prompts/对象](src/regrow/prompts/对象)。当前代码含未整体验收的研究候选，不是发布版；不覆盖远端原分支，也不宣称已合并其全部行为修复。运行数据及凭据未上传。

---

## 上次导出说明（历史）

# 当前遍历源码快照（2026-10-18）
当前维护入口为 [src/regrow](src/regrow)，运行入口为 `python src step ...` / `python src session ...`。历史 experiments 目录保留历史版本，不是本快照的活动实现。
本分支是研究快照，部分行为仅经聚焦测试及原始保存帧验证，不是发布或全框架验收。已知身份复核理由、部分前景门槛、辅助介绍任务生成及参数探索收敛问题仍在；详见 [快照说明](design/TRAVERSAL_SNAPSHOT_20261018.md)。
运行记录、截图、凭据、模型配置和Prompt工作台个人笔记没有上传；工具仍需本地数据目录。

---

# regrow

当前 GUI 遍历研究代码快照。保留主框架、逐步遍历器、独立 prompt、测试及当前设计文档；不含运行截图/账本、模型凭据或虚拟机镜像。

- [开发入口：按问题找代码、设计与测试](DEVELOPMENT.md)
- [逐步遍历器](experiments/clock_manual_20260919/README.md)
- [当前框架与模块索引](design/CURRENT_FRAMEWORK.md)
- [原项目说明](README.upstream.md)
- [本次快照说明](SNAPSHOT.md)

这是研究中的工作区快照，不是经过全框架回归的发布版本。外部 OSWorld/Android 环境和模型认证需自行配置，不在代码包内。
