# 视觉主导遍历 (路 B) - VS Code (code)
# VLM + OmniParser，不依赖 A11y。用法: .\run_visual_vscode.ps1
#
# 目的 (2026-07-09):
#   遍历本地真实 VM 的 VS Code，记录问题出现在哪(已知: popup menu-item 回放失败
#   → 大量节点标不可达、交互元素覆盖率低，见 memory vscode-traversal-low-coverage)。
#   本轮用当前工作区代码(含计数器账本口径修 + 所在页面名显示)全新跑。
#
# 布局: VS Code = 活动栏 + 侧栏 + 编辑器 (主从) → 必须带
#   --vlm_grounding --region_dedup (否则到达帧不重感知，整应用塌成 1 节点)。
# 模型: DashScope Qwen(compatible-mode)；本地去 --enable_thinking(大图超时)。

$env:PYTHONPATH = "$env:PYTHONPATH;.;OSWorld"
if (-not $env:API_KEY) {
    $env:API_KEY = $env:DASHSCOPE_API_KEY
}
if (-not $env:API_KEY) {
    throw "Set API_KEY or DASHSCOPE_API_KEY before running this script."
}
if (-not $env:API_BASE_URL) {
    $env:API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
}

& "C:\Users\Admin\miniconda3\envs\guiwalk\python.exe" gui_rewalk/run_visual_traversal.py `
    --vm_provider "vmware" `
    --path_to_vm "C:\Users\Admin\Desktop\GUI agent\mywork\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx" `
    --app_name vs_code `
    --model Qwen `
    --model_version qwen3-vl-plus `
    --ocr_model_path "OmniParser/weights/icon_detect/model.pt" `
    --vlm_grounding `
    --region_dedup `
    --max_states 40 `
    --max_actions 150 `
    --result_dir result_visual_vscode
