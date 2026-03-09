# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-09 evening)
**Goal**: Multi-chain quality stabilization - investigate zkSync/Scroll NO_DATA, tune configs

### Workflow Contract (enforced 2026-03-09)
> **Order**: 1) code/config/tests → 2) verification runs → 3) docs/artifacts update
> Any report generated before final reruns is non-canonical by process.

### Blocker Classification (2026-03-09 19:45 CORRECTED)
```
code_blocker:            LOW (pytest 1506 passed, CI green, safety PASS)
multicall_blocker:       LOW (success_rate=1.0 all chains)
websocket_blocker:       LOW (ws_connected=true, ALL 6 chains)
cost_reporting_blocker:  RESOLVED (cost_model_version v3)
dex_compatibility_blocker:
  zkSync:   MARKET_CONSTRAINED + POLICY_FIXED (thin liquidity + raised suspect_spread_bps_hard to 1000)
  Scroll:   MARKET_CONSTRAINED (pools LIQUIDITY_ZERO/NOTIONAL_DRIFT)
  Linea:    DEX_BLOCKED (only 1 DEX active, require_cross_dex fails)
  Arbitrum: SIGNAL_PRODUCING (4 signals, $3.13 net)
  Base:     SIGNAL_PRODUCING (historical)
  Mantle:   SIGNAL_PRODUCING (historical)
```

**v3.2.63 Fix (2026-03-09 19:45)**: `suspect_spread_bps_hard` config propagation
- FIXED: `engine/opportunity_engine.py` now accepts `max_gross_spread_bps` parameter
- FIXED: `strategy/jobs/run_scan_real.py` passes `config.get("suspect_spread_bps_hard")` to `evaluate_quotes()`
- CONFIG: zkSync `suspect_spread_bps_hard: 1000` (was 800, default was 500 - too aggressive)
- CONFIG: Scroll `suspect_spread_bps_hard: 1000` + market constraint documentation
- RESULT: zkSync now gates 8 opportunities (was over-rejecting before), 26 legitimate SUSPECT_SPREAD_HARD rejects remain (>10% spreads = bad data/stale prices)

**CORRECTED**: Previous report incorrectly classified zkSync as purely "MARKET_BLOCKED". Truth: both market constraint (thin liquidity) AND policy was too aggressive (500 bps default). Now fixed.

**Cost-aware reporting summary (2026-03-09 v3.2.58)**:
1. `strategy/artifacts.py`: Extended `_compute_execution_pnl` with canonical cost formula:
   - `cost_model_version: "paper_gas_slippage_l1_v3"` (upgraded from v2)
   - **FIXED**: `slippage_usd = paper_size_usd * slippage_bps / 10000 * num_signals` (position-based)
   - **FIXED**: `gas_usd = gas_usd_estimate * num_signals` (per-signal aggregation)
   - Total cost invariant: `total_cost_usd = gas_usd + slippage_usd + l1_cost_usd`
2. `strategy/jobs/run_scan_real.py`: Same-DEX fallback artifact reconciliation
   - Added `same_dex_fallback_mode`, `spread_signals_count`, `same_dex_signals_active`
   - Prevents artifact mismatch when signals > 0 but total_opportunities = 0
3. `strategy/quotes.py`: Per-chain SUSPECT_LIQUIDITY threshold
   - New config keys: `quoter_max_gas_estimate`, `quoter_max_ticks_crossed`
   - zkSync: 1M gas threshold (default 500k too aggressive)
4. Config freezes: Linea frozen, zkSync/Scroll relaxed gas thresholds
5. `tests/unit/test_same_dex_policy.py`: 6 new same-DEX fallback artifact tests

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

### Multi-chain Coverage Results (2026-03-09 18:57-18:59, --cycles 3, session evidence)
| Chain | RunDir | M5.0 Infra | signals | net_usdc | Status | Root Cause |
|-------|--------|------------|---------|----------|--------|------------|
| **Arbitrum** | 185759 | PASS | **4** | **$3.13** | ✅ SIGNAL_PRODUCING | Baseline |
| zkSync | 185400 | PASS | 0 | $0 | ❌ MARKET_BLOCKED | PRICE_SANITY, LIQUIDITY_ZERO, NOTIONAL_DRIFT |
| Scroll | 185703 | PASS | 0 | $0 | ❌ MARKET_BLOCKED | LIQUIDITY_ZERO (all SushiSwap pools empty) |
| Linea | 185726 | PASS | 1 | $0 | ⚠️ DEX_BLOCKED | Only 1 DEX (PancakeSwap), no cross-DEX |

**Investigation conclusion**: zkSync/Scroll are **MARKET_BLOCKED** - infrastructure works perfectly (quotes flow, multicall success), but on-chain liquidity doesn't support arbitrage. Config thresholds relaxed 30x with no improvement.

**Session fixes applied (2026-03-09 12:30)**:
1. **WebSocket endpoint resolution FIX**: ci_m5_0_gate.py now reads chain_id from config for correct WS host
2. **strategy/infra.py FIX**: Clears stale WS env vars, uses OVERWRITE not setdefault; extracts provider_id_ws from URL
3. **zkSync quoter_v2 FIX**: Added `use_quoter_v2: true` to coverage_intent_zksync.yaml
4. **Linea/Scroll same-DEX FIX**: Set `require_cross_dex: false` (MIXED_SOURCE workaround)
5. **ALL_OPPORTUNITIES_REJECTED FIX**: Triggers when total_opps > 0 regardless of profitable_count
6. **provider_id_ws FIX**: Extracts provider from WS URL when resolver returns "unknown"
7. **WS host validation**: Added validate_chain_rpc_consistency() in ci_m5_0_gate.py

## 0) Meta
timestamp_utc: 2026-03-09T19:50:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain quality investigation + config fix verification)
test_count: 1506 passed, 2 skipped

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | Multi-chain quality stabilization (zkSync/Scroll/Linea signal production) |
| goal_status | **IN_PROGRESS** (config fix applied, need fresh verification) |
| close_allowed | false |
| remaining_blockers | zkSync: MARKET_CONSTRAINED (thin liquidity, 26/34 opps >10% spread), Scroll: MARKET_CONSTRAINED, Linea: DEX_BLOCKED |
| evidence_session_run_dirs | ci_m5_gate_20260309_194223 (zkSync fresh), ci_m5_gate_20260309_185400 (zkSync stale), ci_m5_gate_20260309_185703 (Scroll), ci_m5_gate_20260309_185726 (Linea) |
| primary_blocker_of_session | suspect_spread_bps_hard config propagation |
| blocker_status_before | ACTIVE (500 bps default too aggressive for L2s) |
| blocker_status_after | **FIXED** (config now propagates to OpportunityEngine) |
| docs_reread_confirmed | true |

**Session Correction (2026-03-09 19:45)**:
- ❌ Previous report incorrectly claimed `goal_status: REACHED` with `MARKET_BLOCKED`
- ✅ Corrected: zkSync was BOTH market-constrained AND policy-blocked
- ✅ Fixed `engine/opportunity_engine.py`: added `max_gross_spread_bps` parameter
- ✅ Fixed `strategy/jobs/run_scan_real.py`: passes `suspect_spread_bps_hard` from config
- ✅ Updated `AGENTS.md`: Added Session Closure Contract with hard rules
- ⏳ Remaining: zkSync thin liquidity is genuine market constraint (26/34 opps have >10% spread)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest tests/unit -q: 1506 passed, 2 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL GATES PASSED (elapsed 20.8s)

# Config tuning applied:
# zkSync: quoter_max_gas_estimate 1M→30M, quoter_max_ticks_crossed: 50
# Scroll: quoter_max_gas_estimate 800k→3M, quoter_max_ticks_crossed: 40
# Linea:  quoter_max_gas_estimate 800k→3M, quoter_max_ticks_crossed: 30

# cost_model_version aligned:
# strategy/artifacts.py: v2 → v3
# tests/unit/test_execution_pnl_golden.py: 2 assertions fixed
# tests/unit/test_truth_report.py: 1 assertion fixed

# Online verification runs (fresh evidence):
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3: PASS, 4 signals, $3.13 (185759)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 3: M5.0 PASS, 0 signals (185400)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 3: M5.0 PASS, 0 signals (185703)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 3: M5.0 PASS, 1 signal (185726)
```

## 2) Evidence Artifacts

**Fresh verification (2026-03-09 18:57-18:59, 4 chains x 3 cycles)**:

| RunDir | Chain | M5.0 Infra | signals | net_usdc | Root Cause |
|--------|-------|------------|---------|----------|------------|
| **185759** | **Arbitrum** | PASS | **4** | **$3.13** | Baseline (working) |
| 185400 | zkSync | PASS | 0 | $0 | PRICE_SANITY, LIQUIDITY_ZERO |
| 185703 | Scroll | PASS | 0 | $0 | LIQUIDITY_ZERO (all pools) |
| 185726 | Linea | PASS | 1 | $0 | Only 1 DEX (no cross-DEX) |

**Key distinction**: `M5.0 PASS` = infrastructure/schema/coverage OK. `signals_count` shows actual signal production.

**Chain quality classification**:
- **Arbitrum**: SIGNAL_PRODUCING (4 signals, $3.13 net - proves infra works)
- **zkSync**: MARKET_BLOCKED (pools have stale prices, zero liquidity)
- **Scroll**: MARKET_BLOCKED (SushiSwap V3 pools empty)
- **Linea**: DEX_BLOCKED (only PancakeSwap active, no second DEX)

**Code changes (this session)**:
- `config/coverage_intent_zksync.yaml`: `quoter_max_gas_estimate: 30000000`, `quoter_max_ticks_crossed: 50`
- `config/coverage_intent_scroll.yaml`: `quoter_max_gas_estimate: 3000000`, `quoter_max_ticks_crossed: 40`
- `config/coverage_intent_linea.yaml`: `quoter_max_gas_estimate: 3000000`, `quoter_max_ticks_crossed: 30`
- `strategy/artifacts.py`: `cost_model_version` v2 → v3
- `tests/unit/test_execution_pnl_golden.py`: 2 assertions updated for v3
- `tests/unit/test_truth_report.py`: 1 assertion updated for v3
- `docs/status/Status_M5_0.md`: Updated with investigation findings

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **Session complete**: multi-chain quality investigation done; zkSync/Scroll classified as MARKET_BLOCKED
2. **Path forward**: Accept 3-chain coverage (Arbitrum, Base, Mantle) until L2 DEX ecosystems mature
3. **Linea**: Consider adding second DEX (SushiSwap V3 or PancakeSwap compliant) for cross-DEX capability
4. **zkSync/Scroll**: Monitor monthly for liquidity improvements; re-test when TVL increases

---
*Generated: 2026-03-09T19:00:00Z*
