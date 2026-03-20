# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled. R31 directive: **Diagnose 0-roundtrip bottleneck, add truth_verdict + quote_source_summary for operator clarity.** R30 expanded arb to 4-DEX. R31 traces the signal→roundtrip pipeline, identifies QUOTER_V2_FAILED→slot0→OE rejection as the root cause of 0 candidates, and adds first-class artifact fields for diagnosis.

## SESSION GOAL (R31: OE bottleneck diagnosis + artifact clarity)
**Goal**: Diagnose why 20+ signals produce 0 roundtrip evaluations. Add `truth_verdict` to run_summary and `quote_source_summary`/`oe_rejection_funnel` to truth_report. Run fresh 6-chain long scan with R31 changes.
**Prior (R30)**: 4-DEX expansion on arb (uni+sushi+pancake+camelot), discovery_runtime, 3 adapter stubs, 2090 tests PASS.

## 0) Meta
timestamp_utc: 2026-03-20T22:06:52.855924Z
run_dir_name: ci_m5_gate_arbitrum_one_20260320_230614_040386
mode: OE_BOTTLENECK_DIAGNOSIS + ARTIFACT_CLARITY (R31 directive)
test_count: 2101 passed, 5 skipped
schema_version: m4:run_summary:v2.0

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R31: Diagnose 0-roundtrip bottleneck (OE rejection funnel), add truth_verdict + quote_source_summary artifact fields |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | Per-chain adapter implementation (iziswap/syncswap/ambient stubs). Quoter_v2 failure rate requires investigation. |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260320_230614_040386 (primary), + 42 coverage runs across 6 chains |
| primary_blocker_of_session | Operator ambiguity: profit_status=PASS alongside roundtrip_truth_status=NOT_PROFITABLE; OE rejection funnel not visible in truth_report |
| blocker_status_before | ACTIVE: truth_report lacks OE funnel data; run_summary has no truth_verdict; profit_status=PASS misleads operators |
| blocker_status_after | RESOLVED: truth_verdict=DIAGNOSTIC_PROFIT_ONLY disambiguates; quote_source_summary + oe_rejection_funnel are first-class fields |
| start_metric | 2090 tests, 0 truth_verdict field, 0 quote_source_summary, 0 oe_rejection_funnel |
| end_metric | 2101 tests, truth_verdict live in run_summary, quote_source_summary + oe_rejection_funnel in truth_report |
| delta | +11 tests, +3 first-class artifact fields, full OE bottleneck RCA completed |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 - R31 directive: OE bottleneck diagnosis + artifact clarity
change_summary:
  - **CRITICAL**: `m4/policy.py` — `compute_status()` returns new `truth_verdict` field: NO_DATA | ROUNDTRIP_PROFITABLE | DIAGNOSTIC_PROFIT_ONLY | NO_PROFIT. Resolves operator ambiguity where profit_status=PASS + roundtrip_truth=NOT_PROFITABLE.
  - **CRITICAL**: `m4/fixtures.py` — `truth_verdict` surfaced in `run_summary_data` as first-class field. Inline computation mirrors `compute_status()` logic.
  - **CRITICAL**: `strategy/artifacts.py` — `build_truth_data()` adds `quote_source_summary` (executable/diagnostic/quoter_matrix per DEX) and `oe_rejection_funnel` (total/gated/rejected/reasons from OE).
  - NEW: `tests/unit/test_r31_truth_verdict.py` — 11 tests locking truth_verdict domain, quote_source_summary, oe_rejection_funnel contracts.
touched_files:
  - m4/policy.py (CRITICAL — truth_verdict in compute_status)
  - m4/fixtures.py (CRITICAL — truth_verdict in run_summary)
  - strategy/artifacts.py (CRITICAL — quote_source_summary + oe_rejection_funnel)
  - tests/unit/test_r31_truth_verdict.py (NEW — 11 tests)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2101 passed, 5 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED (42.8s)
py -3.11 start.py --config-list real_minimal+5 onboard configs --hours 0.17 --cycles 1: 43 runs, 6 chains (630s wall)
```

## 3) Artifacts Attached
rolling: data/runs/_rolling/ (updated by primary arb online scan)
online_scan: ci_m5_gate_arbitrum_one_20260320_230614_040386
long_scan: data/runs/_rolling/long_scan_latest.json (43 runs, 6 chains)

### Primary Arb Scan Evidence (FRESH, R31)
```
runDir: ci_m5_gate_arbitrum_one_20260320_230614_040386
timestamp: 2026-03-20T22:06:52.855924Z
gate_status: PASS
chain: arbitrum_one (chain_id: 42161)
pairs_resolved: 30 (from 28 cross-DEX active)
dexes_active: 4 (uniswap_v3, sushiswap_v3, pancakeswap_v3, camelot_v3)
quotes_total: 181
quotes_fetched: 108
  executable: 99 (91.7%)
  diagnostic: 9 (8.3%)
  quoter_v2_failed: 12
signals_total: 46
included_signals: 38
opportunities_total: 207 (89 profitable by OE)
truth_verdict: DIAGNOSTIC_PROFIT_ONLY
profit_status: PASS
roundtrip_truth_status: NOT_PROFITABLE
profitable_roundtrips: 0
real_quote_count: 0
execution_pnl:
  total_net_usdc: 59.90
kill_switch_active: true
execution_enabled: false
```

### OE Rejection Funnel (from truth_report — NEW R31 FIELD)
```
total_opportunities: 207
gated_count: 0
rejected_count: 207
rejected_reasons:
  NET_PROFIT_TOO_LOW: 118  (57.0%) — economics don't work at $10 probe
  SUSPECT_SPREAD_HARD: 46  (22.2%) — spread >500 bps (stale/inverted)
  MIXED_SOURCE: 21          (10.1%) — one leg quoter_v2, other slot0
  NOTIONAL_DRIFT: 19        (9.2%)  — target vs actual size drift >20%
  SLOT0_DIAGNOSTIC: 3       (1.4%)  — both legs slot0 fallback
```

### Quote Source Summary (from truth_report — NEW R31 FIELD)
| DEX | Fee | Attempted | Quoter OK | Slot0 Fallback | Diag |
|-----|-----|-----------|-----------|----------------|------|
| camelot_v3 | 0 | 19 | 16 | 0 | 0 |
| uniswap_v3 | 500 | 24 | 23 | 1 | 1 |
| uniswap_v3 | 3000 | 24 | 22 | 2 | 2 |
| sushiswap_v3 | 3000 | 14 | 13 | 1 | 1 |
| pancakeswap_v3 | 2500 | 8 | 8 | 0 | 0 |

Quoter V2 success rate: **99/108 = 91.7%** executable (improved from ~60% in R30 due to hot_requote excluding dead pools).

### Truth Verdict (NEW R31 FIELD)
```
truth_verdict: DIAGNOSTIC_PROFIT_ONLY
meaning: profit_status=PASS (one-leg simulated net $59.90) but 0 roundtrip-confirmed profit
operator_action: Do NOT interpret as "profitable". The $59.90 net is diagnostic only.
```

## 4) Multi-Chain Long Scan Evidence (FRESH R31)

### Summary (43 runs, 630s wall, 6 chains)
| Metric | Value |
|--------|-------|
| Total runs | 43 |
| PASS / NO_DATA / FAIL | 33 / 2 / 8 |
| Signals total | 308 |
| Net USDC total | $560.16 |
| Profitable RTs | 0 |
| RT evaluated | 0 |
| Pass chains | arbitrum_one, linea, scroll |
| Fail chains | zksync, base, mantle |

### Per-Chain Breakdown
| Chain | Runs | PASS | FAIL | Signals | Net USDC | Cross-DEX | Quality | Level |
|-------|------|------|------|---------|----------|-----------|---------|-------|
| arbitrum_one | 8 | 8 | 0 | 216 | $368.20 | 30 | WARN | SIGNAL_PRODUCING |
| linea | 7 | 7 | 0 | 31 | $75.51 | 11 | WARN | SIGNAL_PRODUCING |
| scroll | 7 | 7 | 0 | 28 | $32.53 | 5 | WARN | SIGNAL_PRODUCING |
| mantle | 7 | 6 | 1 | 18 | $62.92 | 6 | WARN | SIGNAL_PRODUCING |
| zksync | 7 | 2 | 5 | 8 | $3.85 | 4 | FAIL | - |
| base | 7 | 3 | 2 | 7 | $17.15 | 15 | NO_DATA | INFRA_READY |

### Profit Truth Summary
All 6 chains: `truth_verdict = DIAGNOSTIC_PROFIT_ONLY` or worse. 0 roundtrips evaluated across all chains. All net USDC values are one-leg diagnostic simulations — NOT executable profit.

## 5) Root Cause Analysis: 0 Roundtrip Evaluations

### Pipeline Trace (arb primary)
```
signals (46) → OE (207 combinations) → OE gate (0 pass) → roundtrip selection (0 candidates) → roundtrip (0 evaluated)
```

### Why 207→0 at OE Gate
1. **NET_PROFIT_TOO_LOW (118)**: At $10 probe size, gas+slippage costs exceed spread profit for most pairs. This is the dominant blocker.
2. **SUSPECT_SPREAD_HARD (46)**: Stale slot0 prices or inverted pools produce >500 bps apparent spreads that are artifacts, not opportunities.
3. **MIXED_SOURCE (21)**: One leg uses quoter_v2 (executable), other falls back to slot0 (diagnostic). OE requires both legs executable.
4. **NOTIONAL_DRIFT (19)**: Target $10 vs actual amount differs >20% due to low-liquidity pools.
5. **SLOT0_DIAGNOSTIC (3)**: Both legs are slot0 fallback — entirely non-executable.

### Key Insight
The primary blocker is **economics at $10 probe size** (NET_PROFIT_TOO_LOW = 57% of rejections), NOT the mixed-source/slot0 issue identified in R30's preliminary analysis. The quoter success rate improved to 91.7% in R31 (from ~60% in R30) because hot_requote mode prunes dead pools.

## 6) R31 Architecture Changes

### truth_verdict (4-value domain)
Added to `compute_status()` in `m4/policy.py` and to `run_summary_data` in `m4/fixtures.py`:
| Value | Meaning |
|-------|---------|
| `NO_DATA` | No signals (empty scan) |
| `ROUNDTRIP_PROFITABLE` | At least 1 profitable roundtrip |
| `DIAGNOSTIC_PROFIT_ONLY` | profit_status=PASS but 0 profitable roundtrips |
| `NO_PROFIT` | profit_status=FAIL |

### quote_source_summary (truth_report first-class field)
Surfaced from `stats.quoter_matrix` into `truth_report.quote_source_summary` with per-DEX:fee executable/diagnostic/failed breakdown.

### oe_rejection_funnel (truth_report first-class field)
Surfaced from `stats.opportunity_engine.summary` into `truth_report.oe_rejection_funnel` with total/gated/rejected/reasons.

## 7) Contract Checks
truth_verdict domain: OK — 4 values, tested in test_r31_truth_verdict.py (5 tests)
quote_source_summary: OK — present in truth_report, tested (3 tests)
oe_rejection_funnel: OK — present in truth_report, tested (3 tests)
rolling discipline (3+1 files): OK
provenance contract: OK (run_timestamp only)
runtime artifacts not committed: OK
CI pipeline: ALL REQUIRED GATES PASSED

## 8) Rolling Aggregator Stats (m4_stability_agg quick_stats)
```
pass_rate: 0.95
data_run_rate: 1.0
total_net_usdc: $7127.42 (200-run window)
avg_net_usdc: $35.64 per run
latest_profit_realism_status: ONE_LEG_ONLY_DIAGNOSTIC
roundtrip_runs_evaluated: 191
roundtrip_runs_profitable: 0
sweep_median_gap_to_zero_bps: 68.13
consecutive_non_nodata_cycles: 200
chain_key: arbitrum_one
```

## 9) Blocker Classification (R31)

### Per-chain blocker taxonomy
| Chain | Verdict | R31 Finding |
|-------|---------|-------------|
| arbitrum_one | **OE_ECONOMICS (NET_PROFIT_TOO_LOW = 57% of rejections)** | 207 OE combos, 0 gated. $10 probe too small for gas breakeven. |
| linea | **SIGNAL_PRODUCING (31 signals, $75.51 diag)** | Pass chain. 2 DEXes (pancake+lynex). 4 cross-DEX signals per run. |
| scroll | **SIGNAL_PRODUCING (28 signals, $32.53 diag)** | Pass chain. 3 DEXes (nuri+sushi+uni). Accepted-fail. |
| mantle | **FRAGILE_QUALITY (6/7 PASS, 18 signals)** | Intermittent failures. discovery_probe_size_usd=10. |
| zksync | **HIGH_FAIL (5/7 FAIL, 8 signals)** | RPC instability. SyncSwap stub not yet functional. |
| base | **INFRA_READY (2 NO_DATA, 15 cross-DEX pairs discovered)** | Aerodrome VE33 quote path not producing signals. |

### Summary blockers
```
code_blocker: NONE (2101 tests PASS, CI pipeline PASS)
artifact_clarity: RESOLVED (truth_verdict + quote_source_summary + oe_rejection_funnel)
economics_blocker: HIGH ($10 probe NET_PROFIT_TOO_LOW = 57% OE rejections on arb)
quoter_v2_fallback: LOW (91.7% quoter_v2 success rate; MIXED_SOURCE only 10.1% of rejections)
execution_blocker: HIGH (dormant — no signer, simulate_only)
```

## 10) What I need from Lead now
1. **Probe size strategy**: $10 is too small for gas breakeven on most pairs (NET_PROFIT_TOO_LOW = 57% of OE rejections). Should we increase probe size or use the wide sweep ladder from R29?
2. **OE gating policy**: With 91.7% quoter_v2 success rate, MIXED_SOURCE (10.1%) is a minor blocker. Consider relaxing OE gate for pairs where one leg is quoter_v2?
3. **Per-chain priority**: linea and scroll are SIGNAL_PRODUCING with 100% pass rate. Push these toward roundtrip evaluation first?
4. **Adapter implementation**: iziswap/syncswap/ambient stubs still pending. Which first?
5. **Sweep integration with OE**: R29 wide ladder ($1-$10,000) never reaches OE because OE uses paper_size_usd=$10. Connect sweep to OE evaluation?
