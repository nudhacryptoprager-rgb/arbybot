param(
  [Parameter(Mandatory=$true)][int]$IssueNumber,
  [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$RunDir,
  [string]$Repo = "nudhacryptoprager-rgb/arbybot",
  [string]$RoadmapPath = "Roadmap.md",
  [string]$StatusPath = "",
  [int]$ScanLogTailLines = 140,
  [switch]$Dbg
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function ReadTextUtf8Raw([string]$Path, [string]$MissingMsg) {
  if (-not (Test-Path $Path)) { return $MissingMsg }
  try { return Get-Content -Path $Path -Raw -Encoding UTF8 }
  catch { return Get-Content -Path $Path -Raw }
}

function ReadTextUtf8Tail([string]$Path, [int]$Lines, [string]$MissingMsg) {
  if (-not (Test-Path $Path)) { return $MissingMsg }
  try { return (Get-Content -Path $Path -Tail $Lines -Encoding UTF8) -join "`r`n" }
  catch { return (Get-Content -Path $Path -Tail $Lines) -join "`r`n" }
}

function FindLatestStatusPath([string]$DocsDir) {
  if (-not (Test-Path $DocsDir)) { return $null }
  $files = Get-ChildItem -Path $DocsDir -Filter "Status_*.md" -File -ErrorAction SilentlyContinue
  if (-not $files) { return $null }
  return ($files | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}

function GetLatestFile([string]$Dir, [string]$Pattern) {
  if (-not (Test-Path $Dir)) { return $null }
  $f = Get-ChildItem -Path $Dir -Filter $Pattern -File -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
  return $f
}

function ReadGhIssue([int]$N, [string]$R) {
  $gh = (Get-Command gh -ErrorAction Stop).Source

  $argsMeta = @("issue","view",$N,"-R",$R,"--json","title,url")
  $argsBody = @("issue","view",$N,"-R",$R,"--json","body")

  if ($Dbg) {
    Write-Host ("DEBUG IssueNumber = [{0}] ({1})" -f $N, ($N.GetType().FullName))
    Write-Host ("DEBUG Repo        = [{0}]" -f $R)
    Write-Host ("DEBUG PWD         = [{0}]" -f (Get-Location).Path)
    Write-Host ("DEBUG gh path     = [{0}]" -f $gh)
    Write-Host ("DEBUG gh meta args = {0}" -f ($argsMeta -join " "))
  }

  $rawMeta = & $gh @argsMeta 2>&1 | Out-String
  if ($Dbg) {
    Write-Host "DEBUG gh meta raw (first 300):"
    if ($rawMeta) { Write-Host ($rawMeta.Substring(0,[Math]::Min(300,$rawMeta.Length))) } else { Write-Host "<empty>" }
  }
  if (-not $rawMeta -or ($rawMeta.Trim().Length -eq 0) -or (-not $rawMeta.Trim().StartsWith("{"))) {
    throw ("Cannot read issue meta #{0} via gh. Raw: {1}" -f $N, ($rawMeta.Trim()))
  }
  $meta = $rawMeta | ConvertFrom-Json

  if ($Dbg) { Write-Host ("DEBUG gh body args = {0}" -f ($argsBody -join " ")) }
  $rawBody = & $gh @argsBody 2>&1 | Out-String
  if ($Dbg) {
    Write-Host "DEBUG gh body raw (first 300):"
    if ($rawBody) { Write-Host ($rawBody.Substring(0,[Math]::Min(300,$rawBody.Length))) } else { Write-Host "<empty>" }
  }
  if (-not $rawBody -or ($rawBody.Trim().Length -eq 0) -or (-not $rawBody.Trim().StartsWith("{"))) {
    throw ("Cannot read issue body #{0} via gh. Raw: {1}" -f $N, ($rawBody.Trim()))
  }
  $bodyObj = $rawBody | ConvertFrom-Json

  return [PSCustomObject]@{
    title = [string]$meta.title
    url   = [string]$meta.url
    body  = [string]$bodyObj.body
  }
}

function LooksLikeFloat([string]$s) {
  if (-not $s) { return $false }
  return ($s -match '(?<!\d)\d+\.\d+(?!\d)')
}

# --- Validate RunDir ---
if (-not (Test-Path $RunDir)) { throw ("RunDir does not exist: {0}" -f $RunDir) }
$runDirFull = (Resolve-Path $RunDir).Path

# --- Issue ---
$issueObj = ReadGhIssue -N $IssueNumber -R $Repo

# --- Roadmap + Status (UTF-8) ---
$roadmapText = ReadTextUtf8Raw $RoadmapPath ("<missing Roadmap.md at {0}>" -f $RoadmapPath)

$statusResolved = $null
if ($StatusPath -and (Test-Path $StatusPath)) {
  $statusResolved = (Resolve-Path $StatusPath).Path
} else {
  $statusResolved = FindLatestStatusPath "docs"
}

if ($statusResolved) {
  $statusText = ReadTextUtf8Raw $statusResolved ("<missing status at {0}>" -f $statusResolved)
  $statusFileLine = $statusResolved
} else {
  $statusText = "<missing Status_*.md in docs/>"
  $statusFileLine = "<missing>"
}

# --- RunDir evidence ---
$scanLogPath = Join-Path $runDirFull "scan.log.txt"
$scanLogTail = ReadTextUtf8Tail $scanLogPath $ScanLogTailLines "<missing scan.log.txt in runDir>"

$scanJson   = GetLatestFile $runDirFull "scan_*.json"
$truthJson  = GetLatestFile $runDirFull "truth_report_*.json"
$rejectJson = GetLatestFile $runDirFull "reject_histogram_*.json"
$paperJsonl = GetLatestFile $runDirFull "paper_trades_*.jsonl"

if ($truthJson) { $truthRaw = ReadTextUtf8Raw $truthJson.FullName "<missing truth_report>" } else { $truthRaw = "<missing truth_report_*.json in runDir>" }
if ($paperJsonl) { $paperFirstLine = ReadTextUtf8Tail $paperJsonl.FullName 1 "<missing paper_trades>" } else { $paperFirstLine = "<missing paper_trades_*.jsonl>" }

$truthHasFloat = LooksLikeFloat $truthRaw
$paperHasFloat = LooksLikeFloat $paperFirstLine

# --- Build packet ---
$sb = New-Object System.Text.StringBuilder

$null = $sb.AppendLine(("Repo: https://github.com/{0}" -f $Repo))
$null = $sb.AppendLine(("Issue: #{0} — {1}" -f $IssueNumber, $issueObj.title))
$null = $sb.AppendLine(("Issue URL: {0}" -f $issueObj.url))
$null = $sb.AppendLine(("RunDir: {0}" -f $RunDir))
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== ISSUE BODY (source of AC) ===")
$null = $sb.AppendLine($issueObj.body)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== ROADMAP.md (source of truth) ===")
$null = $sb.AppendLine($roadmapText)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== STATUS (resolved) ===")
$null = $sb.AppendLine(("Status file: {0}" -f $statusFileLine))
$null = $sb.AppendLine($statusText)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== EVIDENCE (run folder) ===")
if (Test-Path $scanLogPath) { $null = $sb.AppendLine(("scan.log.txt: {0}" -f $scanLogPath)) } else { $null = $sb.AppendLine("scan.log.txt: <missing>") }
if ($scanJson)   { $null = $sb.AppendLine(("scan json: {0}" -f $scanJson.Name)) } else { $null = $sb.AppendLine("scan json: <missing scan_*.json>") }
if ($truthJson)  { $null = $sb.AppendLine(("truth json: {0}" -f $truthJson.Name)) } else { $null = $sb.AppendLine("truth json: <missing truth_report_*.json>") }
if ($rejectJson) { $null = $sb.AppendLine(("reject json: {0}" -f $rejectJson.Name)) } else { $null = $sb.AppendLine("reject json: <missing reject_histogram_*.json>") }
if ($paperJsonl) { $null = $sb.AppendLine(("paper jsonl: {0}" -f $paperJsonl.Name)) } else { $null = $sb.AppendLine("paper jsonl: <missing paper_trades_*.jsonl>") }
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== scan.log tail ===")
$null = $sb.AppendLine($scanLogTail)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("--- truth_report excerpt ---")
$null = $sb.AppendLine($truthRaw.Substring(0,[Math]::Min(4000,$truthRaw.Length)))
$null = $sb.AppendLine("")
$null = $sb.AppendLine("--- paper_trades first line ---")
$null = $sb.AppendLine($paperFirstLine)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== QUICK CHECKS ===")
$null = $sb.AppendLine(("truth_report contains float-like numbers: {0}" -f $truthHasFloat))
$null = $sb.AppendLine(("paper_trades first line contains float-like numbers: {0}" -f $paperHasFloat))
$null = $sb.AppendLine("")

$null = $sb.AppendLine("REQUEST:")
$null = $sb.AppendLine("- Provide minimal diff/patch to satisfy Issue AC.")
$null = $sb.AppendLine("- Provide PowerShell verify commands for Windows.")
$null = $sb.AppendLine("- No cosmetic refactors; scope only.")
$null = $sb.AppendLine("- Return FULL file contents for changed files (not just a diff), so I can paste-save quickly.")

$outFile = Join-Path $runDirFull ("claude_packet_issue{0}.md" -f $IssueNumber)
Set-Content -Path $outFile -Value $sb.ToString() -Encoding UTF8

try {
  Set-Clipboard -Value (Get-Content -Path $outFile -Raw -Encoding UTF8)
  Write-Host ("OK: Claude packet saved to {0} and copied to clipboard." -f $outFile)
} catch {
  Write-Host ("OK: Claude packet saved to {0}. NOTE: clipboard copy failed; copy the file manually." -f $outFile)
}
