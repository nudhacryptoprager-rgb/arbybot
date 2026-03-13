# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-13, Session 4 Round 21)
**Goal**: R21 AUDIT — per_chain/per_pair NOTIONAL_DRIFT summary as top-level blocks, dashboard canonical operator surface, chain config concrete stabilization, measured block as sole operational truth, discovery vs truth-probe universe split.

## 0) Meta
timestamp_utc: 2026-03-13T11:54:40Z
rolling_provenance: 2026-03-13T11:54:40Z (arbitrum_one, ci_m5_gate_20260313_125401)
mode: ONLINE
test_count: 1699 passed, 2 skipped
schema_version: start:long_scan_summary:v1.4

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R21: per_chain_drift_summary block, universe_split block, notional_drift_bps in frontier, measured_economics as sole truth, concrete stabilization_kpi_target in chain configs |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb (gap=23.2 bps); scroll PROBE_ONLY (single DEX) |
| evidence_session_run_dirs | ci_m5_gate_20260313_124614 (base#1), ci_m5_gate_20260313_124714 (base#2), ci_m5_gate_20260313_124927 (mantle), ci_m5_gate_20260313_125124 (zksync), ci_m5_gate_20260313_125250 (scroll), ci_m5_gate_20260313_125321 (linea), ci_m5_gate_20260313_125401 (arb rolling) + 6 earlier runs |
| primary_blocker_of_session | per_chain_drift_summary missing; universe_split absent; notional_drift_bps not in frontier; chain configs lacked concrete KPI targets |
| blocker_status_before | R20: per-pair drift only, no per-chain aggregation, no universe_split, stabilization YAML directives instead of KPI targets |
| blocker_status_after | RESOLVED (code+tests+scan). MARKET blockers remain (roundtrip_profitable=0) |
| start_metric | R20: 1685 tests, 10 panels, v1.3 schema, no per_chain_drift_summary |
| end_metric | R21: 1699 tests, 10 panels (drift shows per-pair), v1.4 schema, per_chain_drift_summary + universe_split + notional_drift_bps in frontier + operational_truth_source="measured_economics" |
| delta | +14 tests, schema v1.3→v1.4, per_chain_drift_summary block, universe_split block, notional_drift_bps in frontier, measured_economics sole truth, stabilization_kpi_target in 4 chain configs |
| docs_reread_confirmed | true |

## 1) Changes This Session (R21)

1. **per_chain_drift_summary block** (`start.py`): New `_compute_per_chain_drift_summary()` aggregates per-chain drift metrics: `drift_excluded_total`, `drift_rejection_rate_median`, `notional_drift_median_bps`, `drift_pairs_with_data_total`, `runs_sampled`. Included in `long_scan_latest.json` as top-level field.
2. **universe_split block** (`start.py`): New `_compute_universe_split()` classifies chains into `discovery_chains` (cross-dex active), `truth_probe_chains` (frontier_ready + target_for_truth_probe), `monitoring_only_chains` (PROBE_ONLY/accepted-fail). Included in `long_scan_latest.json`.
3. **notional_drift_bps in frontier_ranking** (`start.py`): `_compute_frontier_ranking()` now includes `drift_rejection_rate_median`, `notional_drift_median_bps`, `drift_excluded_total`, `drift_pairs_with_data_total` for each chain entry.
4. **operational_truth_source** (`strategy/artifacts.py`): `build_truth_data()` now includes `operational_truth_source: "measured_economics"` to mark measured block as sole operational truth.
5. **per_pair_drift_summary** (`strategy/artifacts.py`): `_build_drift_summary()` returns unified `per_pair_drift_summary` list (includes both excluded and included pairs with exclusion counts).
6. **Dashboard Panel 2 drift column**: Frontier ranking shows "Drift bps" column with `notional_drift_median_bps`.
7. **Dashboard Panel 7 per_pair table**: Drift panel shows `per_pair_drift_summary` table with excluded/included counts per pair.
8. **Dashboard Panel 10 cost column**: Truth-probe targets show `measured_total_cost_bps` in "Cost bps" column.
9. **stabilization_kpi_target in chain configs**: All 4 coverage configs (zksync/mantle/linea/scroll) have concrete `stabilization_kpi_target` block replacing textual `stabilization_directive`.
10. **Tests**: 38 tests in test_drift_summary.py (up from 24): TestR21PerPairDriftSummary (6), TestR21OperationalTruth (1), TestR21PerChainDriftSummary (2), TestR21FrontierDrift (2), TestR21DashboardEnhancements (3).

## 2) Evidence Artifacts (R21 — 15-min 6-chain scan)

### Rolling State (R21 — 13-run 6-chain scan, 923s wall time)

| Artifact | Key Metric | Value |
|----------|-----------|-------|
| long_scan_latest | schema | start:long_scan_summary:v1.4 |
| long_scan_latest | total_runs | 13 (PASS=11, FAIL=2) |
| long_scan_latest | total_included_signals | 38 |
| long_scan_latest | total_net_usdc | $38.45 |
| long_scan_latest | pass_chains | arbitrum_one, base, mantle, zksync, linea |
| long_scan_latest | accepted_fail_chains | scroll |
| run_summary | run_id | ci_m5_gate_20260313_125401 |
| run_summary | chain_key | arbitrum_one |
| run_summary | status | PASS |
| run_summary | signals_count | 4 |
| run_summary | sweep.gap_to_zero_bps | 23.23 |
| run_summary | sweep.measured_total_cost_bps | 25.10 |
| m4_stability_agg | total_runs_in_window | 187+ |

### Multi-Chain Frontier (R21 fresh — 13 runs)

| # | Chain | Gap bps | Net bps | Median bps | Sweeps | Signals | xDex | Drift bps | Status |
|---|-------|---------|---------|------------|--------|---------|------|-----------|--------|
| 1 | **zksync** | **0.0** | 0.0 | 0.0 | 2 | 2 | 10 | 1472 | PASS |
| 2 | arbitrum_one | 23.23 | -23.23 | 23.27 | 3 | 12 | 3 | 315 | PASS |
| 3 | base | 89.06 | -89.06 | 92.15 | 2 | 14 | 15 | 338 | PASS |
| 4 | linea | n/a | — | n/a | 0 | 6 | 0 | 307 | PASS |
| 5 | mantle | n/a | — | n/a | 0 | 4 | 0 | 315 | PASS |
| 6 | scroll | n/a | — | n/a | 0 | 0 | 0 | 2576 | AF |

### Per-Chain Drift Summary (R21 — new block)

| Chain | Drift Rej Rate | Drift Median bps | Excluded | Pairs w/Data |
|-------|----------------|------------------|----------|--------------|
| arbitrum_one | 16.7% | 315 | 6 | 9 |
| base | 30.3% | 338 | 33 | 10 |
| mantle | 6.3% | 315 | 4 | 6 |
| zksync | 34.9% | 1472 | 36 | 8 |
| linea | 11.5% | 307 | 4 | 10 |
| scroll | 35.2% | 2576 | 10 | 2 |

### Universe Split (R21 — new block)

| Category | Chains |
|----------|--------|
| discovery | base, linea, mantle, zksync |
| truth_probe | arbitrum_one |
| monitoring_only | scroll |
| total_chains | 6 |

### Cost Decomposition (arb frontier, R21 latest)

| Component | bps |
|-----------|-----|
| LP Fee | 10.00 |
| Slippage | 11.94 |
| Gas | 3.16 |
| **Total** | **25.10** |

### Cost Decomposition (base frontier, R21)

| Component | bps |
|-----------|-----|
| LP Fee | **101.00** |
| Slippage | 1.42 |
| Gas | 25.04 |
| **Total** | **127.46** |

### Verification Gates (R21)

| Gate | Result |
|------|--------|
| pytest | 1699 passed, 2 skipped |
| ci_full_pipeline | ALL REQUIRED GATES PASSED |
| check_repo_safety | 19/19 PASS, 0 warnings |
| drift_summary tests | PASS (38 tests, +14 from R20) |
| 15-min online scan | 13 runs (11 PASS, 2 AF) |

## 3) Key Results

```
theoretical_net_profit:
  mode: paper_simulated
  gross_pnl_usdc: 38.45 (13 runs, 6 chains, 15 min)
  cost_breakdown:
    gas_usd: ~0.10 per trade (arb)
    slippage_bps: 11.94 (arb latest), 1.42 (base latest)
    l1_cost_usd: 0.0
    total_cost_bps: 25.10 (arb), 127.46 (base)
  net_pnl_usdc: diagnostic only (roundtrip_profitable=2, but base only via false SUSPECT_SPREAD)
  base_anomaly: 2 ROUNDTRIP_PROFITABLE on base (+2549 bps), BUT = SUSPECT_SPREAD (pancakeswap_v3 pricing)
  disclaimer: Theoretical profit based on simulated execution. No real trades.
```

## 4) Honest Assessment

**M4.2 NOT closed**: roundtrip_total_profitable=0 on arbitrum_one (primary chain). base shows 2 profitable but is FALSE POSITIVE.

**base ROUNDTRIP_PROFITABLE = FALSE POSITIVE**: 2 profitable roundtrips detected on base (2549 bps net), but this is a **SUSPECT_SPREAD** from pancakeswap_v3 returning bad WETH/USDC prices. Real arb does not exist at this magnitude. The sweep (which uses correct prices) shows gap=89.06 bps. **This is NOT real profit.**

**arbitrum_one economics (R21)**:
- gap_to_zero = 23.23 bps (latest), median = 23.27 bps
- Total cost = 25.10 bps (fee=10+slip=11.94+gas=3.16)
- Gap worsened vs R20 (10.44 bps→23.23 bps) — market volatility

**zksync frontier = 0.0 bps gap** (confirmed R21): breakeven on fee-tier arb, but 34.9% drift rejection rate means data quality is fragile. Notional drift median = 1472 bps (high).

**Per-Chain Blocker Classification (R21)**:
- **arbitrum_one**: MARKET — gap=23.23 bps (latest). Need fee=100 pool or slippage reduction
- **zksync**: MARKET+DRIFT — gap=0.0 bps breakeven, but 34.9% drift rejection rate. Drift=1472 bps median
- **base**: SYSTEM — pancakeswap_v3 returns bad prices (SUSPECT_SPREAD). fee=101 bps cost structure
- **mantle**: SYSTEM — single DEX (agni_v3), stratum incompatible. 6.3% drift (lowest)
- **linea**: SYSTEM — single DEX (pancakeswap_v3), lynex incompatible. 11.5% drift (low)
- **scroll**: SYSTEM — PROBE_ONLY permanent, single DEX (sushiswap_v3), 35.2% drift (high)

**Universe Classification (R21)**:
- **truth_probe**: arbitrum_one (frontier_ready + target_for_truth_probe=true)
- **discovery**: base, linea, mantle, zksync (cross-dex work but not frontier_ready)
- **monitoring_only**: scroll (PROBE_ONLY, accepted-fail)

## 5) Contract Checks
status/reasons consistency: OK
rolling discipline (3 canonical files): OK
provenance contract: OK (run_timestamp, code_identity, no SHA)
runtime artifacts not committed: OK
schema version: v1.4 (upgraded from v1.3)
per_chain_drift_summary: PRESENT (new R21 block)
universe_split: PRESENT (new R21 block)
operational_truth_source: "measured_economics" (new R21 field in truth_data)

## 6) Blocker Classification
```
profit_truth:           IN_PROGRESS (market-blocked: roundtrip_profitable=0 on arb, gap=23.23)
per_chain_drift_summary: RESOLVED (R21: top-level block in long_scan_latest.json)
universe_split:         RESOLVED (R21: discovery/truth_probe/monitoring_only classification)
notional_drift_bps:     RESOLVED (R21: in frontier_ranking entries)
operational_truth:      RESOLVED (R21: measured_economics in truth_data)
stabilization_kpi:      RESOLVED (R21: concrete targets in 4 chain configs)
base_pricing:           ACTIVE (pancakeswap_v3 SUSPECT_SPREAD, 127.46 bps cost)
zksync_drift:           ACTIVE (34.9% drift rejection, 1472 bps median)
```

## 7) R21 Audit Steps (10 fix steps from reviewer)
step_01: DONE - per_chain_drift_summary block. evidence: long_scan_latest.json per_chain_drift_summary
step_02: DONE - Dashboard drift column + per_pair table. evidence: dashboard.html Panel 2+7
step_03: DONE - zksync stabilization_kpi_target. evidence: coverage_intent_zksync.yaml
step_04: DONE - mantle stabilization_kpi_target. evidence: coverage_intent_mantle.yaml
step_05: DONE - linea stabilization_kpi_target. evidence: coverage_intent_linea.yaml
step_06: DONE - scroll stabilization_kpi_target. evidence: coverage_intent_scroll.yaml
step_07: DONE - measured_economics sole truth. evidence: artifacts.py operational_truth_source
step_08: DONE - universe_split block. evidence: long_scan_latest.json universe_split
step_09: DONE - CI + 15-min scan. evidence: 13 runs, all gates PASS, 1699 tests
step_10: DONE - Docs update. evidence: DEV_REPORT_LATEST.md (this file), Status_M5_0.md

## 8) Next Steps (R22)
1. zksync drift stabilization: lower drift threshold or add pair-specific limits (34.9% rejection)
2. base pancakeswap_v3 investigation: SUSPECT_SPREAD root cause (or disable pair)
3. Fee=100 pool discovery on arbitrum_one (WBTC/USDC or WETH/USDC) — would reduce cost ~8 bps
4. Cross-dex enablement for mantle/linea (need algebra-compatible quoter or alternative DEX)
5. M4.2 closure: gap_to_zero needs to reach ≤0 on arbitrum_one with real sweep economics

---
*Generated: 2026-03-13 R21*
