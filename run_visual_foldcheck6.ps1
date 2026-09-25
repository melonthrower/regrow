# foldcheck6 — 短验证跑 (2026-07-06): 验证 mis-click 三层防线 + DEBUG-agent 落盘
#   三层防线: (a) 侧栏名字去重 (b) 小区块 OCR 核名 (c) 出区块守卫(_region_guard_reject)
#   GUIWALK_REVIEW_DEBUG=1 → <result_dir>/.../ _review_debug.jsonl (逐节点 review + 点飞事件)
# 用法: .\run_visual_foldcheck6.ps1

$env:PYTHONPATH = "$env:PYTHONPATH;."
$env:API_KEY = "<REDACTED_CREDENTIAL>"
$env:API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:GUIWALK_REVIEW_DEBUG = "1"          # ← review agent 变 debug agent

python gui_rewalk/run_visual_traversal.py `
    --vm_provider "vmware" `
    --path_to_vm "C:\Users\Admin\Desktop\GUI agent\mywork\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx" `
    --app_name setting `
    --model Qwen `
    --model_version qwen3.7-plus `
    --ocr_model_path "OmniParser/weights/icon_detect/model.pt" `
    --vlm_grounding `
    --region_dedup `
    --max_states 20 `
    --max_actions 60 `
    --result_dir result_foldcheck6
