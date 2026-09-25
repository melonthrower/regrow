# 视觉主导遍历 (路 B) - Settings (gnome-control-center)
# VLM + OmniParser，不依赖 A11y。
#
# 用法:
#   .\run_visual_setting.ps1
#   .\run_visual_setting.ps1 -MaxStates 400 -MaxActions 1600 -ResultDir result_custom
# 也可通过 GUIWALK_SETTINGS_MAX_STATES / GUIWALK_SETTINGS_MAX_ACTIONS /
# GUIWALK_SETTINGS_RESULT_DIR 覆盖默认值；显式 PowerShell 参数优先。
#
# 注 (2026-07-08):
#   1. 用当前工作区代码全新跑一轮 setting — 产出带 region_id 的可续跑底图
#      (旧 fc19/fc20 图不含 region_id，无法验证 tier-2 区块账本续跑)。
#   2. 模型 DashScope Qwen(compatible-mode)；本地跑去掉 --enable_thinking
#      (大图 grounding 常整轮超时)。见 memory local-visual-run-config。
#   3. 续跑: 本轮跑完后 .\run_visual_setting.ps1 之外，用
#      python gui_rewalk/run_visual_traversal.py ... --resume <本图 graph.json>
#   4. 图质量门禁: 默认 300/1200 是完整遍历预算上限；
#      --require_complete 必须通过完整性认证，否则本脚本传递非零退出码。

[CmdletBinding()]
param(
    [int]$MaxStates = 0,
    [int]$MaxActions = 0,
    [string]$ResultDir = ""
)

function Resolve-PositiveInteger {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [Parameter(Mandatory = $true)][int]$DefaultValue,
        [Parameter(Mandatory = $true)][bool]$WasExplicit,
        [Parameter(Mandatory = $true)][int]$ExplicitValue
    )

    if ($WasExplicit) {
        if ($ExplicitValue -lt 1) {
            throw "$Name must be a positive integer."
        }
        return $ExplicitValue
    }

    $raw = [Environment]::GetEnvironmentVariable($EnvironmentName)
    if (-not [string]::IsNullOrWhiteSpace($raw)) {
        $parsed = 0
        if (-not [int]::TryParse($raw, [ref]$parsed) -or $parsed -lt 1) {
            throw "$EnvironmentName must be a positive integer."
        }
        return $parsed
    }

    return $DefaultValue
}

$MaxStates = Resolve-PositiveInteger `
    -Name "MaxStates" `
    -EnvironmentName "GUIWALK_SETTINGS_MAX_STATES" `
    -DefaultValue 300 `
    -WasExplicit ($PSBoundParameters.ContainsKey("MaxStates")) `
    -ExplicitValue $MaxStates
$MaxActions = Resolve-PositiveInteger `
    -Name "MaxActions" `
    -EnvironmentName "GUIWALK_SETTINGS_MAX_ACTIONS" `
    -DefaultValue 1200 `
    -WasExplicit ($PSBoundParameters.ContainsKey("MaxActions")) `
    -ExplicitValue $MaxActions

if (-not $PSBoundParameters.ContainsKey("ResultDir")) {
    $ResultDir = $env:GUIWALK_SETTINGS_RESULT_DIR
}
if ([string]::IsNullOrWhiteSpace($ResultDir)) {
    $ResultDir = "result_visual_setting"
}

$env:PYTHONPATH = "$env:PYTHONPATH;.;OSWorld"

if (-not $env:DASHSCOPE_API_KEY) {
    throw "DASHSCOPE_API_KEY must be provided by the environment."
}

& "C:\Users\Admin\miniconda3\envs\guiwalk\python.exe" gui_rewalk/run_visual_traversal.py `
    --vm_provider "vmware" `
    --path_to_vm "C:\Users\Admin\Desktop\GUI agent\mywork\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx" `
    --app_name setting `
    --model Qwen `
    --model_version qwen3-vl-plus `
    --ocr_model_path "OmniParser/weights/icon_detect/model.pt" `
    --vlm_grounding `
    --region_dedup `
    --max_states $MaxStates `
    --max_actions $MaxActions `
    --require_complete `
    --result_dir $ResultDir

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
