# Time-to-mirror hot_delta lane (≤50 tokens, skip-secondary, 15m SLA).
param(
    [int]$MaxRadarTokens = 50,
    [switch]$SkipShadow = $true,
    [int]$HeartbeatStaleMinutes = 15,
    [switch]$ForceRerunSteps = $false
)

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$Log = Join-Path $Repo "data\tmp\start_time_to_mirror_753.log"
$Err = Join-Path $Repo "data\tmp\start_time_to_mirror_753.err"
$Meta = Join-Path $Repo "data\tmp\start_time_to_mirror_753.meta.log"
$Done = Join-Path $Repo "data\tmp\start_time_to_mirror_753.done"
$Fail = Join-Path $Repo "data\tmp\start_time_to_mirror_753.fail"

New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
Remove-Item $Done, $Fail -ErrorAction SilentlyContinue

function Write-Meta([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $Meta -Value $line -Encoding utf8
}

$python = (& py -3.11 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1).Trim()
if (-not $python) {
    Write-Meta "FATAL: could not resolve py -3.11 interpreter"
    Set-Content -Path $Fail -Value "missing_python"
    exit 1
}

Write-Meta "=== time_to_mirror_hot_delta_start python=$python max_radar=$MaxRadarTokens ==="

$env:PYTHONUNBUFFERED = "1"
$startArgs = @(
    "start.py",
    "-time_to_mirror",
    "--hot",
    "--hot-lane", "hot_delta",
    "--max-radar-tokens", "$MaxRadarTokens",
    "--skip-secondary",
    "--allow-roadmap-edit",
    "--no-dashboard",
    "--heartbeat-stale-minutes", "$HeartbeatStaleMinutes"
)
if ($SkipShadow) {
    $startArgs += "--skip-shadow"
}
if ($ForceRerunSteps) {
    $startArgs += "--force-rerun-steps"
}

$proc = Start-Process -FilePath $python -ArgumentList $startArgs -WorkingDirectory $Repo -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $Log -RedirectStandardError $Err
$rc = $proc.ExitCode

if ($rc -eq 0) {
    Write-Meta "=== time_to_mirror_hot_delta_done exit=0 ==="
    Set-Content -Path $Done -Value (Get-Date -Format o)
    exit 0
}

Write-Meta "=== time_to_mirror_hot_delta_failed exit=$rc ==="
Set-Content -Path $Fail -Value "exit=$rc"
exit $rc
