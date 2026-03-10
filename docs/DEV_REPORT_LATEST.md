# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-10, Session 4 Round 8)
**Goal**: Make dynamic sweep canonical truth-probe mechanism, integrate into truth_report artifacts.

### Blocker Classification (current)
```
code_blocker:            RESOLVED (pytest 1612 passed, all gates PASS)
cross_dex_pairs_count:   RESOLVED (artifact key fix + safety assertion)
accepted_fail_model:     RESOLVED (--accepted-fail-chains in start.py)
placeholder_detection:   RESOLVED (header-aware scanner in check_repo_safety)
market_visibility:       RESOLVED (2h scan: 302 included signals, 5/6 chains PASS)
roundtrip_evaluation:    RESOLVED (code bug fixed: evaluated_count=3)
profit_truth:            IN_PROGRESS (sweep best: -17.13 bps @ $50, was -13.44 bps last session)
sweep_canonical:         RESOLVED (CANONICAL_SWEEP_SIZES_USD, truth_report.roundtrip_summary.dynamic_sweep)
```

**IMPORTANT**: `infra_gate: PASS` != `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

## 0) Meta
timestamp_utc: 2026-03-10T16:17:34Z
rolling_provenance: 2026-03-10T16:17:34Z (arbitrum_one, ci_m5_gate_20260310_171714)
mode: ONLINE
test_count: 1612 passed, 2 skipped

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | Make dynamic sweep canonical truth-probe, integrate into truth_report artifacts |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | M4.2 economics: sweep_best_net_pnl_bps=-17.13 (target: >=0) |
| evidence_session_run_dirs | manual_run_20260310_205633 (sweep canonical: 3 routes x 7 sizes, truth_report.roundtrip_summary.dynamic_sweep present) |
| primary_blocker_of_session | Sweep was side-experiment not in truth_report → canonical mechanism with artifact integration |
| blocker_status_before | ACTIVE |
| blocker_status_after | RESOLVED |
| start_metric | sweep_best_net_pnl_bps=-13.44 (R7), sweep fields absent from roundtrip_summary |
| end_metric | sweep_best_net_pnl_bps=-17.13 @ $50 (R8), CANONICAL_SWEEP_SIZES_USD in roundtrip.py, dynamic_sweep in truth_report |
| delta | Sweep canonicalized + artifact-integrated. Market PnL -17.13 bps (conditions vary; mechanism is now canonical) |
| docs_reread_confirmed | true |

## 1) Changes This Session

1. **Canonical sweep constant** (`engine/roundtrip.py`): Added `CANONICAL_SWEEP_SIZES_USD = [50, 75, 100, 125, 150, 200, 250]` module-level constant. `sweep_roundtrip_sizes()` defaults to this when no explicit sizes passed. Header updated to mark sweep as canonical truth-probe mechanism.
2. **Sweep in truth_report artifacts** (`strategy/artifacts.py`): Extracted `_build_roundtrip_summary()` helper. Adds `dynamic_sweep` sub-block with `sweep_best_size_usd`, `sweep_best_net_pnl_bps`, `sweep_best_frontier_reason`, `frontier_pair`, `sizes_evaluated`, `routes_swept` to curated `roundtrip_summary`.
3. **Canonical import** (`strategy/jobs/run_scan_real.py`): Imports `CANONICAL_SWEEP_SIZES_USD` from `engine.roundtrip` as fallback sweep sizes.
4. **Contract tests**: 3 tests in `test_roundtrip.py` (TestCanonicalSweep: constant stability, default ladder, best-size selection). 3 tests in `test_truth_report.py` (TestBuildRoundtripSummary: sweep included when enabled, omitted when not, baseline fields always present). Total: 1612 passed.

## 2) Evidence Artifacts

### Fresh Scan Results (Arbitrum, manual_run_20260310_205633)

**truth_report.roundtrip_summary** (new canonical format):
```json
{
  "enabled": true,
  "evaluated_count": 3,
  "profitable_count": 0,
  "real_quote_count": 3,
  "best_net_pnl_bps": -29.96,
  "best_measured_spread_gap_bps": -12.8,
  "dynamic_sweep": {
    "enabled": true,
    "routes_swept": 3,
    "sizes_evaluated": 7,
    "sweep_best_size_usd": 50,
    "sweep_best_net_pnl_bps": -17.13,
    "sweep_best_frontier_reason": "BEST_NEG",
    "frontier_pair": "WBTC/USDC"
  }
}
```

### Before/After: Sweep Canonicalization

| Metric | R7 (side experiment) | R8 (canonical) | Status |
|--------|---------------------|----------------|--------|
| Sweep in truth_report.roundtrip_summary | **No** | **Yes** | RESOLVED |
| CANONICAL_SWEEP_SIZES_USD module constant | No | Yes | RESOLVED |
| Contract tests for sweep | 8 (mechanism only) | 14 (mechanism + artifact + canonical) | RESOLVED |
| test_count | 1606 | 1612 | +6 |
| sweep_best_net_pnl_bps (market-dependent) | -13.44 (WBTC/WETH) | -17.13 (WBTC/USDC) | Market conditions vary |
| Fixed baseline best_net_pnl_bps | -20.98 | -29.96 | Market conditions vary |

### Verification Gates

| Gate | Result |
|------|--------|
| pytest | 1612 passed, 2 skipped |
| ci_m5_0_gate --offline | PASS |
| ci_m4 --offline --profile profit | PASS |

## 3) Honest Assessment

**Sweep is now canonical and artifact-integrated.** The `roundtrip_summary` in every truth_report now contains a `dynamic_sweep` sub-block with all fields needed by gates and consumers. The sweep constant `CANONICAL_SWEEP_SIZES_USD` is bounded and deterministic.

**The economics gap remains** — sweep_best_net_pnl_bps = -17.13 @ $50 means all routes are still unprofitable. The primary blockers are:
1. **LP fees**: 30-35 bps roundtrip on fee=3000 pairs, 10 bps on fee=500.
2. **Slippage**: Even at $50, 8-24 bps depending on route.
3. **Spread evaporation**: Cross-DEX spread (60-80 bps raw) compresses to ~17-30 bps net after execution.

**M4.2 is NOT closed** — `profitable_count = 0`. Next steps should focus on expanding to fee=100 pairs or adding a third DEX.

## 4) Next Steps

1. **Fee=100 pair hunt**: Add WETH/USDC fee=100 and wstETH/WETH fee=100 — 2 bps roundtrip LP cost
2. **Camelot V3 integration**: Third DEX for more cross-venue opportunities
3. **Long scan with sweep**: Multi-hour scan to capture volatile periods where dislocations may exceed breakeven
4. **Lower sweep floor**: Test $25/$10 to see if PnL curve continues improving
5. **Slippage decomposition**: Investigate why QuoterV2 loses ~12 bps gross from observed spread

---
*Generated: 2026-03-10*