# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-10, Session 4 Round 4)
**Goal**: 2-hour multi-chain long scan to validate market visibility and signal recurrence; online M4 truth checks.

### Blocker Classification (current)
```
code_blocker:            RESOLVED (pytest 1597 passed, all gates PASS)
cross_dex_pairs_count:   RESOLVED (artifact key fix + safety assertion)
accepted_fail_model:     RESOLVED (--accepted-fail-chains in start.py)
placeholder_detection:   RESOLVED (header-aware scanner in check_repo_safety)
market_visibility:       RESOLVED (2h scan: 302 included signals, 5/6 chains PASS)
profit_truth:            IN_PROGRESS (total_profitable_roundtrips=0, profit_truth_available=false)
```

**IMPORTANT**: `infra_gate: PASS` != `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

## 0) Meta
timestamp_utc: 2026-03-10T16:18:14Z
rolling_provenance: 2026-03-10T16:18:14Z (arbitrum_one, ci_m5_gate_20260310_171754)
mode: ONLINE
test_count: 1597 passed, 2 skipped

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | 2h long scan + online M4 truth checks for market visibility |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | M4.2/M4.3 profit truth (total_profitable_roundtrips=0) |
| evidence_session_run_dirs | ci_m5_gate_20260310_{171754,171232,171441,171524,171642,171714} (2h long scan last runs) |
| primary_blocker_of_session | Market visibility (can the system see live recurring signals?) |
| blocker_status_before | UNKNOWN (no multi-hour evidence) |
| blocker_status_after | RESOLVED (115 runs, 302 included signals, 5 chains PASS, $275.20 paper net) |
| docs_reread_confirmed | true |

## 1) Changes This Session

1. **Placeholder detection hardened** (`scripts/check_repo_safety.py`): Rewrote `check_dev_report_placeholders()` to scan every table **data** row (after `|---|` separator), checking each cell against forbidden words. Prevents false positives on header cells. 4 regression tests added.
2. **cross_dex safety assertion** (`scripts/ci_m5_0_gate.py`): Added 3rd-tier safety net after fallback chain — re-reads truth_report if cross_dex_pairs_count is still 0 despite data existing.
3. **2-hour long scan completed**: 115 runs × 6 chains, $275.20 total paper net, 302 included signals. Result: market visibility confirmed on 5/6 chains.
4. **Online M4 gates**: All 4 candidate chains (Arbitrum, Base, Mantle, Linea) pass online M4 gate with exit code 0.

## 2) Evidence Artifacts

### 2h Long Scan Summary (2026-03-10)

| Metric | Value |
|--------|-------|
| wall_seconds | 7205.3 |
| total_runs | 115 |
| total_pass | 96 |
| total_fail | 15 (all Scroll) |
| total_no_data | 4 (all Scroll) |
| total_included_signals | 302 |
| total_net_usdc | $275.20 (paper, ONE_LEG_DIAGNOSTIC) |
| total_profitable_roundtrips | 0 |
| profit_truth_available | false (all chains) |

**Per-Chain (last run of 2h scan)**:

| Chain | RunDir | M5 Gate | Status | Quality | Signals | Included | Net USD | Cross-DEX | Profit Source |
|-------|--------|---------|--------|---------|---------|----------|---------|-----------|---------------|
| **Arbitrum** | 171754 | PASS | PASS | WARN | 3 | 3 | $2.95 | 3 | ONE_LEG_DIAGNOSTIC |
| **Base** | 171232 | PASS | PASS | WARN | 8 | 7 | $4.39 | 15 | ONE_LEG_UNVERIFIED |
| **Mantle** | 171441 | PASS | PASS | WARN | 3 | 2 | $2.46 | 0 | ONE_LEG_DIAGNOSTIC |
| **zkSync** | 171524 | PASS | PASS | WARN | 4 | 1 | $0.71 | 10 | ONE_LEG_DIAGNOSTIC |
| **Linea** | 171714 | PASS | PASS | WARN | 3 | 2 | $2.78 | 0 | ONE_LEG_DIAGNOSTIC |
| Scroll | 171642 | PASS | FAIL | FAIL | 1 | 0 | $0.00 | 0 | ONE_LEG_DIAGNOSTIC |

**Per-Chain (2h aggregate)**:

| Chain | Runs | Pass | Included Signals | Net USD |
|-------|------|------|------------------|---------|
| **Arbitrum** | 20 | 20 | 66 | $61.64 |
| **Base** | 19 | 19 | 138 | $98.32 |
| **Mantle** | 19 | 19 | 38 | $46.75 |
| **zkSync** | 19 | 19 | 21 | $15.21 |
| **Linea** | 19 | 19 | 39 | $53.28 |
| Scroll | 19 | 0 | 0 | $0.00 |

**Online M4 Gate Results** (profile=profit):

| Chain | RunDir | M4 Gate | Exit Code |
|-------|--------|---------|-----------|
| Arbitrum | 171754 | PASS | 0 |
| Base | 171232 | PASS | 0 |
| Mantle | 171441 | PASS | 0 |
| Linea | 171714 | PASS | 0 |

**Result**: 5 PASS / 1 FAIL (Scroll, accepted-fail) / 0 INFRA_FAIL

**Chain quality classification**:
- **Arbitrum**: SIGNAL_PRODUCING (primary, rolling, cross-dex=3, WARN_PROFIT_DIAGNOSTIC)
- **Base**: SIGNAL_PRODUCING (cross-dex=15, WARN_TOP_PAIR_DOMINANCE_HIGH)
- **Mantle**: SIGNAL_PRODUCING (same-dex, WARN_LOW_SAMPLE, WARN_SAME_DEX_PRESENT)
- **zkSync**: SIGNAL_PRODUCING (cross-dex=10, WARN_LOW_SAMPLE, WARN_SAME_DEX_PRESENT)
- **Linea**: SIGNAL_PRODUCING (same-dex, WARN_LOW_SAMPLE, WARN_SAME_DEX_PRESENT)
- **Scroll**: INFRA_READY (single DEX, probe-only, accepted-fail, FAIL_ALL_EXCLUDED)

**Rolling canonical** (arbitrum_one):
- `data/runs/_rolling/run_summary_latest.json`

## 3) Honest Assessment

The 2h scan proved **market visibility and signal recurrence** on 5 chains, not profit truth:
- All signals are `ONE_LEG_DIAGNOSTIC` — single-side quote dislocation, not verified roundtrip arbitrage
- `total_profitable_roundtrips=0` and `profit_truth_available=false` on all chains
- This is a genuine advance from "data blindness" to "market visibility", but does NOT close M4.2/M4.3
- The $275.20 net is paper/diagnostic only — not executable profit proof

## 4) Next Steps

1. **M4.2/M4.3 profit truth**: Enable roundtrip evaluation to convert ONE_LEG_DIAGNOSTIC → verified profit
2. **Base pair diversification**: Reduce TOP_PAIR_DOMINANCE_HIGH
3. **Mantle/Linea/zkSync**: Address SAME_DEX_PRESENT and LOW_SAMPLE warnings
4. **Scroll**: Keep as probe-only/accepted-fail until second DEX venue appears

---
*Generated: 2026-03-10*