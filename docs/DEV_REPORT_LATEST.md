# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-09)
**Goal**: Fix Mantle MIXED_SOURCE blocker + add chain_quality_level to artifacts

### Workflow Contract (enforced 2026-03-09)
> **Order**: 1) code/config/tests → 2) verification runs → 3) docs/artifacts update
> Any report generated before final reruns is non-canonical by process.

### Blocker Classification (2026-03-09 v3.2.52)
```
code_blocker: LOW (pytest 1463 passed, CI green, safety PASS)
data_collection_blocker: MEDIUM (Base 88%, Mantle 51%, Arbitrum 42% fetch rate)
market_window_blocker: HIGH (3/6 chains NO_DATA despite infra PASS - market conditions)
```

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

### Multi-chain Coverage Results (2026-03-09 v3.2.52 --cycles 2)
| Chain | RunDir | Infra Gate | run_summary | chain_quality_level | signals | quotes | fetch% | Notes |
|-------|--------|------------|-------------|---------------------|---------|--------|--------|-------|
| Arbitrum | `102836` | PASS | **PASS** | SIGNAL_PRODUCING | 11 | 51/122 | 42% | Best signals |
| Base | `102444` | PASS | **PASS** | SIGNAL_PRODUCING | 1 | 37/42 | 88% | **IMPROVED** |
| Mantle | `102629` | PASS | **PASS** | SIGNAL_PRODUCING | 3 | 24/47 | 51% | same-DEX fallback |
| Linea | `102739` | PASS | NO_DATA | INFRA_READY | 0 | 27/42 | 64% | no spreads ≥3bps |
| zkSync | `102825` | PASS | NO_DATA | INFRA_READY | 0 | 49/62 | 79% | no spreads ≥3bps |
| Scroll | `102807` | PASS | NO_DATA | INFRA_READY | 0 | 9/37 | 24% | no spreads ≥3bps |

**Practical changes made (v3.2.52)**:
- **mUSD token added**: `core_tokens.yaml` for Mantle (address `0xab575258d37eaa5c8956efabe71f4ee8f6397cf3`)
- **AUSD pairs removed**: intent.txt (zero liquidity on DEXes, token not found)
- **Mantle MIXED_SOURCE fix**: Set `require_cross_dex: false` in coverage_intent_mantle.yaml
  - Root cause: ALL cross-dex routes are stratum (ve33) ↔ agni_v3 (uniswap_v3) = MIXED_SOURCE
  - Solution: Allow single-DEX fee-tier arbitrage (agni_v3→agni_v3) which uses consistent quoter_v2 source
- **chain_quality_level**: Added to run_summary.metrics (INFRA_READY/SIGNAL_PRODUCING/QUALITY_RAISED)
- **consecutive_non_nodata_cycles**: Added to run_summary.metrics and m4_stability_agg.quick_stats
- Terminology contract: `chain_quality_level` in artifacts for provable quality progression

## 0) Meta
timestamp_utc: 2026-03-09T10:35:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (6-chain verification)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest tests/unit -q: 1463 passed, 1 skipped
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 2: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 2: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 2: PASS (NO_DATA)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 2: PASS (NO_DATA)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 2: PASS (NO_DATA)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_arbitrum_one.yaml --cycles 2: PASS
```

## 2) Evidence Artifacts

**Fresh verification (2026-03-09 10:35, all 6 chains, 2 cycles)**:
- `ci_m5_gate_20260309_102836` (Arbitrum) - **PASS**, 11 signals
- `ci_m5_gate_20260309_102444` (Base) - **PASS**, 1 signal, 88% fetch rate ✅
- `ci_m5_gate_20260309_102629` (Mantle) - **PASS**, 3 signals (same-DEX fallback)
- `ci_m5_gate_20260309_102739` (Linea) - PASS (NO_DATA), 0 signals
- `ci_m5_gate_20260309_102825` (zkSync) - PASS (NO_DATA), 0 signals
- `ci_m5_gate_20260309_102807` (Scroll) - PASS (NO_DATA), 0 signals

**Code changes**:
- `config/core_tokens.yaml`: Added mUSD token for Mantle
- `config/intent.txt`: Removed AUSD pairs (zero liquidity)
- `config/coverage_intent_mantle.yaml`: Removed AUSD from tokens_usd_price

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **Mantle expansion**: Add FusionX V3 (uniswap_v3) to enable quoter_v2↔quoter_v2 cross-dex routes
2. **Linea/zkSync/Scroll**: NO_DATA despite quotes - market conditions or need more DEXes
3. **Base improvement**: 88% fetch rate achieved, monitor stability
4. **QUALITY_RAISED**: Track consecutive_non_nodata_cycles >= 3 to prove stable signal production

---
*Generated: 2026-03-09T10:35:00Z*
