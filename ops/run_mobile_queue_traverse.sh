#!/usr/bin/env bash
# 队列式并发遍历: WORKERS 个 worker 从共享 app 队列取活, 做完一个立刻顶上下一个,
# 直到队列清空。**每个 app 开始前 kill+重启只读实例 = 恢复 default_boot 快照**
# (只读模式下 `snapshot load` 被禁用, 只能靠重启重载快照), 保证每个 app 都从
# 干净种子态起步、不被上个 app 的探索污染。纯 CPU 不抢卡。
#
# 用法: setsid bash -c 'cd ~/GUI-ReWalk-mobile && ./ops/run_mobile_queue_traverse.sh \
#         > q_master.log 2>&1' < /dev/null &
#   预算覆盖: --max-states 400 --max-actions 1600 --timeout-seconds 18000
#   等价环境变量: GUIWALK_MOBILE_MAX_STATES / GUIWALK_MOBILE_MAX_ACTIONS /
#     GUIWALK_MOBILE_TIMEOUT_SECONDS / GUIWALK_MOBILE_WORKERS / GUIWALK_MOBILE_RESULT_DIR
#   进度: tail -f q_master.log ; 各 app: tail -f logs/traverse_<run_id>/<app>_w*.log ; 结果: ls graphs/<date>/
set -u
cd /home/shenghonghui/GUI-ReWalk-mobile
source ~/.guiwalk_secrets 2>/dev/null
export ANDROID_SDK_ROOT=$HOME/android-sdk ANDROID_HOME=$HOME/android-sdk
export LD_LIBRARY_PATH=$HOME/miniconda3/envs/guiwalk-android/lib
export PATH=$HOME/android-sdk/platform-tools:$HOME/android-sdk/emulator:$PATH
export PYTHONPATH=.:OSWorld PYTHONUTF8=1
PY=$HOME/miniconda3/envs/guiwalk-android/bin/python
A=$HOME/android-sdk/platform-tools/adb
EMU=$HOME/android-sdk/emulator/emulator

WORKERS="${GUIWALK_MOBILE_WORKERS:-${WORKERS:-6}}"                 # 并发模拟器数; 端口 5612,5614,...
MAXS="${GUIWALK_MOBILE_MAX_STATES:-${MAXS:-300}}"                 # 每 app 状态上限
MAXA="${GUIWALK_MOBILE_MAX_ACTIONS:-${MAXA:-1200}}"               # 每 app 动作上限
TRAVERSE_TIMEOUT_SECONDS="${GUIWALK_MOBILE_TIMEOUT_SECONDS:-${TRAVERSE_TIMEOUT_SECONDS:-14400}}"
RESULT_DIR="${GUIWALK_MOBILE_RESULT_DIR:-${RESULT_DIR:-graphs}}"
QUEUE=/tmp/trav_queue.txt
LOCK=/tmp/trav_queue.lock

usage() {
  cat <<'EOF'
Usage: run_mobile_queue_traverse.sh [options]
  --workers N          Concurrent emulator workers (default: 6)
  --max-states N       Per-app state budget (default: 300)
  --max-actions N      Per-app action budget (default: 1200)
  --timeout-seconds N  Per-app wall-clock timeout (default: 14400)
  --result-dir PATH    Traversal result root (default: graphs)
EOF
}

require_positive_integer() {
  local name=$1 value=$2
  case "$value" in
    ''|*[!0-9]*) echo "[config] $name must be a positive integer: $value" >&2; return 2 ;;
  esac
  if [ "$value" -lt 1 ]; then
    echo "[config] $name must be a positive integer: $value" >&2
    return 2
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --workers|--max-states|--max-actions|--timeout-seconds|--result-dir)
      if [ "$#" -lt 2 ]; then
        echo "[config] missing value for $1" >&2
        usage >&2
        exit 2
      fi
      option=$1
      value=$2
      shift 2
      case "$option" in
        --workers) WORKERS=$value ;;
        --max-states) MAXS=$value ;;
        --max-actions) MAXA=$value ;;
        --timeout-seconds) TRAVERSE_TIMEOUT_SECONDS=$value ;;
        --result-dir) RESULT_DIR=$value ;;
      esac
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[config] unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

require_positive_integer WORKERS "$WORKERS" || exit $?
require_positive_integer MAXS "$MAXS" || exit $?
require_positive_integer MAXA "$MAXA" || exit $?
require_positive_integer TRAVERSE_TIMEOUT_SECONDS "$TRAVERSE_TIMEOUT_SECONDS" || exit $?
if [ -z "$RESULT_DIR" ]; then
  echo "[config] RESULT_DIR must not be empty" >&2
  exit 2
fi
# [2026-07-08 用户] 每次运行一个唯一 RUN_ID,日志放进 logs/<run_id>/ 子目录。
# 之前 traverse_q_<app>_w<wid>.log 无 run 标识、mode 覆盖,上一轮的旧日志会残留,
# 按 app 名 grep 时命中过期文件(clipper 日志里翻出的是上一轮 clock 的内容),
# 归因全乱。带 run_id 的子目录 = 每轮各 app 日志物理隔离,不会串。
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOGDIR="logs/traverse_${RUN_ID}"
mkdir -p "$LOGDIR"
echo "[run] RUN_ID=$RUN_ID  日志目录=$LOGDIR"
echo "[run] budget states=$MAXS actions=$MAXA timeout=${TRAVERSE_TIMEOUT_SECONDS}s result_dir=$RESULT_DIR"
: > "$LOCK"

# ── 全部待遍历 app 队列(种子型 + AOSP + 第三方; 没装的会被 focus-guard 优雅跳过)──
APPS=(
  android_settings android_files android_clock android_calculator android_contacts
  markor tasks "simple gallery pro" "simple calendar pro" "retro music"
  "pro expense" broccoli joplin "simple draw pro" audio_recorder clipper vlc
)
printf '%s\n' "${APPS[@]}" > "$QUEUE"
echo "[queue] ${#APPS[@]} 个 app, $WORKERS 个 worker"

# 前置守卫: 杀「可写」种子实例(常驻 5574)避免 AVD 锁; 不碰 5554(base)
pkill -9 -f "[-]port 5574" 2>/dev/null; sleep 2

# 原子取队首(flock 串行化, 防两 worker 抢同一 app)
next_app() {
  exec 200>>"$LOCK"; flock 200
  local a; a=$(head -n1 "$QUEUE" 2>/dev/null)
  [ -n "$a" ] && sed -i '1d' "$QUEUE"
  flock -u 200
  printf '%s' "$a"
}

boot_seeded() {  # kill 该端口旧实例 + 重启只读种子实例 = 恢复 default_boot 干净态
  local wid=$1 port=$2 grpc=$3
  pkill -9 -f "[-]port $port" 2>/dev/null; sleep 4
  setsid bash -c "$EMU -avd Small_Phone_seeded -no-window -no-audio -no-boot-anim \
      -gpu swiftshader_indirect -read-only -port $port -grpc $grpc \
      > ~/emu_q_$port.log 2>&1" < /dev/null &
  for t in $(seq 1 90); do
    if [ "$($A -s emulator-$port shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then
      sleep 25   # settle: 等 launcher/MediaStore 就绪 — 修 app 启动失败(calculator off-app)
      # [2026-07-08 用户] 抑制软键盘: config.ini 已声明 hw.keyboard=yes(不再随输入框
      # 自动弹软键盘); 这里再显式关掉"有硬键盘也显示软键盘",双保险。TYPE 走 `input text`
      # 直接注入,不依赖软键盘渲染,所以关掉不影响输入,只是不再遮挡/干扰页面身份识别
      # (修 tasks 这类因软键盘占屏被判'同页'而坍缩的问题)。best-effort,失败不影响遍历。
      $A -s emulator-$port shell settings put secure show_ime_with_hard_keyboard 0 2>/dev/null || true
      return 0   #         + 给媒体库重扫时间(music/gallery)
    fi
    sleep 3
  done
  return 1
}

worker() {
  local wid=$1 port=$2 grpc=$3
  local failed=0
  while true; do
    local app; app=$(next_app)
    [ -z "$app" ] && break
    local safe; safe=$(echo "$app" | tr ' ' '_')
    # ── 恢复快照: 每个 app 前 kill+重启只读实例, 重载 default_boot 干净种子态 ──
    echo "[w$wid:$port] 恢复快照(重启) -> 准备遍历 $app"
    if ! boot_seeded "$wid" "$port" "$grpc"; then
      echo "[w$wid:$port] boot 失败, 无法认证 $app"
      failed=1
      continue
    fi
    echo "[w$wid:$port] >>> 遍历 $app (干净种子态)"
    local rc=0
    CUDA_VISIBLE_DEVICES="" timeout "$TRAVERSE_TIMEOUT_SECONDS" "$PY" -u gui_rewalk/run_visual_traversal.py \
      --vm_provider android --avd_name Small_Phone_seeded --app_name "$app" \
      --android_console_port "$port" --android_grpc_port "$grpc" \
      --model Qwen --model_version qwen3.7-plus \
      --max_states "$MAXS" --max_actions "$MAXA" \
      --require_complete \
      --result_dir "$RESULT_DIR" --ocr_lang en --vlm_grounding --stitch_node_image \
      > "$LOGDIR/${safe}_w${wid}.log" 2>&1 || rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "[w$wid:$port] <<< 完整性认证通过 $app"
    else
      echo "[w$wid:$port] <<< 遍历/完整性认证失败 $app (exit=$rc, log=$LOGDIR/${safe}_w${wid}.log)"
      failed=1
    fi
  done
  pkill -9 -f "[-]port $port" 2>/dev/null
  echo "[w$wid:$port] 队列空, worker 退出"
  return "$failed"
}

PORT=5612
PIDS=()
for w in $(seq 1 "$WORKERS"); do
  worker "$w" "$PORT" "$((PORT + 3000))" &
  PIDS+=("$!")
  PORT=$((PORT + 2))
  sleep 25   # 错峰 boot, 减并发开机压力
done

FAILED=0
for pid in "${PIDS[@]}"; do
  if ! wait "$pid"; then
    FAILED=1
  fi
done

if [ "$FAILED" -ne 0 ]; then
  echo "[ALL INCOMPLETE] 队列已清空，至少一个 app 未通过完整性认证"
  exit 1
fi

echo "[ALL CERTIFIED] 队列已清空，全部 app 完整性认证通过"
