# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-13, Session 4 Round 20)
**Goal**: Full NOTIONAL DRIFT per-pair/per-chain analysis, dashboard default-on, truth-probe panel, chain stabilization directives, blocker root-cause analysis.

## 0) Meta
timestamp_utc: 2026-03-13T10:38:33Z
rolling_provenance: 2026-03-13T10:38:33Z (arbitrum_one, ci_m5_gate_20260313_113747)
mode: ONLINE
test_count: 1685 passed, 2 skipped

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | Full drift bps analysis + dashboard default-on + truth-probe panel + blocker root-cause |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb (gap=10.4 bps); SUSPECT_SPREAD on base (pancakeswap_v3 bad prices) |
| evidence_session_run_dirs | ci_m5_gate_20260313_113020 (arb), ci_m5_gate_20260313_113128 (base), ci_m5_gate_20260313_113421 (mantle), ci_m5_gate_20260313_113506 (zksync), ci_m5_gate_20260313_113635 (scroll), ci_m5_gate_20260313_113707 (linea), ci_m5_gate_20260313_113747 (arb#2), ci_m5_gate_20260313_113853 (base#2) |
| primary_blocker_of_session | Drift not per-pair/bps; dashboard not default; no truth-probe panel; no stabilization directives |
| blocker_status_before | R19: drift aggregate-only, --dashboard opt-in, 9 panels, no per-pair bps |
| blocker_status_after | RESOLVED (code). MARKET blockers remain (roundtrip_profitable=0) |
| start_metric | R19: 1674 tests, 9 panels, drift no-bps, --dashboard opt-in |
| end_metric | R20: 1685 tests, 10 panels, drift per-pair bps, --no-dashboard opt-out, stabilization directives |
| delta | +11 tests, 1 new panel, drift bps end-to-end, dashboard default-on, 4 chain directives |
| docs_reread_confirmed | true |

## 1) Changes This Session

1. **NOTIONAL_DRIFT per-pair bps**: Enhanced `_build_drift_summary()` with `median_drift_bps`, `max_drift_bps`, `drift_reject_reason` per worst pair; `per_pair_signal_drift` (top 10 pairs with bps); `pairs_with_drift_data`/`pairs_with_exclusions` counts. Propagated to rolling_store per-run, per-chain frontier, quick_stats.
2. **Dashboard default-on**: `--dashboard` is now a no-op (backward-compat). Added `--no-dashboard` to disable. Dashboard launches automatically with scan.
3. **Panel 10 — Truth-Probe Targets**: Shows frontier_ranking entries with `target_for_truth_probe=true`, including gap/PnL/frontier pair/signals/blocker classification badge.
4. **Panel 7 enhanced**: Added bps KPIs, per_pair_signal_drift table, pairs_with_drift_data/exclusions counts, rolling drift_bps_p50.
5. **Chain stabilization directives**: Added `stabilization_directive` field to all 4 coverage configs (zksync/mantle/linea/scroll) with concrete R20 next-step instructions.
6. **Tests**: 24 tests in test_drift_summary.py (up from 13): drift bps fields, per_pair_signal_drift, drift propagation contract, dashboard HTML panels, default-on behavior.

## 2) Evidence Artifacts

### Rolling State (R20 — 8-run 6-chain scan)

| Artifact | Key Metric | Value |
|----------|-----------|-------|
| run_summary | run_id | ci_m5_gate_20260313_113747 |
| run_summary | chain_key | arbitrum_one |
| run_summary | status | PASS |
| run_summary | signals_count | 5 |
| run_summary | sweep.gap_to_zero_bps | 10.44 |
| run_summary | sweep.measured_total_cost_bps | 25.13 |
| run_summary | drift.median_bps | 385 |
| run_summary | drift.p90_bps | 627 |
| m4_stability_agg | total_runs_in_window | 184 |
| m4_stability_agg | agg_status | PASS |
| m4_stability_agg | total_net_usdc | $1142.02 |
| m4_stability_agg | sweep_gap_to_zero_min | 4.10 bps |
| m4_stability_agg | drift_signal_median_bps_p50 | 373.5 |

### Multi-Chain Frontier (R20 fresh — 8 runs, 2 cycles)

| # | Chain | Gap bps | Net bps | Sweeps | Signals | RT Prof | xDex | Status |
|---|-------|---------|---------|--------|---------|---------|------|--------|
| 1 | **zksync** | **0.0** | 0.0 | 1 | 6 | 0/2 | 10 | PASS |
| 2 | arbitrum_one | 10.44 | -10.44 | 2 | 10 | 0/5 | 3 | PASS |
| 3 | **base** | 38.69 | -38.69 | 2 | 17 | **1/4** | 15 | PASS |
| 4 | mantle | n/a | — | 0 | 3 | 0/0 | 0 | PASS |
| 5 | linea | n/a | — | 0 | 5 | 0/0 | 0 | PASS |
| 6 | scroll | n/a | — | 0 | 1 | 0/0 | 0 | AF |

### Cost Decomposition (arb frontier, R20 latest)

| Component | bps |
|-----------|-----|
| LP Fee | 10.00 |
| Slippage | 11.97 |
| Gas | 3.16 |
| **Total** | **25.13** |

### Cost Decomposition (base frontier, R20)

| Component | bps |
|-----------|-----|
| LP Fee | **101.00** |
| Slippage | 2.83 |
| Gas | 12.52 |
| **Total** | **116.32** |

### Drift Summary (arb, R20 latest)

| Pair | Signal Count | Median Drift bps | P90 Drift bps |
|------|-------------|-------------------|---------------|
| WBTC/WETH | 4 | 204 | 229 |
| WBTC/USDC | 4 | 601 | 627 |
| WETH/USDT | 2 | 385 | 385 |
| Excluded (unknown) | 2 | 5674 | 5674 |

### Drift Summary (zksync, R20)

| Pair | Signal Count | Median Drift bps | P90 Drift bps |
|------|-------------|-------------------|---------------|
| WETH/USDC | 4 | 320 | 2248 |
| WETH/USDT | 4 | 1472 | 3676 |
| WSTETH/WETH | 2 | 3768 | 3768 |
| drift_rejection_rate | — | 40.4% | — |

### Verification Gates

| Gate | Result |
|------|--------|
| pytest | 1685 passed, 2 skipped |
| ci_full_pipeline | ALL REQUIRED GATES PASSED |
| check_repo_safety | 19/19 PASS, 0 warnings |
| drift_summary tests | PASS (24 tests) |

## 3) Key Results

```
theoretical_net_profit:
  mode: paper_simulated
  gross_pnl_usdc: 1142.02 (184 runs cumulative, arb_one rolling)
  cost_breakdown:
    gas_usd: ~0.10 per trade
    slippage_bps: 11.97 (latest), 8.06 (rolling median)
    l1_cost_usd: 0.0
    total_cost_bps: 25.13 (latest arb)
  net_pnl_usdc: diagnostic only (roundtrip profitable_count=0 on arb)
  base_anomaly: 1 ROUNDTRIP_PROFITABLE on base, BUT confidence=suspect (2488 bps spread = PRICE_OUTLIER from pancakeswap_v3)
  disclaimer: Theoretical profit based on simulated execution. No real trades.
```

## 4) Honest Assessment

**M4.2 NOT closed**: roundtrip_total_profitable=0 on arbitrum_one (primary chain).

**base ROUNDTRIP_PROFITABLE = FALSE POSITIVE**: 1 profitable roundtrip detected on base (2548 bps net), but this is a **SUSPECT_SPREAD** from pancakeswap_v3 returning bad WETH/USDC prices (2488 bps spread). Real arb does not exist at this magnitude — pancakeswap_v3 on base has a pricing anomaly. The sweep (which uses correct prices) shows gap=38.69 bps. **This is NOT real profit.**

**arbitrum_one economics (R20)**:
- gap_to_zero = 10.44 bps (latest), 4.10 bps (rolling best)
- Total cost = 25.13 bps (fee=10+slip=11.97+gas=3.16)
- Slippage worsened this run (11.97 vs 8.06 rolling median) — volatile market
- LP fee (10 bps) is ~40% of total cost → fee=100 pool lever would save 8 bps

**zksync frontier = 0.0 bps gap** (confirmed R20): breakeven on fee-tier arb, but 40.4% drift rejection rate means data quality is fragile. Only WETH/USDC is reliable (320 bps drift median).

**Per-Chain Blocker Classification (R20)**:
- **arbitrum_one**: MARKET — gap=10.44 bps (latest), 4.10 bps (best). Need fee=100 pool or slippage reduction
- **zksync**: MARKET+DRIFT — gap=0.0 bps breakeven, but 40.4% drift rejection rate. Data unreliable
- **base**: SYSTEM — pancakeswap_v3 returns bad prices (WETH/USDC 2488 bps spread = PRICE_OUTLIER). fee=101 bps cost structure makes arb impossible even with correct prices
- **mantle**: SYSTEM — single DEX (agni_v3), same-dex routes only, no cross-dex sweep possible
- **linea**: SYSTEM — single DEX (pancakeswap_v3), same-dex routes only
- **scroll**: SYSTEM — PROBE_ONLY permanent, single DEX (sushiswap_v3)

## 5) Contract Checks
status/reasons consistency: OK
rolling discipline (3 canonical files): OK
provenance contract: OK (run_timestamp, code_identity, no SHA)
runtime artifacts not committed: OK

## 6) Blocker Classification
```
profit_truth:      IN_PROGRESS (market-blocked: roundtrip_profitable=0, gap_best=4.10)
drift_per_pair:    RESOLVED (R20: bps fields, per_pair_signal_drift, propagated to rolling)
dashboard_default: RESOLVED (R20: default-on, --no-dashboard opt-out)
truth_probe_panel: RESOLVED (R20: Panel 10 truth-probe targets)
chain_directives:  RESOLVED (R20: stabilization_directive in all 4 coverage configs)
base_pricing:      NEW (R20: pancakeswap_v3 PRICE_OUTLIER on base, needs investigation)
slippage_variance: WATCH (R20: arb slippage 11.97 vs 8.06 median, needs monitoring)
```

## 7) Lead's Previous 10 Steps (R20)
step_01: DONE - Full NOTIONAL DRIFT per-pair bps. evidence: artifacts.py, rolling_store.py, run_summary drift_summary
step_02: DONE - Dashboard default-on. evidence: start.py --no-dashboard, 1685 tests
step_03: DONE - Panel 10 (Truth-Probe Targets). evidence: dashboard.html panel 10
step_04: DONE - Panel 7 enhanced (drift bps). evidence: dashboard.html per_pair_signal_drift
step_05: DONE - zksync stabilization directive. evidence: coverage_intent_zksync.yaml
step_06: DONE - mantle stabilization directive. evidence: coverage_intent_mantle.yaml
step_07: DONE - linea stabilization directive. evidence: coverage_intent_linea.yaml
step_08: DONE - scroll stabilization directive. evidence: coverage_intent_scroll.yaml
step_09: DONE - Tests (24). evidence: test_drift_summary.py, 1685 passed
step_10: DONE - CI + 6-chain scan. evidence: 8 runs, all gates PASS

## 8) Next Steps
1. Investigate pancakeswap_v3 pricing anomaly on base (WETH/USDC 2488 bps spread is PRICE_OUTLIER)
2. Fee=100 pool discovery on arbitrum_one (WBTC/USDC) — would save 8 bps → breakeven
3. Reduce arb slippage variance (11.97 bps latest vs 8.06 median — adaptive size or tighter filtering)
4. zksync drift: lower drift threshold or add pair-specific drift limits (40.4% rejection rate too high)
5. Camelot V3 integration for third DEX venue (arb_one diversity)

---
*Generated: 2026-03-13 R20*
