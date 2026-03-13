# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-13, Session 4 Round 22)
**Goal**: R22 AUDIT — Full per-pair rejection_rate + drift_worst_pair, dashboard live streaming, honest per-chain blocker classification (market vs system vs ecosystem), drift as frontier ranking factor, 3-hour 6-chain stabilization scan.

## 0) Meta
timestamp_utc: 2026-03-13T16:04:37Z
rolling_provenance: 2026-03-13T16:04:37Z (arbitrum_one, 109 runs)
mode: ONLINE
test_count: 1708 passed, 2 skipped
schema_version: start:long_scan_summary:v1.4

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R22: per-pair rejection_rate, drift_worst_pair in rolling, dashboard live updates, honest chain blocker classification, drift as ranking factor, 3-hour scan evidence |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb; scroll ECOSYSTEM_BLOCKED (single DEX) |
| evidence_session_run_dirs | 109 runs across 6 chains (3-hour scan), last=ci_m5_gate_20260313_160437 |
| primary_blocker_of_session | per-pair rejection_rate missing; no live dashboard streaming; chain blockers not classified; drift not in ranking |
| blocker_status_before | R21: per-pair drift summary without rejection_rate, dashboard update every ~7-10 min, no blocker_classification in config |
| blocker_status_after | RESOLVED (code+tests+3h scan). 5/6 chains 100% PASS, scroll expected FAIL |
| start_metric | R21: 1699 tests, dashboard batch updates, no rejection_rate, no drift ranking factor |
| end_metric | R22: 1708 tests, live streaming per-chain (~1-2 min), rejection_rate+drift_worst_pair, drift_rejection_rate_median as 4th ranking factor |
| delta | +9 tests, live dashboard, rejection_rate per pair, drift_worst_pair, drift ranking factor, 5 chain configs with blocker_classification |
| docs_reread_confirmed | true |

## 1) Changes This Session (R22)

1. **rejection_rate per pair** (`strategy/artifacts.py`): `per_pair_drift_summary` now includes `rejection_rate` (excluded/total) for each pair.
2. **drift_worst_pair in rolling** (`m4/rolling_store.py`): Per-run and per-chain frontier now includes `drift_worst_pair` and `drift_worst_pair_bps` extracted from per_pair_drift_summary[0].
3. **Live dashboard streaming** (`start.py`): `long_scan_latest.json` now updated after each chain run (~1-2 min) instead of after full cycle (~7-10 min). `setInterval(loadData, 15000)` in dashboard.
4. **Dashboard Panel 7 Rej%** (`monitoring/dashboard.html`): Drift table shows "Rej%" column with per-pair rejection rate.
5. **Dashboard Panel 8 drift context** (`monitoring/dashboard.html`): Blockers panel shows `drift_worst_pair` and `drift_worst_pair_bps`.
6. **Dashboard Panel 10 drift** (`monitoring/dashboard.html`): Truth-probe table shows drift columns.
7. **Chain blocker_classification configs**: 5 chain configs updated with explicit `blocker_classification`:
   - `coverage_intent_base.yaml`: `blocker_classification: MARKET` + stabilization_kpi_target
   - `coverage_intent_zksync.yaml`: `blocker_classification: mixed_blocker` + max_per_pair_rejection_rate: 0.40
   - `coverage_intent_mantle.yaml`: `blocker_classification: structural` + probe_only_threshold_runs: 10
   - `coverage_intent_linea.yaml`: `blocker_classification: structural` + pool health monitoring
   - `coverage_intent_scroll.yaml`: `blocker_classification: ECOSYSTEM_BLOCKED` + quarterly review
8. **drift as ranking factor** (`start.py`): `_compute_frontier_ranking()` now uses `drift_rejection_rate_median` as 4th sort factor (lower drift = better rank).
9. **Tests** (`tests/unit/test_drift_summary.py`): +9 tests for R22: TestR22PerPairRejectionRate (4), TestR22DriftWorstPairRolling (2), test_frontier_ranking_drift_as_sort_factor (1), dashboard tests (2).

## 2) Evidence Artifacts (R22 — 3-hour 6-chain scan)

### Rolling State (R22 — 109-run 6-chain scan, 10805s wall time)

| Artifact | Key Metric | Value |
|----------|-----------|-------|
| long_scan_latest | schema | start:long_scan_summary:v1.4 |
| long_scan_latest | total_runs | 109 (PASS=91, FAIL=18) |
| long_scan_latest | total_included_signals | 309 |
| long_scan_latest | total_net_usdc | $414.04 |
| long_scan_latest | pass_chains | arbitrum_one, base, mantle, zksync, linea |
| long_scan_latest | fail_chains | scroll (18/18 expected) |
| run_summary | run_id | ci_m5_gate_20260313_160437 (latest) |
| run_summary | chain_key | arbitrum_one |
| run_summary | status | PASS |
| m4_stability_agg | total_runs_in_window | 200+ |

### Multi-Chain Results (R22 — 109 runs, 3 hours)

| Chain | Runs | Pass | Fail | Signals | Status |
|-------|------|------|------|---------|--------|
| arbitrum_one | 19 | 19 | 0 | 76 | ✅ 100% PASS |
| base | 18 | 18 | 0 | 110 | ✅ 100% PASS |
| zksync | 18 | 18 | 0 | 18 | ✅ 100% PASS |
| mantle | 18 | 18 | 0 | 53 | ✅ 100% PASS |
| linea | 18 | 18 | 0 | 52 | ✅ 100% PASS |
| scroll | 18 | 0 | 18 | 0 | ❌ ECOSYSTEM_BLOCKED |

### Per-Chain Drift Summary (R22 — 3-hour aggregated)

| Chain | Drift Excluded | Drift Rej % | Median bps | Blocker Class |
|-------|----------------|-------------|------------|---------------|
| arbitrum_one | 38 | 16.7% | 315 | MARKET |
| base | 248 | 30.3% | 338 | MARKET |
| zksync | 308 | 36.9% | 1472 | mixed_blocker |
| mantle | 36 | 6.3% | 315 | structural |
| linea | 36 | 11.5% | 307 | structural |
| scroll | 90 | 35.2% | 2576 | ECOSYSTEM_BLOCKED |

### Frontier Ranking (R22 — with drift as sort factor)

| # | Chain | Gap bps | Signals | xDex | Drift Rej % | Drift bps | Rank Score |
|---|-------|---------|---------|------|-------------|-----------|------------|
| 1 | zksync | 0.0 | 18 | 10 | 36.9% | 1472 | frontier_ready |
| 2 | arbitrum_one | 23.2 | 76 | 3 | 16.7% | 315 | truth_probe |
| 3 | base | 89.1 | 110 | 15 | 30.3% | 338 | discovery |
| 4 | mantle | n/a | 53 | 0 | 6.3% | 315 | discovery |
| 5 | linea | n/a | 52 | 0 | 11.5% | 307 | discovery |
| 6 | scroll | n/a | 0 | 0 | 35.2% | 2576 | blocked |

### Verification Gates (R22)

| Gate | Result |
|------|--------|
| pytest | 1708 passed, 2 skipped (+9 from R21) |
| ci_full_pipeline | ALL REQUIRED GATES PASSED |
| 3-hour online scan | 109 runs (91 PASS, 18 AF scroll) |
| live dashboard | updates every ~1-2 min per chain |

## 3) Key Results

```
theoretical_net_profit:
  mode: paper_simulated
  gross_pnl_usdc: 414.04 (109 runs, 6 chains, 3 hours)
  net_pnl_usdc: diagnostic only (roundtrip_profitable detected on base, but SUSPECT_SPREAD)
  base_anomaly: ROUNDTRIP_PROFITABLE detections = SUSPECT_SPREAD (pancakeswap_v3 pricing)
  disclaimer: Theoretical profit based on simulated execution. No real trades.
```

## 4) Honest Assessment

**M4.2 NOT closed**: roundtrip_profitable still shows false positives on base due to pancakeswap_v3 SUSPECT_SPREAD.

**5/6 chains 100% PASS rate over 3 hours**:
- arbitrum_one: 19/19 PASS, 76 signals, primary chain
- base: 18/18 PASS, 110 signals, highest signal volume
- zksync: 18/18 PASS, 18 signals, breakeven frontier
- mantle: 18/18 PASS, 53 signals, single DEX (structural)
- linea: 18/18 PASS, 52 signals, single DEX (structural)
- scroll: 0/18 PASS, ECOSYSTEM_BLOCKED (single DEX, no second DEX expected)

**Per-Chain Blocker Classification (R22 — honest)**:
| Chain | Classification | Reason | Actionable |
|-------|---------------|--------|------------|
| arbitrum_one | **MARKET** | gap=23.2 bps, need fee=100 pool or slippage reduction | Wait for market or discover fee tier |
| base | **MARKET** | pancakeswap_v3 SUSPECT_SPREAD, but sweep shows real gap ~89 bps | Fix pricing or wait for market |
| zksync | **mixed_blocker** | gap=0.0 bps but 36.9% drift rejection | Pair-specific drift limits (max_per_pair_rejection_rate=0.40) |
| mantle | **structural** | single DEX (agni_v3), stratum incompatible | Monitor, wait for 2nd DEX with V3 quoter |
| linea | **structural** | single DEX (pancakeswap_v3), lynex incompatible | Monitor, wait for 2nd DEX |
| scroll | **ECOSYSTEM_BLOCKED** | single DEX (sushiswap_v3), no 2nd DEX expected | Quarterly ecosystem review |

**Live Dashboard**:
- Rolling artifact updates after each chain (~1-2 min) instead of full cycle (~7-10 min)
- HTML auto-refresh every 15 seconds
- Drift context visible in all relevant panels (Rej%, worst pair, drift bps)

## 5) Contract Checks
status/reasons consistency: OK
rolling discipline (3 canonical files): OK
provenance contract: OK (run_timestamp, code_identity, no SHA)
runtime artifacts not committed: OK
schema version: v1.4
per_chain_drift_summary: PRESENT
universe_split: PRESENT
operational_truth_source: "measured_economics"
blocker_classification: PRESENT in 5 chain configs
live_dashboard_streaming: ENABLED (per-chain updates)

## 6) Blocker Classification
```
profit_truth:             IN_PROGRESS (market-blocked: roundtrip_profitable=false on arb)
per_pair_rejection_rate:  RESOLVED (R22: rejection_rate field in per_pair_drift_summary)
drift_worst_pair:         RESOLVED (R22: in rolling per-run and per-chain)
live_dashboard:           RESOLVED (R22: updates per-chain ~1-2 min)
blocker_classification:   RESOLVED (R22: 5 chain configs with explicit classification)
drift_ranking_factor:     RESOLVED (R22: drift_rejection_rate_median as 4th sort factor)
base_pricing:             ACTIVE (pancakeswap_v3 SUSPECT_SPREAD persists)
scroll_ecosystem:         ACCEPTED (ECOSYSTEM_BLOCKED, quarterly review)
```

## 7) R22 Audit Steps (10 fix steps from reviewer)
step_01: DONE - per-pair rejection_rate. evidence: per_pair_drift_summary in truth_data
step_02: DONE - Dashboard Rej% + drift_worst columns. evidence: dashboard.html Panel 7+8+10
step_03: DONE - Base chain MARKET blocker. evidence: coverage_intent_base.yaml blocker_classification
step_04: DONE - ZKsync mixed_blocker. evidence: coverage_intent_zksync.yaml max_per_pair_rejection_rate
step_05: DONE - Mantle structural blocker. evidence: coverage_intent_mantle.yaml
step_06: DONE - Linea structural blocker. evidence: coverage_intent_linea.yaml
step_07: DONE - Scroll ECOSYSTEM_BLOCKED. evidence: coverage_intent_scroll.yaml
step_08: DONE - Drift as ranking factor. evidence: start.py _compute_frontier_ranking sort key
step_09: DONE - CI + tests (1708 passed). evidence: pytest + ci_full_pipeline
step_10: DONE - 3-hour scan + docs. evidence: 109 runs (91 PASS), this file

## 8) Next Steps (R23)
1. base pancakeswap_v3 SUSPECT_SPREAD root cause investigation (or disable pair)
2. Fee=100 pool discovery on arbitrum_one (WBTC/USDC or WETH/USDC) — would reduce cost ~8 bps
3. zksync pair-specific drift control enforcement (max_per_pair_rejection_rate=0.40)
4. Cross-dex enablement for mantle/linea (need algebra-compatible quoter or alternative DEX)
5. M4.2 closure: gap_to_zero needs to reach ≤0 on arbitrum_one with real sweep economics

---
*Generated: 2026-03-13 R22*
