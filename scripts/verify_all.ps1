# PATH: scripts/verify_all.ps1
# Complete verification script for ARBY Issue #3

param(
    [switch]$SkipSmoke,
    [int]$SmokeCycles = 1
)

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "ARBY Issue #3 - Complete Verification" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check we're in project root
if (-not (Test-Path "core/format_money.py")) {
    Write-Host "ERROR: Run this script from the project root directory" -ForegroundColor Red
    exit 1
}

# Track results
$results = @{}
$allPassed = $true

# Function to run test and track result
function Run-Test {
    param([string]$Name, [string]$Command)
    
    Write-Host "`n[$Name]" -ForegroundColor Yellow
    Write-Host "Running: $Command" -ForegroundColor Gray
    
    Invoke-Expression $Command
    $exitCode = $LASTEXITCODE
    
    if ($exitCode -eq 0) {
        Write-Host "  PASSED" -ForegroundColor Green
        $script:results[$Name] = "PASS"
    } else {
        Write-Host "  FAILED" -ForegroundColor Red
        $script:results[$Name] = "FAIL"
        $script:allPassed = $false
    }
    
    return $exitCode
}

# 1. Core format_money tests
Run-Test "format_money" "python -m pytest tests/unit/test_format_money.py -v --tb=short"

# 2. Error contract tests (AC requirement)
Run-Test "error_contract" "python -m pytest tests/unit/test_error_contract.py -v --tb=short"

# 3. Paper trading tests (AC requirement)
Run-Test "paper_trading" "python -m pytest tests/unit/test_paper_trading.py -v --tb=short"

# 4. Confidence tests (AC requirement)
Run-Test "confidence" "python -m pytest tests/unit/test_confidence.py -v --tb=short"

# 5. Truth report tests
Run-Test "truth_report" "python -m pytest tests/unit/test_truth_report.py -v --tb=short"

# 6. Core models tests
if (Test-Path "tests/unit/test_core_models.py") {
    Run-Test "core_models" "python -m pytest tests/unit/test_core_models.py -v --tb=short"
}

# 7. Math tests
if (Test-Path "tests/unit/test_math.py") {
    Run-Test "math" "python -m pytest tests/unit/test_math.py -v --tb=short"
}

# 8. Time tests
if (Test-Path "tests/unit/test_time.py") {
    Run-Test "time" "python -m pytest tests/unit/test_time.py -v --tb=short"
}

# 9. Config tests
if (Test-Path "tests/unit/test_config.py") {
    Run-Test "config" "python -m pytest tests/unit/test_config.py -v --tb=short"
}

# 10. SMOKE test
if (-not $SkipSmoke) {
    Write-Host "`n[SMOKE Test]" -ForegroundColor Yellow
    
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $runDir = "data/runs/verify_$timestamp"
    
    Write-Host "Running $SmokeCycles cycle(s) to: $runDir" -ForegroundColor Gray
    
    python -m strategy.jobs.run_scan --cycles $SmokeCycles --output-dir $runDir
    
    # Check for crashes
    $hasCrash = $false
    if (Test-Path "$runDir/scan.log") {
        $crashes = Select-String -Path "$runDir/scan.log" -Pattern "Traceback|ValueError.*format code|TypeError.*unexpected keyword" -SimpleMatch
        if ($crashes) {
            $hasCrash = $true
            Write-Host "  Crashes found in log!" -ForegroundColor Red
        }
    }
    
    # Check artifacts
    $hasArtifacts = (Test-Path "$runDir/scan.log") -and 
                   (Get-ChildItem "$runDir/reports/truth_report_*.json" -ErrorAction SilentlyContinue)
    
    if ($hasCrash) {
        $results["SMOKE"] = "FAIL (crashes)"
        $allPassed = $false
    } elseif (-not $hasArtifacts) {
        $results["SMOKE"] = "FAIL (missing artifacts)"
        $allPassed = $false
    } else {
        $results["SMOKE"] = "PASS"
        Write-Host "  PASSED" -ForegroundColor Green
    }
    
    # Check paper_trades.jsonl
    if (Test-Path "$runDir/paper_trades.jsonl") {
        $lineCount = (Get-Content "$runDir/paper_trades.jsonl" | Measure-Object -Line).Lines
        Write-Host "  paper_trades.jsonl: $lineCount trade(s)" -ForegroundColor Gray
    } else {
        Write-Host "  paper_trades.jsonl: not created (no WOULD_EXECUTE)" -ForegroundColor Gray
    }
    
    # Check RPC consistency
    $truthFile = Get-ChildItem "$runDir/reports/truth_report_*.json" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($truthFile) {
        $truth = Get-Content $truthFile.FullName | ConvertFrom-Json
        $rpcTotal = $truth.health.rpc_total_requests
        $rpcFailed = $truth.health.rpc_failed_requests
        Write-Host "  RPC metrics: total=$rpcTotal, failed=$rpcFailed" -ForegroundColor Gray
    }
}

# Summary
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "SUMMARY" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

foreach ($test in $results.Keys | Sort-Object) {
    $status = $results[$test]
    if ($status -eq "PASS") {
        Write-Host "  [PASS] $test" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $test" -ForegroundColor Red
    }
}

Write-Host ""
if ($allPassed) {
    Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "SOME CHECKS FAILED" -ForegroundColor Red
    exit 1
}