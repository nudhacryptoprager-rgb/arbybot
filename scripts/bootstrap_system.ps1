# Bootstrap_System.ps1
# ARBY3 / arbybot — повний bootstrap системи після перезавантаження.
#
# Що робить:
#   1) Активує venv (Python 3.11) і перевіряє інтерпретатор.
#   2) Підвантажує .env (ALCHEMY/TENDERLY/RPC keys).
#   3) Виставляє operational ENV для M7 (strict-provider, archive, premium).
#   4) Чистить stale entries у rolling JSON.
#   5) Snapshot-ить pre-soak baseline для reviewer_soak_summary.
#   6) Optional: запускає anvil fork (з ARBY_ANVIL_AUTO_REFRESH).
#   7) Запускає start_nonstop_runtime supervisor у detached режимі.
#
# Параметри:
#   -Hours <float>          Тривалість soak у годинах (default 0.5)
#   -ProdSimBackend <str>   tenderly|rpc_fork (default rpc_fork — fallback при 403)
#   -DiscSimBackend <str>   tenderly|rpc_fork (default rpc_fork)
#   -StartAnvil             Перемикач: запустити anvil fork
#   -SkipBaseline           Пропустити baseline snapshot
#
# Приклад:
#   pwsh -File scripts/bootstrap_system.ps1 -Hours 0.5
#   pwsh -File scripts/bootstrap_system.ps1 -Hours 2 -StartAnvil
[CmdletBinding()]
param(
    [double]$Hours = 0.5,
    [ValidateSet('tenderly','rpc_fork')]
    [string]$ProdSimBackend = 'rpc_fork',
    [ValidateSet('tenderly','rpc_fork')]
    [string]$DiscSimBackend = 'rpc_fork',
    [switch]$StartAnvil,
    [switch]$SkipBaseline
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$msg) {
    Write-Host ("[bootstrap] " + $msg) -ForegroundColor Cyan
}

# Repo root: this script lives in scripts/, so parent of $PSScriptRoot is repo root.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Step ("repo root: " + $repoRoot)

# --- 1) venv activation ---
$activate = Join-Path $repoRoot 'venv\Scripts\Activate.ps1'
if (-not (Test-Path $activate)) {
    Write-Error "venv not found at $activate. Run: py -3.11 -m venv venv"
}
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& $activate

$pyver = & py -3.11 -c "import sys; print(sys.version.split()[0])"
Write-Step ("python: " + $pyver)
if ($pyver -notmatch '^3\.11') {
    Write-Error ("Expected Python 3.11.x, got " + $pyver)
}

# --- 2) load .env ---
$envFile = Join-Path $repoRoot '.env'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#') { return }
        if ($_ -notmatch '=') { return }
        $kv = $_ -split '=', 2
        $k = $kv[0].Trim()
        $v = $kv[1].Trim().Trim('"').Trim("'")
        if ($k) { Set-Item -Path ("Env:" + $k) -Value $v }
    }
    Write-Step ".env loaded"
} else {
    Write-Warning ".env not found — Tenderly/Alchemy ENV will be missing"
}

# --- 3) operational ENV ---
$env:PYTHONIOENCODING                          = 'utf-8'
$env:ARBY_STRICT_PROVIDER_POLICY               = '1'
$env:ARBY_RPC_PREMIUM_ONLY                     = '1'
$env:ARBY_REQUIRE_PREMIUM                      = '1'
$env:ARBY_REQUIRE_ARCHIVE                      = '1'
$env:ARBY_SIM_BACKEND                          = $ProdSimBackend
$env:ARBY_SIM_BACKEND_DISC                     = $DiscSimBackend
$env:ARBY_SIM_ADMISSION_STRICT                 = '1'
$env:ARBY_SIM_MIN_NET_BPS                      = '1.0'
$env:ARBY_SIM_BYPASS_GUARD                     = '0'
$env:ARBY_PAPER_SIGNING                        = '1'
$env:ARBY_ROUNDTRIP_SIM                        = '1'
$env:ARBY_ADAPTIVE_SIZING                      = '1'
$env:ARBY_WS_RECV_TIMEOUT_S                    = '30'
$env:ARBY_WS_MAX_RECONNECT_ATTEMPTS            = '4'
$env:ARBY_WS_RECONNECT_RATE_LIMIT_COOLDOWN_S   = '30'
$env:ARBY_BASE_USE_FLASHBLOCKS_WS              = '0'

# soak16: explicit RPC rate-limit bypass routes (avoid 403/429 from
# Tenderly / Alchemy / dRPC). All of these activate already-implemented
# fallback paths in core/rpc_rate_limiter.py and core/rpc_urls.py.
$env:ARBY_RPC_THROTTLE                         = '1'      # token bucket on
$env:ARBY_RPC_RPS_LIMIT                        = '60'     # safe under dRPC free 100 rps
$env:ARBY_RPC_RPS_BURST                        = '20'
$env:ARBY_PERSISTENT_POOL_CACHE                = '1'      # P0.1
$env:ARBY_BACKRUN_MAX_INPUT_RATIO              = '1000'   # P0.2 sanity clamp
$env:ARBY_RT_BPS_FLOOR                         = '-1000'  # P0.2 outlier filter
$env:ARBY_FAST_PATH_COMPONENTS_RING_SIZE       = '50'     # P1.5 dump
$env:ARBY_RPC_PUBLIC_WS_FALLBACK               = '1'      # publicnode.com fallback when Alchemy 429
$env:ARBY_RPC_FALLBACK_ON_429                  = '1'
$env:ARBY_TENDERLY_DISABLE                     = '1'      # explicit bypass — sim runs via rpc_fork

Write-Step ("ENV set; PROD sim=" + $ProdSimBackend + ", DISC sim=" + $DiscSimBackend)

# --- 4) clean rolling ---
Write-Step "cleaning rolling artifacts ..."
& py -3.11 scripts\clean_rolling_artifacts.py | Out-Null

# --- 5) baseline snapshot ---
if (-not $SkipBaseline) {
    $rollDir = Join-Path $repoRoot 'data\runs\_rolling'
    if (Test-Path (Join-Path $rollDir 'm7_hot_rollup_latest.json')) {
        Copy-Item (Join-Path $rollDir 'm7_hot_rollup_latest.json') (Join-Path $rollDir 'reviewer_soak_baseline_latest.json') -Force
    }
    if (Test-Path (Join-Path $rollDir 'm7_hot_rollup_latest_discovery.json')) {
        Copy-Item (Join-Path $rollDir 'm7_hot_rollup_latest_discovery.json') (Join-Path $rollDir 'reviewer_soak_baseline_latest_discovery.json') -Force
    }
    Write-Step "baseline snapshots created"
}

# --- 6) optional anvil ---
if ($StartAnvil) {
    $startAnvilPy = Join-Path $repoRoot 'scripts\start_anvil_fork.py'
    if (Test-Path $startAnvilPy) {
        Write-Step "starting anvil fork (detached) ..."
        $anvilLog = Join-Path $repoRoot ("data\runs\_sessions\anvil_" + (Get-Date -Format 'yyyyMMdd_HHmmss') + ".log")
        $env:ARBY_ANVIL_AUTO_REFRESH       = '1'
        $env:ARBY_ANVIL_REFRESH_INTERVAL_S = '60'
        $env:ARBY_ANVIL_REFRESH_DRIFT_BLOCKS = '120'
        Start-Process -FilePath py -ArgumentList @('-3.11', $startAnvilPy) -RedirectStandardOutput $anvilLog -RedirectStandardError "$anvilLog.err" -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 5
    } else {
        Write-Warning "start_anvil_fork.py not found, skipping anvil"
    }
}

# --- 7) launch supervisor ---
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$logDir = Join-Path $repoRoot 'data\runs\_sessions'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("m7_bootstrap_" + $ts + ".out.log")
$errFile = $logFile + '.err'

$argsList = @(
    '-3.11', 'scripts/start_nonstop_runtime.py',
    '--chain', 'base',
    '--hours', $Hours.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    '--with-discovery',
    '--no-m4',
    '--dashboard-port', '8109',
    '--m7-hot-pause', '1',
    '--m7-cold-pause', '5'
)
$proc = Start-Process -FilePath py -ArgumentList $argsList -RedirectStandardOutput $logFile -RedirectStandardError $errFile -PassThru -WindowStyle Hidden
Write-Step ("supervisor PID=" + $proc.Id + ", log=" + $logFile + ", hours=" + $Hours)
Write-Host ("supervisor PID: " + $proc.Id)
Write-Host ("log: " + $logFile)
Write-Host ("started: " + (Get-Date -Format 'HH:mm:ss'))
