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
#   pwsh -File scripts/bootstrap_system.ps1 -Hours 0.17 -ProviderBudget free
[CmdletBinding()]
param(
    [double]$Hours = 0.5,
    [ValidateSet('tenderly','rpc_fork')]
    [string]$ProdSimBackend = 'rpc_fork',
    [ValidateSet('tenderly','rpc_fork')]
    [string]$DiscSimBackend = 'rpc_fork',
    [ValidateSet('standard','free')]
    [string]$ProviderBudget = 'standard',
    [int]$RpcRpsLimit = 60,
    [int]$RpcRpsBurst = 20,
    [int]$WsMaxReconnectAttempts = 4,
    [int]$WsReconnectCooldownSeconds = 30,
    [switch]$StartAnvil,
    [switch]$SkipBaseline,
    # soak18 step 4: fail-fast probe. After supervisor starts we wait
    # this many seconds for the hot rollup to advance past its baseline
    # snapshot. If the lane never writes a fresh rollup in that window
    # the supervisor is killed so the operator does not waste a full
    # soak on a stuck WS connection. Set to 0 to disable.
    # Reviewer post-1h-soak fix: bumped default from 90s -> 180s. Cold
    # warmup of the bridge/registry can take 120-150s on Base before
    # the first hot-rollup advance, and the previous 90s default
    # frequently false-aborted healthy supervisors.
    [int]$RollupProbeSeconds = 180,
    # post-2h-soak step #5: heartbeat-aware probe. When set (>0), if the
    # rollup has not advanced by $RollupProbeSeconds but the supervisor
    # log file has been written-to within the last $HeartbeatWindowSeconds,
    # extend the probe up to $RollupProbeSeconds * 2 instead of hard
    # aborting. This avoids killing healthy long-warmup runs on idle
    # markets while still catching truly stuck WS subscriptions.
    # Reviewer post-1h-soak fix: bumped 30s -> 60s. Hot rollup writes on
    # event windows; on cold-warmup the bridge can stay quiet for 45-60s
    # before the first PTT event, which previously false-failed dual
    # liveness even when the supervisor was healthy.
    [int]$RollupProbeHeartbeatSeconds = 60,
    [switch]$NoRollupProbe)

$ErrorActionPreference = 'Stop'

if ($ProviderBudget -eq 'free') {
    if (-not $PSBoundParameters.ContainsKey('RpcRpsLimit')) {
        $RpcRpsLimit = 35
    }
    if (-not $PSBoundParameters.ContainsKey('RpcRpsBurst')) {
        $RpcRpsBurst = 5
    }
    if (-not $PSBoundParameters.ContainsKey('WsMaxReconnectAttempts')) {
        $WsMaxReconnectAttempts = 1
    }
    if (-not $PSBoundParameters.ContainsKey('WsReconnectCooldownSeconds')) {
        $WsReconnectCooldownSeconds = 180
    }
}

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
if (-not $env:ARBY_SIM_MIN_NET_BPS) { $env:ARBY_SIM_MIN_NET_BPS = '1.0' }  # E1.40: respect caller override
$env:ARBY_SIM_BYPASS_GUARD                     = '0'
$env:ARBY_PAPER_SIGNING                        = '1'
$env:ARBY_ROUNDTRIP_SIM                        = '1'
$env:ARBY_ADAPTIVE_SIZING                      = '1'
$env:ARBY_WS_RECV_TIMEOUT_S                    = '30'
$env:ARBY_WS_MAX_RECONNECT_ATTEMPTS            = [string]$WsMaxReconnectAttempts
$env:ARBY_WS_RECONNECT_RATE_LIMIT_COOLDOWN_S   = [string]$WsReconnectCooldownSeconds
$env:ARBY_BASE_USE_FLASHBLOCKS_WS              = '0'

# soak16: explicit RPC rate-limit bypass routes (avoid 403/429 from
# Tenderly / Alchemy / dRPC). All of these activate already-implemented
# fallback paths in core/rpc_rate_limiter.py and core/rpc_urls.py.
$env:ARBY_RPC_THROTTLE                         = '1'      # token bucket on
$env:ARBY_RPC_RPS_LIMIT                        = [string]$RpcRpsLimit
$env:ARBY_RPC_RPS_BURST                        = [string]$RpcRpsBurst
$env:ARBY_PERSISTENT_POOL_CACHE                = '1'      # P0.1
$env:ARBY_BACKRUN_MAX_INPUT_RATIO              = '1000'   # P0.2 sanity clamp
$env:ARBY_RT_BPS_FLOOR                         = '-1000'  # P0.2 outlier filter
$env:ARBY_FAST_PATH_COMPONENTS_RING_SIZE       = '50'     # P1.5 dump
$env:ARBY_RPC_PUBLIC_WS_FALLBACK               = '1'      # publicnode.com fallback when Alchemy 429
$env:ARBY_RPC_FALLBACK_ON_429                  = '1'
$env:ARBY_TENDERLY_DISABLE                     = '1'      # explicit bypass — sim runs via rpc_fork
# E1.51: local pool price-state registry (feed_raw_logs in WS recv loop).
# Respect caller override; default ON so bootstrap-launched children
# benefit from Swap/Sync log decoding without extra CLI flags.
if (-not $env:ARBY_USE_LOCAL_PRICE_STATE)   { $env:ARBY_USE_LOCAL_PRICE_STATE   = '1' }
if (-not $env:ARBY_REGISTRY_FIRST_POOL_STATE) { $env:ARBY_REGISTRY_FIRST_POOL_STATE = '0' }  # safe default OFF

Write-Step ("ENV set; PROD sim=" + $ProdSimBackend + ", DISC sim=" + $DiscSimBackend + ", provider_budget=" + $ProviderBudget + ", rpc_rps=" + $RpcRpsLimit + ", rpc_burst=" + $RpcRpsBurst + ", ws_attempts=" + $WsMaxReconnectAttempts + ", ws_cooldown_s=" + $WsReconnectCooldownSeconds)

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
# Force unbuffered Python stdout so log lines are visible even when the
# supervisor is killed early by the rollup probe (Windows blocks stdout
# until process exit when using Start-Process -RedirectStandardOutput).
$env:PYTHONUNBUFFERED = '1'
$proc = Start-Process -FilePath py -ArgumentList $argsList -RedirectStandardOutput $logFile -RedirectStandardError $errFile -PassThru -WindowStyle Hidden
$env:PYTHONUNBUFFERED = $null   # restore; child already inherited it
Write-Step ("supervisor PID=" + $proc.Id + ", log=" + $logFile + ", hours=" + $Hours)
Write-Host ("supervisor PID: " + $proc.Id)
Write-Host ("log: " + $logFile)
Write-Host ("started: " + (Get-Date -Format 'HH:mm:ss'))

# --- 8) rollup-progress probe (soak18 step 4) -----------------------------
# Verify the hot lane actually advanced the rollup past its baseline
# snapshot within $RollupProbeSeconds. If not, kill the supervisor so
# we don't burn a full soak window on a dead WS subscription.
if (-not $NoRollupProbe -and $RollupProbeSeconds -gt 0) {
    $rollupPath = Join-Path $repoRoot 'data\runs\_rolling\m7_hot_rollup_latest.json'
    $baselinePath = Join-Path $repoRoot 'data\runs\_rolling\reviewer_soak_baseline_latest.json'
    $baselineLU = $null
    if (Test-Path $baselinePath) {
        try { $baselineLU = (Get-Content $baselinePath -Raw | ConvertFrom-Json).last_updated } catch {}
    }
    Write-Step ("rollup probe: waiting up to " + $RollupProbeSeconds + "s for fresh write past baseline.last_updated=" + $baselineLU)
    $probeElapsed = 0
    $progressed = $false
    $maxProbe = $RollupProbeSeconds
    while ($probeElapsed -lt $maxProbe) {
        Start-Sleep -Seconds 5
        $probeElapsed += 5
        if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
            Write-Step "rollup probe: supervisor exited early — aborting probe"
            # E1.45 step 4: lane-aware exit. If the supervisor exited
            # cleanly and the rollup carries a fresh shutdown_flush_at
            # / supervisor_end_utc stamp, treat that as positive proof
            # that the system flushed at least once (even if no fresh
            # active hot write occurred). This avoids killing the
            # post-mortem reviewer summary on short windows where the
            # supervisor finishes before the probe wakes up.
            if (Test-Path $rollupPath) {
                try {
                    $rJson = Get-Content $rollupPath -Raw | ConvertFrom-Json
                    if ($rJson.shutdown_flush_at -or $rJson.supervisor_end_utc) {
                        Write-Step ("rollup probe: PASS-by-shutdown — shutdown_flush_at=" + $rJson.shutdown_flush_at + " supervisor_end_utc=" + $rJson.supervisor_end_utc)
                        $progressed = $true
                    }
                } catch {}
            }
            break
        }
        if (Test-Path $rollupPath) {
            try {
                $curLU = (Get-Content $rollupPath -Raw | ConvertFrom-Json).last_updated
                if ($curLU -and ($curLU -ne $baselineLU)) {
                    Write-Step ("rollup probe: PASS — last_updated advanced to " + $curLU + " after " + $probeElapsed + "s")
                    $progressed = $true
                    break
                }
            } catch {}
        }
        # post-2h-soak step #5 + post-20m-control step #1: heartbeat
        # extension. If at the original deadline we still haven't seen a
        # rollup advance, the probe extends ONCE only when BOTH proxies
        # of liveness agree:
        #   (a) supervisor log has been written within $RollupProbeHeartbeatSeconds
        #       (proves the supervisor process is alive), AND
        #   (b) the hot rollup file mtime has advanced within the same
        #       window (proves the hot-lane writer is alive even if
        #       last_updated has not yet crossed the baseline value —
        #       e.g., heartbeat-on-error windows on a quiet feed).
        # The reviewer flagged log-only heartbeat as insufficient because
        # a dead hot-lane writer can still leave the supervisor logging.
        if ($probeElapsed -ge $RollupProbeSeconds -and $maxProbe -eq $RollupProbeSeconds -and $RollupProbeHeartbeatSeconds -gt 0) {
            $logHealthy = $false
            $rollupHealthy = $false
            try {
                if (Test-Path $logFile) {
                    $logLastWrite = (Get-Item $logFile).LastWriteTimeUtc
                    $logAgeSec = ((Get-Date).ToUniversalTime() - $logLastWrite).TotalSeconds
                    if ($logAgeSec -le $RollupProbeHeartbeatSeconds) {
                        $logHealthy = $true
                    }
                }
            } catch {}
            try {
                if (Test-Path $rollupPath) {
                    $rollupLastWrite = (Get-Item $rollupPath).LastWriteTimeUtc
                    $rollupAgeSec = ((Get-Date).ToUniversalTime() - $rollupLastWrite).TotalSeconds
                    if ($rollupAgeSec -le $RollupProbeHeartbeatSeconds) {
                        $rollupHealthy = $true
                    }
                }
            } catch {}
            if ($logHealthy -and $rollupHealthy) {
                $maxProbe = $RollupProbeSeconds * 2
                Write-Step ("rollup probe: dual heartbeat OK (log+rollup written within " + $RollupProbeHeartbeatSeconds + "s); extending probe to " + $maxProbe + "s")
            } elseif ($logHealthy -and -not $rollupHealthy) {
                Write-Step ("rollup probe: log heartbeat OK but rollup writer silent for >" + $RollupProbeHeartbeatSeconds + "s; NOT extending probe (hot lane suspected dead)")
            }
        }
    }
    if (-not $progressed) {
        Write-Step ("rollup probe: FAIL — no fresh rollup write in " + $RollupProbeSeconds + "s; stopping supervisor PID " + $proc.Id)
        # post-1h-soak fix: enumerate descendant PIDs BEFORE stopping the
        # supervisor; otherwise children orphan and keep writing to the
        # shared rollup, masking the next session's writes (root cause of
        # iter5 false-stalled session_id). Walk Win32_Process tree.
        $descendantPids = @()
        try {
            $allProcs = Get-CimInstance -ClassName Win32_Process -ErrorAction SilentlyContinue |
                Select-Object ProcessId, ParentProcessId
            $queue = [System.Collections.Queue]::new()
            $queue.Enqueue([int]$proc.Id)
            while ($queue.Count -gt 0) {
                $parent = [int]$queue.Dequeue()
                foreach ($p in $allProcs) {
                    if ([int]$p.ParentProcessId -eq $parent) {
                        $descendantPids += [int]$p.ProcessId
                        $queue.Enqueue([int]$p.ProcessId)
                    }
                }
            }
        } catch {}
        # soak18 step 7: graceful stop supervisor first (CloseMainWindow
        # + 10s wait so it can flush m7_session_state.json and close WS
        # cleanly), then -Force only if it ignores the request.
        $gracefulStopped = $false
        try {
            $closed = $proc.CloseMainWindow()
            if ($closed) {
                if ($proc.WaitForExit(10000)) {
                    $gracefulStopped = $true
                }
            }
        } catch {}
        if (-not $gracefulStopped) {
            try {
                Stop-Process -Id $proc.Id -ErrorAction Stop
                if ($proc.WaitForExit(10000)) { $gracefulStopped = $true }
            } catch {}
        }
        if (-not $gracefulStopped) {
            Write-Step ("rollup probe: graceful stop ignored; escalating to -Force")
            try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch {}
        }
        # Now reap descendants — supervisor's graceful stop should have
        # ended them, but anything still alive must be force-killed to
        # prevent orphan writers polluting the next run's rollup.
        if ($descendantPids.Count -gt 0) {
            $stillAlive = @()
            foreach ($cpid in ($descendantPids | Sort-Object -Unique)) {
                try {
                    if (Get-Process -Id $cpid -ErrorAction SilentlyContinue) {
                        Stop-Process -Id $cpid -Force -ErrorAction SilentlyContinue
                        $stillAlive += $cpid
                    }
                } catch {}
            }
            if ($stillAlive.Count -gt 0) {
                Write-Step ("rollup probe: force-killed " + $stillAlive.Count + " orphan child PIDs: " + ($stillAlive -join ','))
            }
        }
        Write-Host ("BOOTSTRAP_ABORTED: rollup probe timed out (set -NoRollupProbe to skip).")
        exit 2
    }
}
