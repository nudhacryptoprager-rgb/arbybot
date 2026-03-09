# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-09)
**Goal**: Fix WebSocket endpoint resolution, zkSync quoter_v2, Linea/Scroll MIXED_SOURCE, add ALL_OPPORTUNITIES_REJECTED reason

### Workflow Contract (enforced 2026-03-09)
> **Order**: 1) code/config/tests → 2) verification runs → 3) docs/artifacts update
> Any report generated before final reruns is non-canonical by process.

### Blocker Classification (2026-03-09 12:45)
```
code_blocker: LOW (pytest 1471 passed, CI green, safety PASS)
multicall_blocker: LOW (success_rate=1.0 all chains, 4 RPC calls)
websocket_blocker: LOW (ws_connected=true, ALL 6 chains chain-correct hosts, provider_id_ws=alchemy)
dex_compatibility_blocker: MED (zkSync/Linea/Scroll = ALL_OPPORTUNITIES_REJECTED, Arbitrum/Base/Mantle = SIGNAL_PRODUCING)
```

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
timestamp_utc: 2026-03-09T12:45:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain full verification, all 6 chains x 3 cycles)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest tests/unit -q: 1471 passed, 2 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_arbitrum_one.yaml --cycles 3: PASS (runDir 123641)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 3: PASS (runDir 123829)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 3: PASS (runDir 124009)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 3: PASS (runDir 124137)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 3: PASS (runDir 124320)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 3: PASS (runDir 124403)
```

## 2) Evidence Artifacts

**Fresh verification (2026-03-09 12:45, ALL 6 chains x 3 cycles)**:
- `ci_m5_gate_20260309_123641` (Arbitrum) - **PASS**, signals=9, opps=78, WS=arb-mainnet.g.alchemy.com ✅
- `ci_m5_gate_20260309_123829` (Base) - **PASS**, signals=1, opps=47, WS=base-mainnet.g.alchemy.com ✅
- `ci_m5_gate_20260309_124009` (Mantle) - **PASS**, signals=3, opps=9, WS=mantle-mainnet.g.alchemy.com ✅
- `ci_m5_gate_20260309_124137` (zkSync) - NO_DATA, signals=0, opps=22, no_data_reason=ALL_OPPORTUNITIES_REJECTED, WS=zksync-mainnet.g.alchemy.com ✅
- `ci_m5_gate_20260309_124320` (Linea) - NO_DATA, signals=0, opps=17, no_data_reason=ALL_OPPORTUNITIES_REJECTED, WS=linea-mainnet.g.alchemy.com ✅
- `ci_m5_gate_20260309_124403` (Scroll) - NO_DATA, signals=0, opps=6, no_data_reason=ALL_OPPORTUNITIES_REJECTED, WS=scroll-mainnet.g.alchemy.com ✅

**Code changes**:
- `scripts/ci_m5_0_gate.py`: Read chain_id from config for WS resolution; added WS host validation with validate_chain_rpc_consistency()
- `strategy/infra.py`: Clear stale WS env vars, use OVERWRITE not setdefault; extract provider_id_ws from URL when "unknown"
- `strategy/jobs/run_scan_real.py`: Fixed ALL_OPPORTUNITIES_REJECTED condition (triggers when total_opps > 0, not dependent on profitable_count)
- `core/no_data.py`: Deprecated profitable_accepted param; simplified compute_no_data_reason()
- `config/coverage_intent_zksync.yaml`: Added `use_quoter_v2: true`
- `config/coverage_intent_linea.yaml`: Set `require_cross_dex: false` (MIXED_SOURCE workaround)
- `config/coverage_intent_scroll.yaml`: Set `require_cross_dex: false` (MIXED_SOURCE workaround)

**Tests added**:
- `tests/unit/test_no_data_reason.py`: test_all_opportunities_rejected_with_profitable
- `tests/unit/test_truth_report.py`: TestNoDataReasonArtifactContract (3 tests)
- `tests/unit/test_providers.py`: TestMultiChainWSRegression (3 tests)

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **zkSync/Linea/Scroll**: All opps rejected (SUSPECT_SPREAD_HARD, MIXED_SOURCE) - investigate policy tuning
2. **SIGNAL_PRODUCING chains**: Arbitrum (9), Mantle (3), Base (1) - stable, continue monitoring
3. **QUALITY_RAISED**: Track consecutive_non_nodata_cycles >= 3 to prove stable signal production
4. **Cross-DEX expansion**: Add quoter_v2-compatible DEXes to resolve MIXED_SOURCE on Linea/Scroll

---
*Generated: 2026-03-09T12:45:00Z*
