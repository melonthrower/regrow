#!/usr/bin/env bash
# Desktop pure-visual (a11y-free + VLM grounding) traversal QUEUE for js1.
#
# Mirrors deploy-asr's mobile queue, but "restart emulator" -> "recreate docker
# container": every run_visual_traversal invocation spins a FRESH container that
# mounts /tmp/System_seeded.qcow2 read-only, so each app starts from the SEEDED
# init state = the desktop equivalent of "revert to snapshot". CPU mode so it
# never contends for the GPU. Docker provider auto-allocates host ports under a
# FileLock (~/mytmp/docker_port_allocation.lck), so parallel workers are safe.
#
# Container hygiene: run_visual_traversal now calls env.close() in a finally
# (patched 2026-06-30), so a normally-finished or errored app releases its
# container. The EXIT trap below sweeps any leftovers (e.g. a timeout-killed app)
# but ONLY containers whose mount source matches System*.qcow2 (== ours; never
# touches knowu_bench / verl2 / other images — see ops/container_ops_log.md).
#
# Usage:  setsid bash ops/run_desktop_queue_traverse.sh > _vis_queue.log 2>&1 < /dev/null &
# Env overrides: NWORKERS, MAX_STATES, MAX_ACTIONS, STAGGER, PER_APP_TIMEOUT, APPS_OVERRIDE
set -u

REPO=/data/shenghonghui/GUI-ReWalk-mobile
cd "$REPO"
source ~/.guiwalk_secrets
export PYTHONPATH=.:OSWorld
export CUDA_VISIBLE_DEVICES=""          # CPU mode: do not grab a GPU
PY=/data/shenghonghui/miniconda3/envs/guiwalk/bin/python
mkdir -p ~/mytmp                          # docker provider port-allocation lock dir

QCOW=/tmp/System_seeded.qcow2             # the SEEDED desktop VM (== ours)
MAX_STATES="${MAX_STATES:-1000}"
MAX_ACTIONS="${MAX_ACTIONS:-2000}"
NWORKERS="${NWORKERS:-6}"
STAGGER="${STAGGER:-45}"                  # delay between worker launches (boot I/O)
PER_APP_TIMEOUT="${PER_APP_TIMEOUT:-14400}"   # 4h hard cap per app (safety net)
STAMP=$(date +%y%m%d_%H%M%S)
LOGDIR="$REPO/_vis_queue/$STAMP"
mkdir -p "$LOGDIR"
QLOG="$LOGDIR/_queue.log"

# OSWorld 10-domain aligned desktop apps. Names MUST match APP_BINARY_MAP keys.
# (setting/Chrome/GIMP/Calc/Writer/Impress/VLC/Thunderbird/VSCode/Files/Terminal)
if [ -n "${APPS_OVERRIDE:-}" ]; then
  IFS='|' read -ra APPS <<< "$APPS_OVERRIDE"
else
  APPS=(
    "setting" "Chrome" "GNU image" "LibreOffice calc" "LibreOffice writer"
    "libreoffice impress" "vlc" "thunderbird" "vs_code" "files" "terminal"
  )
fi

log() { echo "[$(date +%T)] $*" | tee -a "$QLOG"; }

cleanup() {
  log "teardown: removing leftover System*.qcow2 containers (ours only)"
  for c in $(docker ps -aq 2>/dev/null); do
    m=$(docker inspect --format '{{range .Mounts}}{{.Source}} {{end}}' "$c" 2>/dev/null)
    if echo "$m" | grep -q "System.*qcow2"; then
      docker rm -f "$c" >/dev/null 2>&1 && log "  removed $c"
    fi
  done
}
trap cleanup EXIT INT TERM

run_one() {
  local app="$1" wid="$2"
  local safe; safe=$(echo "$app" | tr ' /' '__')
  log "w$wid START  $app  (fresh container = seed state)"
  timeout "$PER_APP_TIMEOUT" "$PY" gui_rewalk/run_visual_traversal.py \
    --vm_provider docker --path_to_vm "$QCOW" \
    --app_name "$app" --vlm_grounding --stitch_node_image \
    --result_dir graphs --model Qwen --model_version qwen3.7-plus \
    --max_states "$MAX_STATES" --max_actions "$MAX_ACTIONS" \
    > "$LOGDIR/${safe}.log" 2>&1
  local rc=$?
  log "w$wid DONE   $app  rc=$rc"
}

worker() {
  local wid="$1" i
  for i in "${!APPS[@]}"; do
    if (( i % NWORKERS == wid )); then
      run_one "${APPS[$i]}" "$wid"
    fi
  done
  log "w$wid: all assigned apps done"
}

log "QUEUE START $STAMP : ${#APPS[@]} apps / $NWORKERS workers / states=$MAX_STATES actions=$MAX_ACTIONS"
log "apps: ${APPS[*]}"
for w in $(seq 0 $((NWORKERS-1))); do
  worker "$w" &
  sleep "$STAGGER"
done
wait
log "ALL WORKERS DONE"
