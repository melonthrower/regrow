#!/usr/bin/env bash
# 隔夜全自动编排(无人值守)。链路:
#   stage1 等当前队列 q_master.log 跑完
#   stage2 清模拟器 → 重跑「修复版」队列(settle-delay+per-app超时) -> q_master2.log → 等完
#   stage3 对每个 >=3 节点的新图跑功能合成(run_capability_synth) -> page_capabilities.json
# 全程写 ~/overnight.log;功能合成细节写 ~/synth.log。
set -u
cd /home/shenghonghui/GUI-ReWalk-mobile
source ~/.guiwalk_secrets 2>/dev/null
export ANDROID_SDK_ROOT=$HOME/android-sdk ANDROID_HOME=$HOME/android-sdk
export LD_LIBRARY_PATH=$HOME/miniconda3/envs/guiwalk-android/lib
export PATH=$HOME/android-sdk/platform-tools:$HOME/android-sdk/emulator:$PATH
export PYTHONPATH=.:OSWorld PYTHONUTF8=1
PY=$HOME/miniconda3/envs/guiwalk-android/bin/python
LOG=$HOME/overnight.log
log(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG"; }

clean_emus(){ for p in 5612 5614 5616 5618 5620 5622 5624 5626; do pkill -9 -f "[-]port $p" 2>/dev/null; done; sleep 8; }

# 等待某队列跑完: ALL DONE 出现, 或「无遍历进程 且 队列空」连续 2 次(防卡死)
wait_done(){
  local ml=$1 dry=0
  while true; do
    grep -q "ALL DONE" "$ml" 2>/dev/null && return 0
    local p q
    p=$(pgrep -c -f "[r]un_visual_traversal.py" 2>/dev/null); p=${p:-9}
    q=$(wc -l < /tmp/trav_queue.txt 2>/dev/null); q=${q:-9}
    if [ "$p" -eq 0 ] && [ "$q" -eq 0 ]; then dry=$((dry+1)); else dry=0; fi
    [ "$dry" -ge 2 ] && return 0
    sleep 90
  done
}

log "===== OVERNIGHT START (pid $$) ====="

log "stage1: 等当前队列 q_master.log 跑完..."
wait_done "$HOME/GUI-ReWalk-mobile/q_master.log"
log "stage1 done. 当前各 app 节点数:"
for g in graphs/$(date +%Y%m%d)/*/graph.json; do [ -f "$g" ] && log "   $(basename "$(dirname "$g")"): $(grep -o '"state_id"' "$g" 2>/dev/null | wc -l)"; done
clean_emus

log "stage2: 重跑修复版队列 -> q_master2.log"
setsid bash -c "cd $HOME/GUI-ReWalk-mobile && ./ops/run_mobile_queue_traverse.sh > q_master2.log 2>&1" < /dev/null &
# 等队列真正起来(遍历进程出现)再 wait, 防误判已完成
for i in $(seq 1 50); do [ "$(pgrep -c -f '[r]un_visual_traversal.py' 2>/dev/null)" -gt 0 ] && break; sleep 10; done
log "stage2 队列已启动, 等跑完..."
wait_done "$HOME/GUI-ReWalk-mobile/q_master2.log"
log "stage2 done. 重跑各 app 节点数:"
for g in graphs/$(date +%Y%m%d)/*/graph.json; do [ -f "$g" ] && log "   $(basename "$(dirname "$g")"): $(grep -o '"state_id"' "$g" 2>/dev/null | wc -l)"; done
clean_emus

log "stage3: 功能合成(近14h内 >=3 节点的图)"
find graphs -name graph.json -newermt "-14 hours" 2>/dev/null | sort | while read -r g; do
  dir=$(dirname "$g"); n=$(grep -o '"state_id"' "$g" 2>/dev/null | wc -l)
  if [ "${n:-0}" -lt 3 ]; then log "   synth skip $(basename "$dir") (${n} nodes)"; continue; fi
  log "   synth $(basename "$dir") (${n} nodes)..."
  if timeout 1200 $PY gui_rewalk/run_capability_synth.py --graph_path "$g" --node_dir "$dir/node_artifacts" --model Qwen >> "$HOME/synth.log" 2>&1; then
    cap=$(grep -o '"capabilities"' "$dir"/node_artifacts/*/page_capabilities.json 2>/dev/null | wc -l)
    log "   synth OK $(basename "$dir")"
  else
    log "   synth FAIL $(basename "$dir") (见 synth.log)"
  fi
done
log "采集阶段已暂停：等待基于视觉遍历契约的新执行器实现。"
log "===== OVERNIGHT ALL DONE ====="
