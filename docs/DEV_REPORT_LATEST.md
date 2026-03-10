# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-10, Session 4 Round 5)
**Goal**: Audit and fix the root cause of `total_profitable_roundtrips=0`. Convert market visibility into roundtrip evaluation truth.

### Blocker Classification (current)
```
code_blocker:            RESOLVED (pytest 1598 passed, all gates PASS)
cross_dex_pairs_count:   RESOLVED (artifact key fix + safety assertion)
accepted_fail_model:     RESOLVED (--accepted-fail-chains in start.py)
placeholder_detection:   RESOLVED (header-aware scanner in check_repo_safety)
market_visibility:       RESOLVED (2h scan: 302 included signals, 5/6 chains PASS)
roundtrip_evaluation:    RESOLVED (code bug fixed: run_scan_real.py overwrite + start.py data path)
profit_truth:            IN_PROGRESS (evaluated_count=2, profitable_count=0, best_net=-66.6 bps)
```

**IMPORTANT**: `infra_gate: PASS` != `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

## 0) Meta
timestamp_utc: 2026-03-10T16:17:34Z
rolling_provenance: 2026-03-10T16:17:34Z (arbitrum_one, ci_m5_gate_20260310_171754)
mode: ONLINE
test_count: 1598 passed, 2 skipped

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | Audit and fix root cause of total_profitable_roundtrips=0 |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | M4.2 economics: roundtrip slippage exceeds spread (best_net=-66.6 bps) |
| evidence_session_run_dirs | manual_run_20260310_190854 (fresh scan with fix, evaluated_count=2), ci_m5_gate_20260310_171714 (rolling canonical) |
| primary_blocker_of_session | Roundtrip evaluation broken (evaluated_count=0 always) |
| blocker_status_before | ACTIVE (code bug: paper viability overwritten by measured slippage) |
| blocker_status_after | RESOLVED (fix applied, fresh scan shows evaluated_count=2) |
| docs_reread_confirmed | true |

## 1) Changes This Session

1. **Root cause audit** (`strategy/jobs/run_scan_real.py`): Found and fixed critical bug at line 481 where paper-based viability gate fields (`min_required_spread_bps`, `spread_minus_required_bps`, `is_roundtrip_viable`) were overwritten by measured-slippage values from spread_signal. Paper slippage=5 bps (viable), measured=50-120 bps (never viable), so ALL opportunities were rejected by roundtrip evaluator.
2. **Paper/measured separation** (`strategy/jobs/run_scan_real.py`): Stopped overwriting paper gate fields. Now stores measured values as separate `measured_min_required_spread_bps`, `measured_spread_minus_required_bps`, `measured_is_roundtrip_viable` for RCA.
3. **Start.py data path fix** (`start.py`): Fixed `roundtrip_summary` extraction from `metrics.roundtrip` (was reading wrong key). Added `roundtrip_evaluated_total`, `best_roundtrip_net_bps` tracking. Schema bumped to v1.2.
4. **Tests**: Added `test_roundtrip_from_metrics_roundtrip`. Updated both `_make_per_chain` helpers and `test_summary_profitable_roundtrips` with new fields. 1598 tests pass.

## 2) Evidence Artifacts

### Roundtrip Audit (Arbitrum, fresh scan with fix)

| Metric | Value |
|--------|-------|
| runDir | manual_run_20260310_190854 |
| evaluated_count | 2 (was 0 before fix) |
| profitable_count | 0 |
| best_net_pnl_bps | -66.65 |
| l1_cost_wei | 15701570000 |
| gas_price_wei_used | 20002000 |

### Roundtrip Economics Decomposition (Arbitrum)

| Pair | Route | Spread bps | Paper Viable | Measured Viable | Eff. Slippage bps | Measured Min Req bps |
|------|-------|-----------|-------|---------|----------|----------|
| WETH/USDT | sushi_v3->uni_v3 | 56.3 | True | False | 116.9 | 132.9 |
| WBTC/USDC | sushi_v3->uni_v3 | 30.3 | True | False | n/a | n/a |
| WBTC/WETH | sushi_v3->uni_v3 | 39.7 | False | False | n/a | n/a |

**Root cause**: Measured QuoterV2 slippage (117 bps) dwarfs captured spread (56 bps). Paper min_required ~22 bps allows evaluation, but real roundtrip economics yield -66.6 bps net. This is MARKET reality, not a code bug.

### 2h Long Scan Summary (from Round 4, pre-fix)

| Metric | Value |
|--------|-------|
| total_runs | 115 |
| total_pass | 96 |
| total_included_signals | 302 |
| total_net_usdc | $275.20 (paper, ONE_LEG_DIAGNOSTIC) |
| total_profitable_roundtrips | 0 |

### Verification Gates (post-fix)

| Gate | Result |
|------|--------|
| pytest | 1598 passed, 2 skipped |
| check_repo_safety | PASS (0 warnings) |
| ci_full_pipeline --mode ci | ALL PASS |
| ci_m4 --offline --profile profit --strict | PASS |
| ci_m4 --online Arbitrum 171754 | PASS |
| ci_m4 --online Base 171232 | PASS |
| ci_m4 --online Mantle 171441 | PASS |
| ci_m4 --online Linea 171714 | PASS |

### Chain quality classification (unchanged from Round 4)
- **Arbitrum**: SIGNAL_PRODUCING (primary, rolling, cross-dex=3, WARN_PROFIT_DIAGNOSTIC)
- **Base**: SIGNAL_PRODUCING (cross-dex=15, WARN_TOP_PAIR_DOMINANCE_HIGH)
- **Mantle**: SIGNAL_PRODUCING (same-dex, WARN_LOW_SAMPLE, WARN_SAME_DEX_PRESENT)
- **zkSync**: SIGNAL_PRODUCING (cross-dex=10, WARN_LOW_SAMPLE, WARN_SAME_DEX_PRESENT)
- **Linea**: SIGNAL_PRODUCING (same-dex, WARN_LOW_SAMPLE, WARN_SAME_DEX_PRESENT)
- **Scroll**: INFRA_READY (single DEX, probe-only, accepted-fail, FAIL_ALL_EXCLUDED)

**Rolling canonical** (arbitrum_one):
- `data/runs/_rolling/run_summary_latest.json`

## 3) Honest Assessment

**Two code bugs fixed this session:**
1. `run_scan_real.py:481` overwrote paper-based viability with measured-slippage values, preventing ANY roundtrip evaluation
2. `start.py:228` read wrong key for roundtrip data, preventing aggregation in long scan summary

**After fix**: `evaluated_count=2` (was 0). Roundtrip pipeline now correctly evaluates candidates.

**New primary blocker**: Economics. Current recurring spreads (30-60 bps) cannot cover measured QuoterV2 slippage (50-120 bps). `best_net_pnl_bps=-66.6` shows a ~67 bps gap between spread captured and roundtrip cost.

**What this means**: The system correctly sees market dislocations and correctly evaluates whether they form profitable roundtrips. They currently don't. This is a legitimate M4.2 economics blocker, not a code defect.

## 4) Next Steps

1. **New long scan with fix**: Run 2h multi-chain scan to collect fresh `roundtrip_evaluated_total` and `best_roundtrip_net_bps` evidence
2. **Spread-slippage gap analysis**: Track `best_net_pnl_bps` over time; even if negative, improving trend indicates progress toward M4.2
3. **Base pair diversification**: Reduce TOP_PAIR_DOMINANCE_HIGH via config tuning
4. **Mantle/Linea/zkSync**: Address SAME_DEX/LOW_SAMPLE via fee-tier and venue expansion
5. **Scroll**: Keep probe-only/accepted-fail until second DEX venue appears

---
*Generated: 2026-03-10*