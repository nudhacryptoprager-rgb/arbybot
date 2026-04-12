# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-12T21:59:20Z
run_id: rolling (M7 nonstop sessions, not discrete runDir)
mode: ONLINE (M7.E1.12.4 — Anvil backend diversification, canonical rolling evidence)
artifact_mode: rolling
config: Base M7 nonstop (production + discovery), ARBY_SIM_BACKEND=anvil, Anvil Base fork block 44619899
code_identity:
  primary: ts:2026-04-12T21:59:20Z
  dirty: true
  desc: E1.12.4 engineering closure — simulation_backend field in rollup writer, Anvil fork sim backend, Status_M7.md honest exit criteria, DEV_REPORT refresh.
provenance_note:
  m4_rolling: run_summary_latest references ci_m5_gate_arbitrum_one_20260411_123905_815779 (run_timestamp: 2026-04-11T10:39:56Z). M4/M5 not touched this session.
  m7_evidence: M7 rolling evidence is from nonstop sessions on Base (21:29-22:00Z). Session IDs: production=589aeda7 (21:31:24-21:59:57Z), discovery=4551099e (21:35:10-22:00:08Z).

## Session Completion
session_goal: E1.12.4 canonical rolling evidence — run 2×30m soaks with ARBY_SIM_BACKEND=anvil, confirm simulation_backend=anvil in canonical rolling artifacts, update Status_M7 + DEV_REPORT honestly.
goal_status: REACHED
close_allowed: true
remaining_blockers: (1) Rolling sim_passed_total=0 — market-dependent (no events pass profit guard), not code bug. Proven working via focused soak (4C: 40/200) and acceptance test (4D: 1/1).
evidence_session_run_dirs: [rolling sessions: production=589aeda7, discovery=4551099e]
primary_blocker_of_session: simulation_backend_null_in_rolling
blocker_status_before: ACTIVE (simulation_backend field missing from rollup writer; ordering bug set field after guard_passed early return)
blocker_status_after: RESOLVED (simulation_backend=anvil confirmed in both prod+disc rolling after 2×30m soaks)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.12.4 = Anvil backend diversification + canonical rolling evidence with simulation_backend=anvil
change_summary:
  - m7/orderflow/execution_gate.py: Added simulation_backend field to ExecutionGateResult; fixed ordering bug (field set BEFORE guard_passed early return)
  - m7/orderflow/hot_runtime_artifacts.py: Added rollup["simulation_backend"] from gate_result
  - docs/status/Status_M7.md: Header downgraded to honest formulation; exit criteria updated; compressed 374→198 lines; blocker #3 updated
  - .gitignore: Added foundryup.sh
  - docs/DEV_REPORT_LATEST.md: Full overwrite with fresh evidence
touched_files:
  - m7/orderflow/execution_gate.py
  - m7/orderflow/hot_runtime_artifacts.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md
  - .gitignore

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3924 passed, 6 skipped)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.5 --no-m4 --chain base --m7-profile production --dashboard-port 8101 --m7-hot-pause 1 --m7-cold-pause 5: COMPLETED (21:29:57→21:59:57Z, 0 restarts, ARBY_SIM_BACKEND=anvil)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.5 --no-m4 --chain base --m7-profile discovery --dashboard-port 8102 --m7-hot-pause 1 --m7-cold-pause 5: COMPLETED (21:30:08→22:00:08Z, 0 restarts, ARBY_SIM_BACKEND=anvil)
py -3.11 scripts/ci_full_pipeline.py --mode ci: NOT RUN (M7 only, no M4/M5 changes)

## 3) Artifacts Attached

rolling:
  - data/runs/_rolling/m7_hot_rollup_latest.json (Base production, 5301 cumulative windows, 1698 events, simulation_backend=anvil)
  - data/runs/_rolling/m7_hot_rollup_latest_discovery.json (Base discovery, 500 windows, 532 events, simulation_backend=anvil)
  - data/runs/_rolling/m7_orderflow_latest.json (Base production cold)
  - data/runs/_rolling/m7_orderflow_latest_discovery.json (Base discovery cold)

## 4) Key Results

### 4.1) E1.12.4 Fresh Soak Evidence (2026-04-12, Anvil backend)

**Production** (session_id=589aeda7, 21:31:24→21:59:57Z, 30min):
| Metric | Session delta | Cumulative |
|--------|--------------|------------|
| Windows | +32 | 5301 |
| Events | +155 | 1698 |
| Fast scored | +4 | 465 |
| Fast positive | +0 | 37 |
| Guard passed | +0 | 31 |
| Sim attempted | +0 | 10 |
| Sim passed | +0 | 0 |
| WS connected | 31/32 | — |
| Heartbeat errors | 0 | 0 |
| Restarts | 0 | — |
| **simulation_backend** | **anvil** | — |
| sim_disabled | false | — |

**Discovery** (session_id=4551099e, 21:35:10→22:00:08Z, 30min):
| Metric | Session delta | Cumulative |
|--------|--------------|------------|
| Windows | +28 | 500 |
| Events | +140 | 532 |
| Fast scored | +6 | 94 |
| Fast positive | +0 | 7 |
| Guard passed | +0 | 7 |
| Sim attempted | +0 | 3 |
| Sim passed | +0 | 0 |
| WS connected | 28/28 | — |
| Heartbeat errors | 0 | 0 |
| Restarts | 0 | — |
| **simulation_backend** | **anvil** | — |
| sim_disabled | false | — |

**Ключове спостереження**: `simulation_backend=anvil` підтверджено в обох канонічних rolling артефактах. Rolling `sim_passed_total=0` — жодна подія не пройшла profit guard у поточних ринкових умовах. Це market-dependent, не code bug. Anvil sim pipeline доведений через:
- Focused soak (4C): 40 sim_passed / 200 sim_attempted / 0 crashes
- Acceptance test (4D): 1 sim_passed / 1 sim_attempted, gas_used=144810, backend=anvil

## 5) Contract Checks
status/reasons consistency: OK — Status_M7.md header honest, exit criteria honest about sim_passed=0 in rolling
rolling discipline (canonical files only): OK
provenance contract: OK — run_timestamp based
runtime artifacts not committed: OK

## 6) Blocker Classification

code_blocker: LOW (pytest 3924 PASS, simulation_backend wired and confirmed)
data_collection_blocker: LOW (WS stable, events flowing)
market_window_blocker: HIGH (0 events pass profit guard → sim_attempted=0 this session → sim_passed=0 in rolling)

## 6.1) Blockers / Risks (max 5)
1. **sim_passed=0 in canonical rolling** — market-dependent. Anvil pipeline proven via focused soak (40/200) and acceptance test (1/1).
2. **GAS_EXCEEDS_GROSS** — ~7% viable rate, near-exec frontier at -2.20 bps.
3. **dRPC HTTP 429** — 100% HTTP fallback this session. WS 100% stable. Not blocking.
4. **Tenderly HTTP 403 in discovery histogram** — Legacy pre-Anvil errors. Irrelevant with Anvil backend.

## 7) Lead's Previous 10 Steps: Execution Map
step_01: DONE — Fix Status_M7.md contradictions. evidence: Status_M7.md header + E1.12.4 heading
step_02: DONE — Add simulation_backend to rollup writer. evidence: execution_gate.py + hot_runtime_artifacts.py
step_03: DONE — Fix ordering bug (field before guard_passed). evidence: execution_gate.py
step_04: DONE — Compress Status_M7.md 374→198 lines. evidence: Status_M7.md
step_05: DONE — Add foundryup.sh to .gitignore. evidence: .gitignore
step_06: DONE — Start Anvil fork (block 44619899). evidence: Anvil terminal
step_07: DONE — Run 2×30m prod+disc ARBY_SIM_BACKEND=anvil. evidence: supervisor 0 restarts
step_08: DONE — Verify simulation_backend=anvil in rolling. evidence: m7_hot_rollup_latest*.json
step_09: DONE — Update Status_M7.md exit criteria. evidence: Status_M7.md line 107
step_10: DONE — Overwrite DEV_REPORT_LATEST.md. evidence: this file

## 8) What I need from Lead now
request_1: Review E1.12.4 closure. Confirm honest exit criteria (sim_passed proven via soak/test, not in rolling due to market).
request_2: If sim_passed>0 required in rolling for closure, run peak-hours soak or lower profit guard threshold temporarily.
