#!/usr/bin/env bash
set -euo pipefail

# Optional local Qwen2.5-VL service for OSWorld. The smoke script can also use
# DashScope directly, so run this only when you intentionally want local GPUs.

ENV_NAME="${ENV_NAME:-qwen25vl-vllm}"
MODEL_PATH="${MODEL_PATH:-Qwen/Qwen2.5-VL-7B-Instruct}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen2.5-vl-7b-instruct}"
PORT="${PORT:-31425}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-}"
TP="${TP:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.85}"
LOG="${LOG:-vllm_qwen25vl_${PORT}.log}"

if [[ -z "$CUDA_VISIBLE_DEVICES" ]]; then
  echo "Set CUDA_VISIBLE_DEVICES to an idle GPU id before starting vLLM." >&2
  nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader || true
  exit 2
fi

if ! command -v conda >/dev/null 2>&1; then
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
fi

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  conda create -y -n "$ENV_NAME" python=3.11
fi

conda run -n "$ENV_NAME" python - <<'PY' || conda run -n "$ENV_NAME" pip install -U "vllm>=0.8.5" "transformers>=4.51.0" qwen-vl-utils accelerate
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("vllm") else 1)
PY

export CUDA_VISIBLE_DEVICES
export VLLM_USE_V1=1
echo "[vllm-qwen25vl] model=$MODEL_PATH served=$SERVED_MODEL_NAME port=$PORT cuda=$CUDA_VISIBLE_DEVICES tp=$TP"
setsid conda run -n "$ENV_NAME" \
  vllm serve "$MODEL_PATH" \
  --served-model-name "$SERVED_MODEL_NAME" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --tensor-parallel-size "$TP" \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --trust-remote-code \
  > "$LOG" 2>&1 < /dev/null &

echo "$!" > "vllm_qwen25vl_${PORT}.pid"
echo "Started PID $(cat "vllm_qwen25vl_${PORT}.pid"). Logs: $LOG"
echo "Use: export DASHSCOPE_BASE_URL=http://127.0.0.1:${PORT}/v1 DASHSCOPE_API_KEY=EMPTY MODEL=$SERVED_MODEL_NAME"
