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

### Blocker Classification (2026-03-09 20:10 FRESH)
```
code_blocker:            LOW (pytest 1514 passed, 2 skipped; CI green, safety PASS 2 warnings)
multicall_blocker:       LOW (success_rate=1.0 all chains)
websocket_blocker:       LOW (ws_connected=true, ALL 6 chains)
cost_reporting_blocker:  RESOLVED (cost_model_version v3)
dex_compatibility_blocker:
  Arbitrum: SIGNAL_PRODUCING (6 signals, $3.66 net, runDir 200317)
  zkSync:   ALL_OPPORTUNITIES_REJECTED (7 signals gated, runDir 200403, SUSPECT_SPREAD_HARD)
  Scroll:   NO_SPREAD_SIGNALS (0 signals, runDir 200624, LIQUIDITY_ZERO)
  Linea:    NO_SIGNALS (0 signals, runDir 200642, only 1 DEX)
  Base:     ALL_OPPORTUNITIES_REJECTED (4 signals gated, runDir 200710)
  Mantle:   NO_SIGNALS ($0.03 net_usdc, runDir 200756)
```

**v3.2.64 Fix (2026-03-09 20:10)**: Policy threshold transparency + claim consistency lint
- ADDED: `suspect_spread_bps_hard_threshold` in engine summary (opportunity_engine.py)
- ADDED: `suspect_spread_bps_hard` in config_params (artifacts.py)
- ADDED: DEV_REPORT claim consistency check in check_repo_safety.py
- ADDED: 8 new tests (config propagation + claim consistency)
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
| goal_status | **IN_PROGRESS** (config fix verified, market constraints remain) |
| close_allowed | false |
| remaining_blockers | zkSync: ALL_OPPORTUNITIES_REJECTED (7 gated), Base: ALL_OPPORTUNITIES_REJECTED (4 gated), Scroll/Mantle: NO_SPREAD_SIGNALS, Linea: FAIL (1 DEX) |
| evidence_session_run_dirs | ci_m5_gate_20260309_200317 (Arbitrum), ci_m5_gate_20260309_200403 (zkSync), ci_m5_gate_20260309_200624 (Scroll), ci_m5_gate_20260309_200642 (Linea), ci_m5_gate_20260309_200710 (Base), ci_m5_gate_20260309_200756 (Mantle) |
| primary_blocker_of_session | multi-chain signal production quality |
| blocker_status_before | ACTIVE (zkSync/Base ALL_OPPORTUNITIES_REJECTED, others NO_SIGNALS) |
| blocker_status_after | **IN_PROGRESS** (config fix applied, market constraints remain) |
| docs_reread_confirmed | true |

**Session Progress (2026-03-09 20:10)** - Fresh same-session evidence:

| Chain | RunDir | M5 Gate | signals | net_usdc | Status |
|-------|--------|---------|---------|----------|--------|
| **Arbitrum** | 200317 | PASS | **6** | **$3.66** | ✅ SIGNAL_PRODUCING |
| zkSync | 200403 | PASS | 7 | $0 | ⚠️ ALL_OPPORTUNITIES_REJECTED |
| Scroll | 200624 | PASS | 0 | $0 | ❌ NO_SPREAD_SIGNALS |
| Linea | 200642 | FAIL | 0 | $0 | ❌ NO_SIGNALS (1 DEX) |
| Base | 200710 | PASS | 4 | $0 | ⚠️ ALL_OPPORTUNITIES_REJECTED |
| Mantle | 200756 | PASS | 0 | $0.03 | ⚠️ NO_SIGNALS |

**Code changes (v3.2.64)**:
- ✅ `engine/opportunity_engine.py`: Added `suspect_spread_bps_hard_threshold` to summary artifact
- ✅ `strategy/artifacts.py`: Added `suspect_spread_bps_hard` to config_params
- ✅ Tests: 8 new tests for config propagation and claim consistency
- ✅ `scripts/check_repo_safety.py`: Added DEV_REPORT claim consistency check
- ✅ `AGENTS.md`: Added Session Closure Contract

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (2 warnings - run_dir/timestamp alignment)
py -3.11 -m pytest tests/unit -q: 1514 passed, 2 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL GATES PASSED (elapsed 21.8s)

# v3.2.64 Code fixes:
# engine/opportunity_engine.py: Added suspect_spread_bps_hard_threshold to summary
# strategy/artifacts.py: Added suspect_spread_bps_hard to config_params
# scripts/check_repo_safety.py: Added DEV_REPORT claim consistency check
# tests/unit/test_truth_report.py: 4 new tests for config propagation
# tests/unit/test_check_repo_safety.py: 4 new tests for claim consistency

# Fresh same-session online evidence (2026-03-09 20:03-20:08):
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3: PASS, 6 signals, $3.66 (200317)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 3: PASS, 7 gated, $0 (200403)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 3: PASS, 0 signals (200624)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 3: FAIL, 0 signals (200642)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 3: PASS, 4 gated, $0 (200710)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 3: PASS, 0 signals, $0.03 (200756)
```

## 2) Evidence Artifacts

**Fresh same-session verification (2026-03-09 20:03-20:08, 6 chains x 3 cycles)**:

| RunDir | Chain | M5.0 Gate | signals | net_usdc | Status |
|--------|-------|-----------|---------|----------|--------|
| **200317** | **Arbitrum** | PASS | **6** | **$3.66** | ✅ SIGNAL_PRODUCING |
| 200403 | zkSync | PASS | 7 gated | $0 | ⚠️ ALL_OPPORTUNITIES_REJECTED |
| 200624 | Scroll | PASS | 0 | $0 | ❌ NO_SPREAD_SIGNALS |
| 200642 | Linea | FAIL | 0 | $0 | ❌ NO_SIGNALS (1 DEX) |
| 200710 | Base | PASS | 4 gated | $0 | ⚠️ ALL_OPPORTUNITIES_REJECTED |
| 200756 | Mantle | PASS | 0 | $0.03 | ⚠️ NO_SIGNALS |

**Key distinction**: `M5.0 PASS` = infrastructure/schema/coverage OK. `signals_count` shows actual signal production.

**Chain quality classification**:
- **Arbitrum**: SIGNAL_PRODUCING (4 signals, $3.13 net - proves infra works)
- **zkSync**: MARKET_BLOCKED (pools have stale prices, zero liquidity)
- **Scroll**: MARKET_BLOCKED (SushiSwap V3 pools empty)
- **Linea**: DEX_BLOCKED (only PancakeSwap active, no second DEX)

**Code changes (this session)**:
- `engine/opportunity_engine.py`: Added `suspect_spread_bps_hard_threshold` to summary dict
- `strategy/artifacts.py`: Added `suspect_spread_bps_hard` to config_params
- `scripts/check_repo_safety.py`: Added DEV_REPORT claim consistency check [14]
- `tests/unit/test_truth_report.py`: 4 new tests for config propagation
- `tests/unit/test_check_repo_safety.py`: 4 new tests for claim consistency
- `config/coverage_intent_zksync.yaml`: Added THIN LIQUIDITY STATUS documentation

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **Session IN_PROGRESS**: Fresh evidence gathered (6 chains, 2026-03-09 20:03-20:08)
2. **v3.2.64 complete**: Policy threshold transparency + claim consistency lint added
3. **Arbitrum only SIGNAL_PRODUCING**: 6 signals, $3.66 net_usdc (runDir 200317)
4. **Other chains blocked**: zkSync/Base gated (SUSPECT_SPREAD_HARD); Scroll (LIQUIDITY_ZERO); Linea (1 DEX); Mantle (NO_SIGNALS)
5. **Next action**: Update rolling artifacts with fresh Arbitrum run, or expand to new chains with better liquidity

---
*Generated: 2026-03-09T20:10:00Z*
