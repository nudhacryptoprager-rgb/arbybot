# DEV REPORT — E1.59 Soak Verification + Two Bug Fixes

**Session**: 2026-05-05 · Base chain · DISCOVERY + PROD lanes
**Status**: COMPLETE — two root-cause bugs fixed, E1.59 all 6 modules verified live

---

## 1. Root Cause Fixes

### Fix A — `simulation.py`: default backend `tenderly` → `rpc_fork`

**File**: `m7/orderflow/simulation.py`
**Problem**: `os.environ.get("ARBY_SIM_BACKEND", BACKEND_TENDERLY)` — when env var unset, every soak defaulted to Tenderly, causing 429 rate-limit errors and WS drops.
**Fix**: Changed default to `BACKEND_RPC_FORK`. Tenderly is now opt-in via `ARBY_SIM_BACKEND=tenderly`. Fallback for unknown backends also changed to `rpc_fork`.
**Impact**: `session_ws_failed_429_windows` dropped from 37-41 (E1.58 soaks) to **0** in this session.

### Fix B — `loop_runner.py`: bridge re-read each iteration

**File**: `m7/orderflow/loop_runner.py`
**Problem**: `_bridge = _read_cold_hot_bridge()` called once at hot-lane init (~t=0). Cold lane writes its first bridge ~15 min later. Result: `cold_immediate_sim_input_count=0` for the entire first WS window.
**Fix**: Added `_bridge = _read_cold_hot_bridge()` inside the `queue_cold_executable_for_sim` block, re-reading before each sim call.
**Impact**: `bridge_loaded_candidate_count_total` 0 -> **498**, `cold_imm_sim_input` 0 -> **243**.

---

## 2. Tests

6 tests updated to reflect `rpc_fork` as new default (Tenderly tests now explicit via `ARBY_SIM_BACKEND=tenderly`).
**Full suite**: **4730 PASS / 6 skipped / 0 failures**

---

## 3. Soak 2 Results (15:40:11Z-16:10:11Z, base, bridge-refresh fix applied)

**Supervisor**: 5/5 alive, 0 crashes, 0 restarts across 30 min

### DISCOVERY Hot Lane:

| Metric | Value |
|--------|-------|
| `sim_backend` | `rpc_fork` |
| `session_429_windows` | **0** |
| `provider_throttle.total_429` | **0** |
| `events_seen_total` | 1445 |
| `fast_path_positive_total` | 79 |
| `bridge_loaded_candidate_count_total` | **498** |
| `cold_imm_sim_input` | **243** |
| `cold_imm_sim_profitable` | **113** |
| `cold_imm_submit_ready` | **35** |
| `cold_imm_roundtrip_profitable` | **35** |

### E1.59 Module Keys in Rollup (all PRESENT):
- `revert_taxonomy` | `pool_promotion` | `preflight_aggregator` (candidates=3, blocked=0) | `canary_rehearsal` | `sim_v1_dry_compare` | `provider_throttle` (429=0)

---

## 4. Operator Command (next soak)

```powershell
.\.venv\Scripts\Activate.ps1
Get-Content .env | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' } | ForEach-Object { $p=$_ -split '=',2; [System.Environment]::SetEnvironmentVariable($p[0].Trim(),$p[1].Trim(),'Process') }
$env:ARBY_SIM_BACKEND="rpc_fork"; $env:ARBY_SIM_BACKEND_PROD="rpc_fork"; $env:ARBY_SIM_BACKEND_DISC="rpc_fork"
$env:ARBY_REVERT_TAXONOMY="1"; $env:ARBY_POOL_PROMOTION="1"; $env:ARBY_EXECUTION_PREFLIGHT="1"
$env:ARBY_CANARY_REHEARSAL="1"; $env:ARBY_SIM_V1_DRY_COMPARE="1"; $env:ARBY_PROVIDER_THROTTLE="1"
$env:ARBY_POOL_STATE_HTTP_FEED="1"; $env:ARBY_RPC_URL_HTTP=$env:BASE_RPC
$env:ARBY_COLD_IMMEDIATE_SIM="1"; $env:ARBY_PAPER_SIGNING="1"; $env:ARBY_COLD_IMMEDIATE_MIN_NET_BPS="0"
python scripts/start_nonstop_runtime.py --hours 2 --no-m4 --chain base --with-discovery --m7-cold-pause 3
```
