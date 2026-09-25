#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/data/shenghonghui/GUI-ReWalk-mobile}"
PY="${PY:-/data/shenghonghui/miniconda3/envs/guiwalk/bin/python}"
VM="${VM:-/tmp/System_seeded_v2.qcow2}"
MODEL="${MODEL:-qwen2.5-vl-72b-instruct}"
META="${META:-OSWorld/evaluation_examples/test_small.json}"
LIMIT="${LIMIT:-1}"
MAX_STEPS="${MAX_STEPS:-1}"
RESULT_DIR="${RESULT_DIR:-results_qwen25vl_smoke}"

cd "$ROOT"
source "$HOME/.guiwalk_secrets" 2>/dev/null || true
export PYTHONPATH="$ROOT/OSWorld:$ROOT:${PYTHONPATH:-}"
export DASHSCOPE_BASE_URL="${DASHSCOPE_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"

mkdir -p logs
echo "[osworld-qwen25vl-smoke] root=$ROOT vm=$VM model=$MODEL meta=$META limit=$LIMIT max_steps=$MAX_STEPS"

"$PY" tools/run_osworld_qwen25vl_docker.py \
  --osworld_dir OSWorld \
  --provider_name docker \
  --path_to_vm "$VM" \
  --headless \
  --observation_type screenshot \
  --action_space pyautogui \
  --model "$MODEL" \
  --test_all_meta_path "$META" \
  --test_config_base_dir OSWorld/evaluation_examples \
  --limit "$LIMIT" \
  --max_steps "$MAX_STEPS" \
  --sleep_after_execution 3 \
  --client_password password \
  --result_dir "$RESULT_DIR" \
  --log_level INFO
