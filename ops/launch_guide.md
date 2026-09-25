# 启动手册 (Launch Guide)

> 各 pipeline 的启动脚本 + 用法 + 输出目录约定。**以后启动直接查这里,别再 grep 找脚本。**
> 配套: [apps_to_explore.md](apps_to_explore.md)(待探索应用清单)。

## 两台部署机

| 机器 | 用途 | SSH | 仓库 | conda env |
|---|---|---|---|---|
| **deploy-asr** | 移动端(模拟器) | `ssh deploy-asr` (<PRIVATE_HOST>:10022) | `~/GUI-ReWalk-mobile` | `guiwalk-android` (py3.11) |
| **js1** | 桌面端(docker VM) | `ssh -p 31400 shenghonghui@js1.blockelite.cn` | `/data/shenghonghui/GUI-ReWalk-mobile` | `guiwalk` |

- key 存各机 `~/.guiwalk_secrets` (chmod 600),脚本 `source` 它拿 `DASHSCOPE_API_KEY`。
- 后台启动统一用 `setsid bash -c '...' < /dev/null &`(普通 nohup 会被 SSH 断开杀掉)。

---

## 阶段1:功能探索遍历(图)

### 移动端 — 8 路并发,纯视觉(VLM grounding + 长图拼接)
```bash
ssh deploy-asr
cd ~/GUI-ReWalk-mobile
setsid bash -c './ops/run_mobile_8route_traverse.sh > mob8.log 2>&1' < /dev/null &
tail -f traverse_8route_*.log          # 进度
ls graphs/$(date +%Y%m%d)/             # 各 app 的图
```
- 脚本: [`ops/run_mobile_8route_traverse.sh`](run_mobile_8route_traverse.sh)
- 模拟器: `Small_Phone_seeded` 只读克隆,端口 5612~5626(+grpc 3000),**GPU 1/2/5**。
- 单 app 手动跑(内层 runner): `./_run_vis.sh "<app>" <out_dir> <console> <grpc> <maxS> <maxA> --vlm_grounding --stitch_node_image`
  - ⚠️ `_run_vis.sh` 默认**不带** grounding/stitch(靠第 7+ 参透传),必须显式补 `--vlm_grounding --stitch_node_image`。
- app_name 可用显示名(`"simple gallery pro"`),`config._normalize_app_key` 会归一化到包名(空格/下划线/大小写都认)。新应用加包名映射在 `gui_rewalk/src/config/config.py:APP_PACKAGE_MAP`。

### 桌面端 — custom/docker VM(纯视觉, 同一引擎)
```bash
ssh -p 31400 shenghonghui@js1.blockelite.cn
cd /data/shenghonghui/GUI-ReWalk-mobile
# 单 app: run_visual_traversal.py --vm_provider docker --path_to_vm /tmp/System.qcow2 \
#   --app_name setting --vlm_grounding --stitch_node_image --result_dir graphs
```
- 桌面 VM = `/tmp/System.qcow2`(本地真实 Ubuntu 桌面,装好应用)。docker provider 只读挂载,容器重启=回 init_state。

---

## 阶段4:指令实机执行采集(轨迹) — A11y 框架,勿动其策略

### 移动端采集
脚本模板: `_run_settings1200.sh`
```bash
python gui_rewalk/run_parallel_collect.py --phase collect --provider android \
  --result_glob 'result_android_d21_verify' --total 1200 \
  --parallel 5 --chunk 8 --launch_stagger 30 \
  --platform mobile --date <批次名> --model Qwen --max_steps 12 --android_base_port 5568
```

### 桌面端采集 — 6 路
脚本模板: `_run_partest.sh`
```bash
python gui_rewalk/run_parallel_collect.py --phase all --provider docker \
  --path_to_vm /tmp/System.qcow2 --extra_result <result_dir> \
  --only_app setting --per_app 10 --parallel 6 --chunk 5 --launch_stagger 20 \
  --platform OS --date <批次名> --model Qwen
```
- `--parallel N` = N 路并发 docker VM(桌面 6 路即 `--parallel 6`)。

---

## 输出目录约定

| 类型 | 路径 |
|---|---|
| 图(遍历) | `graphs/<YYYYMMDD>/<app>/`  (graph.json + node_artifacts/ + screenshots/) |
| 轨迹(采集) | `collections/<platform>/<date>/<app>/episodes/<EP_id>/`  (step*.png + trajectory.json + meta.json) |
| 旧式图 | `result_*/<app>_<时间戳>/graph.json`(历史散落,逐步迁到 graphs/) |

## 历史数据登记
- **移动 settings 1000 条** = `deploy-asr:~/GUI-ReWalk-mobile/collections/mobile/260624m/android_settings/`(1.4G)。
  ⚠️ 此批为**帧串号污染批**(并发采集观测交叉,数据不可信),已标"不作数",待复核后重采。
- 移动 settings 1150 条 = `collections/mobile/settings1200/android_settings/`(2.0G)。
- 桌面多应用采集 = `js1:collections/OS/260624d/`(GNU image/inkscape/LibreOffice/rhythmbox/setting/shotwell/transmission/vlc 等 9 app)。

## 安全约束(硬性)
- **默认 CPU 模式、不用显卡**(grounding 算力在 DashScope 云端)→ 天然不抢卡。仅当手动启用 GPU 模式(脚本里 `CVD=<卡号>`)时,才需 `nvidia-smi` 复核、只挑空闲卡(别人常在 deploy-asr 的 3/4/6/7 训练)。
- 只动**自己起的**模拟器/容器:移动端保留 5554(常驻 base)/5574(种子可写);js1 上 `knowu_bench_*`、`nguizishu` 是别人的,勿碰。
- 登录类 App 用**测试/小号**;国内 App 不进 `pm clear` 白名单(会丢登录态)。

---

## 启动踩坑教训(2026-06-30 实战,务必避免重复)

> 当晚起 8 路移动遍历,连踩 6 坑。下面每条 = 症状 → 根因 → 修法。

1. **第三方 app 秒退、图 0 节点** —— 日志 `WARNING desktopenv.graph.mobile: launch_app: 'tasks' not in APP_PACKAGE_MAP`。
   根因: `config.py:APP_PACKAGE_MAP` 只有系统/国内 app,缺 android_world 第三方;且批次用显示名 `"simple gallery pro"`(带空格)对不上下划线 key。
   修: 补全 16 个第三方映射 + 新增 `_normalize_app_key`/`_resolve_app_entry`(空格/下划线/大小写归一化)。**加新 app 必先在此登记包名。**

2. **只读模拟器全起不来** —— `emu_<port>.log` 报 `ERROR | Another emulator instance is running. Please close it or run all emulators with -read-only flag.`
   根因: **种子「可写」实例(常驻 5574,无 `-read-only`)锁死了 AVD**,只读克隆拿不到锁。
   修: 启动前 `pkill -9 -f "port 5574"`(脚本已内置前置守卫)。种子快照已落盘,kill 无损。**绝不 kill 5554(base)。**

3. **种子数据丢失/跑成 base** —— 5612 上跑的是 `Small_Phone`(base)不是 `Small_Phone_seeded`。
   根因: `run_visual_traversal` **没传 `--avd_name`** → env 自己用默认 AVD(`Small_Phone`)拉了个新模拟器。
   修: 必传 `--avd_name Small_Phone_seeded`。

4. **以为在抢显卡,其实没有** —— `nvidia-smi --query-compute-apps` 里一堆 python 各吃 ~7.8GB。
   根因: 那些是**别人的**进程(`/proc/<pid>/environ` 读不了=非本人所有,误判成自己)。
   核实法: `pgrep -f "[r]un_visual_traversal"` 取**自己** PID,核对**不在** compute-apps 列表里、`CUDA_VISIBLE_DEVICES` 为空。本批纯 CPU(grounding 算力在 DashScope 云端,YOLO/OCR 只是 CPU 兜底)→ **零 GPU**。

5. **`pkill -f` 把自己这条 ssh 也杀了** —— 命令 exit 255,清理只跑一半。
   根因: `pkill -f run_visual_traversal` 的模式字符串出现在**当前 shell 自己的 cmdline** 里 → 自杀。
   修: 用 `[r]un_visual_traversal` 括号技巧(正则匹配 `run...`,但自身 cmdline 是 `[r]un...` 不匹配)。

6. **`adb emu kill` 在高负载下卡死** —— ssh 超时 255。
   修: 改用 `pkill -9 -f "port <N>"`(瞬时、按 qemu argv 精确匹配单个端口,不碰 5554)。

**起飞前固定两查**(默认 **CPU 模式,不碰显卡 → 无需查 GPU**):① `ss -ltn` 查目标端口空;② `pgrep -af qemu-system` 确认只有自己的模拟器(留 5554 / 勿碰别人 docker)。⚠️ 仅当手动把脚本里 `CVD=` 改成 GPU 卡号(罕见)时,才需先 `nvidia-smi` 找空闲卡。

---

## 部署同步记录

### 2026-07-10 — 本地 working tree 同步到 js1

- 源:本地 `chore/dead-code-sweep`，HEAD `f7aa5c9e`，包含当时尚未提交的框架改动。
- 目标:`js1:/data/shenghonghui/GUI-ReWalk-mobile`；同步前远端同样基于 `f7aa5c9e`，且没有运行中的框架进程。
- 范围:`gui_rewalk/`、`ops/`、`tools/`、`design/CURRENT_FRAMEWORK.md`、`design/modules/`。
- 策略:非删除式覆盖；保留远端独有的 `server_env.sh`、外部依赖、数据、结果、容器和服务器专用脚本。
- 回滚包:`/data/shenghonghui/deploy_backups/guiwalk_framework_pre_20260710_1135.tgz`。
- 一致性:265 个本地框架文件逐文件执行 `git hash-object`，本地/远端差异为 0。
- 离线验证:远端 `compileall`、四个主入口 `--help`、`test_visual_cache.py`、`test_region_click_ledger.py`、`test_resume_from_graph.py`、`test_edge_attribution.py`、`test_list_content_merge.py`、`test_overlay_split.py`、`test_d27_logic.py` 和 `git diff --check` 均通过。
- 未验证:未启动 VM/容器，未调用外部模型，未做真实桌面遍历或采集；因此本次不声称真机运行验证。
- 环境提示:`run_capability_collection.py --help` 期间出现 requests 依赖版本、Python 3.10 未来停止支持及缺少 AWS proxy 示例文件的警告，但入口退出码为 0。
