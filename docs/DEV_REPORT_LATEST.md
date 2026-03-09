# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-09)
**Goal**: Cost-aware reporting standardization + L1 cost model verification for L2 chains

### Workflow Contract (enforced 2026-03-09)
> **Order**: 1) code/config/tests → 2) verification runs → 3) docs/artifacts update
> Any report generated before final reruns is non-canonical by process.

### Blocker Classification (2026-03-09 14:15)
```
code_blocker: LOW (pytest 1482 passed, CI green, safety PASS)
multicall_blocker: LOW (success_rate=1.0 all chains)
websocket_blocker: LOW (ws_connected=true, ALL 6 chains chain-correct hosts)
cost_reporting_blocker: RESOLVED (theoretical_net_profit block added, schema v1.2)
dex_compatibility_blocker: MED (zkSync/Linea/Scroll same-DEX fallback active)
```

**Cost-aware reporting summary (2026-03-09 v3.2.57)**:
1. `strategy/artifacts.py`: Extended `_compute_execution_pnl` with full cost breakdown:
   - `cost_model_version: "paper_gas_slippage_l1_v2"` (upgraded from v1)
   - `slippage_usd`, `l1_cost_usd`, `total_cost_usd` fields added
   - Total cost invariant: `total_cost_usd = gas_usd + slippage_usd + l1_cost_usd`
2. `scripts/generate_daily_report.py`: Added mandatory `theoretical_net_profit` block
   - Schema bumped from v1.1 to v1.2
   - `mode: "paper_simulated"` + disclaimer
3. `docs/DEV_REPORT_CANONICAL_UA.md`: Added section 4.1 Theoretical Net Profit rules
4. `tests/unit/test_execution_pnl_golden.py`: Added 6 new cost breakdown invariant tests

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

### Multi-chain Coverage Results (2026-03-09 12:45 --cycles 3)
| Chain | RunDir | Infra Gate | run_summary | signals | quotes | opps | no_data_reason | WS Host |
|-------|--------|------------|-------------|---------|--------|------|----------------|---------|
| Arbitrum | 123641 | PASS | **PASS** | 9 | 40/122 | 78 | — | arb-mainnet.g.alchemy.com |
| Base | 123829 | PASS | **PASS** | 1 | 34/54 | 47 | — | base-mainnet.g.alchemy.com |
| Mantle | 124009 | PASS | **PASS** | 3 | 24/50 | 9 | — | mantle-mainnet.g.alchemy.com |
| zkSync | 124137 | PASS | NO_DATA | 0 | 31/49 | 22 | ALL_OPPORTUNITIES_REJECTED | zksync-mainnet.g.alchemy.com |
| Linea | 124320 | PASS | NO_DATA | 0 | 29/30 | 17 | ALL_OPPORTUNITIES_REJECTED | linea-mainnet.g.alchemy.com |
| Scroll | 124403 | PASS | NO_DATA | 0 | 10/24 | 6 | ALL_OPPORTUNITIES_REJECTED | scroll-mainnet.g.alchemy.com |

**Session fixes applied (2026-03-09 12:30)**:
1. **WebSocket endpoint resolution FIX**: ci_m5_0_gate.py now reads chain_id from config for correct WS host
2. **strategy/infra.py FIX**: Clears stale WS env vars, uses OVERWRITE not setdefault; extracts provider_id_ws from URL
3. **zkSync quoter_v2 FIX**: Added `use_quoter_v2: true` to coverage_intent_zksync.yaml
4. **Linea/Scroll same-DEX FIX**: Set `require_cross_dex: false` (MIXED_SOURCE workaround)
5. **ALL_OPPORTUNITIES_REJECTED FIX**: Triggers when total_opps > 0 regardless of profitable_count
6. **provider_id_ws FIX**: Extracts provider from WS URL when resolver returns "unknown"
7. **WS host validation**: Added validate_chain_rpc_consistency() in ci_m5_0_gate.py

## 0) Meta
timestamp_utc: 2026-03-09T14:15:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (L2 chains verification, zkSync/Linea/Scroll x 3 cycles)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest tests/unit -q: 1482 passed, 2 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 3: PASS (runDir 140901)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 3: PASS (runDir 141019, M4 PASS)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 3: PASS (runDir 141050)
```

## 2) Evidence Artifacts

**Fresh verification (2026-03-09 14:10, L2 chains x 3 cycles)**:
- `ci_m5_gate_20260309_140901` (zkSync) - **M5.0 PASS**, quotes=30, pairs=9, l1_cost_usd=0 ✅
- `ci_m5_gate_20260309_141019` (Linea) - **M5.0 PASS**, M4 PASS, quotes=12, pairs=7, l1_cost_usd=$0.003 ✅
- `ci_m5_gate_20260309_141050` (Scroll) - **M5.0 PASS**, quotes=7, pairs=5, l1_cost_usd=0 ✅

**theoretical_net_profit sample** (Linea run):
```json
{
  "gross_pnl_usdc": 3.2086,
  "gas_usd": 0.05,
  "slippage_bps": 5,
  "slippage_usd": 0.001604,
  "l1_cost_usd": 0.003,
  "total_cost_usd": 0.054604,
  "net_pnl_usdc": 3.1086,
  "cost_model_version": "paper_gas_slippage_l1_v2",
  "mode": "paper_simulated"
}
```

**Code changes (v3.2.57)**:
- `strategy/artifacts.py`: Extended `_compute_execution_pnl` with slippage_usd, l1_cost_usd, total_cost_usd
- `scripts/generate_daily_report.py`: Added `theoretical_net_profit` block, schema v1.2
- `docs/DEV_REPORT_CANONICAL_UA.md`: Added section 4.1 with cost-aware reporting rules
- `tests/unit/test_execution_pnl_golden.py`: Added 6 cost breakdown invariant tests
- `tests/unit/test_daily_report_aggregator.py`: Updated schema version expectation to v1.2
- `tests/unit/test_truth_report.py`: Updated cost_model_version expectation to v2

**Tests added (v3.2.56)**:
- `tests/unit/test_chain_quality_level.py`: TestEnhancedQualityRaised (5 tests for quality metrics path)

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **Run online coverage gates**: Execute with updated configs to verify MIXED_SOURCE/SUSPECT_SPREAD_HARD fixes
   ```
   py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 3
   py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 3
   py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 3
   ```
2. **QUALITY_RAISED path**: Track consecutive_non_nodata_cycles >= 3 with quality metrics (fragile_rate, unique_pairs, net_profit)
3. **SIGNAL_PRODUCING → QUALITY_RAISED**: Arbitrum/Base/Mantle ready for promotion once 3+ consecutive non-NO_DATA cycles achieved
4. **Linea/Scroll**: Marked as FALLBACK-ONLY (single quoter_v2 DEX) until second compatible DEX added

---
*Generated: 2026-03-09T12:45:00Z*
