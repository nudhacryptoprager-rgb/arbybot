param(
  [Parameter(Mandatory=$true)][int]$IssueNumber,
  [Parameter(Mandatory=$true)][string]$RunDir,
  [string]$Repo = "nudhacryptoprager-rgb/arbybot",
  [string]$RoadmapPath = "Roadmap.md",
  [string]$StatusPath = "",
  [int]$ScanLogTailLines = 120,
  [switch]$Dbg
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function SafeReadRaw([string]$Path, [string]$MissingMsg) {
  if (Test-Path $Path) { return Get-Content $Path -Raw }
  return $MissingMsg
}

function SafeReadTail([string]$Path, [int]$Lines, [string]$MissingMsg) {
  if (Test-Path $Path) { return (Get-Content $Path -Tail $Lines) -join "`r`n" }
  return $MissingMsg
}

function FindLatestStatus([string]$DocsDir) {
  if (-not (Test-Path $DocsDir)) { return $null }
  $c = Get-ChildItem -Path $DocsDir -Filter "Status_*.md" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($c) { return $c.FullName }
  return $null
}

function TryParseJson([string]$Raw) {
  try { return $Raw | ConvertFrom-Json } catch { return $null }
}

function IsMoneyFloat($v) {
  if ($null -eq $v) { return $false }
  if ($v -is [double] -or $v -is [single]) { return $true }
  return $false
}

function HasMoneyFloat([object]$TruthObj) {
  try {
    if ($TruthObj.top_opportunities) {
      foreach ($opp in $TruthObj.top_opportunities) {
        if (IsMoneyFloat $opp.expected_pnl_usdc) { return $true }
        if (IsMoneyFloat $opp.confidence) { return $true }
      }
    }
  } catch {}

  try { if (IsMoneyFloat $TruthObj.cumulative_pnl.total_usdc) { return $true } } catch {}
  try {
    if (IsMoneyFloat $TruthObj.pnl.signal_pnl_usdc) { return $true }
    if (IsMoneyFloat $TruthObj.pnl.would_execute_pnl_usdc) { return $true }
  } catch {}
  try { if (IsMoneyFloat $TruthObj.pnl_normalized.notion_capital_numeraire) { return $true } } catch {}

  return $false
}

function RpcMismatch([object]$TruthObj, [object]$RejectObj) {
  $rpcTotal = 0
  try { $rpcTotal = [int]$TruthObj.health.rpc_total_requests } catch { $rpcTotal = 0 }
  if ($rpcTotal -gt 0) { return $false }

  $infraRpc = 0
  try {
    if ($RejectObj.reasons -and $RejectObj.reasons.INFRA_RPC_ERROR) { $infraRpc = [int]$RejectObj.reasons.INFRA_RPC_ERROR }
    elseif ($RejectObj.histogram -and $RejectObj.histogram.INFRA_RPC_ERROR) { $infraRpc = [int]$RejectObj.histogram.INFRA_RPC_ERROR }
    elseif ($RejectObj.INFRA_RPC_ERROR) { $infraRpc = [int]$RejectObj.INFRA_RPC_ERROR }
    else {
      foreach ($p in $RejectObj.PSObject.Properties) {
        if ($p.Name -eq "INFRA_RPC_ERROR") { $infraRpc = [int]$p.Value }
      }
    }
  } catch { $infraRpc = 0 }

  if ($infraRpc -gt 0 -and $rpcTotal -eq 0) { return $true }
  return $false
}

if ($Dbg) {
  Write-Host ("DEBUG IssueNumber = [{0}] ({1})" -f $IssueNumber, ($IssueNumber.GetType().FullName))
  Write-Host ("DEBUG RunDir      = [{0}]" -f $RunDir)
  Write-Host ("DEBUG Repo        = [{0}]" -f $Repo)
  Write-Host ("DEBUG PWD         = [{0}]" -f (Get-Location))
  $ghCmd = Get-Command gh -ErrorAction SilentlyContinue
  Write-Host ("DEBUG gh path     = [{0}]" -f ($ghCmd.Source))
}

New-Item -Force -ItemType Directory $RunDir | Out-Null

# ---- Read issue via gh (meta + body, safer on PS5.1) ----
$ghArgsMeta = @("issue","view",$IssueNumber,"-R",$Repo,"--json","title,url")
$ghArgsBody = @("issue","view",$IssueNumber,"-R",$Repo,"--json","body")

if ($Dbg) { Write-Host ("DEBUG gh meta args = {0}" -f ($ghArgsMeta -join " ")) }
$rawMeta = & gh @ghArgsMeta 2>&1 | Out-String
if ($Dbg) {
  Write-Host "DEBUG gh meta raw (first 300):"
  Write-Host ($rawMeta.Substring(0,[Math]::Min(300,$rawMeta.Length)))
}
if (-not $rawMeta -or ($rawMeta.Trim().Length -eq 0) -or ($rawMeta.Trim().StartsWith("{") -eq $false)) {
  throw ("Cannot read issue meta #{0} via gh. Raw: {1}" -f $IssueNumber, ($rawMeta.Trim()))
}
$issueMeta = $rawMeta | ConvertFrom-Json

if ($Dbg) { Write-Host ("DEBUG gh body args = {0}" -f ($ghArgsBody -join " ")) }
$rawBody = & gh @ghArgsBody 2>&1 | Out-String
if ($Dbg) {
  Write-Host "DEBUG gh body raw (first 300):"
  Write-Host ($rawBody.Substring(0,[Math]::Min(300,$rawBody.Length)))
}
if (-not $rawBody -or ($rawBody.Trim().Length -eq 0) -or ($rawBody.Trim().StartsWith("{") -eq $false)) {
  throw ("Cannot read issue body #{0} via gh. Raw: {1}" -f $IssueNumber, ($rawBody.Trim()))
}
$issueBodyObj = $rawBody | ConvertFrom-Json

$issueObj = [PSCustomObject]@{
  title = $issueMeta.title
  url   = $issueMeta.url
  body  = $issueBodyObj.body
}

# ---- Roadmap + Status ----
$roadmapText = SafeReadRaw $RoadmapPath ("<missing Roadmap.md at {0}>" -f $RoadmapPath)

$statusResolved = $null
if ($StatusPath -and (Test-Path $StatusPath)) {
  $statusResolved = (Resolve-Path $StatusPath).Path
} else {
  $statusResolved = FindLatestStatus "docs"
}

if ($statusResolved) { $statusText = SafeReadRaw $statusResolved "<missing Status file>" }
else { $statusText = "<missing docs/Status_*.md>" }

# ---- Evidence in run dir ----
$truthFile  = Get-ChildItem $RunDir -Filter "truth_report_*.json" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Desc | Select-Object -First 1
$rejectFile = Get-ChildItem $RunDir -Filter "reject_histogram_*.json" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Desc | Select-Object -First 1
$scanLog    = Get-ChildItem $RunDir -Filter "scan.log*.txt" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Desc | Select-Object -First 1
$paperFile  = Get-ChildItem $RunDir -Filter "paper_trades_*.jsonl" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Desc | Select-Object -First 1

$truthRaw = if ($truthFile) { Get-Content $truthFile.FullName -Raw } else { "<missing truth_report_*.json in RunDir>" }
$rejectRaw = if ($rejectFile) { Get-Content $rejectFile.FullName -Raw } else { "<missing reject_histogram_*.json in RunDir>" }
$scanLogTail = if ($scanLog) { SafeReadTail $scanLog.FullName $ScanLogTailLines "<missing scan.log in RunDir>" } else { "<missing scan.log in RunDir>" }
$paperFirstLine = if ($paperFile) { Get-Content $paperFile.FullName -TotalCount 1 } else { "<missing paper_trades_*.jsonl>" }

$truthObj = TryParseJson $truthRaw
$rejectObj = TryParseJson $rejectRaw

$moneyFloat = $false
$modeIsSmoke = $false
$rpcMismatch = $false

if ($truthObj) {
  $moneyFloat = HasMoneyFloat $truthObj
  try { $modeIsSmoke = ($truthObj.mode -eq "SMOKE") } catch { $modeIsSmoke = $false }
}
if ($truthObj -and $rejectObj) { $rpcMismatch = RpcMismatch $truthObj $rejectObj }

# ---- Build packet ----
$sb = New-Object System.Text.StringBuilder
$null = $sb.AppendLine(("Repo: https://github.com/{0}" -f $Repo))
$null = $sb.AppendLine(("Issue: #{0} — {1}" -f $IssueNumber, $issueObj.title))
$null = $sb.AppendLine(("Issue URL: {0}" -f $issueObj.url))
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== ROADMAP.md (source of truth) ===")
$null = $sb.AppendLine($roadmapText)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== STATUS (latest) ===")
if ($statusResolved) { $null = $sb.AppendLine(("Status file: {0}" -f $statusResolved)) } else { $null = $sb.AppendLine("Status file: <missing>") }
$null = $sb.AppendLine($statusText)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== ISSUE BODY ===")
$null = $sb.AppendLine($issueObj.body)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== EVIDENCE (RunDir) ===")
$null = $sb.AppendLine(("RunDir: {0}" -f $RunDir))
$null = $sb.AppendLine("")

$null = $sb.AppendLine("--- scan.log tail ---")
$null = $sb.AppendLine($scanLogTail)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("--- truth_report (raw) ---")
$null = $sb.AppendLine($truthRaw)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("--- reject_histogram (raw) ---")
$null = $sb.AppendLine($rejectRaw)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("--- paper_trades first line ---")
$null = $sb.AppendLine($paperFirstLine)
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== QUICK CHECKS (strict) ===")
$null = $sb.AppendLine(("money_fields_have_float (MUST be false): {0}" -f $moneyFloat))
$null = $sb.AppendLine(("truth_report.mode_is_smoke (MUST be true for SMOKE tasks): {0}" -f $modeIsSmoke))
$null = $sb.AppendLine(("rpc_mismatch_flag (INFRA_RPC_ERROR>0 but rpc_total_requests==0): {0}" -f $rpcMismatch))
$null = $sb.AppendLine("")

$null = $sb.AppendLine("=== REQUEST (FULL FILE OUTPUT, NO DIFF) ===")
$null = $sb.AppendLine("Return minimal changes to satisfy Issue AC. Do NOT output a patch/diff.")
$null = $sb.AppendLine("Output FULL UPDATED FILE CONTENTS for each changed file (no ellipses). Use format:")
$null = $sb.AppendLine("=== FILE: <path> ===")
$null = $sb.AppendLine('```<language>')
$null = $sb.AppendLine("<entire file content>")
$null = $sb.AppendLine('```')
$null = $sb.AppendLine("")
$null = $sb.AppendLine("Also return PowerShell verify commands for Windows (SMOKE cycle + checks).")
$null = $sb.AppendLine("Scope only; no cosmetic refactors.")

$packetText = $sb.ToString()

$outFile = Join-Path $RunDir ("claude_packet_issue{0}.md" -f $IssueNumber)
Set-Content -Path $outFile -Value $packetText -Encoding UTF8

try {
  Set-Clipboard -Value $packetText
  Write-Host ("OK: Claude packet saved to {0} and copied to clipboard." -f $outFile)
} catch {
  Write-Host ("OK: Claude packet saved to {0}. NOTE: clipboard copy failed; copy the file manually." -f $outFile)
}
