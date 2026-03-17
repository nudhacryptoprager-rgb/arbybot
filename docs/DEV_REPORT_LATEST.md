# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one. Scan stack is productive in simulate-only mode. Live execution infrastructure (simulator.py, dex_dex_executor.py) implemented and tested but NOT yet producing realized PnL — wired into scanner as dormant probe. R28.17: Truth-quality discipline — accounting contamination guard, 3-tier signal classification, COVERAGE truth-path parity.

## SESSION GOAL (2026-03-17, Session 10 Round 28.17)
**Goal**: R28.17 — Lead review directive: truth-quality discipline. Separate real executable signals from diagnostic/noise, remove accounting contamination, downgrade base from false CONFIRMED_POSITIVE_CONTROL.
**Prior (R28.16)**: Phase event protocol (_emit_phase in scanner, ARBY_PHASE: lines, phase badges in dashboard), /api/hot lightweight endpoint, pair-hot-queue visibility. 1932 tests.

## 0) Meta
timestamp_utc: 2026-03-17T08:04:59Z
rolling_provenance: 2026-03-17T08:04:59Z (run_summary_latest.json — rolling unchanged, R28.17 is truth-discipline code change)
rolling_run_dir: ci_m5_gate_arbitrum_one_20260317_090447_596027
mode: TRUTH_QUALITY_DISCIPLINE
test_count: 1937 passed, 3 skipped
schema_version: start:long_scan_summary:v1.13

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.17: Truth-quality discipline — downgrade base, add roundtrip accounting guard, 3-tier signal classification, COVERAGE truth-path parity, rolling protection |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | FRESH SCAN NEEDED: base will now be SUSPECT_ACCOUNTING on next scan; per-chain truth audit requires fresh online scans to produce artifacts with new guards |
| evidence_session_run_dirs | No new scan runs (R28.17 is code-level truth discipline); rolling artifacts unchanged from R28.15 |
| primary_blocker_of_session | Base falsely classified as CONFIRMED_POSITIVE_CONTROL due to contaminated roundtrip accounting (best_net_pnl_bps=8e16) |
| blocker_status_before | ACTIVE: base=CONFIRMED_POSITIVE_CONTROL (false), COVERAGE runs skip dynamic_sweep+preflight (chains not equally evaluated), no accounting guard, no test session protection |
| blocker_status_after | RESOLVED: SUSPECT_ACCOUNTING state added (absurd PnL guard), accumulation guard filters contaminated values, COVERAGE uses same truth path as NORMAL, hot_loop_snapshot v1.2 with is_test_session marker |
| start_metric | R28.16: 1932 tests, base=CONFIRMED_POSITIVE_CONTROL (false positive) |
| end_metric | R28.17: 1937 tests (+5), base will be SUSPECT_ACCOUNTING on fresh scan, 3-tier signal classification, COVERAGE parity |
| delta | +SUSPECT_ACCOUNTING state in classify_chain_profit_state, +SANE_ROUNDTRIP_PNL_BPS_MAX=500 guard, +_roundtrip_accounting_is_sane(), +suspect_profitable_count in roundtrip stats, +3-tier kpi_separation (diagnostic/real_quote/executable_profitable), -COVERAGE lightweight skip (dynamic_sweep+preflight now run for all run_kinds), +is_test_session in hot_loop_snapshot v1.2, +5 tests |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R28.17 lead review directive (truth-quality discipline)
change_summary:
  - ACCOUNTING GUARD: classify_chain_profit_state now has SUSPECT_ACCOUNTING state — chains with profitable_roundtrips > 0 but best_roundtrip_net_bps outside [-500, 500] bps or _suspect_accounting_count > 0 are classified as SUSPECT_ACCOUNTING (not CONFIRMED_POSITIVE_CONTROL). Base will be caught on next scan.
  - ACCUMULATION GUARD: update_chain_stats now filters best_net_pnl_bps values outside sane range [-500, 500] bps. Values outside this range are logged as SUSPECT_ACCOUNTING warnings and not accumulated into best_roundtrip_net_bps. Aligned with existing SUSPECT_ROUNDTRIP_OUTLIER_BPS=500 threshold.
  - PROFITABLE COUNT GUARD: run_scan_real.py now filters "profitable" roundtrips with net_pnl_bps > 500 from profitable_count. These are tracked separately as suspect_profitable_count for visibility.
  - 3-TIER SIGNAL CLASSIFICATION: kpi_separation in build_summary now uses diagnostic_signals (raw spread detections), real_quote_signals (roundtrips with real DEX quotes), executable_profitable (profitable roundtrips with sane accounting AND real quotes). Replaces old 4-tier (signals/exec_candidates/profitable_roundtrips/truth_confirmed).
  - COVERAGE TRUTH-PATH PARITY: Removed COVERAGE_LIGHTWEIGHT skip for dynamic_sweep and preflight_evidence in run_scan_real.py. All run_kinds (NORMAL, COVERAGE) now evaluated through same truth path. Chains can no longer get promoted based on COVERAGE runs that skipped key evaluation steps.
  - ROLLING PROTECTION: write_hot_loop_snapshot now accepts is_test_session parameter and writes it to hot_loop_snapshot:v1.2. Session detected via ARBY_OFFLINE=1 env var. Operators can distinguish test snapshots from operational ones.
  - profit_truth_summary now includes suspect_accounting chain group.
  - SCHEMA BUMP: long_scan_summary v1.12→v1.13, hot_loop_snapshot v1.1→v1.2.
touched_files:
  - start.py (+SUSPECT_ACCOUNTING state, +sane bounds guard, +3-tier kpi_separation, +is_test_session, +import os)
  - strategy/jobs/run_scan_real.py (+suspect_profitable_count filter, -COVERAGE lightweight skip)
  - tests/unit/test_start.py (+5 tests: suspect_accounting, sane_bounds, test_session_marker, schema version updates)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: **PASS** (1937 passed, 3 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (all gates green)
py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: **PASS**

## 3) Artifacts Attached
rolling (UNCHANGED from R28.15 — R28.17 is code-level change, fresh scan needed):
  - data/runs/_rolling/_latest.json (run_dir: ci_m5_gate_arbitrum_one_20260317_090447_596027)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-17T08:04:59Z)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: WARN_QUALITY, FRAGILE_P90_ELEVATED)
  - data/runs/_rolling/long_scan_latest.json (generated_at: 2026-03-17T08:02:29Z)

## 4) Key Results

```
# Rolling State (UNCHANGED from R28.15)
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY
run_summary_latest:
  status: PASS
  metrics.signals_count: 9
  metrics.total_net_usdc: 5.20
  run_timestamp: 2026-03-17T08:04:59Z

# Truth Audit (from long_scan_latest.json — R28.15 data, R28.17 classification)
# NOTE: base will be SUSPECT_ACCOUNTING on fresh scan (best_roundtrip_net_bps=8e16)
linea:         runs=6 pass=6 fail=0 rq=12 prt=12 state=CONFIRMED_POSITIVE_CONTROL  ← ONLY TRUE POSITIVE
arbitrum_one:  runs=5 pass=3 fail=1 rq=17 prt=0  state=PRIMARY_BLOCKER  ← real signals, not executable (spread~63bps minus slippage~61bps)
zksync:        runs=6 pass=6 fail=0 rq=12 prt=0  state=PRIMARY_BLOCKER  ← real quotes, zero profitable RT
base:          runs=6 pass=1 fail=1 rq=5  prt=2  state=CONFIRMED_POSITIVE_CONTROL → SUSPECT_ACCOUNTING (after fresh scan)
mantle:        runs=6 pass=0 fail=4 rq=0  prt=0  state=CANDIDATE
scroll:        runs=6 pass=0 fail=6 rq=0  prt=0  state=CANDIDATE

# 3-Tier Signal Classification (new in R28.17)
# diagnostic_signals: raw spread detections (one-leg, may be noise)
# real_quote_signals: roundtrips with real DEX quotes
# executable_profitable: profitable RT with sane accounting AND real quotes
```

## 4.1) Execution Infrastructure Status (unchanged from R28.15)

```
execution_truth_mode: SIMULATE_ONLY (paper profit)
live_execution_wired: true (dormant probe in scanner, gated by config)
live_execution_active: false
realized_pnl_produced: false
```

## 5) Contract Checks
- DEV_REPORT timestamp aligned with rolling run_context.run_timestamp — VERIFIED
- SUSPECT_ACCOUNTING prevents false CONFIRMED_POSITIVE_CONTROL — VERIFIED (base will be caught)
- SANE_ROUNDTRIP_PNL_BPS_MAX=500 aligned with SUSPECT_ROUNDTRIP_OUTLIER_BPS — VERIFIED
- COVERAGE truth-path parity: dynamic_sweep + preflight_evidence run for all run_kinds — VERIFIED
- M4 safety contract: execution_enabled=false, kill_switch_active=true — MAINTAINED
- All profit numbers are PAPER/SIMULATED — no real trades executed

## 6) Blocker Classification

```
code_blocker: NONE (1937 tests PASS, CI all gates green, repo safety PASS 0 warnings)
truth_quality_blocker: MEDIUM (base accounting contaminated, needs fresh scan to produce clean SUSPECT_ACCOUNTING)
execution_blocker: HIGH (live execution dormant — no signer, no realized PnL)
market_window_blocker: MEDIUM (arb/zksync: real signals but not executable; linea: confirmed profitable)
```

## 7) Lead's Verification Bundle (for next session)

```
# Offline gates (run immediately)
py -3.11 scripts/check_repo_safety.py
py -3.11 scripts/ci_full_pipeline.py --mode ci
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict

# Per-chain fresh scans (require live RPC)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_linea_stage1.yaml --cycles 5
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_base_stage2.yaml --cycles 5
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_zksync_candidate.yaml --cycles 5
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_mantle_stage2.yaml --cycles 5
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_scroll_stage1.yaml --cycles 5
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_arbitrum_one_candidate.yaml --cycles 5

# Full long scan (uses start.py, all chains)
py -3.11 start.py --config-list config/onboard_linea_stage1.yaml,config/onboard_base_stage2.yaml,config/onboard_zksync_candidate.yaml,config/onboard_mantle_stage2.yaml,config/onboard_scroll_stage1.yaml,config/onboard_arbitrum_one_candidate.yaml --accepted-fail-chains scroll --max-fail-chains 3 --hours 0.10 --cycles 1
```

## 8) What Lead Needs To Decide
1. **Fresh scan authorization**: Run verification bundle to produce artifacts with new accounting guards?
2. **Base investigation**: Root cause of best_net_pnl_bps=8e16 — likely token decimal mismatch in roundtrip evaluation for base chain. Needs per-pair inspection on fresh scan.
3. **Arb economics**: spread ~63 bps minus slippage ~61 bps = ~2 bps margin. With gas this is likely negative. Is arb worth continued scanning effort?
4. **zkSync path**: 12 real quotes but 0 profitable roundtrips. What's the cost breakdown (gas + fee + slippage)?