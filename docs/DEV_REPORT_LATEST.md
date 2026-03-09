# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-09)
**Goal**: Add Transport Health Contract, run full 6-chain verification, update docs with fresh evidence

### Workflow Contract (enforced 2026-03-09)
> **Order**: 1) code/config/tests → 2) verification runs → 3) docs/artifacts update
> Any report generated before final reruns is non-canonical by process.

### Blocker Classification (2026-03-09 v3.2.53)
```
code_blocker: LOW (pytest 1463 passed, CI green, safety PASS)
multicall_blocker: LOW (success_rate=1.0 all chains, 4 RPC calls)
websocket_blocker: LOW (ws_connected=true, no fallback, lag <200ms all chains)
data_collection_blocker: MEDIUM (zkSync/Linea 96-100%, others 42-69%)
market_window_blocker: HIGH (3/6 chains NO_DATA despite healthy transport)
```

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

### Multi-chain Coverage Results (2026-03-09 v3.2.53 --cycles 2)
| Chain | RunDir | Infra Gate | run_summary | chain_quality_level | signals | quotes | fetch% | Notes |
|-------|--------|------------|-------------|---------------------|---------|--------|--------|-------|
| Arbitrum | `104851` | PASS | **PASS** | SIGNAL_PRODUCING | 9 | 42/101 | 42% | Best signals |
| Base | `104548` | PASS | **PASS** | SIGNAL_PRODUCING | 2 | 29/42 | 69% | ⚠️ |
| Mantle | `104720` | PASS | **PASS** | SIGNAL_PRODUCING | 3 | 24/50 | 48% | same-DEX fallback |
| Linea | `104751` | PASS | NO_DATA | INFRA_READY | 0 | 27/28 | 96% | ✅ EXCELLENT |
| zkSync | `104838` | PASS | NO_DATA | INFRA_READY | 0 | 49/49 | 100% | ✅ EXCELLENT |
| Scroll | `104818` | PASS | NO_DATA | INFRA_READY | 0 | 10/21 | 48% | improved from 24% |

**Session changes made (v3.2.53)**:
- **Transport Health Contract**: Added ws_connected, ws_fallback_to_http, ws_lag_ms, multicall.success_rate thresholds
- **Blocker Classification v3.2.53**: Reclassified code/multicall/websocket as LOW, data_collection as chain-specific
- **PAPER/SYN removed**: intent.txt Scroll (no token addresses in core_tokens.yaml)
- **Mantle Routing Directive**: Documented same-DEX fallback status for Mantle
- **Transport Health table**: Added to Status_M5_0.md (all 6 chains HEALTHY)

## 0) Meta
timestamp_utc: 2026-03-09T11:00:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (6-chain verification)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (2 expected warnings)
py -3.11 -m pytest tests/unit -q: 1463 passed, 1 skipped
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 2: PASS (runDir 104548)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 2: PASS (runDir 104720)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 2: PASS (runDir 104751, NO_DATA)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 2: PASS (runDir 104818, NO_DATA)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 2: PASS (runDir 104838, NO_DATA)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_arbitrum_one.yaml --cycles 2: PASS (runDir 104851)
```

## 2) Evidence Artifacts

**Fresh verification (2026-03-09 11:00, all 6 chains, 2 cycles)**:
- `ci_m5_gate_20260309_104851` (Arbitrum) - **PASS**, 9 signals, 42% fetch rate
- `ci_m5_gate_20260309_104548` (Base) - **PASS**, 2 signals, 69% fetch rate
- `ci_m5_gate_20260309_104720` (Mantle) - **PASS**, 3 signals, same-DEX fallback
- `ci_m5_gate_20260309_104751` (Linea) - PASS (NO_DATA), 0 signals, 96% fetch rate ✅
- `ci_m5_gate_20260309_104838` (zkSync) - PASS (NO_DATA), 0 signals, 100% fetch rate ✅
- `ci_m5_gate_20260309_104818` (Scroll) - PASS (NO_DATA), 0 signals, 48% fetch rate (improved)

**Session config changes**:
- `config/intent.txt`: Removed Scroll PAPER/SYN pairs (no token addresses)
- `docs/status/Status_M5_0.md`: Added Transport Health Contract, Transport Health table, Mantle Routing Directive

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **Mantle expansion**: Add FusionX V3 (uniswap_v3) to enable quoter_v2↔quoter_v2 cross-dex routes
2. **Arbitrum/Base fetch rate**: Investigate 42-69% rates (may be pool liquidity or RPC throttling)
3. **QUALITY_RAISED**: Track consecutive_non_nodata_cycles >= 3 to prove stable signal production
4. **M5.0 focus**: Market window remains the main blocker (3/6 NO_DATA despite healthy transport)

---
*Generated: 2026-03-09T11:00:00Z*
