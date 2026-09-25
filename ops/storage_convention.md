# 存储与容器规范 (2026-06-30 立)

今天的事故复盘: 采集进程被杀后 docker 容器未回收 → 孤儿容器(挂 /tmp/System.qcow2)
堆积 → 共享机磁盘 I/O 争抢 → 后续 QEMU 开机超 5 分钟就绪超时 → 并行采集大面积失败。
根因是 ①容器没人按归属回收 ②文件散乱无约定。本规范立两条线。

## 1. 数据目录版式 (date / app / {graph,instructions,trajectories})

统一根: `data/<date>/<app>/` , 三个子目录(ASCII 名, 对应 图/指令/轨迹):

```
data/
  260630/
    setting/
      graph/          # 图遍历产物 (= 旧 result_*/gen_data/.../{graphs,0/nodes}); 节点截图/a11y/page_capabilities
      instructions/   # 该 app 该批次的指令 json (= 旧 _instructions_*.json)
      trajectories/   # 采集到的轨迹 episodes (= 旧 collections/OS/<date>/<app>/episodes)
    calculator/
      graph/ instructions/ trajectories/
  260701/
    ...
```

- `<date>` = 采集批次日期 (YYMMDD)。`<app>` = 应用名 (setting/calculator/...)。
- 一次"图→指令→轨迹"完整链路的产物都在同一个 `data/<date>/<app>/` 下, 一一对应, 不再散落根目录。
- 并行采集: 各 worker 仍写各自临时根, 跑完 **合并** 到 `trajectories/` (按 episode 目录名 CAPxxx_hash 去重)。

## 2. 临时文件

- 所有一次性产物统一进入 `artifacts/`，该目录除 `artifacts/README.md` 外不进 git。
- 运行图与截图进入 `artifacts/runs/`；日志进入 `artifacts/logs/`；诊断 HTML/JSON/PNG
  进入 `artifacts/diagnostics/`；压缩包进入 `artifacts/archives/`；短期测试与基线进入
  `artifacts/tmp_tests/<唯一任务或运行名>/`，脚本、pytest临时目录和输出放在同一处；
  `artifacts/scratch/`只保留历史材料。不要再在仓库根目录创建临时测试目录、
  `result_*`、`logs_*` 或 `_scratch/`。
- `data/`、`collections/`、`research/`、`issues/` 是持久数据或证据，不按临时文件清理。
- 正式工具进 `tools/`，离线测试进 `tests/`。
- 过时的设计与实施方案统一归档到`design/archive/<主题或日期>/`；当前合同仍在
  `design/CURRENT_FRAMEWORK.md`和`design/modules/`，变更历史仍在`design/changelog/`。
- 真实遍历的请求、回复、截图和checkpoint不是临时测试；保留对应运行目录与证据引用。

## 3. 容器开关纪律 (防孤儿)

- **归属判别(已验证)**: 容器挂载的 VM 盘 = 归属。我们的桌面 docker 挂 `/tmp/System.qcow2`
  或 `/tmp/System_seeded.qcow2`(均 owner=shenghonghui); 别人的是 knowu_bench / verl2 等
  **不同镜像**(`docker ps` 看 IMAGE 非 happysixd/osworld-docker)。
- **只清自己的**: 用 `cleanup_mine.sh` (按上面的挂载盘过滤), **绝不** 碰别的镜像/别人的盘。
- **每次 run 收尾必清**: 并行启动器结束/被中断都应回收自己起的容器 (teardown)。
- **开关记录**: 每次起/停批量容器, 记到 `design/container_ops_log.md` (时间/机器/数量/qcow2/用途)。

## 4. 当前迁移状态

- 2026-07-15 已把仓库根目录的历史 `result*`、`logs*`、压缩包、明确生成的诊断文件和
  下划线临时目录原地移动到 `artifacts/*/legacy/`，未复制、未删除内容。
- 根目录导入图已归档到 `data/imported/downloaded_graphs/`；评测集归档到
  `data/evaluation/{desktop_done_20,desktop_impossible_samples}/`。旧截图诊断进入
  `artifacts/diagnostics/legacy/`，上传包进入 `artifacts/archives/legacy/`，临时 demo
  进入 `artifacts/scratch/legacy/`，成本日志进入 `artifacts/logs/legacy/`。
- 论文计划、生成分析、参考和图片统一位于 `research/paper/`；日期化监控、交接、会话
  和历史 agent prompt 位于 `research/history/`。仓库根 Markdown 只保留维护入口。
- 旧采集数据合同仍按第 1 节的 `data/<date>/<app>/` 管理；`collections/` 等现有持久目录
  未并入 artifacts。
- 新视觉遍历默认根为 `artifacts/runs/`。需要长期保留的研究证据应显式整理到
  `issues/`、`research/` 或约定的数据目录。

## 5. 远端证据回收

- 禁止对 `codex_runs/<run>/` 整体执行 `scp -r`。远端 `repo/OSWorld` 可能是符号链接，
  递归 SCP 会跟随链接并下载 VMware 磁盘，符号链接环还会产生无限同名嵌套。
- 使用 `ops/pull_remote_run_evidence.ps1`，只回收 `results/` 和运行根目录的日志、退出码与
  起止时间。工具在传输前拒绝结果树中的符号链接和超过默认 5 GiB 的证据，并检查本地剩余空间。
- 代码部署包与远端 `repo/` 不属于运行证据；需要核对源码时保存提交号、补丁或小型源码包，
  不把远端工作副本整体拉回 `artifacts/`。
