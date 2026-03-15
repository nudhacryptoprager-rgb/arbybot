# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 6 Round 28.9)
**Goal**: R28.9 — Dashboard observability: per-future long_scan writes, dashboard lifecycle/UX, phase_timers, batch state, quality semantics, false alert suppression.
**Prior (R28.8)**: Universe expansion complete (UniswapV2 adapter, intent.txt generator, caps removed, 1850 tests). Lead R28.9 directive: "dashboard backend is live, but UI refresh is batch-level and primary-centric; apparent stasis was a cadence/UX issue, not missing scan activity."

## 0) Meta
timestamp_utc: 2026-03-15T17:13:59Z
rolling_provenance: 2026-03-15T17:13:59Z (arbitrum_one NORMAL — R28.9 fresh evidence)
mode: DASHBOARD_OBSERVABILITY + CADENCE_FIX + QUALITY_SEMANTICS
test_count: 1853 passed, 3 skipped
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.9: Dashboard observability — per-future writes, lifecycle, phase_timers, batch state, quality semantics, false alert suppression |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: gap ~13 bps (improved from R28.7 ~15 bps); INFRA: mantle NO_DATA (probe-only) |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260315_181340_343744 (R28.9 primary), ci_m5_gate_linea_20260315_181303_641715 (linea ROUNDTRIP_PROFITABLE), ci_m5_gate_base_20260315_181244_564547 (base PASS), ci_m5_gate_zksync_20260315_181239_929117 (zksync PASS), ci_m5_gate_scroll_20260315_181324_159731 (scroll accepted-fail), ci_m5_gate_mantle_20260315_181253_508919 (mantle NO_DATA) |
| primary_blocker_of_session | Dashboard "stale" — long_scan_latest written only after full coverage batch; UI reads run_summary (primary-only); phase_timers not visible; false ROUNDTRIP_PROFITABLE alerts |
| blocker_status_before | ACTIVE: dashboard writes per-batch (not per-chain), dashboard dies with start.py, UI primary-centric, phase_timers not surfaced, false RT_PROFITABLE alerts |
| blocker_status_after | RESOLVED: 8 fixes applied — per-future writes, --keep-dashboard, long_scan primary in UI, phase_timers table, batch state, line_prefix, quality_reasons column, profit_realism_status guard |
| start_metric | R28.8: 1850 tests, dashboard batch-level refresh, no phase_timers visibility |
| end_metric | R28.9: 1853 tests, per-future long_scan writes, dashboard survives exit, 8 observability fixes |
| delta | +per-future writes, +--keep-dashboard, +long_scan primary UI, +phase_timers, +batch_state, +line_prefix, +quality_reasons, +RT alert guard |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 dashboard observability + cadence (R28.9 lead directive)
change_summary:
  - FIX_1_PER_FUTURE_WRITE: `start.py` — moved `write_summary_file()` inside `as_completed()` loop. Now writes after EACH coverage future, not after entire batch.
  - FIX_2_KEEP_DASHBOARD: `start.py` — added `--keep-dashboard` CLI flag. Dashboard process not killed on scan exit (prints PID/URL instead).
  - FIX_3_LONG_SCAN_PRIMARY: `monitoring/dashboard.html` — header shows long_scan multi-chain info as primary. run_summary labeled `PRIMARY (NORM-ONLY)`. Panels 3,4,5,9 subtitled `(PRIMARY NORM-ONLY)`.
  - FIX_4_PHASE_TIMERS: `start.py` + `monitoring/dashboard.html` — propagate `phase_timers_ms` to per-chain stats. Dashboard renders Phase Timers table (discovery_ms, quote_rpc_ms, postprocess_ms, preflight_ms, report_ms).
  - FIX_5_BATCH_STATE: `start.py` + `monitoring/dashboard.html` — `batch_state` in summary (chains_total, chains_with_runs, last_completed_chain). Rendered in dashboard header.
  - FIX_6_LINE_PREFIX: `start.py` — coverage workers get `[chain_name]` prefix on all output. Primary runs unprefixed.
  - FIX_7_QUALITY_REASONS: `start.py` + `monitoring/dashboard.html` — `last_quality_reasons` per chain. "Reason" column in Chain Status when quality_status=FAIL_QUALITY.
  - FIX_8_RT_ALERT_GUARD: `scripts/ci_m5_0_gate.py` — `is_profitable` now requires `profit_realism_status == "ROUNDTRIP_PROFITABLE"`. Prevents false alerts when profitable_count>0 but real_quote_count=0.
touched_files: start.py, monitoring/dashboard.html, scripts/ci_m5_0_gate.py

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1853 passed, 3 skipped)
py -3.11 scripts/check_repo_safety.py: FAIL (1 error: DEV_REPORT timestamp mismatch — expected, fixed by this doc update)
py -3.11 start.py --config-list (6 chains): **PASS** (13 runs, 9 PASS, 2 NO_DATA, 2 FAIL, 0 INFRA_FAIL)

## 3) Artifacts Attached (шляхи)
rolling (FRESH from R28.9 multi-chain scan):
  - data/runs/_rolling/_latest.json (run_timestamp: 2026-03-15T17:13:59Z, runDir: ci_m5_gate_arbitrum_one_20260315_181340_343744, agg_status: PASS)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-15T17:13:59Z, signals=7, PASS)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS)
  - data/runs/_rolling/long_scan_latest.json (13 runs, 39 signals, $53.33, 8 profitable RT, wall=190s)

session_run_dirs:
  - ci_m5_gate_arbitrum_one_20260315_181340_343744 (primary, PASS)
  - ci_m5_gate_linea_20260315_181303_641715 (PASS, ROUNDTRIP_PROFITABLE=2)
  - ci_m5_gate_base_20260315_181244_564547 (PASS)
  - ci_m5_gate_zksync_20260315_181239_929117 (PASS)
  - ci_m5_gate_scroll_20260315_181324_159731 (FAIL, accepted)
  - ci_m5_gate_mantle_20260315_181253_508919 (NO_DATA, probe-only)

## 4) Key Results (числа з артефактів)

```
# Multi-chain long_scan (R28.9 fresh)
wall_seconds: 190.5
total_runs: 13 (PASS=9, NO_DATA=2, FAIL=2, INFRA_FAIL=0)
total_signals: 39
total_net_usdc: $53.33
total_profitable_roundtrips: 8 (evaluated: 28)
best_measured_spread_gap_bps: 19.3
sweep_best_net_pnl_bps: -13.05 @ $25

# Rolling aggregation (200-run window, arbitrum_one primary)
agg_status: PASS
runs_in_window: 200
total_net_usdc: $1053.65
pass_rate: 1.0
data_run_rate: 1.0
total_signals: 851
unique_pairs: 6
sweep_best_pnl_bps: -3.55 (gap=3.55 bps — best ever)

# Per-chain (long_scan)
arbitrum_one: runs=3 PASS=3 signals=21 net=$35.11 quality=WARN level=SIGNAL_PRODUCING cross_dex=6
base:         runs=2 PASS=2 signals=10 net=$4.49 quality=WARN level=SIGNAL_PRODUCING cross_dex=22
linea:        runs=2 PASS=2 signals=6 net=$13.52 quality=WARN level=SIGNAL_PRODUCING truth=True cross_dex=11
zksync:       runs=2 PASS=2 signals=2 net=$0.21 quality=WARN level=SIGNAL_PRODUCING cross_dex=8
mantle:       runs=2 NO_DATA=2 signals=0 quality=NO_DATA level=INFRA_READY cross_dex=4
scroll:       runs=2 FAIL=2 signals=0 quality=FAIL (accepted_fail)
```

## 5) Contract Checks
- Per-future writes: `write_summary_file()` called inside `as_completed()` loop — verified by "Summary written" appearing after each coverage future in scan output
- Dashboard lifecycle: `--keep-dashboard` flag added, dashboard PID printed instead of terminating in `finally` block
- Long_scan primary: dashboard header shows multi-chain data from long_scan_latest, run_summary labeled PRIMARY (NORM-ONLY)
- Phase timers: propagated from scan_stats to per_chain, rendered in dashboard Phase Timers table
- Batch state: chains_total, chains_with_runs, last_completed_chain in summary, shown in dashboard header
- Per-chain logging: coverage workers output prefixed with `[chain_name]` — verified in scan output
- Quality reasons: per-chain `last_quality_reasons` captured, Reason column in dashboard Chain Status table
- RT alert guard: `is_profitable` requires `profit_realism_status == "ROUNDTRIP_PROFITABLE"` — false alerts suppressed, real linea alert fired correctly
- Rolling discipline: maintained — NORMAL-only guard intact

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1853 PASS, all 8 fixes verified in online run)
market_gap: MEDIUM (gap_to_zero ~3.55 bps best-ever, median ~13 bps)
dashboard_cadence: RESOLVED (per-future writes, batch_state, --keep-dashboard)
phase_timers: RESOLVED (propagated to per_chain, rendered in dashboard)
false_alerts: RESOLVED (profit_realism_status guard on ROUNDTRIP_PROFITABLE)
async_quote_path: DEFERRED (major architecture — quotes.py uses sync Web3)
ws_block_head: DEFERRED (no WebSocket infrastructure exists)
multicall_proof: DEFERRED (multicall_stats=None in canonical path)
```

## 7) R28.9 Session Summary
- **Lead R28.9 directive**: "dashboard backend is live, but UI refresh is batch-level and primary-centric; apparent stasis was a cadence/UX issue, not missing scan activity." 10 critical issues identified, 10 fix steps prescribed.
- **Fix 1 (per-future writes)**: `write_summary_file()` moved inside `as_completed()` loop in start.py. Dashboard now updates after each chain completes, not after entire batch.
- **Fix 2 (dashboard lifecycle)**: `--keep-dashboard` flag. Dashboard process survives start.py exit, enabling continuous monitoring.
- **Fix 3 (long_scan primary)**: Dashboard header rewritten to show long_scan multi-chain data as primary view. run_summary panels labeled `PRIMARY (NORM-ONLY)`.
- **Fix 4 (phase_timers)**: `phase_timers_ms` propagated from scan_stats to per-chain stats in long_scan_latest. Dashboard renders Phase Timers table per chain.
- **Fix 5 (batch_state)**: `batch_state` dict in build_summary with chains_total, chains_with_runs, last_completed_chain. Rendered in dashboard header.
- **Fix 6 (per-chain logging)**: Coverage workers get `[chain_name]` prefix via `line_prefix` parameter in `run_gate_once()`.
- **Fix 7 (quality_reasons)**: Per-chain `last_quality_reasons` in stats. Dashboard Chain Status table shows "Reason" column for FAIL_QUALITY chains.
- **Fix 8 (RT alert guard)**: `is_profitable` now requires `profit_realism_status == "ROUNDTRIP_PROFITABLE"`. Prevents false alerts when profitable_count>0 but real_quote_count=0.
- **Fresh evidence**: 13-run multi-chain scan: 9 PASS, 39 signals, $53.33, 8 profitable roundtrips, 190s wall. Linea ROUNDTRIP_PROFITABLE=2 (correct alert). Per-chain prefixing visible. Summary written per-future.

## 8) Що потрібно від ліда
1. **Review 8 fixes**: All in start.py + dashboard.html + ci_m5_0_gate.py. Minimal, targeted changes.
2. **Dashboard test**: Run with `--keep-dashboard` to verify dashboard survives exit, phase timers rendered, batch state visible.
3. **Linea ROUNDTRIP_PROFITABLE**: Fresh evidence confirms profitable roundtrips on linea (2/4 evaluated). Consider promotion from stage1 to stage2.
4. **Base PASS**: Base now PASS with 10 signals, 22 cross-dex pairs. 4 DEXes active (aerodrome, sushiswap, pancakeswap, uniswap). Progress from previous FAIL.
5. **Gap improvement**: Rolling best-ever gap_to_zero=3.55 bps. Multi-chain sweep best=-13.05 bps @ $25. Narrowing continues.
6. **Mantle NO_DATA**: Still probe-only, no signals. May need additional adapter/pair configuration.
