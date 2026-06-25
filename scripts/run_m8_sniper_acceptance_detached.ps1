# Detached M8 sniper acceptance run (survives Cursor shell exit).
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Stdout = Join-Path $RepoRoot "data\tmp\m8_sniper_acceptance_stdout.log"
$Stderr = Join-Path $RepoRoot "data\tmp\m8_sniper_acceptance_stderr.log"
$PidFile = Join-Path $RepoRoot "data\tmp\m8_sniper_acceptance.pid"
$MetaFile = Join-Path $RepoRoot "data\tmp\m8_sniper_acceptance_meta.json"

New-Item -ItemType Directory -Force -Path (Split-Path $Stdout) | Out-Null

# Load RPC env from repo bootstrap helper (non-interactive).
$bootstrap = Join-Path $RepoRoot "scripts\bootstrap_productive_rpc_env.py"
if (Test-Path $bootstrap) {
    & py -3.11 $bootstrap -- py -3.11 -c "import os; print('bootstrap_ok')" 2>&1 | Out-Null
}

$env:ARBY_SNIPER_ENABLE = "1"

$args = @(
    "-3.11", "-u", "scripts/sniper_smoke_run.py",
    "--chain", "base",
    "--duration-minutes", "45",
    "--acceptance-run",
    "--blocks-back", "50"
)

$proc = Start-Process `
    -FilePath "py" `
    -ArgumentList $args `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $Stdout `
    -RedirectStandardError $Stderr `
    -WindowStyle Hidden `
    -PassThru

$proc.Id | Set-Content -Path $PidFile -Encoding utf8
@{
    pid = $proc.Id
    started_at_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    duration_minutes = 45
    stdout_log = $Stdout.Replace("\", "/")
    stderr_log = $Stderr.Replace("\", "/")
} | ConvertTo-Json | Set-Content -Path $MetaFile -Encoding utf8

Write-Output "m8_sniper_acceptance_started pid=$($proc.Id)"
Write-Output "stdout=$Stdout"
Write-Output "stderr=$Stderr"
