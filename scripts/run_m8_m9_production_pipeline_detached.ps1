$Repo = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $Repo "data\tmp\m8_m9_production_pipeline.log"
$PidFile = Join-Path $Repo "data\tmp\m8_m9_production_pipeline.pid"
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
$proc = Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $Repo "scripts\run_m8_m9_production_pipeline.ps1")
) -WorkingDirectory $Repo -RedirectStandardOutput $Log -RedirectStandardError (Join-Path $Repo "data\tmp\m8_m9_production_pipeline_stderr.log") -WindowStyle Hidden -PassThru
$proc.Id | Set-Content $PidFile
Write-Output "pipeline_started pid=$($proc.Id) log=$Log"
