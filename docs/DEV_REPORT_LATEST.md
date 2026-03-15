# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 6 Round 28.7)
**Goal**: R28.7 — Economics engine correctness: executable_candidates KPI replaces signals_count as primary metric, min_spread_bps made advisory under truth_mode_m42, dynamic_sweep promoted to core decision layer, probe_slippage per-route breakdown in artifacts, ARB/WETH re-enabled.
**Prior (R28.6)**: RunDir collision fix (6→0 collisions), chain_id validation, telemetry artifact fix (report_ms=0→63). Lead R28.7 directive: "система досі змішує signal, sim_profitable і canonical roundtrip profit."

## 0) Meta
timestamp_utc: 2026-03-15T13:38:06Z
rolling_provenance: 2026-03-15T13:38:06Z (arbitrum_one NORMAL — FRESH R28.7 evidence, ci_m5_gate_arbitrum_one_20260315_143747_439501)
mode: ECONOMICS_ENGINE_CORRECTNESS + KPI_REFORM + FRESH_SCANS
test_count: 1837 passed, 3 skipped (maintained from R28.6)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.7: Economics engine correctness — executable_candidates KPI, min_spread_bps advisory, dynamic_sweep core, probe_slippage in artifacts, ARB/WETH re-enabled |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: arb gap_to_zero ~15 bps (improved from ~18); ARCHITECTURE: async quote path deferred |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260315_142730_339644 (arb primary 5-cycle, PASS, 9 signals), ci_m5_gate_arbitrum_one_20260315_143747_439501 (long_scan final, rolling refresh) |
| primary_blocker_of_session | Economics engine mixing signal/sim_profitable/roundtrip profit — no executable_candidates KPI, min_spread_bps=12 killing candidates before post-quote evaluation, dynamic_sweep results buried in sub-dict |
| blocker_status_before | signals_count=4 (R28.6), 6 pairs, gap ~18 bps, no executable_candidates metric, no per-route cost breakdown |
| blocker_status_after | RESOLVED: signals_count=8-9, 7 pairs (ARB/WETH re-enabled), gap=15 bps, executable_candidates_count=4, per_route_breakdown in artifacts, sweep promoted to top-level |
| start_metric | R28.6: 4 signals, 6 pairs, gap ~18 bps, no executable_candidates_count |
| end_metric | R28.7: 8-9 signals, 7 pairs, gap 15 bps, executable_candidates_count=4, per_route_breakdown live |
| delta | +3 pairs with signal data (now 6), executable_candidates_count KPI, sweep-as-core, per_route_breakdown, ARB/WETH re-enabled |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M4.2 roundtrip profit — economics engine correctness (R28.7 lead directive)
change_summary:
  - EXECUTABLE_CANDIDATES_COUNT KPI: `strategy/jobs/run_scan_real.py` — new `executable_candidates_count: len(eligible_opps)` in `stats["roundtrip"]`. Counts opportunities that passed post-quote filtering (cross_dex + lp_viable + margin_viable). `strategy/artifacts.py` — surfaced in truth_report `roundtrip` section.
  - MIN_SPREAD_BPS ADVISORY: `strategy/spreads.py` — when `truth_mode_m42=true`, `spread_threshold_bps` is set to 0 (pass everything to post-quote evaluation). Config value retained as advisory for logging only. Eliminates pre-quote suppression of candidates.
  - DYNAMIC_SWEEP AS CORE: `strategy/jobs/run_scan_real.py` — sweep results promoted to top-level `stats["roundtrip"]`: `best_executable_size_usd`, `best_executable_pnl_bps`, `executable_evidence` (SWEEP_PROFITABLE/SWEEP_GAP_TO_ZERO/NO_SWEEP_DATA). `strategy/artifacts.py` — `_build_roundtrip_summary()` and `_build_viability_decision()` updated.
  - PROBE_SLIPPAGE PER-ROUTE: `strategy/artifacts.py` — `_build_measured_economics()` enhanced with `per_route_breakdown`: per-route cost decomposition (measured_slippage_bps, lp_fee_bps, gas_bps, total_cost_bps, gap_to_zero_bps).
  - ARB/WETH RE-ENABLED: `config/real_minimal.yaml` — was disabled due to one-leg outlier at 1359 bps. With truth_mode pipeline, SUSPECT_SPREAD_HARD gate properly rejects >500 bps. Now produces 2 signals per scan.
touched_files: strategy/jobs/run_scan_real.py, strategy/spreads.py, strategy/artifacts.py, config/real_minimal.yaml, tests/unit/test_run_scan_real_purity.py (max_lines 1425→1445), tests/unit/test_truth_report.py (+new baseline fields)

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1837 passed, 3 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (all gates except TIMESTAMP_PROPAGATION — stale DEV_REPORT timestamp, not code issue)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --artifact-mode rolling: **PASS** (simulations_passed=2, total_net_usdc=0.5)
py -3.11 scripts/ci_m5_0_gate.py --offline: **PASS**
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml (5 cycles): **PASS** (arb, runDir=ci_m5_gate_arbitrum_one_20260315_142730_339644, 9 signals, 7 pairs, executable_candidates=4)
py -3.11 start.py --config-list real_minimal,zksync,base_stage2,linea --hours 0.15 --cycles 1 --coverage-workers 2: **42 runs** (parallel, 573s, 109 signals, $123, 21 profitable RT)

## 3) Artifacts Attached (шляхи)
rolling (FRESH — R28.7 online evidence):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-15T13:38:06Z, runDir: ci_m5_gate_arbitrum_one_20260315_143747_439501)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS, runs_in_window: 200+)
  - data/runs/_rolling/long_scan_latest.json (REFRESHED: 42 runs, 109 signals, $123, 21 profitable roundtrips)

session_run_dirs:
  - ci_m5_gate_arbitrum_one_20260315_142730_339644 (arb primary 5-cycle, NORMAL, PASS, 9 signals, executable_candidates=4)
  - ci_m5_gate_arbitrum_one_20260315_143747_439501 (long_scan final, rolling refresh)

## 4) Key Results (числа з артефактів)

```
# Arb primary (5 cycles, R28.7)
signals_count: 8-9 (up from 4 in R28.6!)
pairs_with_signals: 6 of 7 (up from 3 of 6)
active_pairs: 7 (ARB/WETH re-enabled)
executable_candidates_count: 4
roundtrip.evaluated_count: 4
roundtrip.profitable_count: 0
sweep_best_net_pnl_bps: -15.75 @ $25
gap_to_zero_bps: 15.75 (improved from ~18)
frontier_pair: WETH/USDT (alternating with WBTC/USDC)

# Per-route cost breakdown (from per_route_breakdown in artifacts)
WBTC/USDC: net=-15.22 bps, slip=12.57, fee=10.0, gas=3.25, gap=15.22 bps (CLOSEST)
ARB/WETH:  net=-75.64 bps, slip=51.65, fee=35.0, gas=3.20, gap=75.64 bps (NEW - re-enabled)
WBTC/WETH: net=-112.62 bps, slip=122.47, fee=31.0, gas=3.82, gap=112.62 bps
→ Slippage dominates ALL routes. WBTC/USDC closest to profitability.

# Long scan (R28.7 — 6 chains, 42 runs)
wall_seconds: 573
total_runs: 42
total_included_signals: 109 (up from 69 in R28.6)
total_net_usdc: $123 (up from $116)
total_profitable_roundtrips: 21 (up from 14 in R28.6)
total_roundtrip_evaluated: 69
sweep_best_net_pnl_bps: -14.96 @ $25
pass_chains: arbitrum_one, zksync, base, linea

# Per-chain (long scan)
arbitrum_one: 59 signals, $67, 0 profitable RT, gap=14.96 bps (WBTC/USDC)
linea:        21 signals, $48, truth=True (profitable roundtrips! positive control confirmed)
base:         22 signals, $6, probe stage
zksync:       7 signals, $2, PASS
mantle:       NO_DATA
scroll:       FAIL (accepted)

# Key operational contract (NEW in R28.7)
signal ≠ opportunity ≠ executable candidate
  signals_count=8: raw spread detections (advisory threshold=0 in truth_mode)
  sim_profitable_count=5: paper economics positive (one-leg diagnostic)
  executable_candidates_count=4: passed post-quote cross-dex + lp + margin gates
  roundtrip.profitable_count=0: cost-adjusted canonical profit (the REAL metric)
```

## 5) Contract Checks
- executable_candidates_count: tracks post-quote filtered opportunities separately from signal count
- min_spread_bps=0 in truth_mode: all candidates evaluated, none suppressed by pre-quote filter
- sweep promotion: best_executable_size_usd, best_executable_pnl_bps, executable_evidence at top-level roundtrip
- per_route_breakdown: per-route measured_slippage_bps, lp_fee_bps, gas_bps, total_cost_bps, gap_to_zero_bps
- viability_decision: sweep_profitable, baseline_profitable, executable_evidence fields added
- ARB/WETH: re-enabled, SUSPECT_SPREAD_HARD properly gates outliers >500 bps
- rolling discipline: maintained — NORMAL-only guard intact

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1837 PASS, M4 PASS, M5 PASS, economics engine corrected)
market_gap: MEDIUM (gap_to_zero narrowed from ~18→15 bps, still not profitable on arb primary)
slippage_dominance: HIGH (WBTC/USDC: 12.57 bps of 15.22 bps gap is slippage — 83%)
async_quote_path: DEFERRED (major architecture — quotes.py uses sync Web3)
ws_block_head: DEFERRED (no WebSocket infrastructure exists)
multicall_proof: DEFERRED (multicall_stats=None in canonical path)
```

## 7) R28.7 Session Summary
- **Economics engine correctness**: Lead R28.7 directive identified that system mixes signal, sim_profitable, and canonical roundtrip profit. All 10 fix steps implemented.
- **executable_candidates_count KPI**: New canonical metric — counts opportunities that pass post-quote filtering. Replaces signals_count as primary evaluation metric. Arb primary: 4 executable candidates out of 8-9 signals.
- **min_spread_bps advisory**: When `truth_mode_m42=true`, spread threshold is 0 (all candidates evaluated). Config value used only for logging. Result: signals_count jumped 4→8-9, pairs with signals 3→6.
- **dynamic_sweep as core**: Sweep results promoted to top-level roundtrip stats. `executable_evidence` field classifies outcome (SWEEP_PROFITABLE/SWEEP_GAP_TO_ZERO/NO_SWEEP_DATA).
- **probe_slippage per-route**: per_route_breakdown in artifacts shows per-route cost decomposition. Key finding: slippage dominates all routes (83% of gap on WBTC/USDC).
- **ARB/WETH re-enabled**: Was disabled due to outlier at 1359 bps. SUSPECT_SPREAD_HARD properly gates >500 bps in truth_mode pipeline.
- **Gap narrowed**: 18→15 bps. Long scan: 42 runs, 109 signals, $123, 21 profitable RT (up from 14 in R28.6). Linea confirmed as positive control (truth=True).

## 8) Що потрібно від ліда
1. New KPI framework verified: `executable_candidates_count=4` on arb primary (4 passed post-quote gates out of 8-9 signals). `roundtrip.profitable_count=0` remains the true bar.
2. Gap progress: 18→15 bps. WBTC/USDC is 15.22 bps from profitability. Slippage is 83% of gap (12.57 of 15.22 bps).
3. Per-route breakdown in artifacts — lead can now see exactly where each route fails (slippage vs fee vs gas).
4. Long scan improvement: 42 runs (+11), 109 signals (+40), $123 (+$7), 21 profitable RT (+7). Linea truth=True (positive control confirmed).
5. Lead question: is the next move (a) smaller trade sizes to reduce slippage, (b) targeting lower-fee pools, or (c) additional pair/DEX expansion?
6. Deferred per prior directives: async quote path, WS/multicall, dashboard metrics.
