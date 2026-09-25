[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+$')]
    [string]$Remote,

    [ValidateRange(1, 65535)]
    [int]$Port = 22,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^/[A-Za-z0-9._/-]+/codex_runs/[A-Za-z0-9._-]+$')]
    [string]$RunRoot,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$ArtifactName,

    [ValidateRange(1, 100)]
    [int]$MaxGiB = 5,

    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifactsRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $repoRoot 'artifacts')
)
$destination = [System.IO.Path]::GetFullPath(
    (Join-Path $artifactsRoot $ArtifactName)
)
if (-not $destination.StartsWith(
        $artifactsRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Destination must stay under artifacts/: $destination"
}

$transferId = [Guid]::NewGuid().ToString('N')
$remoteArchive = "$RunRoot/.codex-evidence-$transferId.tar.gz"
$maxBytes = [int64]$MaxGiB * 1GB

if ($PlanOnly) {
    [pscustomobject]@{
        destination = $destination
        remote_run_root = $RunRoot
        max_gib = $MaxGiB
        included = @(
            'results/'
            'root-level *.log, *.exit_code, *.started_at, *.finished_at'
        )
        excluded = @('repo/', 'OSWorld/', 'remote source archives')
        recursive_scp = $false
    } | ConvertTo-Json -Compress
    return
}

if (Test-Path -LiteralPath $destination) {
    throw "Destination already exists: $destination"
}

$prepareScript = @'
set -eu
root=$1
archive=$2
max_bytes=$3

test -d "$root/results"
cd "$root"

if find results -type l -print -quit | grep -q .; then
  echo "refusing results tree containing symbolic links" >&2
  exit 41
fi

set -- results
for item in *.log *.exit_code *.started_at *.finished_at; do
  [ -e "$item" ] || continue
  if [ -L "$item" ] || [ ! -f "$item" ]; then
    echo "refusing non-regular root evidence: $item" >&2
    exit 42
  fi
  set -- "$@" "$item"
done

total_bytes=$(
  {
    find results -type f -printf '%s\n'
    for item in "$@"; do
      [ "$item" = results ] || stat -c '%s' "$item"
    done
  } | awk '{ total += $1 } END { printf "%.0f\n", total }'
)
if [ "$total_bytes" -gt "$max_bytes" ]; then
  echo "refusing evidence larger than configured limit: $total_bytes bytes" >&2
  exit 43
fi

tmp="$archive.tmp"
test ! -e "$archive"
test ! -e "$tmp"
tar -czf "$tmp" -- "$@"
mv "$tmp" "$archive"
archive_bytes=$(stat -c '%s' "$archive")
if [ "$archive_bytes" -gt "$max_bytes" ]; then
  rm -f -- "$archive"
  echo "refusing archive larger than configured limit: $archive_bytes bytes" >&2
  exit 44
fi
printf '%s\n' "$archive_bytes"
'@

$encodedPrepare = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($prepareScript)
)
$sshArgs = @(
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=15',
    '-p', [string]$Port,
    $Remote
)
$scpArgs = @(
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=15',
    '-P', [string]$Port
)
$remoteCommand = (
    "echo '$encodedPrepare' | base64 -d | bash -s -- " +
    "'$RunRoot' '$remoteArchive' '$maxBytes'"
)
$cleanupCommand = "rm -f -- '$remoteArchive' '$remoteArchive.tmp'"
$createdDestination = $false

try {
    $prepareOutput = & ssh @sshArgs $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Remote evidence preflight failed with exit code $LASTEXITCODE"
    }
    $archiveBytesText = $prepareOutput | Where-Object {
        $_ -match '^\d+$'
    } | Select-Object -Last 1
    if (-not $archiveBytesText) {
        throw 'Remote evidence preflight did not return an archive size'
    }
    $archiveBytes = [int64]$archiveBytesText
    if ($archiveBytes -gt $maxBytes) {
        throw "Remote archive exceeds the configured limit: $archiveBytes bytes"
    }

    $driveName = [System.IO.Path]::GetPathRoot($destination).TrimEnd('\').TrimEnd(':')
    $freeBytes = (Get-PSDrive -Name $driveName).Free
    if ($freeBytes -lt ($archiveBytes + 1GB)) {
        throw 'Local disk does not have archive size plus 1 GiB safety headroom'
    }

    New-Item -ItemType Directory -Path $destination | Out-Null
    $createdDestination = $true
    $localArchive = Join-Path $destination 'evidence.tar.gz'
    $remoteSource = "${Remote}:$remoteArchive"
    & scp @scpArgs $remoteSource $localArchive
    if ($LASTEXITCODE -ne 0) {
        throw "Evidence download failed with exit code $LASTEXITCODE"
    }
    if ((Get-Item -LiteralPath $localArchive).Length -ne $archiveBytes) {
        throw 'Downloaded archive size does not match the remote preflight'
    }

    $entries = & tar -tzf $localArchive
    if ($LASTEXITCODE -ne 0) {
        throw 'Downloaded evidence archive is unreadable'
    }
    foreach ($entry in $entries) {
        if ($entry -match '(^|/)\.\.(/|$)' -or
            $entry.StartsWith('/') -or
            $entry -match '(^|/)(repo|OSWorld)(/|$)') {
            throw "Unsafe archive entry: $entry"
        }
    }

    & tar -xzf $localArchive -C $destination
    if ($LASTEXITCODE -ne 0) {
        throw 'Evidence archive extraction failed'
    }
    Remove-Item -LiteralPath $localArchive -Force

    [pscustomobject]@{
        destination = $destination
        downloaded_bytes = $archiveBytes
        extracted_entries = @($entries).Count
    } | ConvertTo-Json -Compress
}
catch {
    if ($createdDestination -and (Test-Path -LiteralPath $destination)) {
        Remove-Item -LiteralPath $destination -Recurse -Force
    }
    throw
}
finally {
    & ssh @sshArgs $cleanupCommand 2>$null | Out-Null
}
