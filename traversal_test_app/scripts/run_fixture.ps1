[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("scroll", "loop", "back", "region_merge")]
    [string]$Fixture,

    [ValidateSet("acceptance", "guided", "edges")]
    [string]$Mode = "acceptance",

    [string]$CaseId = "",
    [switch]$ListCases,
    [string]$Model = "qwen3.7-plus",
    [string]$Python = "python",
    [string]$ResultDir = "artifacts/runs/quick_fixture_scripts",
    [int]$MaxStates = 20,
    [int]$MaxActions = 40
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$fixtureRoot = Join-Path $repoRoot "traversal_test_app"
$entryPoint = Join-Path $repoRoot "gui_rewalk\run_visual_traversal.py"
$caseManifest = Join-Path $fixtureRoot "edge_cases.json"
$oracle = Join-Path $fixtureRoot "oracle.json"
$acceptanceValidator = Join-Path $repoRoot "tools\validate_quick_traversal_run.py"

$configs = @{
    scroll = @{
        File = "scroll.html"
        StartHash = "#/inbox"
        AppName = "quick-scroll-script"
    }
    loop = @{
        File = "loop.html"
        StartHash = "#/1"
        AppName = "quick-loop-script"
    }
    back = @{
        File = "back.html"
        StartHash = "#/1"
        AppName = "quick-back-script"
    }
    region_merge = @{
        File = "region_merge.html"
        StartHash = "#/overview"
        AppName = "quick-region-merge-script"
    }
}

$config = $configs[$Fixture]
$htmlPath = Join-Path $fixtureRoot $config.File
$cases = @(
    (Get-Content -Raw -Encoding UTF8 $caseManifest | ConvertFrom-Json).cases |
        Where-Object { $_.file -eq $config.File }
)

if ($ListCases) {
    $cases | ForEach-Object {
        "{0}: {1} --{2}--> {3}" -f `
            $_.id, $_.source_page, $_.target, $_.expected_destination
    }
    exit 0
}

if ($CaseId -and $Mode -ne "edges") {
    throw "-CaseId requires -Mode edges"
}

$commonArgs = @(
    $entryPoint,
    "--vm_provider", "local_html",
    "--html_path", $htmlPath,
    "--screen_width", "1365",
    "--screen_height", "900",
    "--max_states", [string]$MaxStates,
    "--max_actions", [string]$MaxActions,
    "--result_dir", $ResultDir,
    "--fixture_oracle_inventory", "off",
    "--fixture_oracle_grounding", "off",
    "--no_live_monitor"
)

Push-Location $repoRoot
try {
    if ($Mode -eq "acceptance") {
        $runAppName = "{0}-acceptance-{1}" -f `
            $config.AppName, (Get-Date -Format "HHmmssfff")
        Write-Host "Running full autonomous $Fixture acceptance..."
        & $Python @commonArgs `
            "--local_html_start_hash" $config.StartHash `
            "--app_name" $runAppName `
            "--autonomous-agent" `
            "--autonomous-model" $Model `
            "--autonomous_fixture_audit"
        $runExit = $LASTEXITCODE
        $runDir = Get-ChildItem -LiteralPath $ResultDir -Directory -Recurse `
            -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq $runAppName } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($null -eq $runDir) {
            throw "Autonomous run did not create an artifact directory for $runAppName"
        }
        if ($runExit -ne 0) {
            Write-Host "Autonomous process failed before acceptance ($runExit)." `
                -ForegroundColor Red
            exit $runExit
        }
        & $Python $acceptanceValidator $Fixture $runDir.FullName `
            "--oracle" $oracle `
            "--edge-cases" $caseManifest
        exit $LASTEXITCODE
    }

    if ($Mode -eq "guided") {
        Write-Host "Running full $Fixture fixture with guided traversal..."
        & $Python @commonArgs `
            "--local_html_start_hash" $config.StartHash `
            "--app_name" $config.AppName `
            "--model_version" $Model `
            "--require_complete"
        exit $LASTEXITCODE
    }

    $selectedCases = $cases
    if ($CaseId) {
        $selectedCases = @($cases | Where-Object { $_.id -eq $CaseId })
        if ($selectedCases.Count -ne 1) {
            throw "Unknown case '$CaseId' for fixture '$Fixture'. Use -ListCases."
        }
    }

    $failed = @()
    foreach ($case in $selectedCases) {
        $startHash = if ($case.start_hash) {
            [string]$case.start_hash
        } else {
            [string]$config.StartHash
        }
        $scope = "{0}::{1}::{2}" -f `
            $case.source_page, $case.target, $case.expected_destination
        $appName = "{0}-{1}" -f $config.AppName, $case.id
        Write-Host "Running edge $($case.id)..."
        & $Python @commonArgs `
            "--local_html_start_hash" $startHash `
            "--app_name" $appName `
            "--autonomous-agent" `
            "--autonomous-model" $Model `
            "--autonomous_test_target_edge" $scope `
            "--autonomous_fixture_audit"
        if ($LASTEXITCODE -ne 0) {
            $failed += $case.id
        }
    }

    if ($failed.Count -gt 0) {
        Write-Host ("Failed target edges: " + ($failed -join ", ")) `
            -ForegroundColor Red
        exit 3
    }
    Write-Host "All $($selectedCases.Count) target edges passed."
    exit 0
}
finally {
    Pop-Location
}
