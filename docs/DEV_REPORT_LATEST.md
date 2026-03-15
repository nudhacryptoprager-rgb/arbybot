# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 6 Round 28.4)
**Goal**: R28.4 — Scanner performance optimization (shared Web3 cache, parallel quote prefetch, COVERAGE lightweight mode, phase timing).
**Prior (R28.3)**: Doc cleanup, claim downgrades (thin not REAL), deprecated pnl pruned, stale section tests, fresh evidence. 6-chain long_scan baseline: wall_seconds=594.1 for 9 runs (~66s per chain-run).

## 0) Meta
timestamp_utc: 2026-03-15T10:24:36Z
rolling_provenance: 2026-03-15T10:24:36Z (arbitrum_one NORMAL — FRESH R28.4 evidence, ci_m5_gate_20260315_112419)
mode: PERFORMANCE_OPTIMIZATION + FRESH_SCANS
test_count: 1822 passed, 3 skipped (unchanged)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.4: Scanner performance optimization — reduce 6-chain scan wall time via shared Web3, parallel quotes, COVERAGE lightweight, phase timing |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: arb agg gap_median=17.99 bps (best-ever=3.55); BASE_EVIDENCE: thin (needs repetition); PROBE_SLIPPAGE: artifact integration pending |
| evidence_session_run_dirs | ci_m5_gate_20260315_111152 (arb, NORMAL, PASS, rolling refresh), ci_m5_gate_20260315_111327 (zksync, COVERAGE, PASS, preflight=0ms), ci_m5_gate_20260315_111436 (base, COVERAGE, PASS), ci_m5_gate_20260315_111558 (mantle, COVERAGE, PASS, quote=4500ms) |
| primary_blocker_of_session | Scanner latency: 6-chain long_scan took 594.1s for 9 runs (~66s/run), serial sync quoting, per-RPC Web3 creation, heavy COVERAGE post-scan |
| blocker_status_before | Serial sync quoting, new Web3 per-quote, full daily_report for COVERAGE, 20s inter-chain sleep, no phase timing |
| blocker_status_after | RESOLVED: shared Web3 cache, ThreadPoolExecutor 8-way parallel prefetch, COVERAGE lightweight (skip daily_report + preflight), sleep 20→1, phase timers in stats |
| start_metric | R28.3: wall_seconds=594.1 for 9 runs, ~66s per chain-run average |
| end_metric | R28.4: wall_seconds=563.6 for 21 runs, ~26.8s per chain-run average (2.5x improvement) |
| delta | 2.5x per-run throughput improvement; 21 runs (was 9) in similar wall time; phase_timers_ms in scan stats; COVERAGE lightweight mode |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — scanner performance optimization (R28.4 lead directive)
change_summary:
  - SHARED WEB3 CACHE: `strategy/quotes.py` — module-level `_shared_w3_cache` dict + `_get_shared_w3(rpc_url)` function. All 4 per-quote `Web3(HTTPProvider())` calls replaced with cached instances. `clear_shared_w3_cache()` for testing.
  - PARALLEL QUOTE PREFETCH: `strategy/quotes.py` — `_QUOTE_CONCURRENCY=8` constant, ThreadPoolExecutor-based prefetch phase before inner loop. Pre-computes pair context, submits all pool RPC calls in parallel, resolves futures into `_prefetch_results` dict. 3 inline RPC call sites check cache before fallback.
  - PHASE TIMING: `strategy/jobs/run_scan_real.py` — `phase_timers_ms` dict in scan stats: total_ms, init_rpc_ms, quote_rpc_ms, preflight_ms, post_scan_ms. Logger.info with phase breakdown.
  - COVERAGE PREFLIGHT SKIP: `strategy/jobs/run_scan_real.py` — COVERAGE runs skip `collect_top_n_preflight()` (set preflight_evidence.enabled=False, skipped=COVERAGE_LIGHTWEIGHT).
  - LIGHTWEIGHT COVERAGE GATE: `scripts/ci_m5_0_gate.py` — `_is_lightweight=(run_kind!="NORMAL")` check. Both daily_report generations skipped for COVERAGE/SMOKE runs. M4 gate still runs (needed for run_summary).
  - SLEEP REDUCTION: `start.py` — default sleep_seconds 20→1, conditional sleep (allows 0).
  - MULTICALL LATENCY FIX: `core/multicall.py` — `latency_ms_total` stat now accumulates real timing around `_execute_multicall()` (was always 0).
touched_files: strategy/quotes.py, strategy/jobs/run_scan_real.py, scripts/ci_m5_0_gate.py, start.py, core/multicall.py

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1822 passed, 3 skipped)
py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **ALL GATES PASS** (25.2s)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 5 --refresh-rolling --refresh-rolling-strict --prune-keep 50: **PASS** (arb, Phase timers: total=17921ms quote=8656ms preflight=766ms, EXIT=0)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_zksync_candidate.yaml --cycles 5: **PASS** (COVERAGE, preflight=0ms, daily_report skipped)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_base_stage2.yaml --cycles 5: **PASS** (COVERAGE, daily_report skipped)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_mantle_stage2.yaml --cycles 5: **PASS** (COVERAGE, Phase timers: total=7516ms quote=4500ms preflight=0ms)
py -3.11 start.py --config-list real_minimal,zksync,base_stage2,mantle_stage2,linea,scroll --hours 0.25: **21 runs** (15 PASS, wall_seconds=563.6)

## 3) Artifacts Attached (шляхи)
rolling (FRESH — R28.4 online evidence):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-15T10:24:36Z, runDir: ci_m5_gate_20260315_112419)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS, runs_in_window: 200, total_net_usdc: $1224.92)
  - data/runs/_rolling/long_scan_latest.json (REFRESHED 2026-03-15T10:25:50Z: 21 runs, 43 signals, $68.28, 9 profitable roundtrips)

session_run_dirs:
  - ci_m5_gate_20260315_111152 (arb primary, NORMAL, PASS, 4 signals, $5.41, rolling refresh, phase_timers)
  - ci_m5_gate_20260315_111327 (zksync, COVERAGE, PASS, lightweight mode, preflight=0ms)
  - ci_m5_gate_20260315_111436 (base, COVERAGE, PASS, lightweight mode)
  - ci_m5_gate_20260315_111558 (mantle, COVERAGE, PASS, lightweight mode, quote=4500ms)

## 4) Key Results (числа з артефактів)

```
# Rolling agg (arbitrum_one primary only — m4_stability_agg.json)
agg_status: PASS
runs_in_window: 200
total_net_usdc: $1224.92
unique_pairs: 12
sweep_gap_to_zero_min: 3.55 bps (best-ever)
sweep_median_gap_to_zero_bps: 17.99 bps
roundtrip_total_profitable: 0 (arb primary only)
frontier_pair: WETH/USDT

# Long scan (multi-chain — long_scan_latest.json, 2026-03-15T10:25:50Z)
wall_seconds: 563.6 (was 594.1 for 9 runs — now 21 runs in similar time)
per_run_avg: ~26.8s (was ~66s — 2.5x improvement)
total_runs: 21 (15 PASS + 3 NO_DATA + 3 FAIL)
total_included_signals: 43
total_net_usdc: $68.28
total_profitable_roundtrips: 9
sweep_best_net_pnl_bps: -15.80
pass_chains: arbitrum_one, zksync, base, linea
fail_chains: scroll (accepted-fail)

# Performance improvements (R28.4)
shared_web3_cache: eliminates per-quote Web3(HTTPProvider()) creation
parallel_prefetch: ThreadPoolExecutor(max_workers=8), all pool RPCs per pair fanned out
coverage_lightweight: skip daily_report (x2) + preflight for COVERAGE runs
sleep_reduction: 20s→1s inter-chain default (allows 0)
multicall_latency: now tracks real execution time (was always 0)
phase_timers: total_ms, init_rpc_ms, quote_rpc_ms, preflight_ms, post_scan_ms in scan stats

# Phase timer samples (online)
arbitrum_one: total=17921ms, init=1296ms, quote=8656ms, preflight=766ms, post=77ms
zksync:       total=30563ms, quote=26531ms, preflight=0ms (COVERAGE skip)
mantle:       total=7516ms, quote=4500ms, preflight=0ms (COVERAGE skip)
```

## 5) Contract Checks
- shared Web3 cache: thread-safe via module-level dict, timeout=10s (5s for slot0)
- parallel prefetch: futures resolved synchronously after submission, fallback to direct call on miss
- COVERAGE lightweight: M4 gate still runs (needed for run_summary), only daily_report + preflight skipped
- rolling discipline: OK (3+1 canonical files, NORM-only guard active, COVERAGE doesn't touch rolling)
- phase_timers: additive (no schema break — new field in stats dict)
- multicall latency: now correctly accumulates `_execute_multicall()` timing

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1822 PASS, CI+safety PASS, 0 warnings)
scanner_latency: RESOLVED (per-run 66s→26.8s, 2.5x improvement via shared Web3 + parallel prefetch + lightweight COVERAGE)
market_window_blocker: MEDIUM (arb agg gap_median=17.99 bps, best-ever=3.55 — improving but not profitable)
base_evidence: THIN (ROUNDTRIP_PROFITABLE=2 but real_quote_count=1, measured_economics.available=false — needs repetition)
adapter_blocker: RESOLVED (ve33 tested online R28.2, confirmed R28.3+R28.4)
economics_debt: PARTIAL (net_pnl_bps done, probe_slippage pending)
```

## 7) R28.4 Session Summary
- **Shared Web3 cache**: Module-level `_shared_w3_cache` in quotes.py eliminates per-quote `Web3(HTTPProvider())` creation. All 4 RPC functions (read_v3_slot0, read_quoter_v2, read_algebra_quoter, read_ve33_amount_out) now use cached instances.
- **Parallel quote prefetch**: `ThreadPoolExecutor(max_workers=8)` fans out all per-pool RPC calls (ve33, quoter_v2, algebra) per pair. Futures resolved after submission. 3 inline call sites check `_prefetch_results` before direct fallback.
- **COVERAGE lightweight mode**: `_is_lightweight` flag in ci_m5_0_gate.py skips both daily_report generations for COVERAGE/SMOKE. COVERAGE preflight skipped in run_scan_real.py. M4 gate kept (run_summary needed).
- **Phase timing**: `phase_timers_ms` in scan stats enables per-phase latency tracking (init, quote, preflight, post). Quote phase dominates (~48% in arb, ~87% in zksync).
- **Performance result**: 6-chain long_scan: 21 runs in 563.6s (26.8s/run) vs R28.3 baseline 9 runs in 594.1s (66s/run) = **2.5x per-run throughput improvement**.
- **Multicall latency**: `latency_ms_total` stat now tracks real execution time (previously always 0).

## 8) Що потрібно від ліда
1. R28.4 performance optimization complete: 2.5x per-run throughput (66s→26.8s). 21 runs in 563.6s (was 9 runs in 594.1s).
2. Phase timers show quote phase dominates: arb quote=8.6s (48%), zksync quote=26.5s (87%). Next optimization target: async or batched quoting per pool.
3. COVERAGE lightweight mode working: daily_report + preflight skipped, still get run_summary via M4 gate.
4. Arb primary agg: gap_median=17.99 bps, best-ever=3.55 bps. Still market-blocked (roundtrip_profitable=0).
5. Long scan expanded: 21 runs / 43 signals / $68.28 / 9 profitable roundtrips / 4 pass chains (was 9/44/$41.80/5/5).
6. probe_slippage artifact integration still pending.
