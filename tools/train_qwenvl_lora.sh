#!/usr/bin/env bash
# =============================================================================
# train_qwenvl_lora.sh — 在 js1 (8×A100-80G) 上用 ms-swift 对 Qwen2.5-VL-7B
# 做 LoRA 微调, 训练数据来自 tools/export_sft_dataset.py 导出的 SFT 数据集。
#
# 前置 (一次性):
#   conda create -n guiwalk-sft python=3.11 -y && conda activate guiwalk-sft
#   pip install "ms-swift[llm]" -U          # ModelScope 出品, 国内直连不用代理
#   pip install qwen-vl-utils decord
#   # 基座权重走 ModelScope (默认), 不用挂 clash 代理
#
# 数据准备 (本地导出后传到服务器, 并重写图片路径):
#   # 本地:
#   python tools/export_sft_dataset.py --collections collections/OS --out data/sft \
#       --image_root_replace 'C:\Users\Admin\Desktop\GUI agent\mywork::/data/shenghonghui/GUI-ReWalk-mobile'
#   # 把 data/sft/*.jsonl 和 collections/ (截图) 一起 scp 到服务器同一相对结构下
#   #   scp -P 31400 -r data collections shenghonghui@js1.blockelite.cn:~/GUI-ReWalk-mobile/
#   # 注意: jsonl 里图片是绝对路径, 必须和服务器上真实路径一致
# =============================================================================
set -euo pipefail

export USE_MODELSCOPE_HUB=1          # 基座从 ModelScope 拉 (国内可直连)
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0,1}
NGPU=$(echo "$CUDA_VISIBLE_DEVICES" | awk -F',' '{print NF}')

DATA_DIR=${DATA_DIR:-data/sft}
OUT_DIR=${OUT_DIR:-output/qwen2_5_vl_settings_lora}

# 数据量小 (~300 条), LoRA + 冻结 ViT, 多跑几个 epoch。
NPROC_PER_NODE=$NGPU \
swift sft \
    --model Qwen/Qwen2.5-VL-7B-Instruct \
    --model_type qwen2_5_vl \
    --dataset "${DATA_DIR}/train.jsonl" \
    --val_dataset "${DATA_DIR}/val.jsonl" \
    --train_type lora \
    --lora_rank 16 \
    --lora_alpha 32 \
    --target_modules all-linear \
    --freeze_vit true \
    --torch_dtype bfloat16 \
    --num_train_epochs 5 \
    --per_device_train_batch_size 1 \
    --gradient_accumulation_steps 8 \
    --learning_rate 1e-4 \
    --warmup_ratio 0.05 \
    --max_length 8192 \
    --gradient_checkpointing true \
    --eval_steps 50 \
    --save_steps 50 \
    --save_total_limit 3 \
    --logging_steps 5 \
    --dataloader_num_workers 4 \
    --output_dir "${OUT_DIR}" \
    --deepspeed zero2

echo "[done] LoRA checkpoints in ${OUT_DIR}"
echo "合并权重 (可选, 用于部署):"
echo "  swift export --adapters ${OUT_DIR}/checkpoint-xxx --merge_lora true"
echo "快速验证 (单图推理):"
echo "  swift infer --adapters ${OUT_DIR}/checkpoint-xxx --stream true"
