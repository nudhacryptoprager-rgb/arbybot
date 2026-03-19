# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one. R28.26: Lead's 4-layer ladder experiment isolating stateful suppression layers. Result: **suppression is NOT the surface killer**. Quarantine never triggers (0 pools). runtime_disabled acts as performance cache (147 pools = LIQUIDITY_ZERO already). Disabling suppression gives FEWER rt_real_quote (L0=7 vs L3=12, all 0 profitable). Next layer to isolate: hard caps in run_scan_real.py.

## SESSION GOAL (R28.26)
**Goal**: R28.26 — 4-layer ladder experiment to isolate which stateful suppression layer kills the quote surface. L0=all OFF, L1=quarantine OFF, L2=runtime_disabled OFF, L3=baseline.
**Prior (R28.25)**: Lead audit 10-step — config alignment, suppression reform, roundtrip_truth_status elevation. 1961 tests.
**Prior (R28.24)**: Deep pipeline analysis — phantom spread root cause. 37-run scan, 6 chains.

## 0) Meta
timestamp_utc: 2026-03-19T19:45:37Z
run_dir_name: ci_m5_gate_arbitrum_one_20260319_204506_400389
mode: LADDER_EXPERIMENT (R28.26 — 4 layers x 10 min x 6 chains)
test_count: 1966 passed, 3 skipped
schema_version: start:long_scan_summary:v1.14, start:hot_loop_snapshot:v1.3

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.26: 4-layer ladder to isolate stateful suppression impact on quote surface |
| goal_status | **REACHED** (ladder complete, suppression NOT the blocker) |
| close_allowed | true |
| remaining_blockers | 0 profitable RT remains — next: hard caps in run_scan_real.py |
| evidence_session_run_dirs | 4 ladder runs saved: L0/L1/L2/L3 in data/tmp/ |
| primary_blocker_of_session | Stateful suppression (quarantine + runtime_disabled) suspected as surface killer |
| blocker_status_before | ACTIVE: R28.25 suspected suppression as material blocker |
| blocker_status_after | RESOLVED: suppression empirically proven NOT the blocker via 4-layer ladder |
| start_metric | R28.25: 0 profitable RT, suspected suppression kills surface |
| end_metric | R28.26: suppression OFF gives 0 profitable RT. runtime_disabled = performance cache. Next: hard caps |
| delta | 4 ladder runs, no code changes. Suppression isolation complete. |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R28.26: Isolate suppression layer impact via 4-layer ladder
change_summary:
  - EXPERIMENT: 4-layer ladder (L0-L3) using R28.25/R28.26 safe toggles (ARBY_DISABLE_RUNTIME_SUPPRESSION, ARBY_DISABLE_RUNTIME_QUARANTINE, ARBY_DISABLE_RUNTIME_DISABLED)
  - NO CODE CHANGES — lead added toggle system, this session runs the experiment
touched_files: None (experiment-only session, toggles via env vars)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit/test_quotes_runtime_filter_switches.py tests/unit/test_run_scan_live_stream.py -q: PASS (10/10)
py -3.11 scripts/check_repo_safety.py: PASS (3 warnings — stale report, expected)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (1966 passed, 3 skipped; all gates green)

L0: ARBY_DISABLE_RUNTIME_SUPPRESSION=1 (all OFF)  — 10 min, 6 chains
L1: ARBY_DISABLE_RUNTIME_QUARANTINE=1 (quarantine OFF, rtdis ON) — 10 min, 6 chains
L2: ARBY_DISABLE_RUNTIME_DISABLED=1 (rtdis OFF, quarantine ON) — 10 min, 6 chains
L3: no env vars (baseline, all ON) — 10 min, 6 chains
```

## 3) Artifacts Attached
rolling: data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}
ladder: data/tmp/{L0_all_suppression_off.json,L1_quarantine_off.json,L2_runtime_disabled_off.json,L3_baseline_all_on.json}

## 4) Key Results: 4-Layer Ladder Comparison

### Aggregate (all 6 chains)

| Metric | L0 (all OFF) | L1 (quar OFF) | L2 (rtdis OFF) | L3 (baseline) |
|--------|-------------|----------------|-----------------|---------------|
| quotes_fetched | 241 | 233 | 244 | 233 |
| spread_signals | 29 | 53 | 31 | 58 |
| rt_candidates | 34 | 60 | 34 | 60 |
| rt_passed_eval | 11 | 16 | 9 | 14 |
| **rt_real_quote** | **7** | **13** | **7** | **12** |
| **rt_profitable** | **0** | **0** | **0** | **0** |
| quarantined_skip | 0 | 0 | 0 | 0 |
| runtime_disabled_skip | 0 | 147 | 0 | 147 |

### Per-Chain (arbitrum_one — primary)

| Metric | L0 | L1 | L2 | L3 |
|--------|----|----|----|----|
| quotes_fetched | 104 | 97 | 101 | 98 |
| spread_signals | 19 | 43 | 21 | 47 |
| rt_passed_eval | 4 | 10 | 3 | 8 |
| **rt_real_quote** | **3** | **9** | **3** | **8** |
| runtime_disabled_skip | 0 | 61 | 0 | 61 |
| LIQUIDITY_ZERO (rejects) | 61 | 0 | 61 | 0 |

### Per-Chain Summary (other chains)

| Chain | L0 rt_rq | L3 rt_rq | Delta | Dominant Blocker |
|-------|----------|----------|-------|------------------|
| zksync | 2 | 2 | 0 | ECONOMICS (stable) |
| base | 0 | 0 | 0 | QUOTE_PATH (0 in all layers) |
| mantle | 1 | 1 | 0 | ECONOMICS (stable) |
| linea | 1 | 1 | 0 | ECONOMICS (stable) |
| scroll | 0 | 0 | 0 | DEAD_POOLS |

## 4.1) R28.26 KEY FINDINGS

### Finding 1: Quarantine has ZERO impact
`quarantined_skipped = 0` in ALL four layers across ALL chains. Within a 10-minute window on fresh caches, no pools accumulate enough failures to trigger quarantine.

### Finding 2: runtime_disabled is a PERFORMANCE CACHE, not a surface killer
147 LIQUIDITY_ZERO pools are classified as runtime_disabled. When OFF (L0, L2), those same pools appear as LIQUIDITY_ZERO rejects — they fail anyway but waste RPC time.

**Proof**: arb L3 (rtdis ON): 61 rtdis_skip, 0 LIQ_ZERO, 8 rt_real_quote.
arb L0 (rtdis OFF): 0 rtdis_skip, 61 LIQ_ZERO, **3** rt_real_quote. Disabling makes things WORSE.

### Finding 3: 0 profitable roundtrips in ALL layers
`rt_profitable = 0` across all 4 layers and all 6 chains. Suppression definitively NOT the cause of zero profitability.

### Finding 4: Base is a quote-path blocker regardless of suppression
base produces 81-83 quotes in all layers but 0 rt_real_quote. LIQUIDITY_ZERO=41 pools, only 1-2 spread signals.

### Conclusion
R28.26 introduced safe layer-isolation toggles for stateful suppression in strategy/quotes.py. The 4-step 10-minute ladder proves: **neither quarantine nor runtime_disabled kills the quote surface**. runtime_disabled improves throughput by caching LIQUIDITY_ZERO. Next layer to isolate: hard caps in run_scan_real.py.

## 5) Contract Checks
status/reasons consistency: OK — all layers produce consistent funnel structures
rolling discipline (3 files only): OK
runtime artifacts not committed: OK

## 6) Blocker Classification

```
code_blocker: NONE (1966 tests PASS, CI green)
suppression_blocker: NONE (empirically proven via ladder: not the surface killer)
data_collection_blocker: MEDIUM (LIQUIDITY_ZERO dominates: 61/233 pools on arb)
market_window_blocker: HIGH (0/12 RT profitable, spreads insufficient for costs)
quote_path_blocker: MEDIUM (ALGEBRA_NEEDS_QUOTER=9 on arb, VE33_QUOTE_FAILED=1 on mantle)
hard_caps_blocker: UNKNOWN (next isolation target: run_scan_real.py caps)
execution_blocker: HIGH (dormant — no signer)
```

## 7) Lead's R28.26 Ladder Steps: Execution Map
step_01: **DONE** — Read modified files (toggle system in quotes.py), reread docs
step_02: **DONE** — Pre-verification: 1966 tests PASS, check_repo_safety PASS, ci_full_pipeline PASS
step_03: **DONE** — L0: ARBY_DISABLE_RUNTIME_SUPPRESSION=1 (all OFF). 10 min, 6 chains.
step_04: **DONE** — L1: ARBY_DISABLE_RUNTIME_QUARANTINE=1 (quarantine OFF). 10 min, 6 chains.
step_05: **DONE** — L2: ARBY_DISABLE_RUNTIME_DISABLED=1 (runtime_disabled OFF). 10 min, 6 chains.
step_06: **DONE** — L3: baseline (all ON). 10 min, 6 chains.
step_07: **DONE** — Compare 4-layer funnel diffs per chain (see Section 4 tables)
step_08: **DONE** — Determine blocker: suppression NOT the killer, runtime_disabled = perf cache
step_09: **DONE** — Update docs (this report + Status_M5_0 + Status_M4)
step_10: **DONE** — Final validation: tests + safety check

## 8) What I need from Lead now
1. **Hard caps isolation**: Next ladder target — isolate roundtrip_max_candidates, discovery_runtime_max_pairs, min_spread_bps impact in run_scan_real.py
2. **LIQUIDITY_ZERO investigation**: 61 arb pools (26% of universe) are permanently zero-liquidity. Are these dead pools or stale cache?
3. **ALGEBRA_NEEDS_QUOTER**: 9 arb pools need dedicated Algebra globalState reader (not V3 slot0)
4. **Anchor refresh**: Prices stale since 2026-02-17 (NOTIONAL_DRIFT rejects: 29-35 per chain)