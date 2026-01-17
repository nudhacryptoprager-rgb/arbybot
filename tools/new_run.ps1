param(
  [Parameter(Mandatory=$false)]
  [string]$RunId = $(Get-Date -Format "HHmmss")
)

$Date = Get-Date -Format "yyyy-MM-dd"
$Base = Join-Path "data\runs" (Join-Path $Date $RunId)

New-Item -ItemType Directory -Force -Path $Base | Out-Null

Write-Host "Created run folder:" $Base
Write-Output $Base
