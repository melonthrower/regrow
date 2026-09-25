# 视觉主导遍历 (路 B) - Calculator 应用
# VLM + OmniParser，不依赖 A11y
# 用法: .\run_visual_calculator.ps1
#
# 注 (2026-07-03 修正):
#   1. VM 路径改为 mywork 下真实位置 —— 旧 GUI-ReWalk 目录已不存在(启动报"找不到该虚拟机")。
#   2. 模型改用 DashScope Qwen(compatible-mode)—— 本地访问火山引擎 ARK 常整轮超时
#      (3/3 timeout → 只能 caption fallback,数据无效)。DashScope key 见 $env:DASHSCOPE_API_KEY。

$env:PYTHONPATH = "$env:PYTHONPATH;."
if (-not $env:API_KEY) {
    $env:API_KEY = $env:DASHSCOPE_API_KEY
}
if (-not $env:API_KEY) {
    throw "Set API_KEY or DASHSCOPE_API_KEY before running this script."
}
if (-not $env:API_BASE_URL) {
    $env:API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
}

python gui_rewalk/run_visual_traversal.py `
    --vm_provider "vmware" `
    --path_to_vm "C:\Users\Admin\Desktop\GUI agent\mywork\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx" `
    --app_name calculator `
    --model Qwen `
    --model_version qwen3-vl-plus `
    --ocr_model_path "OmniParser/weights/icon_detect/model.pt" `
    --max_states 30 `
    --max_actions 100 `
    --enable_thinking `
    --result_dir result_visual

# 仅验证感知层(不开虚拟机，对单张截图跑 YOLO+VLM 命名):
#   python gui_rewalk/run_visual_traversal.py --perception-only `
#       --image <截图路径> --ocr_model_path "OmniParser/weights/icon_detect/model.pt" `
#       --result_dir result_visual
