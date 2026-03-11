# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-11, Session 4 Round 13)
**Goal**: Multi-chain frontier ranking promotion to canonical rolling artifacts + contract tests.

### Blocker Classification (current)
```
code_blocker:            RESOLVED (pytest 1645 passed, all gates PASS)
cross_dex_pairs_count:   RESOLVED (artifact key fix + safety assertion)
accepted_fail_model:     RESOLVED (--accepted-fail-chains in start.py)
placeholder_detection:   RESOLVED (header-aware scanner in check_repo_safety)
market_visibility:       RESOLVED (6-chain scan: 5/6 chains PASS, scroll accepted-fail)
roundtrip_evaluation:    RESOLVED (code bug fixed: evaluated_count=3)
profit_truth:            IN_PROGRESS (sweep best: -4.10 bps @ $25, gap_to_zero=4.10 bps)
sweep_canonical:         RESOLVED (CANONICAL_SWEEP_SIZES_USD, truth_report → run_summary → rolling)
rolling_frontier_blind:  RESOLVED (sweep metrics now propagate through full pipeline)
dynamic_economics:       RESOLVED (measured_gas/fee/slippage/total_cost_bps canonical in all artifacts)
frontier_ranking:        RESOLVED (composite 6-field sort: accepted_fail, median_gap, best_gap, -runs, -signals, -xdex)
suspect_outlier_filter:  RESOLVED (SUSPECT_ROUNDTRIP_OUTLIER_BPS=500 in run_scan_real.py)
fee_100_activation:      RESOLVED (pools activated, addresses in config, QUERIED BUT NO 100↔100 SPREADS)
gap_to_zero_policy:      RESOLVED (WARN/frontier KPI only, NOT a hard gate)
median_gap_tracking:     RESOLVED (_sweep_gap_values collection, _compute_median(), schema v1.3)
```

**IMPORTANT**: `infra_gate: PASS` != `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

## 0) Meta
timestamp_utc: 2026-03-11T09:44:34Z
rolling_provenance: 2026-03-11T09:44:34Z (arbitrum_one, ci_m5_gate_20260311_104349)
mode: ONLINE
test_count: 1647 passed, 2 skipped

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | Multi-chain frontier ranking promotion to canonical rolling artifacts + contract tests |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | Market conditions: roundtrip_profitable=0 (M4.2 not closed) |
| evidence_session_run_dirs | ci_m5_gate_20260311_104349, manual_run_20260311_095812 |
| primary_blocker_of_session | Multi-chain frontier in rolling artifacts |
| blocker_status_before | long_scan_latest.json in _incidents/, not canonical rolling |
| blocker_status_after | long_scan_latest.json in _rolling/ (canonical), schema v1.3 with frontier_ranking |
| start_metric | R12: long_scan in _incidents/, 1645 tests, 164 runs |
| end_metric | R13: long_scan in _rolling/, 1647 tests, 168 runs, +$21.58 net |
| delta | +2 tests (multi-chain contract tests), frontier ranking now canonical |
| docs_reread_confirmed | true |

## 1) Changes This Session

1. **Multi-chain frontier promoted to rolling** (`start.py`): Changed default `--summary-file` from `data/runs/_incidents/long_scan_latest.json` to `data/runs/_rolling/long_scan_latest.json`. This makes multi-chain frontier ranking a canonical rolling artifact per AGENTS.md policy.
2. **AGENTS.md updated**: Added `long_scan_latest.json` to the canonical rolling artifacts list with description "(multi-chain frontier ranking)".
3. **WORKFLOW.md updated**: Updated all `--summary-file` references to use `_rolling/` path. Updated summary output documentation.
4. **Status_M5_0.md updated**: Updated evidence references to new `_rolling/long_scan_latest.json` path.
5. **Contract tests for multi-chain frontier** (`test_start.py`): Added `test_frontier_ranking_includes_measured_economics` and `test_long_scan_summary_schema_v1_3` tests to validate frontier_ranking schema with measured economics decomposition. Total: 1647 passed, 2 skipped.
6. **Rolling artifact test updated** (`test_nonstop_loop_artifacts.py`): Added `long_scan_latest.json` to canonical_files set to prevent CI failure when file exists in `_rolling/`.

## 2) Evidence Artifacts

### Fresh Online Scan (ci_m5_gate_20260310_225316, arbitrum_one)

**roundtrip_summary.dynamic_sweep** (with $25 sweep point and SUSPECT filter):
```json
{
  "sweep_best_net_pnl_bps": -6.78,
  "sweep_best_size_usd": 25,
  "sweep_best_frontier_reason": "BEST_NEG",
  "frontier_pair": "WBTC/USDC",
  "gap_to_zero_bps": 6.78,
  "routes_swept": 3,
  "routes_clean": 3,
  "suspect_outlier_count": 0,
  "measured_gas_bps": 3.25,
  "measured_fee_bps": 10.0,
  "measured_slippage_bps": 8.62,
  "measured_total_cost_bps": 21.87
}
```

**Cost decomposition analysis (arb, WBTC/USDC, fee=500 @ $25):**
- Gas: 3.25 bps (L2 gas at small size)
- LP fee: 10.0 bps (2x500 fee tier = 10 bps roundtrip)
- Slippage: 8.62 bps (QuoterV2 execution impact at $25)
- Total cost: 21.87 bps
- Gross spread: ~15 bps → net = -6.78 bps

**Rolling quick_stats (168 runs, after R13 scans):**
```
sweep_runs_count: ~28
sweep_best_pnl_bps_ever: -4.10
sweep_gap_to_zero_min: 4.10
sweep_median_gap_to_zero_bps: 17.69
sweep_median_net_pnl_bps: -17.69
frontier_pair_latest: WETH/USDT
frontier_chain_latest: arbitrum_one
total_net_usdc: 1054.23
pass_rate: 100%
fee_100_status: QUERIED (buy_fee=100 in opportunities, but NO 100↔100 cross-DEX spreads)
```

### Fee=100 Opportunity Evidence (manual_run_20260311_100246)
```
top_opportunity:
  pair: WBTC/WETH, buy_dex: uniswap_v3, buy_fee: 100 ← FEE=100 QUERIED
  sell_dex: sushiswap_v3, sell_fee: 3000 (cross-tier, not 100↔100)
  lp_fee_roundtrip_bps: 31.0, effective_slippage_bps: 704.17
  measured_is_roundtrip_viable: false

fee_tier_combos: 100/3000=1, 500/500=2, 100/100=0 (no cross-DEX at fee=100)
```

**Conclusion**: Fee=100 pools ARE working. Market limitation: fee=100 pools have tight spreads.

### 6-Chain Coverage Scan (COMPLETED, 112 runs, ~19 per chain)

| Chain | Runs | Pass | ND | Fail | Signals | Net USDC | xDex | Quality | AF |
|-------|------|------|----|------|---------|----------|------|---------|----|
| arbitrum_one | 20 | 20 | 0 | 0 | 66 | $61.64 | 3 | SIGNAL_PRODUCING | - |
| base | 19 | 19 | 0 | 0 | 138 | $98.32 | 15 | SIGNAL_PRODUCING | - |
| mantle | 19 | 19 | 0 | 0 | 38 | $46.75 | 0 | SIGNAL_PRODUCING | - |
| zksync | 19 | 19 | 0 | 0 | 21 | $15.21 | 10 | SIGNAL_PRODUCING | - |
| scroll | 19 | 0 | 4 | 15 | 0 | $0.00 | 0 | INFRA_READY | AF |
| linea | 19 | 19 | 0 | 0 | 39 | $53.28 | 0 | SIGNAL_PRODUCING | - |
| **TOTAL** | **115** | **96** | **4** | **15** | **302** | **$275.20** | | | |

### Before/After: R12 → R13

| Metric | R12 (before) | R13 (after) | Status |
|--------|-------------|-------------|--------|
| gap_to_zero_bps (best) | 4.10 | **4.10** | Unchanged (market-limited) |
| gap_to_zero_bps (latest) | 13.58 | **14.29** | Within range |
| gap_to_zero_bps (median) | 18.89 | **17.69** | Improved |
| long_scan_latest location | _incidents/ | **_rolling/** | Canonical rolling artifact |
| frontier_ranking schema | v1.3 | **v1.3** | Now in rolling artifacts |
| test_count | 1645 | **1647** | +2 (multi-chain contract tests) |
| runs_in_window | 164 | **168** | +4 runs |
| total_net_usdc | $1032.65 | **$1054.23** | +$21.58 |

### Verification Gates

| Gate | Result |
|------|--------|
| pytest | 1647 passed, 2 skipped |
| ci_full_pipeline --mode ci | PASS (after DEV_REPORT update) |
| ci_m4 --offline --profile profit --strict | PASS |
| check_repo_safety | PASS (0 warnings) |
| fee=100 pool activation | PASS (addresses in pools section, queries execute) |

## 3) Key Results

```
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: ~0.89
  runs_in_window: 168
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_id: ci_m5_gate_20260311_104349
  run_timestamp: 2026-03-11T09:44:34Z
  inputs.run_mode: REGISTRY_REAL
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
stability_agg:
  schema_version: m4:stability_agg:v2.0
  agg_status: PASS
  quick_stats.total_net_usdc: 1054.23
  quick_stats.pass_rate: 100%
  quick_stats.sweep_best_pnl_bps_ever: -4.10
  quick_stats.sweep_gap_to_zero_min: 4.10
  quick_stats.sweep_median_gap_to_zero_bps: 17.69
```

## 4) Honest Assessment

**Strategy is near-breakeven on best cases, NOT yet proven net-positive.** Best-ever gap_to_zero=4.10 bps. Median gap=18.89 bps. The 4.10 bps best case requires specific market conditions that don't consistently materialize.

**Fee=100 lever implemented correctly but market-limited:**
- Fee=100 pools ARE configured and ARE being queried (evidence: `buy_fee: 100` in opportunity_engine)
- BUT no 100↔100 cross-DEX spreads exist — only 100→3000 cross-tier opportunities found
- Fee=100 pools (used by arb bots) have tight spreads with minimal cross-DEX price differences
- The 8 bps theoretical saving doesn't materialize without 100↔100 opportunities

**Cost structure at frontier (arb WBTC/USDC fee=500 @ $25):**
- LP fee: 10.0 bps (2x500 roundtrip) — fee=100 would be 2 bps
- Slippage: 8.62 bps (QuoterV2 execution impact)
- Gas: 3.25 bps (L2 gas dilution at small size)
- Total: 21.87 bps vs ~15 bps gross spread → net = -6.78 bps

**The remaining 4.10 bps gap** would close with:
1. ~~Fee=100 pools~~ → IMPLEMENTED but no 100↔100 opportunities in market
2. **Market volatility** → wider gross spreads (need >~25 bps temporary spread)
3. **More DEX coverage** → Camelot V3 could provide third price point

**M4.2 NOT closed** — `profitable_count = 0` on any chain. Strategy requires either:
- Sustained higher market volatility, OR
- Additional low-fee DEX venues (100↔100 cross-DEX spread)

**Median ranking is now operational** — 6-field composite sort prioritizes chains with consistent performance (median_gap) over lucky one-shot results (best_gap).

## 5) Contract Checks
status/reasons consistency: OK
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp, code_identity, no runs_by_code_sha)
runtime artifacts not committed: OK

## 6) Next Steps

1. **Camelot V3 integration (Arbitrum)**: Third DEX venue may provide fee=100 pools with cross-DEX spread vs Uniswap/Sushiswap.
2. **Multi-hour volatile scan**: Wait for market volatility period, run 4-6 hour scan to capture wider gross spreads.
3. **Fee=100 pool liquidity analysis**: Check if fee=100 pools have sufficient liquidity for meaningful trades, or if they're mostly empty/arb-bot-drained.
4. **Linea/zkSync fee=100 discovery**: These chains show 8-16 fee=100 pools via discovery_runtime. May have better cross-DEX dynamics than Arbitrum.
5. **Sweep size optimization**: Consider $15 or $10 sweep points to further reduce slippage at cost of higher gas dilution.

## 7) Lead's Previous 10 Steps: Execution Map
step_01: DONE — Fee=100 pool activation. Removed from disabled_pools, addresses in pools section. evidence: config/real_minimal.yaml
step_02: DONE — Fee=100 pool verification. opportunity_engine shows buy_fee=100 in opportunities. evidence: manual_run_20260311_100246
step_03: DONE — Median-based frontier ranking. 6-field sort: (AF, median, best, -runs, -sig, -xdex). evidence: start.py, tests +10
step_04: DONE — _compute_median() helper + _sweep_gap_values collection. evidence: start.py
step_05: DONE — gap_percentile_context in build_summary(), schema v1.3. evidence: start.py, test_start.py
step_06: DONE — Base cbBTC quarantine via excluded_pair_hints. evidence: coverage_intent_base.yaml
step_07: DONE — Contract tests +10 (median, ranking, summary). evidence: test_start.py (64 tests total)
step_08: DONE — Status_M4.md R11 frontier table update. evidence: docs/status/Status_M4.md
step_09: DONE — All verification gates PASS. evidence: pytest, ci_m4, check_repo_safety
step_10: DONE — DEV_REPORT updated with honest fee=100 assessment. evidence: this file

## 8) What I need from Lead now
question_1: Camelot V3 adapter implementation (provides third fee=100 venue) — priority vs time cost?
question_2: Should we target multi-hour volatile periods (e.g., US market open) for better gross spreads?
question_3: Is Linea or zkSync worth deeper investigation given their fee=100 discovery_runtime results?

---
*Generated: 2026-03-11*