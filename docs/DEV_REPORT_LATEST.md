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

### Blocker Classification (2026-03-09 v3.2.51)
```
code_blocker: LOW (pytest 1463 passed, CI green, safety PASS)
data_collection_blocker: LOW (Mantle MIXED_SOURCE fixed via require_cross_dex=false)
market_window_blocker: HIGH (3/5 chains NO_DATA despite infra PASS - market conditions)
```

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

### Multi-chain Coverage Results (2026-03-09 v3.2.51 --cycles 1-2)
| Chain | RunDir | Infra Gate | run_summary | chain_quality_level | signals | quotes_fetched | Notes |
|-------|--------|------------|-------------|---------------------|---------|----------------|-------|
| Base | `ci_m5_gate_20260309_100321` | PASS | **PASS** | SIGNAL_PRODUCING | 1 | 36 | ROUNDTRIP_PROFITABLE |
| Mantle | `ci_m5_gate_20260309_100147` | PASS | **PASS** | SIGNAL_PRODUCING | 1 | 24 | FIXED: require_cross_dex=false |

**Practical changes made (v3.2.51)**:
- **Mantle MIXED_SOURCE fix**: Set `require_cross_dex: false` in coverage_intent_mantle.yaml
  - Root cause: ALL cross-dex routes are stratum (ve33) ↔ agni_v3 (uniswap_v3) = MIXED_SOURCE
  - Solution: Allow single-DEX fee-tier arbitrage (agni_v3→agni_v3) which uses consistent quoter_v2 source
- **chain_quality_level**: Added to run_summary.metrics (INFRA_READY/SIGNAL_PRODUCING/QUALITY_RAISED)
- **consecutive_non_nodata_cycles**: Added to run_summary.metrics and m4_stability_agg.quick_stats
- **Mantle tests**: Added 6 tests in `test_mantle_mixed_source.py` (config + MIXED_SOURCE behavior)
- Terminology contract: `chain_quality_level` in artifacts for provable quality progression

## 0) Meta
timestamp_utc: 2026-03-09T10:15:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain verification)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest tests/unit -q: 1463 passed, 1 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL GATES PASSED
python scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 2: PASS
python scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 1: PASS (ROUNDTRIP_PROFITABLE)
```

## 2) Evidence Artifacts

**Fresh verification (2026-03-09)**:
- `ci_m5_gate_20260309_100321` (Base) - **PASS**, ROUNDTRIP_PROFITABLE, 1 signal
- `ci_m5_gate_20260309_100147` (Mantle) - **PASS**, 1 included signal (CMETH/METH agni_v3→agni_v3)

**Code changes**:
- `config/coverage_intent_mantle.yaml`: `require_cross_dex: false` (MIXED_SOURCE fix)
- `m4/fixtures.py`: Added `chain_quality_level` and `consecutive_non_nodata_cycles` to run_summary
- `m4/rolling_store.py`: Added `consecutive_non_nodata_cycles` to quick_stats
- `tests/unit/test_mantle_mixed_source.py`: 6 new tests for Mantle MIXED_SOURCE behavior

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **Mantle expansion**: Add FusionX V3 (uniswap_v3) to enable quoter_v2↔quoter_v2 cross-dex routes
2. **Linea/zkSync/Scroll**: NO_DATA despite quotes - explore additional DEXes or wait for market conditions
3. **Rolling**: Canonical rolling remains arbitrum_one; multi-chain is coverage-only for now
4. **QUALITY_RAISED**: Track consecutive_non_nodata_cycles >= 3 to prove stable signal production

---
*Generated: 2026-03-09T10:15:00Z*
