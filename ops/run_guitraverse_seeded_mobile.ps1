[CmdletBinding()]
param(
    [ValidateScript({
        $_ -eq '' -or $_ -match '^guitraverse_mobile_(?:clean_base|seed)_v[1-9][0-9]*$'
    })]
    [string]$SnapshotName = '',

    [ValidatePattern('^guitraverse_mobile_seed$')]
    [string]$AvdName = 'guitraverse_mobile_seed',

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$AppName,

    [ValidateRange(5554, 5680)]
    [int]$ConsolePort = 5612,

    [ValidateRange(8554, 8680)]
    [int]$GrpcPort = 8612,

    [ValidateRange(0, 1000)]
    [int]$MaxActions = 120,

    [ValidateSet('openai_api', 'qwen_api', 'codex_cli')]
    [string]$ExploreBackend = 'openai_api',

    [ValidateNotNullOrEmpty()]
    [string]$ExploreModel = 'gpt-5.6-luna',

    [string]$PythonExe = 'python',

    [string]$ResultDir = '',

    [string]$SeedManifest = '',

    [string]$RunCheckpointRoot = '',

    [string]$RunCheckpointId = '',

    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$entryPoint = Join-Path $repoRoot 'gui_rewalk\run_visual_traversal.py'
if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "Traversal entry point is missing: $entryPoint"
}
if (-not $ResultDir) {
    $ResultDir = Join-Path $repoRoot 'artifacts\guitraverse_runs'
}
if (-not $SeedManifest) {
    $SeedManifest = Join-Path $repoRoot 'data\dev_seed\guitraverse_explore_seed_v2.yaml'
}
if (-not $PlanOnly -and -not $SnapshotName) {
    throw 'SnapshotName must name an explicitly created clean base before a seeded run.'
}

$arguments = @(
    $entryPoint,
    '--vm_provider', 'android',
    '--avd_name', $AvdName,
    '--android_snapshot_name', $SnapshotName,
    '--android_console_port', [string]$ConsolePort,
    '--android_grpc_port', [string]$GrpcPort,
    '--seed_manifest', $SeedManifest,
    '--app_name', $AppName,
    '--modular-explore',
    '--explore-backend', $ExploreBackend,
    '--explore-model', $ExploreModel,
    '--max_actions', [string]$MaxActions,
    '--result_dir', $ResultDir,
    '--no_live_monitor'
)

if ($RunCheckpointRoot) {
    $arguments += '--run_checkpoint_root', $RunCheckpointRoot
}
if ($RunCheckpointId) {
    $arguments += '--run_checkpoint_id', $RunCheckpointId
}

if ($PlanOnly) {
    [ordered]@{
        schema = 'guitraverse.seeded_mobile_run.plan.v1'
        executable = $PythonExe
        arguments = $arguments
        avd_name = $AvdName
        snapshot_name = $SnapshotName
        seed_manifest = $SeedManifest
        run_checkpoint_root = $RunCheckpointRoot
        run_checkpoint_id = $RunCheckpointId
        read_only_overlay = -not [bool]$RunCheckpointRoot
        clears_app_data = $false
    } | ConvertTo-Json -Depth 4
    exit 0
}

& $PythonExe @arguments
exit $LASTEXITCODE
