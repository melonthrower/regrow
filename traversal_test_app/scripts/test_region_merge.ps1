[CmdletBinding()]
param(
    [ValidateSet("acceptance", "guided", "edges")][string]$Mode = "acceptance",
    [string]$CaseId = "",
    [switch]$ListCases,
    [string]$Model = "qwen3.7-plus",
    [string]$Python = "python",
    [string]$ResultDir = "artifacts/runs/quick_fixture_scripts",
    [int]$MaxStates = 20,
    [int]$MaxActions = 40
)

& (Join-Path $PSScriptRoot "run_fixture.ps1") -Fixture region_merge @PSBoundParameters
exit $LASTEXITCODE
