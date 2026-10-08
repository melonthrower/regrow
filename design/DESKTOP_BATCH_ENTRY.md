# 桌面批次固定入口

本设计对应 `tools/run_stepwise.py`，替代每批临时编写的桌面 prepare/run/resume 脚本。已完成聚焦与有限实机验收，具体范围见月度日志；旧冻结运行不自动换源码。

```sh
python tools/run_stepwise.py --new /path/to/runtime/artifacts/runs/new_batch \
  --template-run /path/to/existing/run --max-calls 100 \
  --clear-app-data --restart-container
python tools/run_stepwise.py --status /path/to/new_batch/batch.json
python tools/run_stepwise.py --resume /path/to/new_batch/batch.json
```

- `--new` 只新建图，默认保留应用数据；输出必须是运行仓库内的新目录。`--template-run` 只提供原有设备、应用、范围配置，不复制知识图。
- `--clear-app-data`、`--restart-container` 均为显式新建参数，续跑禁止使用。当前数据重置只支持 GNOME Clocks：核对专用缓存目录、停止应用、备份并校验 dconf、清空后读回；未知目录或其他应用明确拒绝，不猜数据路径。不删除 Docker 卷。
- `--resume` 使用已有 `run.json` 或本入口的 `batch.json`，保持冻结源码、pending、原始请求/回复和动作回执；额度为原总上限减 run 的 durable 实际调用数，未返回的已发送请求不退款。纠错、恢复、总结仍计入原预算。
- `--status` 不调用模型、不抓图、不修改记录；同时检查用户服务与原生账本。准备中、等待模型、等待截图、已推进、结束、失败及进程消失后的中断分别显示，进程存在不等于动作成功。

启动通过 systemd 用户服务，使用当前用户已有的 Docker 组成员资格；不依赖 Codex 临时执行会话。用户服务管理器仍需可用，不承诺机器重启后自动续跑。

实际后台服务先锁设备、核对冻结源/依赖，再执行有时限的 Docker、真实显示截图、控制器及模型配置预检。预检失败不清数据、不调用 Luna。只有通过预检才执行新建准备或正常续接。新建准备中途失败保留全部证据，拒绝自动重复破坏性准备；须先核查失败再建立新批次。

`run_source.session_command → run_progress_session → run_task_step` 仍是唯一原生执行链。局部 6 HTTP/6 GUI 保护、正常 pending 结算和注册路径不变。新入口不加入模型角色、不修改任务提示，不依据截图或进程状态宣称业务操作成功。

## 文件职责及验证边界

| 文件 | 职责 |
|---|---|
| `tools/run_stepwise.py` | 固定公开命令 |
| `experiments/clock_manual_20260919/batch_launch.py` | CLI、新配置及源码冻结、持久服务启动、只读状态 |
| 同目录 `batch_environment.py` | 有界预检、当前支持的应用数据备份/重置及新图初始化 |
| 同目录 `batch_runtime.py` | 设备锁、源码核验、剩余额度、原生会话子进程与退出记录 |
| `tests/test_batch_entry.py` | 新建/续跑边界、计账、防重复启动、故障状态与备份次序 |

每批保存配置、冻结源码、共享依赖摘要和副本；每次启动另存 `launches/<id>/`，含启动命令、源摘要、预检截图、会话日志、原 manifest 和 worker 状态。原生 `session-*`、calls、attempts、快照继续保持原格式。应用备份不进入源码或公开交付。

接受案例：既有 38 次调用后续跑仅余 62；旧进程消失显示 interrupted；Docker 权限失败在实际服务预检中退出；忙设备拒绝新建；新建可选择保留数据或备份后清空；启动后须看到正常框架原请求、原答及登记，而不只检查 service active。离线、保存帧模型验证和实机验证分别报告。

本批接受证据：31项聚焦检查；独立新桌面实际备份/清空/重启，正常粗发现和局部清点2次Luna调用登记首屏；完整真实记录副本续接1次Luna调用登记9项任务。0遍历GUI，初始设置激活另记。耗尽预算后重启入口不新增调用，busy设备实际拒绝。未验证业务导航或动作执行中断恢复；后者仍沿旧原生合同。
