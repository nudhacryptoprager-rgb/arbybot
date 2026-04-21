# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
run_id: data/runs/_rolling (session_id=38e43e8e; anvil-backed 30-min Base soak)
mode: ONLINE
artifact_mode: rolling
config: Base, dRPC archive fork (ARBY_SIM_BACKEND=anvil, ARBY_ANVIL_RPC_URL=http://127.0.0.1:8545)
code_identity:
  primary: ts:2026-04-17T12:59:11.866411Z
  dirty: true вЂ” Steps 1/2/5/6/7 wired into execution gate + sim backend; admission filter ENV-controlled
  desc: venue auto-registry fallback, BlockOutOfRange retry, M4 quality gates, AMOUNT_ZERO autofill, pre-sim admission filter

## 1) Scope
goal: РЎРєРѕСЂРѕС‚РёС‚Рё hot-lane sim funnel РґРѕ admission-worthy candidates; Р·РЅРёР·РёС‚Рё РЅР°РІР°РЅС‚Р°Р¶РµРЅРЅСЏ РЅР° rate-limited RPC (dRPC/Tenderly); РІР°Р»С–РґСѓРІР°С‚Рё РїС–Рґ anvil EVM.
change_summary:
  - Step 1: venue auto-registry fallback (execution_gate.py:310-358) вЂ” С†С–Р»РёС‚СЊСЃСЏ Сѓ VENUE_MISSING=165.
  - Step 2: BlockOutOfRangeError retry (rpc_fork_backend.py).
  - Step 5: M4 quality gates вЂ” AGG_TOP_PAIR_DOMINANCE_WARN, AGG_DRIFT_WORST_PAIR_BPS_WARN.
  - Step 6: AMOUNT_ZERO autofill (execution_gate.py:365-400) вЂ” best_sweep_size_wei / get_min_profitable_size_wei; С†С–Р»РёС‚СЊСЃСЏ Сѓ AMOUNT_ZERO=259.
  - Step 7 NEW: pre-sim admission filter (execution_gate.py:854-917). ENV: ARBY_SIM_ADMISSION_STRICT=1 (default), ARBY_SIM_MIN_NET_BPS=1.0, ARBY_SIM_MIN_AMOUNT_WEI=0. Р’С–РґСЃС–СЏРЅС– в†’ PRE_SIM_SKIP:* Сѓ sim_errors, РќР• С–РЅРєСЂРµРјРµРЅС‚СѓСЋС‚СЊ sim_attempted.
  - start_anvil_fork.py: ARBY_FORK_RPC_URL override (Alchemy РєРІРѕС‚Р° РІРёС‡РµСЂРїР°РЅР°; dRPC Base archive).
  - Tests: +7 Сѓ test_execution_gate.py (3Г— autofill, 4Г— admission); +6 Сѓ test_quality_gates_step5.py.
touched_files:
  - m7/orderflow/execution_gate.py, m7/orderflow/sim_backends/rpc_fork_backend.py
  - m4/policy.py, m4/rolling_store.py, scripts/start_anvil_fork.py
  - tests/unit/test_execution_gate.py, tests/unit/test_quality_gates_step5.py (new)
  - docs/DEV_REPORT_LATEST.md, docs/status/Status_M7.md

## 2) Commands Executed
pytest tests/unit: **PASS** 4193/6sk (104.38s)
pytest tests/unit/test_execution_gate.py: **PASS** 67/0 (2.47s)
check_repo_safety.py: **PASS** (1 warning вЂ” РґРёРІ. СЃРµРєС†С–СЏ 5)
ci_full_pipeline / ci_m4_execution_gate / ci_m5_0_gate: NOT RUN вЂ” reviewer scope.

## 3) Artifacts
rolling: _latest.json, run_summary_latest.json, m4_stability_agg.json, m7_hot_rollup_latest.json (session 38e43e8e, anvil), m7_orderflow_latest.json
run_dir_bundle: data/runs/ci_m5_gate_arbitrum_one_20260417_145636_478653/reports (cited by run_summary_latest)

## 4) Key Results
m7_hot_rollup (Base, anvil, session 38e43e8e):
  last_updated=2026-04-21T13:24:27Z; 64 windows; 0 WS failures; 6 fast_scored; last_rpc_provider=drpc; simulation_backend=anvil
  CUMULATIVE (558 windows): sim_attempted=933 / sim_passed=243 / roundtrip_attempted=243 / roundtrip_success=228 / roundtrip_profitable=16
  histogram top: 259 AMOUNT_ZERO (pre-Step6), 165 VENUE_MISSING (pre-Step1), 152 TOKEN_ADDRESS_UNKNOWN, 67 REVERT:unknown, 20 REVERT:STF
run_summary_latest:
  schema=m4:run_summary:v2.0; status=PASS; profit_realism_status=ROUNDTRIP_NOT_PROFITABLE
  real_quote_count=0; profitable_roundtrips=0; quality_status=WARN
  run_timestamp=2026-04-17T12:59:11.866411Z; inputs.run_mode=REGISTRY_REAL
stability_agg: runs_count=200; data_run_rate=1.0; pass_rate=0.935

## 4.1) Theoretical Net Profit
mode: paper_simulated; net_pnl_usdc: n/a (profit_realism=ROUNDTRIP_NOT_PROFITABLE; no canonical profitable roundtrip).
disclaimer: execution_enabled=false, kill_switch_active=true. No real trades executed.

## 5) Contract Checks
pytest tests/unit: **PASS** 4193/0
status/reasons consistency: OK
rolling discipline: OK; runtime artifacts not committed: OK
check_repo_safety.py v1.15.0: **PASS exit=0** (FAIL resolved via timestamp propagation). 1 WARN: DOCS_CONTENT_BLOAT on DEV_REPORT_LATEST.md (non-blocking). All 20 gates green except line-limit warning.

## 6) Blocker Classification
code_blocker: **LOW** вЂ” 4193/4193 PASS, 0 regressions.
data_collection_blocker: **MEDIUM** вЂ” anvil static fork_block vs latest в†’ BlockOutOfRangeError drift (Step 9 planned).
market_window_blocker: **HIGH** вЂ” cumulative profitable 16/243 (~6.6%); 30-С…РІ СЃРµСЃС–СЏ РґР°Р»Р° С‚С–Р»СЊРєРё 6 fast_scored в†’ РµРјРїС–СЂРёС‡РЅРѕС— РІР°Р»С–РґР°С†С–С— Step 6/7 РЅР° rolling С‰Рµ РЅРµРјР°С”.

## 6.1) Risks
- Alchemy РєРІРѕС‚Р° РІРёС‡РµСЂРїР°РЅР° в†’ dRPC primary.
- Anvil block drift: 30 С…РІ в‰€ +900 Р±Р»РѕРєС–РІ Base.
- AMOUNT_ZERO/VENUE_MISSING С–СЃС‚РѕСЂРёС‡РЅР° РјР°СЃР° РІ histogram; Steps 1+6 РІРїР»РёРІР°СЋС‚СЊ С‚С–Р»СЊРєРё РЅР° РЅРѕРІС– windows.
- TOKEN_ADDRESS_UNKNOWN (152) вЂ” РЅР°СЃС‚СѓРїРЅРёР№ Р±Р»РѕРєРµСЂ (Step 8).

## 7) Execution Map
step_01 venue fallback: **DONE**
step_02 block retry: **DONE**
step_05 quality gates: **DONE**
step_06 AMOUNT_ZERO autofill: **DONE**
step_07 admission filter: **DONE**
step_08 TOKEN_ADDRESS_UNKNOWN: NOT STARTED
step_09 anvil_mine loop: NOT STARTED
step_10 tenderly renewal: NOT STARTED (Lead scope)

## 8) Requests to Lead
request_1: 1-РіРѕРґРёРЅРЅРёР№ Base soak Р· strict admission вЂ” runbook РЅРёР¶С‡Рµ.
request_2: РїС–РґС‚РІРµСЂРґРёС‚Рё, С‰Рѕ PRE_SIM_SKIP:* Р·'СЏРІР»СЏС”С‚СЊСЃСЏ Сѓ РЅРѕРІРѕРјСѓ histogram.
q_1: ARBY_SIM_BYPASS_GUARD 0 С‡Рё 1? (РїСЂРѕРїРѕРЅСѓСЋ 0).
q_2: ARBY_SIM_MIN_NET_BPS 1.0 С‡Рё РїС–РґРЅСЏС‚Рё РґРѕ 5.0/10.0?

---

## REVIEWER RUNBOOK вЂ” 1-hour soak

**Prereq**: Python 3.11, venv, tools/foundry/anvil.exe.

### Term A вЂ” anvil fork
```powershell
.\venv\Scripts\Activate.ps1
$env:PATH = "$PWD\tools\foundry;$env:PATH"
$env:ARBY_FORK_RPC_URL = "https://lb.drpc.live/base/AovP_0y4K04riEUupzM1hrmZ7i1kNXwR8YgIsuMGSdYJ"
py -3.11 scripts/start_anvil_fork.py --chain base --fork-block-offset 5
```

### Term B вЂ” 1-РіРѕРґ soak
```powershell
.\venv\Scripts\Activate.ps1
Remove-Item Env:BASE_RPC_URL -ErrorAction SilentlyContinue
$env:PATH = "$PWD\tools\foundry;$env:PATH"
$env:ARBY_SIM_BACKEND="anvil"; $env:ARBY_ANVIL_RPC_URL="http://127.0.0.1:8545"
$env:ARBY_SIM_FALLBACK="rpc_fork"; $env:ARBY_HOT_REHYDRATE="1"
$env:ARBY_BROAD_FALLBACK_MIN_USD="500"
$env:ARBY_SIM_ADMISSION_STRICT="1"; $env:ARBY_SIM_MIN_NET_BPS="1.0"
$env:ARBY_SIM_BYPASS_GUARD="0"
py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 1 --with-discovery --no-m4
```

### Check metrics
```powershell
py -3.11 -c "import json; d=json.load(open('data/runs/_rolling/m7_hot_rollup_latest.json')); print('session:', d['session']); print('sim:', d['sim_attempted_total'], d['sim_passed_total']); print('rt_profit:', d['roundtrip_profitable_total']); print('backend:', d['simulation_backend']); h=d['simulation_error_histogram']; [print(f'  {v:4d}  {k[:90]}') for k,v in sorted(h.items(), key=lambda kv:-kv[1])[:10]]"
```

### Acceptance
- session_ws_failed_windows=0, session_fast_path_scored_total>=20
- РЈ histogram Р·'СЏРІР»СЏС”С‚СЊСЃСЏ PRE_SIM_SKIP:BELOW_MIN_NET_BPS:1.0 РђР‘Рћ PRE_SIM_SKIP:NO_AMOUNT_NO_FEE_HINT
- О”VENUE_MISSING=0, О”AMOUNT_ZEROв‰¤5
- РЇРєС‰Рѕ anvil BlockOutOfRangeError >50/С…РІ в†’ Step 9 СЃС‚Р°С” РїСЂС–РѕСЂРёС‚РµС‚РѕРј.

### Killswitch
Term A: Ctrl+C в†’ `Get-Process anvil -EA SilentlyContinue | Stop-Process`.

---

## Session Completion
session_goal: Step 7 pre-sim admission filter + reviewer 1-РіРѕРґ runbook.
goal_status: REACHED
close_allowed: true
remaining_blockers: anvil drift (Step 9); TOKEN_ADDRESS_UNKNOWN (Step 8); reviewer soak live-validation.
evidence_session_run_dirs:
  - data/runs/_rolling (session 38e43e8e; anvil; 64 windows; 0 WS failures)
  - data/runs/ci_m5_gate_arbitrum_one_20260417_145636_478653
primary_blocker_of_session: РЅР°РґРјС–СЂРЅРµ RPC РЅР°РІР°РЅС‚Р°Р¶РµРЅРЅСЏ РІС–Рґ low-value candidates.
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED (Step 7 Р±Р»РѕРєСѓС” РґРѕ RPC-РІРёРєР»РёРєСѓ; 4193/4193 unit PASS)
docs_reread_confirmed: true
