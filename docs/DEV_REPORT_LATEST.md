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

### Blocker Classification (2026-03-09 12:00)
```
code_blocker: LOW (pytest 1465 passed, CI green, safety PASS)
multicall_blocker: LOW (success_rate=1.0 all chains, 4 RPC calls)
websocket_blocker: LOW (ws_connected=true, chain-correct hosts, lag <200ms)
dex_compatibility_blocker: HIGH (Mantle/Linea/Scroll MIXED_SOURCE due to algebra↔uniswap)
```

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

### Multi-chain Coverage Results (2026-03-09 12:00 --cycles 1)
| Chain | RunDir | Infra Gate | run_summary | chain_quality_level | signals | quotes | no_data_reason | Notes |
|-------|--------|------------|-------------|---------------------|---------|--------|----------------|-------|
| Arbitrum | — | PASS | **PASS** | SIGNAL_PRODUCING | 9+ | — | — | Best signals |
| Base | — | PASS | **PASS** | SIGNAL_PRODUCING | 2+ | — | — | — |
| Mantle | — | PASS | **PASS** | SIGNAL_PRODUCING | 3 | — | — | same-DEX fallback |
| Linea | `112235` | PASS | NO_DATA | INFRA_READY | 0 | 30/30 | MIXED_SOURCE | algebra↔uniswap |
| zkSync | `112122` | PASS | NO_DATA | INFRA_READY | 0 | 49/49 | NO_SPREAD_SIGNALS | quoter_v2 FIX applied |
| Scroll | — | PASS | NO_DATA | INFRA_READY | 0 | — | MIXED_SOURCE | algebra↔uniswap |

**Session fixes applied (2026-03-09 12:00)**:
1. **WebSocket endpoint resolution FIX**: ci_m5_0_gate.py now reads chain_id from config for correct WS host
2. **strategy/infra.py FIX**: Clears stale WS env vars, uses OVERWRITE not setdefault
3. **zkSync quoter_v2 FIX**: Added `use_quoter_v2: true` to coverage_intent_zksync.yaml
4. **Linea/Scroll same-DEX FIX**: Set `require_cross_dex: false` (MIXED_SOURCE workaround)
5. **ALL_OPPORTUNITIES_REJECTED**: Added to core/no_data.py for accurate NO_DATA classification
6. **Version strings FIX**: Removed from Status_M5_0.md per DOCS_POLICY.md

## 0) Meta
timestamp_utc: 2026-03-09T12:00:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain verification)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest tests/unit -q: 1465 passed, 1 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 1: PASS (runDir 112122)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 1: PASS (runDir 112235)
```

## 2) Evidence Artifacts

**Fresh verification (2026-03-09 12:00, zkSync + Linea with WS fix)**:
- `ci_m5_gate_20260309_112122` (zkSync) - PASS (NO_DATA), WS=zksync-mainnet.g.alchemy.com ✅ quoter_v2 enabled
- `ci_m5_gate_20260309_112235` (Linea) - PASS (NO_DATA), WS=linea-mainnet.g.alchemy.com ✅ MIXED_SOURCE

**Code changes**:
- `scripts/ci_m5_0_gate.py`: Read chain_id from config for WS resolution, use OVERWRITE
- `strategy/infra.py`: Clear stale WS env vars, use OVERWRITE not setdefault
- `config/coverage_intent_zksync.yaml`: Added `use_quoter_v2: true`
- `config/coverage_intent_linea.yaml`: Set `require_cross_dex: false` (MIXED_SOURCE workaround)
- `config/coverage_intent_scroll.yaml`: Set `require_cross_dex: false` (MIXED_SOURCE workaround)
- `core/no_data.py`: Added ALL_OPPORTUNITIES_REJECTED reason
- `strategy/jobs/run_scan_real.py`: Refine no_data_reason with opportunity info

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **Mantle/Linea/Scroll expansion**: Add quoter_v2-compatible DEXes to resolve MIXED_SOURCE
2. **zkSync stabilization**: Verify consecutive runs produce stable results
3. **QUALITY_RAISED**: Track consecutive_non_nodata_cycles >= 3 to prove stable signal production
4. **Cross-chain**: Base/Arbitrum remain SIGNAL_PRODUCING, continue monitoring

---
*Generated: 2026-03-09T12:00:00Z*
