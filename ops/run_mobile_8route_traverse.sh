#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 移动端 8 路并发「功能探索遍历」(纯视觉 / route B, VLM grounding + 长图拼接)
#
#   平台机   : deploy-asr (<PRIVATE_HOST>:10022)
#   仓库     : ~/GUI-ReWalk-mobile   (conda env guiwalk-android, py3.11)
#   模拟器   : Small_Phone_seeded   (只读克隆, 灌好 6 app 数据)
#   输出     : graphs/<YYYYMMDD>/<app>/   ← ops 标准布局
#   日志     : traverse_8route_<app>.log  (仓库根)
#
# 安全约束 (用户硬性要求):
#   * 不抢卡: 共享机 8 卡常被别人训练占满 → 本批走 CPU 模式 (CUDA_VISIBLE_DEVICES="")。
#     开了 grounding 后 YOLO/OCR 只是极少触发的 fallback(真算力在 DashScope API),
#     CPU 完全够 → 零 GPU 占用。日后若有整块空卡, 把下方 CVD="" 改成 CVD=<idx>。
#   * 只起 5612~5626 端口的模拟器, 绝不碰 5554(常驻 base)/5574(种子可写)
#   * 仅运行视觉遍历；采集框架将在同一视觉图契约上另行实现。
#
# 用法:
#   setsid bash -c 'cd ~/GUI-ReWalk-mobile && ./ops/run_mobile_8route_traverse.sh \
#       > mob8.log 2>&1' < /dev/null &
#   # 进度: tail -f traverse_8route_*.log ; 结果: ls graphs/<date>/
#   # 收尾分裂自检: python tools/probe_d18_scroll_split.py graphs/<date>/<app>
# ─────────────────────────────────────────────────────────────────────────────
set -u
cd /home/shenghonghui/GUI-ReWalk-mobile
source ~/.guiwalk_secrets 2>/dev/null   # DASHSCOPE_API_KEY 等
export ANDROID_SDK_ROOT=$HOME/android-sdk ANDROID_HOME=$HOME/android-sdk
export LD_LIBRARY_PATH=$HOME/miniconda3/envs/guiwalk-android/lib
export PATH=$HOME/android-sdk/platform-tools:$HOME/android-sdk/emulator:$PATH
export PYTHONPATH=.:OSWorld PYTHONUTF8=1
PY=$HOME/miniconda3/envs/guiwalk-android/bin/python
A=$HOME/android-sdk/platform-tools/adb
EMU=$HOME/android-sdk/emulator/emulator

# 8 路应用: 5 个已灌数据(markor/tasks/gallery/calendar/music) + 2 个 android_world
# 新覆盖(pro expense/broccoli) + 1 个内置富 UI(clock)。app_name 用显示名,
# config 的 _normalize_app_key 会归一化到包名(空格/大小写/下划线都认)。
APPS=("markor" "tasks" "simple gallery pro" "simple calendar pro" \
      "retro music" "pro expense" "broccoli" "android_clock")
CVD=""                # CUDA_VISIBLE_DEVICES: ""=CPU(不抢卡); 有空卡时填 GPU 序号
MAXS=100; MAXA=300    # 每 app 状态/动作上限
PORT=5612; i=0

# 前置守卫: 干掉「可写」种子实例(常驻 5574)。它不带 -read-only → 锁住 AVD,
# 我们的只读克隆会报 "Another emulator instance is running"。种子快照已落盘,
# kill 它无损。不碰 5554(base)。pkill 按端口匹配 qemu argv, 不会误伤本脚本。
pkill -9 -f "port 5574" 2>/dev/null && { echo "[guard] killed writable seeded @5574"; sleep 4; }

for app in "${APPS[@]}"; do
  grpc=$((PORT + 3000))
  safe=$(echo "$app" | tr " " "_")
  echo "[route $i] app='$app' port=$PORT grpc=$grpc cvd='${CVD:-cpu}' -> graphs/<date>/$app"

  # 1) 起只读种子模拟器 (软件渲染, 不占 GPU 3D)
  setsid bash -c "$EMU -avd Small_Phone_seeded -no-window -no-audio -no-boot-anim \
      -gpu swiftshader_indirect -read-only -port $PORT -grpc $grpc \
      > ~/emu_$PORT.log 2>&1" < /dev/null &

  # 2) 等 boot_completed (最多 ~240s)
  for t in $(seq 1 80); do
    [ "$($A -s emulator-$PORT shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break
    sleep 3
  done

  # 3) 起视觉遍历 (grounding + 长图拼接, 输出 graphs/<date>/<app>/)
  setsid bash -c "CUDA_VISIBLE_DEVICES=\"$CVD\" $PY -u gui_rewalk/run_visual_traversal.py \
      --vm_provider android --avd_name Small_Phone_seeded --app_name \"$app\" \
      --android_console_port $PORT --android_grpc_port $grpc \
      --model Qwen --model_version qwen3.7-plus \
      --max_states $MAXS --max_actions $MAXA \
      --result_dir graphs --ocr_lang en \
      --vlm_grounding --stitch_node_image \
      > traverse_8route_$safe.log 2>&1" < /dev/null &

  PORT=$((PORT + 2)); i=$((i + 1)); sleep 20
done
echo "[done] 8 路移动视觉遍历已启动 (端口 5612~$((PORT-2)), CVD='${CVD:-cpu}')"
