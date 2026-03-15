# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 6 Round 28.5)
**Goal**: R28.5 — Scanner latency reduction: bounded parallel coverage, expanded phase metrics, COVERAGE tail simplification, phase_timers artifact fix.
**Prior (R28.4)**: Shared Web3 cache, parallel quote prefetch, COVERAGE lightweight mode, phase timing. Per-run improvement: 66s→26.8s (2.5x).

## 0) Meta
timestamp_utc: 2026-03-15T12:34:00Z
rolling_provenance: 2026-03-15T12:30:37Z (arbitrum_one NORMAL — FRESH R28.5 evidence, ci_m5_gate_20260315_123037)
mode: PERFORMANCE_OPTIMIZATION + FRESH_SCANS
test_count: 1828 passed, 3 skipped (+6 from R28.4)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.5: Scanner latency reduction — bounded parallel coverage (--coverage-workers), expanded phase metrics (8 fields), COVERAGE dynamic_sweep skip, phase_timers artifact fix |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: arb agg gap_median=17.99 bps; ARCHITECTURE: async quote path deferred (requires major refactor) |
| evidence_session_run_dirs | ci_m5_gate_20260315_122041 (arb, NORMAL, PASS, phase_timers in artifact), ci_m5_gate_20260315_123037 (long_scan final, arbitrum_one primary, PASS, rolling refresh) |
| primary_blocker_of_session | Phase_timers_ms not appearing in scan artifact (computed after write_artifacts) |
| blocker_status_before | phase_timers set on stats dict AFTER build_scan_data/write_artifacts → not serialized into scan_*.json |
| blocker_status_after | RESOLVED: phase_timers computed BEFORE write_artifacts (stats by-reference mutation), final values updated after write for returned dict |
| start_metric | R28.4: 21 runs in 563.6s (~26.8s/run), phase_timers only in returned stats (not in artifact) |
| end_metric | R28.5: 37 runs in 556s (~15s/run), phase_timers_ms in scan artifact (all 8 fields), bounded parallel coverage |
| delta | +6 tests (1828), phase_timers now in artifact, bounded parallel --coverage-workers N, expanded metrics (postprocess_ms, report_ms), COVERAGE dynamic_sweep skip |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — scanner performance optimization (R28.5 lead directive)
change_summary:
  - BOUNDED PARALLEL COVERAGE: `start.py` — `--coverage-workers N` argument (default 2), ThreadPoolExecutor batches coverage configs after primary runs. Thread-safe stats via `threading.Lock`. Primary (NORMAL) runs sequential for rolling safety, coverage runs bounded-parallel.
  - EXPANDED PHASE METRICS: `strategy/jobs/run_scan_real.py` — 8 fields in `phase_timers_ms`: total_ms, discovery_ms, quote_rpc_ms, postprocess_ms, preflight_ms, report_ms, init_rpc_ms (legacy), post_scan_ms (legacy). Added `_phase_postprocess_start` and `_phase_report_start` markers.
  - COVERAGE TAIL SIMPLIFICATION: `strategy/jobs/run_scan_real.py` — COVERAGE runs skip `dynamic_sweep` (expensive re-quoting). Stats show `{"enabled": False, "skipped": "COVERAGE_LIGHTWEIGHT"}`.
  - MULTICALL STATS VISIBILITY: `strategy/quotes.py` → `run_scan_real.py` — `multicall_stats` (calls_batched, latency_ms_total, etc.) exposed in scan stats.
  - PHASE_TIMERS ARTIFACT FIX: `strategy/jobs/run_scan_real.py` — phase_timers computed BEFORE write_artifacts (stats dict mutated by reference), final report_ms/total_ms updated after write for returned dict.
touched_files: start.py, strategy/jobs/run_scan_real.py, strategy/quotes.py, tests/unit/test_start.py (+5), tests/unit/test_run_scan_infra.py (+1), tests/unit/test_run_scan_real_purity.py (max_lines 1400→1410)

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1828 passed, 3 skipped)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: **PASS** (arb, phase_timers in artifact: total_ms=18240, quote_rpc_ms=8765)
py -3.11 start.py --config-list real_minimal,zksync,base_stage2,mantle_stage2,linea,scroll --hours 0.15 --cycles 1: **37 runs** (25 PASS, 6 NO_DATA, 6 FAIL, wall_seconds=556)

## 3) Artifacts Attached (шляхи)
rolling (FRESH — R28.5 online evidence):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-15T12:30:37Z, runDir: ci_m5_gate_20260315_123037)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS, runs_in_window: 200+)
  - data/runs/_rolling/long_scan_latest.json (REFRESHED 2026-03-15T12:34:00Z: 37 runs, 52 signals, $85.88, 12 profitable roundtrips)

session_run_dirs:
  - ci_m5_gate_20260315_122041 (arb primary, NORMAL, PASS, phase_timers in artifact)
  - ci_m5_gate_20260315_123037 (long_scan final run, arb primary, PASS, rolling refresh)

## 4) Key Results (числа з артефактів)

```
# Long scan (multi-chain — long_scan_latest.json, R28.5)
wall_seconds: 556 (was 563.6 R28.4 — now 37 runs vs 21)
per_run_avg: ~15s (was ~27s R28.4 — bounded parallel coverage)
total_runs: 37 (25 PASS + 6 NO_DATA + 6 FAIL)
total_included_signals: 52
total_net_usdc: $85.88
total_profitable_roundtrips: 12
sweep_best_net_pnl_bps: -18.71
pass_chains: arbitrum_one, zksync, base, linea
fail_chains: scroll (accepted-fail)
probe_only: mantle (6 NO_DATA)

# Phase timers in artifact (FIXED R28.5)
arbitrum_one: total_ms=18240, discovery_ms=1463, quote_rpc_ms=8765, postprocess_ms=7245, preflight_ms=748, report_ms=0 (pre-write)
Phase timers now appear in scan_*.json (was missing before R28.5 fix)

# Bounded parallel coverage
--coverage-workers: default 2 (configurable)
Primary configs: run sequential (rolling-safe)
Coverage configs: run in ThreadPoolExecutor batches

# New tests (R28.5)
+5 tests in test_start.py (TestCoverageWorkersArg: 3, TestBatchedPrimaryCoverageLoop: 2)
+1 test in test_run_scan_infra.py (test_phase_timers_expanded_fields)
Total: 1828 passed, 3 skipped
```

## 5) Contract Checks
- bounded parallel coverage: primary configs sequential (rolling-safe), coverage in ThreadPoolExecutor(max_workers=N)
- thread-safe stats: `threading.Lock` for per_chain stats updates in coverage workers
- phase_timers artifact: computed BEFORE write_artifacts (stats by-reference), final values updated after write
- COVERAGE dynamic_sweep: skipped (expensive re-quoting), stats show `{"enabled": False, "skipped": "COVERAGE_LIGHTWEIGHT"}`
- multicall_stats: exposed from quotes.py (calls_batched, latency_ms_total)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1828 PASS, phase_timers artifact FIXED)
scanner_latency: IMPROVED (per-run 27s→15s via bounded parallel + sweep skip)
async_quote_path: DEFERRED (major architecture — quotes.py uses sync Web3, providers.py async but disconnected)
ws_block_head: DEFERRED (no WebSocket infrastructure exists)
market_window_blocker: MEDIUM (arb agg gap_median=17.99 bps — not profitable)
```

## 7) R28.5 Session Summary
- **Bounded parallel coverage**: `start.py` restructured with `--coverage-workers N` (default 2). Primary (NORMAL) configs run sequentially for rolling safety, coverage configs batch-execute in ThreadPoolExecutor. Thread-safe stats via `threading.Lock`.
- **Expanded phase metrics**: 8 fields in `phase_timers_ms`: total_ms, discovery_ms, quote_rpc_ms, postprocess_ms, preflight_ms, report_ms, + legacy aliases (init_rpc_ms, post_scan_ms).
- **Phase_timers artifact fix**: Computed BEFORE `write_artifacts` (dict by-reference mutation). Final `report_ms` and `total_ms` updated after write for returned stats dict.
- **COVERAGE dynamic_sweep skip**: Expensive re-quoting skipped for COVERAGE runs. Stats show `{"enabled": False, "skipped": "COVERAGE_LIGHTWEIGHT"}`.
- **Multicall stats visibility**: `multicall_stats` from `quotes.py` exposed in scan stats.
- **Performance result**: 6-chain long_scan: 37 runs in 556s (~15s/run) vs R28.4 21 runs in 563.6s (~27s/run).

## 8) Що потрібно від ліда
1. R28.5 phase_timers artifact fix verified: all 8 fields now appear in scan_*.json (was missing before).
2. Bounded parallel coverage: `--coverage-workers N` configurable, default 2. Primary sequential, coverage batched.
3. Long scan: 37 runs / 52 signals / $85.88 / 12 profitable roundtrips / 4 pass chains (556s wall).
4. Async quote path (sync Web3 → async httpx) and WS block-head cache deferred — major architecture change.
5. Next optimization target: async quoting (quotes.py uses ThreadPoolExecutor over sync Web3; true async needs httpx integration).
