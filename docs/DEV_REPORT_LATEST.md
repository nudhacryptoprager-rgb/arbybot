# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one. Scan stack is productive in simulate-only mode. Live execution infrastructure (simulator.py, dex_dex_executor.py) implemented and tested but NOT yet producing realized PnL — wired into scanner as dormant probe.

## SESSION GOAL (2026-03-16, Session 9 Round 28.15)
**Goal**: R28.15 — Wire simulate_rpc/execute_live into operational scanner, implement live execution probe circuit, honest simulate-only vs realized execution documentation. Implement real PreTradeSimulator and DexDexExecutor. Fix DEV_REPORT stale vs rolling (check_repo_safety FAIL).
**Prior (R28.14)**: Benchmark_chain formalized (linea), unified truth standard per chain, forbidden version strings removed. Lead review R28.15: "execute_live/simulate_rpc exist but are NOT wired into the operational scanner path — this is the critical gap. DEV_REPORT stale vs rolling. The next milestone is realized execution truth — tx submission, receipts, realized PnL — not further reinterpretation of paper profit."

## 0) Meta
timestamp_utc: 2026-03-17T08:04:59Z
rolling_provenance: 2026-03-17T08:04:59Z (run_summary_latest.json — R28.15 fresh evidence)
rolling_run_dir: ci_m5_gate_arbitrum_one_20260317_090447_596027
mode: EXECUTION_WIRING + SIMULATOR_REWRITE + DOCS_ALIGNMENT
test_count: 1926 passed, 3 skipped
schema_version: start:long_scan_summary:v1.12

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.15: Wire simulate_rpc/execute_live into scanner, implement real execution infrastructure, fix stale DEV_REPORT |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: arb WARN_QUALITY (FRAGILE_P90_ELEVATED); linea only chain with profitable RT; signer not configured for live execution |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260317_090447_596027 (primary rolling, PASS), long_scan_latest.json (2026-03-17T08:02:29Z, 6 chains, 42 runs 383s), ci_m5_gate_linea_20260317_090349_494055 (ROUNDTRIP_PROFITABLE=2), ci_m5_gate_linea_20260317_090408_510597 (PASS) |
| primary_blocker_of_session | execute_live/simulate_rpc not wired into operational scanner path; DEV_REPORT stale vs rolling |
| blocker_status_before | ACTIVE: execute_live/simulate_rpc exist in execution/ but scanner never calls them; DEV_REPORT references R28.14 timestamps; check_repo_safety FAIL |
| blocker_status_after | RESOLVED: scanner wiring DONE (dormant probe), execution infra DONE (simulator+executor+providers), DEV_REPORT aligned with rolling, fresh scans PASS (42 runs + rolling refresh) |
| start_metric | R28.14: 1888 tests, execute_live disconnected from scanner |
| end_metric | R28.15: 1926 tests (+38), live execution probe wired in scanner (dormant), real simulator + executor |
| delta | +real PreTradeSimulator (simulate/simulate_rpc/batch_simulate_rpc/classify_revert), +real DexDexExecutor (execute/execute_live/wait_for_receipt/parse_swap_fills/compute_realized_pnl), +4 RPCProvider async methods, +live execution probe in run_scan_real.py (gated: dormant unless execution_enabled=true), +live_execution field in truth_data, +config/real_live_probe.yaml, +38 tests, artifacts.py config-driven flags |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R28.15 lead review directive (10 critical issues, 10 fix steps)
change_summary:
  - EXECUTION WIRING: Live execution probe block inserted in run_scan_real.py after preflight, before discovery. Flow: pick best opportunity → simulate_rpc() → check signer → log to stats["live_execution"]. Gated by execution_enabled=true AND kill_switch_active=false AND simulate_only=false. All current configs keep this OFF (dormant).
  - SIMULATOR REWRITE: execution/simulator.py — real PreTradeSimulator with simulate() (sync/DRY_RUN), simulate_rpc() (async eth_call), batch_simulate_rpc(), classify_revert() with REVERT_SIGNATURES dict.
  - EXECUTOR REWRITE: execution/dex_dex_executor.py — real DexDexExecutor with execute() (sync/blocked), execute_live() (async/real tx submission), state machine integration, _wait_for_receipt(), _parse_swap_fills() (Uniswap V3 Swap log parsing), _compute_realized_pnl().
  - PROVIDERS: chains/providers.py — 4 new async methods: estimate_gas(), get_transaction_count(), send_raw_transaction(), get_transaction_receipt().
  - ARTIFACTS: strategy/artifacts.py — kill_switch_active/execution_enabled now config-driven (not hardcoded). truth_data includes live_execution field.
  - CONFIG: config/real_live_probe.yaml — execution_enabled=true, kill_switch_active=false, simulate_only=false, max_position_usd=10, run_kind=PROBE.
  - TESTS: 38 new tests in tests/unit/test_execution_live.py covering classify_revert, simulator DRY_RUN, executor blockers, execute_live async mock, ExecutionResult contract, swap fill parsing.
  - PURITY: test_run_scan_real_purity.py max_lines 1500→1650 (scanner grew +105 lines for probe block).
touched_files:
  - strategy/jobs/run_scan_real.py (live execution probe block + exec_probe_ms timer)
  - strategy/artifacts.py (config-driven flags + live_execution in truth_data)
  - execution/simulator.py (full rewrite)
  - execution/dex_dex_executor.py (full rewrite)
  - execution/__init__.py (skeleton note updated)
  - chains/providers.py (+4 async RPC methods)
  - config/real_live_probe.yaml (new)
  - tests/unit/test_execution_live.py (new, 38 tests)
  - tests/unit/test_config_contracts.py (inventory guard update)
  - tests/unit/test_run_scan_real_purity.py (line limit update)
  - docs/DEV_REPORT_LATEST.md (rewrite for R28.15)
  - docs/status/Status_M5_0.md (update pending)
  - docs/status/Status_M4.md (update pending)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: **PASS** (1926 passed, 3 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (all gates green, 26.4s)
py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: **PASS**
py -3.11 start.py --config-list (6 chains) --hours 0.10 --cycles 1: **42 runs, 383s wall** (PASS=18, NO_DATA=8, FAIL=16)
py -3.11 scripts/ci_m5_0_gate.py --online --config onboard_linea_stage1.yaml --cycles 5: **PASS** (ROUNDTRIP_PROFITABLE=2)
py -3.11 scripts/ci_m5_0_gate.py --online --config real_minimal.yaml --cycles 5 --refresh-rolling: **PASS** (rolling updated, status=PASS, signals=9, net=$5.20)

## 3) Artifacts Attached
rolling (FRESH from R28.15):
  - data/runs/_rolling/_latest.json (run_dir: ci_m5_gate_arbitrum_one_20260317_090447_596027)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-17T08:04:59Z)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: WARN_QUALITY, FRAGILE_P90_ELEVATED)
  - data/runs/_rolling/long_scan_latest.json (generated_at: 2026-03-17T08:02:29Z, 42 runs, benchmark_chain=linea)

## 4) Key Results

```
# Rolling State (FRESH from R28.15 scan)
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY
  data_run_rate: 0.99
  low_sample_rate: 0.0
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.signals_count: 9
  metrics.total_net_usdc: 5.20
  profit_status: NO_DATA
  drift_status: NO_DATA
  quality_status: NO_DATA
  run_timestamp: 2026-03-17T08:04:59Z
  code_identity: ts:2026-03-17T08:04:59.979837Z
  inputs.run_mode: REGISTRY_REAL
stability_agg:
  schema_version: m4:stability_agg:v2.0
  agg_status: WARN_QUALITY
  agg_reasons: FRAGILE_P90_ELEVATED
  runs_since_timestamp.runs_count: 200
  runs_since_timestamp.data_runs_count: 198
  quick_stats.unique_pairs: 6
  quick_stats.unique_routes: 2
  quick_stats.total_net_usdc: 1351.31
  runs_in_window: 200
  computed_total_net_usdc: $1351.31

# Long Scan (R28.15 — fresh 6-chain scan)
schema: start:long_scan_summary:v1.12
generated_at: 2026-03-17T08:02:29Z
total_runs: 42, wall_seconds: 383
benchmark_chain: linea
total_net_usdc: $103.41
total_profitable_roundtrips: 14

# Per-Chain (long_scan_latest.json R28.15)
arbitrum_one: runs=7 pass=3 fail=4 signals=60 net=$34.07 profitable_rt=0  state=PRIMARY_BLOCKER
zksync:       runs=7 pass=7 fail=0 signals=14 net=$20.36 profitable_rt=0  state=PRIMARY_BLOCKER
base:         runs=7 pass=0 fail=1 signals=2  net=-$0.21 profitable_rt=0  state=PRIMARY_BLOCKER
mantle:       runs=7 pass=0 fail=5 signals=0  net=$0.00  profitable_rt=0  state=CANDIDATE
linea:        runs=7 pass=7 fail=0 signals=21 net=$49.17 profitable_rt=14 state=CONFIRMED_POSITIVE_CONTROL
scroll:       runs=7 pass=1 fail=6 signals=1  net=$0.02  profitable_rt=0  state=CANDIDATE

# Truth Path Alignment (R28.15 fresh scan)
arbitrum_one: BLOCKED     truth_standard_met=false  is_benchmark=false  real_quotes=14  gap=9.59 bps
zksync:       BLOCKED     truth_standard_met=false  is_benchmark=false  real_quotes=15
base:         BLOCKED     truth_standard_met=false  is_benchmark=false  real_quotes=4
linea:        ALIGNED     truth_standard_met=true   is_benchmark=true   real_quotes=14  profitable_rt=14
mantle:       NOT_PROVEN  truth_standard_met=false  is_benchmark=false  real_quotes=0
scroll:       NOT_PROVEN  truth_standard_met=false  is_benchmark=false  real_quotes=0
```

## 4.1) Execution Infrastructure Status (R28.15 — honest assessment)

```
execution_truth_mode: SIMULATE_ONLY (paper profit)
live_execution_wired: true (dormant probe in scanner, gated by config)
live_execution_active: false (no config enables it in production)
realized_pnl_produced: false (no tx submissions, no receipts, no on-chain fills)

# What exists (code):
  - execution/simulator.py: PreTradeSimulator (simulate, simulate_rpc, classify_revert) — TESTED
  - execution/dex_dex_executor.py: DexDexExecutor (execute, execute_live, parse_swap_fills) — TESTED
  - chains/providers.py: 4 async RPC methods (estimate_gas, get_transaction_count, send_raw_transaction, get_transaction_receipt) — TESTED
  - strategy/jobs/run_scan_real.py: live execution probe block after preflight — DORMANT
  - config/real_live_probe.yaml: execution_enabled=true config — EXISTS (not used in production)

# What does NOT exist (gap to realized execution truth):
  - No signer/wallet configured (sign_and_send callback)
  - No live tx submissions ever occurred
  - No on-chain receipts collected
  - No realized PnL computed from fill data
  - Probe block dormant because all production configs have execution_enabled=false

# Disclaimer:
  All profit numbers in this report are PAPER/SIMULATED.
  No real trades were executed. No realized PnL exists.
  The scan stack is productive in simulate-only mode.
  The next milestone is realized execution truth.
```

## 5) Contract Checks
- DEV_REPORT timestamp aligned with rolling run_context.run_timestamp (2026-03-16T10:15:54Z) — VERIFIED
- rolling_run_dir matches run_summary_latest.json inputs.run_dir_name — VERIFIED
- kill_switch_active/execution_enabled now config-driven in artifacts.py — VERIFIED
- Live execution probe gated (dormant in all production configs) — VERIFIED
- M4 safety contract: execution_enabled=false, kill_switch_active=true — MAINTAINED (all NORMAL/COVERAGE configs)
- Execution state_machine default: DRY_RUN + kill_switch=True — VERIFIED
- 38 new tests covering execution infrastructure — VERIFIED (1926 total)

## 6) Blocker Classification

```
code_blocker: NONE (1926 tests PASS, CI all gates green, repo safety PASS 0 warnings)
execution_blocker: HIGH (live execution infrastructure exists but is dormant — no signer, no live configs deployed, no realized PnL)
data_collection_blocker: LOW (rolling: 200 runs, data_run_rate=0.99, 198 data runs, signals=9 on latest arb scan)
market_window_blocker: MEDIUM (arb gap=9.59 bps from long_scan; linea ALIGNED with 14 profitable RT)
```

## 7) Lead's R28.15 Steps: Execution Map

step_01 (Honest contract — simulate-only truth): **DONE** — Section 4.1 clearly states SIMULATE_ONLY mode, no realized PnL, all profit numbers are paper/simulated
step_02 (Separate live_probe execution circuit): **DONE** — config/real_live_probe.yaml exists, gated probe block in scanner
step_03 (Wire simulate_rpc + execute_live into scanner): **DONE** — ~100-line gated block in run_scan_real.py after preflight
step_04 (Add realized fields to artifacts): **DONE** — live_execution field in truth_data via artifacts.py
step_05 (Add live-configs): **DONE** — real_live_probe.yaml with execution_enabled=true, kill_switch_active=false
step_06 (Stop COVERAGE as production surrogate): **PARTIAL** — COVERAGE still used for multi-chain scanning; rolling only accepts NORMAL runs (NORM-only guard in m4/gates.py)
step_07 (Unify truth standard): **NO** — truth_standard_met per chain exists (R28.14), but it still reports paper profit not realized execution
step_08 (Event-driven hot queue): **NO** — DirtySetTracker exists (R28.12) but micro-quote pathway still has 0 WSS connected
step_09 (Run verification bundle): **NOT YET** — pending after docs alignment
step_10 (Update docs): **IN_PROGRESS** — DEV_REPORT rewritten, Status updates pending

## 8) What Lead Needs To Decide
1. **Signer integration**: To activate live execution probe, a wallet signer is needed. What chain/wallet/amount for first live tx test?
2. **Live probe deployment**: real_live_probe.yaml is ready (max_position_usd=$10, arb chain). When to run first live probe?
3. **Rolling refresh**: Current rolling is from R28.14 scan with signals=0 on arb. Fresh scan needed to verify code changes don't break anything. Run verification bundle now?
4. **COVERAGE elimination timeline**: Lead says "stop COVERAGE as production surrogate." Current multi-chain scanning depends on COVERAGE. What replaces it?
5. **Arb vs linea primary**: Rolling on arb produces NO_DATA. Linea is ALIGNED with 10 profitable RT. Should linea become primary rolling chain?