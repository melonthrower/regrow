# foldcheck13 "全开" — 打开所有【已验证/真开关】的休眠修复 (2026-07-07)
#   GUIWALK_REVIEW_DEBUG=1    → debug agent 落盘 (_review_debug.jsonl)
#   GUIWALK_LEDGER_FRONTIER=1 → ledger 权威前沿【早停修复】+ ledger 只取 navigation
#                               (剔 display/shallow 表单字段;foldcheck12 验过触发 9 次)
#   GUIWALK_REGION_IDENTITY=1 → 区块集合身份 OBSERVER(只记分歧,0 行为风险)
#   GUIWALK_SCROLL_MAP=1      → VLM 引导滚动伺服(_scrollmap 单测 ALL PASS;真机首跑=重点观察项)
# 不开: --stitch_node_image(与 --region_dedup 互斥 if/else + 桌面不拼帧 → 翻开=静默关掉
#        region_dedup 且啥也不拼,是回归不是开;perceive-once 桌面需真接线,单独做)
# 用法: .\run_visual_foldcheck13_allon.ps1

$env:PYTHONPATH = "$env:PYTHONPATH;."
$env:API_KEY = "<REDACTED_CREDENTIAL>"
$env:API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:GUIWALK_REVIEW_DEBUG = "1"
$env:GUIWALK_LEDGER_FRONTIER = "1"
$env:GUIWALK_REGION_IDENTITY = "1"
$env:GUIWALK_SCROLL_MAP = "1"

python gui_rewalk/run_visual_traversal.py `
    --vm_provider "vmware" `
    --path_to_vm "C:\Users\Admin\Desktop\GUI agent\mywork\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx" `
    --app_name setting `
    --model Qwen `
    --model_version qwen3.7-plus `
    --ocr_model_path "OmniParser/weights/icon_detect/model.pt" `
    --vlm_grounding `
    --region_dedup `
    --max_states 30 `
    --max_actions 150 `
    --result_dir result_foldcheck13_allon
