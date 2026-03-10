# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-10, Session 4 Round 10)
**Goal**: Add dynamic measured economics decomposition + per-chain frontier ranking for all-chain coverage.

### Blocker Classification (current)
```
code_blocker:            RESOLVED (pytest 1627 passed, all gates PASS)
cross_dex_pairs_count:   RESOLVED (artifact key fix + safety assertion)
accepted_fail_model:     RESOLVED (--accepted-fail-chains in start.py)
placeholder_detection:   RESOLVED (header-aware scanner in check_repo_safety)
market_visibility:       RESOLVED (6-chain scan: 5/6 chains PASS, scroll accepted-fail)
roundtrip_evaluation:    RESOLVED (code bug fixed: evaluated_count=3)
profit_truth:            IN_PROGRESS (sweep best: -19.04 bps @ $50, gap_to_zero=19.04 bps)
sweep_canonical:         RESOLVED (CANONICAL_SWEEP_SIZES_USD, truth_report → run_summary → rolling)
rolling_frontier_blind:  RESOLVED (sweep metrics now propagate through full pipeline)
dynamic_economics:       RESOLVED (measured_gas/fee/slippage/total_cost_bps canonical in all artifacts)
frontier_ranking:        RESOLVED (per-chain ranking by gap_to_zero_bps in start.py summary)
```

**IMPORTANT**: `infra_gate: PASS` != `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

## 0) Meta
timestamp_utc: 2026-03-10T21:18:21Z
rolling_provenance: 2026-03-10T21:18:21Z (arbitrum_one, ci_m5_gate_20260310_221747)
mode: ONLINE
test_count: 1627 passed, 2 skipped

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | Add dynamic measured economics decomposition + per-chain frontier ranking |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | M4.2 economics: gap_to_zero_bps=19.04 (target: 0), profitable_count=0 |
| evidence_session_run_dirs | ci_m5_gate_20260310_220502 (arb, measured economics in run_summary + rolling), ci_m5_gate_20260310_220604 (base, ROUNDTRIP_PROFITABLE alert), ci_m5_gate_20260310_221747 (arb, latest rolling) |
| primary_blocker_of_session | Dynamic economics frontier — no cost decomposition, no per-chain ranking |
| blocker_status_before | ACTIVE |
| blocker_status_after | RESOLVED |
| start_metric | No measured_gas/fee/slippage/total_cost_bps. No frontier_curves. No per-chain ranking. Rolling: sweep fields exist but no cost breakdown. |
| end_metric | Full cost decomposition canonical: gas=1.63, fee=10.0, slippage=17.31, total=28.94 bps (arb WBTC/USDC). Rolling: median aggregates + frontier provenance. Per-chain ranking in start.py. |
| delta | 4 new measured cost fields through entire pipeline. Frontier curves in truth_report. Rolling median aggregates. Per-chain ranking by gap_to_zero_bps. +9 tests (1627 total). |
| docs_reread_confirmed | true |

## 1) Changes This Session

1. **Measured cost decomposition** (`engine/roundtrip.py`): Added `fee_bps` to `SizeSweepPoint`. Added `best_gas_bps`, `best_fee_bps`, `best_slippage_bps`, `best_total_cost_bps` to `SizeSweepResult`. Fee computed as `(leg1_fee + leg2_fee) / 100.0` (bps from fee tier).
2. **Sweep cost fields in scan** (`strategy/jobs/run_scan_real.py`): Propagated 4 cost fields (`best_gas_bps`, `best_fee_bps`, `best_slippage_bps`, `best_total_cost_bps`) into `stats["roundtrip"]["dynamic_sweep"]`.
3. **Truth report cost fields** (`strategy/artifacts.py`): Added `measured_gas_bps`, `measured_fee_bps`, `measured_slippage_bps`, `measured_total_cost_bps` to `_build_roundtrip_summary()` dynamic_sweep. Added `frontier_curves` (full size ladder per route).
4. **Run summary propagation** (`m4/fixtures.py`): Extended roundtrip dynamic_sweep to include 4 measured cost fields.
5. **Rolling aggregator** (`m4/rolling_store.py`): Per-run: `sweep_frontier_pair`, 4 measured cost fields. Quick stats: `sweep_median_gap_to_zero_bps` (p50), `sweep_median_net_pnl_bps` (p50), `frontier_pair_latest`, `frontier_chain_latest`.
6. **Per-chain frontier ranking** (`start.py`): Added `_compute_frontier_ranking()` — ranks chains by `gap_to_zero_bps` ascending. `frontier_ready` flag (gap < 30 bps). Added to `build_summary()` and `print_summary()`.
7. **Contract tests** (+9 tests): 2 in test_roundtrip.py (fee_bps in sweep point, cost decomposition at best point). 3 in test_truth_report.py (measured economics, frontier curves). 1 in test_rolling_store_provenance.py (measured cost fields in emit). 3 in test_start.py (ranking order, frontier_ready flag, ranking in summary). Total: 1627 passed.

## 2) Evidence Artifacts

### Fresh Online Scan (ci_m5_gate_20260310_220502, arbitrum_one)

**run_summary.metrics.roundtrip.dynamic_sweep** (measured economics verified):
```json
{
  "sweep_best_net_pnl_bps": -19.04,
  "sweep_best_size_usd": 50,
  "sweep_best_frontier_reason": "BEST_NEG",
  "frontier_pair": "WBTC/USDC",
  "gap_to_zero_bps": 19.04,
  "routes_swept": 3,
  "measured_gas_bps": 1.63,
  "measured_fee_bps": 10.0,
  "measured_slippage_bps": 17.31,
  "measured_total_cost_bps": 28.94
}
```

**Cost decomposition analysis (arb, WBTC/USDC, fee=500):**
- Gas: 1.63 bps (L2 gas negligible)
- LP fee: 10.0 bps (2×500 fee tier = 10 bps roundtrip)
- Slippage: 17.31 bps (QuoterV2 execution impact)
- Total cost: 28.94 bps
- Gross spread: ~10 bps → net = gross - cost = -19.04 bps

**m4_stability_agg.quick_stats** (rolling, with new fields):
```
sweep_runs_count: 2
sweep_best_pnl_bps_ever: -19.04
sweep_gap_to_zero_min: 19.04
sweep_median_gap_to_zero_bps: 19.62
sweep_median_net_pnl_bps: -19.62
frontier_pair_latest: WBTC/USDC
frontier_chain_latest: arbitrum_one
```

### 6-Chain Coverage Scan (in progress)

| Chain | Config | Status | Notes |
|-------|--------|--------|-------|
| arbitrum_one | real_minimal.yaml | PASS | Sweep: -19.04 bps WBTC/USDC |
| base | coverage_intent_base.yaml | PASS | ROUNDTRIP_PROFITABLE alert (2544 bps — suspect, WETH/CBBTC illiquid pool) |
| mantle | coverage_intent_mantle.yaml | PASS | Signals produced |
| zksync | coverage_intent_zksync.yaml | PASS | Signals produced |
| scroll | coverage_intent_scroll.yaml | FAIL (accepted) | 1 DEX only, no cross-dex |
| linea | coverage_intent_linea.yaml | PASS | 1 DEX only, no cross-dex |

### Before/After: Measured Economics Pipeline

| Metric | R9 (before) | R10 (after) | Status |
|--------|-------------|-------------|--------|
| measured_gas_bps | **Not tracked** | 1.63 (arb) | NEW |
| measured_fee_bps | **Not tracked** | 10.0 (arb) | NEW |
| measured_slippage_bps | **Not tracked** | 17.31 (arb) | NEW |
| measured_total_cost_bps | **Not tracked** | 28.94 (arb) | NEW |
| frontier_curves | **Not tracked** | Full size ladder in truth_report | NEW |
| rolling median aggregates | **Not tracked** | median_gap=19.62, median_pnl=-19.62 | NEW |
| frontier_pair_latest | **Not tracked** | WBTC/USDC | NEW |
| frontier_chain_latest | **Not tracked** | arbitrum_one | NEW |
| per-chain frontier ranking | **Not tracked** | In start.py summary | NEW |
| test_count | 1618 | 1627 | +9 |

### Verification Gates

| Gate | Result |
|------|--------|
| pytest | 1627 passed, 2 skipped |
| ci_full_pipeline --mode ci | ALL REQUIRED GATES PASSED |
| ci_m4 --offline --profile profit --strict | PASS |
| 6-chain coverage scan | 5/6 PASS, scroll accepted-fail |

## 3) Key Results

```
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: 0.8732
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.signals_count: 4
  metrics.total_net_usdc: 1.5323
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
  run_timestamp: 2026-03-10T21:05:44Z
  inputs.run_mode: REGISTRY_REAL
stability_agg:
  schema_version: m4:stability_agg:v2.0
  agg_status: PASS
  runs_since_timestamp.runs_count: 142
  quick_stats.unique_pairs: 13
  quick_stats.unique_routes: 6
  quick_stats.total_net_usdc: 995.88
  quick_stats.low_sample_rate: 0.0915
  quick_stats.sweep_runs_count: 2
  quick_stats.sweep_best_pnl_bps_ever: -19.04
  quick_stats.sweep_gap_to_zero_min: 19.04
  quick_stats.sweep_median_gap_to_zero_bps: 19.62
  quick_stats.sweep_median_net_pnl_bps: -19.62
  quick_stats.frontier_pair_latest: WBTC/USDC
  quick_stats.frontier_chain_latest: arbitrum_one
```

## 4) Honest Assessment

**Measured economics pipeline complete.** Every sweep now produces a full cost decomposition (gas, LP fee, slippage, total) that propagates through truth_report → run_summary → rolling → start.py summary. Per-chain frontier ranking allows identifying best truth-probe target.

**Cost structure analysis (arb WBTC/USDC fee=500):**
- **LP fee dominates** at 10.0 bps (2×500 fee tier). Fee=100 pairs would reduce this to 2 bps.
- **Slippage is largest component** at 17.31 bps. This is QuoterV2 execution impact at $50.
- **Gas is negligible** at 1.63 bps on Arbitrum.
- **Total cost** 28.94 bps vs gross spread ~10 bps → net = -19.04 bps.

**The economics gap remains** — gap_to_zero_bps = 19.04 bps. To close:
1. Lower LP fee (fee=100 pairs: 2 bps vs 10 bps)
2. Reduce slippage (lower size, better liquidity pools)
3. Larger gross spread (market volatility periods, more DEX venues)

**M4.2 NOT closed** — `profitable_count = 0` on Arbitrum. Base showed a spurious ROUNDTRIP_PROFITABLE (2544 bps from illiquid WETH/CBBTC pool — data quality issue, not real arb).

## 5) Contract Checks
status/reasons consistency: OK
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp, code_identity, no runs_by_code_sha)
runtime artifacts not committed: OK

## 6) Next Steps

1. **Fee=100 pair hunt**: WETH/USDC fee=100 and wstETH/WETH fee=100 — 2 bps roundtrip LP cost (down from 10 bps)
2. **Slippage reduction**: Lower sweep floor to $25/$10 to reduce QuoterV2 impact
3. **Camelot V3 integration**: Third DEX for more cross-venue opportunities
4. **Volatile period scanning**: Multi-hour scan during high-activity windows
5. **Base chain WETH/USDC investigation**: 3 DEXes (uniswap, sushiswap, pancakeswap) with rich cross-dex but needs anchor tuning

## 7) Lead's Previous 10 Steps: Execution Map
step_01: DONE — primary_blocker = dynamic economics frontier. KPI = measured cost decomposition. evidence: 4 cost fields in run_summary dynamic_sweep
step_02: DONE — Added measured_gas/fee/slippage/total_cost_bps to roundtrip.py, run_scan_real.py, artifacts.py. evidence: engine/roundtrip.py SizeSweepResult/SizeSweepPoint
step_03: DONE — Expanded sweep to full frontier curve. frontier_curves in truth_report. evidence: strategy/artifacts.py _build_roundtrip_summary
step_04: DONE — Rolling frontier aggregates: median_gap_to_zero_bps, median_net_pnl_bps, frontier_pair_latest, frontier_chain_latest. evidence: m4/rolling_store.py quick_stats
step_05: DONE — Per-chain ranking in start.py. _compute_frontier_ranking() ranks by gap_to_zero_bps. frontier_ready flag. evidence: start.py, tests/unit/test_start.py
step_06: DONE — Fixed baseline preserved (real_minimal.yaml paper_size_usd=150). evidence: config/real_minimal.yaml
step_07: DONE — Coverage configs unchanged (focus on frontier metrics). evidence: 6-chain scan: 5/6 PASS
step_08: DONE — Contract tests: +9 tests for dynamic economics propagation and chain ranking. evidence: 1627 passed
step_09: DONE — All gates + 6-chain scan run. evidence: ci_full_pipeline PASS, ci_m4 --strict PASS, 6-chain scan 5/6 PASS
step_10: DONE — DEV_REPORT + Status_M4.md updated with all-chain results, frontier rank, blocker metric before→after
step_09: DONE — All gates + 6-chain scan run. evidence: ci_full_pipeline PASS, ci_m4 --strict PASS, 6-chain scan 5/6 PASS
step_10: DONE — DEV_REPORT + Status_M4.md updated with all-chain results, frontier rank, blocker metric before→after

## 8) What I need from Lead now
question_1: Should gap_to_zero_bps threshold be added to M4 gate policy (e.g., WARN if gap > X bps)?
question_2: Fee=100 pairs first OR lower sweep floor ($25/$10) first for next session?
question_3: Should the spurious ROUNDTRIP_PROFITABLE on base (2544 bps, illiquid WETH/CBBTC) trigger a SUSPECT filter?

---
*Generated: 2026-03-10*