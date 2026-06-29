param(
    [switch]$ForceRerunSteps = $false
)

$Repo = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $Repo "data\tmp\start_time_to_mirror_753.log"
$PidFile = Join-Path $Repo "data\tmp\start_time_to_mirror_753.pid"
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null

$runner = Join-Path $Repo "scripts\run_time_to_mirror_hot.ps1"
$psArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", $runner,
    "-MaxRadarTokens", "50",
    "-HeartbeatStaleMinutes", "15"
)
if ($ForceRerunSteps) {
    $psArgs += "-ForceRerunSteps"
}
$proc = Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $Repo -WindowStyle Hidden -PassThru

$proc.Id | Set-Content $PidFile
Write-Output "time_to_mirror_hot_started pid=$($proc.Id) log=$Log pid_file=$PidFile"
