[CmdletBinding()]
param(
    [ValidateSet("setting", "calculator", "vs_code")]
    [string]$AppName = "setting",
    [string]$PythonExe = "python",
    [string]$VmPath = "",
    [int]$MaxStates = 20,
    [int]$MaxActions = 80,
    [string]$Model = "Qwen",
    [string]$ModelVersion = "qwen3-vl-plus",
    [switch]$RequireComplete,
    [switch]$NoLiveMonitor
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

if (-not $VmPath) {
    $VmPath = Join-Path $repoRoot "OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx"
}
$ocrModel = Join-Path $repoRoot "OmniParser\weights\icon_detect\model.pt"

foreach ($requiredPath in @($VmPath, $ocrModel)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file is missing: $requiredPath. See DEPLOY_LOCAL.md."
    }
}
if (-not $env:DASHSCOPE_API_KEY) {
    throw "Set DASHSCOPE_API_KEY in this PowerShell session before running."
}

$env:PYTHONPATH = "$repoRoot;$repoRoot\OSWorld" +
    $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })

$runArgs = @(
    "-B",
    "gui_rewalk/run_visual_traversal.py",
    "--vm_provider", "vmware",
    "--path_to_vm", $VmPath,
    "--app_name", $AppName,
    "--model", $Model,
    "--model_version", $ModelVersion,
    "--ocr_model_path", $ocrModel,
    "--vlm_grounding",
    "--region_dedup",
    "--max_states", $MaxStates,
    "--max_actions", $MaxActions,
    "--result_dir", "artifacts/runs/local"
)
if ($RequireComplete) { $runArgs += "--require_complete" }
if ($NoLiveMonitor) { $runArgs += "--no_live_monitor" }

& $PythonExe @runArgs
exit $LASTEXITCODE
