# ops/ — 探索与运维参考

新开对话先看这里, 了解"探索哪些应用、数据怎么存、容器怎么管"。

- **[apps_to_explore.md](apps_to_explore.md)** — 待探索应用清单(移动端对齐 android_world ~23 个 / 桌面端对齐 OSWorld 10 域), 含安装/种子/建图进度。**做新的图遍历/采集前先查这里对齐目标应用**。
- **[storage_convention.md](storage_convention.md)** — 数据目录版式 `data/<date>/<app>/{graph,instructions,trajectories}/`、临时文件 `_scratch/`、容器归属判别与纪律。
- **[pull_remote_run_evidence.ps1](pull_remote_run_evidence.ps1)** — 从远端运行目录安全拉取 `results/` 与根级日志/状态；拒绝符号链接、超限证据和整个 `repo/OSWorld` 递归下载。
- **[container_ops_log.md](container_ops_log.md)** — 共享机上我们起/停 docker 容器/模拟器的记录 + 归属判别 + 事故教训。**批量起停容器后记到这里**。
- **[collected_data_log.md](collected_data_log.md)** — 已采数据清单: 每批轨迹在哪台机/哪个目录、多少条、真成功筛选判据。**采完一批数据后记到这里**。

> 约定: 这些是跨会话的"项目运维事实", 改了记得同步更新; 与 design/(技术设计) 区分——design 记"怎么实现", ops 记"探索什么/数据放哪/机器怎么用"。
