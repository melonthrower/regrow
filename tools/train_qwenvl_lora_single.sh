#!/usr/bin/env bash
# 单卡(RTX 5090 32G) Qwen2.5-VL-7B LoRA, ms-swift, 数据=GUI agent 采集轨迹
set -euo pipefail
export PATH=/root/miniconda3/bin:$PATH
export USE_MODELSCOPE_HUB=1                 # 基座从 ModelScope 国内直连拉
export MAX_PIXELS=451584                  # 限制每图 vision token (~576), 1280x800->~850x531, 防 OOM
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export MODELSCOPE_CACHE=/root/autodl-tmp/modelscope_cache
export CUDA_VISIBLE_DEVICES=0
export NPROC_PER_NODE=1
cd /root/autodl-tmp/mywork

swift sft \
    --model Qwen/Qwen2.5-VL-7B-Instruct \
    --model_type qwen2_5_vl \
    --dataset data/sft/train.jsonl \
    --val_dataset data/sft/val.jsonl \
    --tuner_type lora \
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
    --max_length 2048 \
    --gradient_checkpointing true \
    --attn_impl sdpa \
    --eval_steps 50 \
    --save_steps 50 \
    --save_total_limit 3 \
    --logging_steps 5 \
    --dataloader_num_workers 4 \
    --output_dir output/qwen2_5_vl_settings_lora

echo "[done] checkpoints in /root/autodl-tmp/mywork/output/qwen2_5_vl_settings_lora"
