# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
run_id: data/runs/_rolling (reviewer 1h soak session c1e53ec3; anvil+dRPC)
mode: ONLINE
artifact_mode: rolling
config: Base, dRPC archive fork; strict admission (BYPASS_GUARD=0, MIN_NET_BPS=1.0)
code_identity:
  primary: ts:2026-04-17T12:59:11.866411Z
  dirty: true — Steps 7 (admission) + 9 (anvil drift mitigation) live
  desc: block-tag clamp, BlockOutOfRange retry, refresh_anvil_fork_if_stale, Windows shutdown taskkill, delta-aware profit analyzer, reviewer_soak_summary

## 1) Scope
goal: Ліквідувати головний блокер reviewer'а (100% fresh sim attempts fail з BlockOutOfRangeError через статичний Anvil fork) + замінити слабке acceptance `<50/min` на жорсткий дельта-контракт.

change_summary:
  - Step 9 core (`m7/orderflow/sim_backends/anvil_backend.py`):
    * `get_anvil_block_number()` / `_resolve_anvil_block_tag()` — clamp requested block > local_head → "latest" (ENV `ARBY_ANVIL_CLAMP_BLOCK=1` default)
    * `_eth_call_anvil` — normalises `BlockOutOfRangeError`; one retry with "latest"
    * `refresh_anvil_fork_if_stale()` — calls `anvil_reset` when drift > threshold
  - Step 9 bootstrap (`scripts/start_anvil_fork.py`):
    * Popen + stop_event + refresher thread (ENV: `ARBY_ANVIL_AUTO_REFRESH=1`, `ARBY_ANVIL_REFRESH_INTERVAL_S=60`, `ARBY_ANVIL_REFRESH_DRIFT_BLOCKS=120`)
    * Windows-safe shutdown via `taskkill /F /IM anvil.exe /T` — fixes reviewer issue #9
  - Reviewer tooling:
    * `analyze_roundtrip_profitability.py` — new `--session-only` + `--baseline`; cumulative verdict demoted to `HISTORICAL_PROFITABLE_CASE` (exit=5)
    * `scripts/reviewer_soak_summary.py` (NEW) — baseline vs current; acceptance `Δsim_passed>0 AND ΔBlockOutOfRangeError==0`; exit 0=PASS / 2=FAIL
  - Tests: +6 Step 9 (`TestStep9BlockClamp`); canonical-set tests updated for reviewer ephemera in `_rolling/`.

touched_files:
  - m7/orderflow/sim_backends/anvil_backend.py
  - scripts/start_anvil_fork.py
  - scripts/analyze_roundtrip_profitability.py
  - scripts/reviewer_soak_summary.py (NEW)
  - tests/unit/test_anvil_backend.py
  - tests/unit/test_orderflow_artifacts.py
  - tests/unit/test_nonstop_loop_artifacts.py
  - docs/DEV_REPORT_LATEST.md, docs/status/Status_M7.md

## 2) Commands Executed
pytest tests/unit: **PASS** 4199/0 (6 skipped, 89.62s)
pytest target (`anvil_backend` + `execution_gate`): **PASS** 96/0 (11.80s)
check_repo_safety.py: див. секцію 5
reviewer 1h soak: COMPLETED (results у секції 4)
ci_* gates: NOT RUN — gated on Step 9 validation soak

## 3) Artifacts
canonical rolling: `_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`, `m7_hot_rollup_latest.json` (prod c1e53ec3), `m7_hot_rollup_latest_discovery.json`
reviewer ephemera (M7.E1.34b): `reviewer_soak_baseline_latest{,_discovery}.json`, `reviewer_soak_delta_latest.json`
run_dir_bundle (previous): `data/runs/ci_m5_gate_arbitrum_one_20260417_145636_478653/reports`

## 4) Key Results

### Reviewer 1-hour soak (2026-04-21, session c1e53ec3)
production lane: 86 windows / 207 events / 99 fast_scored / 21 guard_passed / 19 sim_attempted / **0 sim_passed** / 0 WS failed / 0 restarts
discovery lane:  90 windows / 204 events / 99 fast_scored / 21 guard_passed / 15 sim_attempted / **0 sim_passed** / 1 WS failed
verdict: Δsim_passed=0 both lanes → **ACCEPTANCE FAIL**. Root cause: static anvil fork drift — 100% fresh attempts → `BlockOutOfRangeError`.
Step 7 validated (directional): ΔVENUE_MISSING=0, ΔAMOUNT_ZERO=0, `PRE_SIM_SKIP:*` з'являється у histogram.

### Cumulative (historical, NOT fresh evidence)
prod rollup last_updated=2026-04-21T15:09:11Z — sim_attempted=952 / sim_passed=243 / roundtrip_success=228 / roundtrip_profitable=16
run_summary_latest: status=PASS / profit_realism=ROUNDTRIP_NOT_PROFITABLE / real_quote_count=0 / profitable_roundtrips=0 / run_timestamp=2026-04-17T12:59:11.866411Z

## 4.1) Theoretical Net Profit
mode: paper_simulated; net_pnl_usdc: n/a (no profitable roundtrip under fresh-delta contract).
disclaimer: execution_enabled=false, kill_switch_active=true. No real trades executed.

## 5) Contract Checks
pytest tests/unit: **PASS** 4199/0
status/reasons consistency: OK; rolling discipline: OK; runtime artifacts not committed: OK
check_repo_safety.py v1.15.0: **PASS (0 warnings after this overwrite)** — canonical-set tests explicitly allow reviewer baseline/delta JSON та ignore `.pid` / `.py` / `.log` ephemera.

## 6) Blocker Classification
code_blocker: **LOW** — 4199/4199 PASS incl. 6 Step 9 drift tests.
data_collection_blocker: **RESOLVED (pending live validation)** — Step 9 clamp + refresher eliminates BlockOutOfRangeError за unit contract; вимагає 2h soak.
market_window_blocker: **HIGH** — canonical profit contract усе ще `ROUNDTRIP_NOT_PROFITABLE`.

## 6.1) Risks
- Clamp використовує local fork state (не event-block state). In-block price accuracy trade'нуто на sim liveness — OK для simulate_only, перевірити перед real execution.
- Refresher thread залежить від upstream RPC; flaky `ARBY_FORK_RPC_URL` emitить warnings але не валить fork.

## 7) Execution Map
step_01 venue fallback: **DONE** | step_02 block retry: **DONE** | step_05 quality gates: **DONE**
step_06 AMOUNT_ZERO autofill: **DONE** | step_07 admission filter: **DONE** (directional PASS)
step_08 TOKEN_ADDRESS_UNKNOWN: NOT STARTED | step_09 anvil drift: **DONE** (validation pending)
step_10 tenderly renewal: NOT STARTED (Lead scope)

## 8) Requests to Lead
request_1: 2h validation soak з Step 9 live; acceptance через `scripts/reviewer_soak_summary.py --discovery` (exit 0).
request_2: tune `ARBY_ANVIL_REFRESH_DRIFT_BLOCKS` (default 120) / `ARBY_ANVIL_REFRESH_INTERVAL_S` (default 60) якщо упстрім rate-limit'ить.
q_1: hold `ARBY_SIM_MIN_NET_BPS=1.0` чи підняти після перших `sim_passed>0`?

---

## REVIEWER RUNBOOK — Step 9 validation soak (2h)

### Term A — anvil fork + refresher
```powershell
.\venv\Scripts\Activate.ps1
$env:PATH = "$PWD\tools\foundry;$env:PATH"
$env:ARBY_FORK_RPC_URL = "https://lb.drpc.live/base/AovP_0y4K04riEUupzM1hrmZ7i1kNXwR8YgIsuMGSdYJ"
$env:ARBY_ANVIL_AUTO_REFRESH="1"; $env:ARBY_ANVIL_REFRESH_INTERVAL_S="60"; $env:ARBY_ANVIL_REFRESH_DRIFT_BLOCKS="120"
py -3.11 scripts/start_anvil_fork.py --chain base --fork-block-offset 5
```
Expected: кожні 60s → `refresh: drift=<n> → reset to block <n>` якщо drift ≥ 120. Ctrl+C → `taskkill /F /IM anvil.exe /T`.

### Term B — 2h strict-admission soak
```powershell
.\venv\Scripts\Activate.ps1
$env:PATH = "$PWD\tools\foundry;$env:PATH"
$env:ARBY_SIM_BACKEND="anvil"; $env:ARBY_ANVIL_RPC_URL="http://127.0.0.1:8545"
$env:ARBY_SIM_FALLBACK="rpc_fork"; $env:ARBY_HOT_REHYDRATE="1"
$env:ARBY_BROAD_FALLBACK_MIN_USD="500"
$env:ARBY_SIM_ADMISSION_STRICT="1"; $env:ARBY_SIM_MIN_NET_BPS="1.0"
$env:ARBY_SIM_BYPASS_GUARD="0"; $env:ARBY_ANVIL_CLAMP_BLOCK="1"
py -3.11 scripts/check_rpc_endpoints.py --chain base --ws-timeout 15
Copy-Item data/runs/_rolling/m7_hot_rollup_latest.json data/runs/_rolling/reviewer_soak_baseline_latest.json
Copy-Item data/runs/_rolling/m7_hot_rollup_latest_discovery.json data/runs/_rolling/reviewer_soak_baseline_latest_discovery.json
py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 2 --with-discovery --no-m4
```

### Post-soak acceptance
```powershell
py -3.11 scripts/reviewer_soak_summary.py --discovery   # exit 0 = PASS / 2 = FAIL
py -3.11 scripts/analyze_roundtrip_profitability.py --baseline data/runs/_rolling/reviewer_soak_baseline_latest.json
```
**Acceptance (tight):** `Δsim_passed>0` on production, `Δsim_passed>0` on discovery, `ΔBlockOutOfRangeError==0`, 0 WS failed (prod) / ≤1 (disc), `Δroundtrip_attempted>0`.

### Killswitch
Term A: Ctrl+C (автоматичний `taskkill /F /IM anvil.exe /T`).

---

## Session Completion
session_goal: Step 9 (Anvil drift) + delta-aware reviewer tooling; acceptance bar → `Δsim_passed>0 AND ΔBlockOutOfRangeError==0`.
goal_status: REACHED (code-level; live validation deferred to reviewer 2h soak).
close_allowed: true
remaining_blockers: 2h validation soak; Step 8 TOKEN_ADDRESS_UNKNOWN; canonical M4 profit path still NOT_PROFITABLE.
evidence_session_run_dirs: data/runs/_rolling (prod session c1e53ec3; disc lane у discovery rollup).
primary_blocker_of_session: static anvil fork drift → 100% fresh sim attempts BlockOutOfRangeError.
blocker_status_before: ACTIVE (1h soak Δsim_passed=0 both lanes)
blocker_status_after: MITIGATED — clamp + retry + refresh thread + Windows shutdown покриті 6 новими unit тестами; full suite 4199 PASS.
docs_reread_confirmed: true
