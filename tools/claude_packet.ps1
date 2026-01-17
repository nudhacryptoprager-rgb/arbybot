param(
  [Parameter(Mandatory=$true)][int]$Issue,
  [Parameter(Mandatory=$true)][string]$RunDir,
  [string]$Repo = "nudhacryptoprager-rgb/arbybot"
)

# 1) Pull Issue body via gh
$issueJson = gh issue view $Issue -R $Repo --json title,body,url 2>$null | ConvertFrom-Json
if (-not $issueJson) { throw "Cannot read issue #$Issue via gh. Run: gh auth status" }

# 2) Evidence files from run dir
$truth = Get-ChildItem $RunDir -Filter "truth_report_*.json" | Sort-Object LastWriteTime -Desc | Select-Object -First 1
$paper = Get-ChildItem $RunDir -Filter "paper_trades_*.jsonl" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Desc | Select-Object -First 1

$truthText = if ($truth) { Get-Content $truth.FullName -Raw } else { "<missing truth_report_*.json>" }
$paperFirstLine = if ($paper) { Get-Content $paper.FullName -TotalCount 1 } else { "<missing paper_trades_*.jsonl>" }

# 3) Quick float scan (heuristic)
$truthHasFloat = ($truthText -match ':\s*-?\d+\.\d+')
$paperHasFloat = ($paperFirstLine -match ':\s*-?\d+\.\d+')

# 4) Compose packet
$packet = @()
$packet += "Repo: https://github.com/$Repo"
$packet += "Issue: #$Issue — $($issueJson.title)"
$packet += "Issue URL: $($issueJson.url)"
$packet += ""
$packet += "=== ISSUE BODY ==="
$packet += $issueJson.body
$packet += ""
$packet += "=== EVIDENCE ==="
$packet += "RunDir: $RunDir"
$packet += ""
$packet += "--- truth_report (raw) ---"
$packet += $truthText
$packet += ""
$packet += "--- paper_trades first line ---"
$packet += $paperFirstLine
$packet += ""
$packet += "=== QUICK CHECKS ==="
$packet += "truth_report contains float-like numbers: $truthHasFloat"
$packet += "paper_trades first line contains float-like numbers: $paperHasFloat"
$packet += ""
$packet += "REQUEST:"
$packet += "- Provide minimal diff/patch to satisfy Issue AC."
$packet += "- Provide PowerShell verify commands for Windows."
$packet += "- No cosmetic refactors; scope only."
$packetText = ($packet -join "`r`n")

# 5) Save + copy to clipboard
$outFile = Join-Path $RunDir "claude_packet_issue$Issue.md"
Set-Content -Path $outFile -Value $packetText -Encoding UTF8
Set-Clipboard -Value $packetText

Write-Host "OK: Claude packet saved to $outFile and copied to clipboard."
