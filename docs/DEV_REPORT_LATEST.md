# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-08)
**Goal**: Practical bring-up - complete 10-step fix plan (code/config → verification → docs)

### Workflow Contract (enforced 2026-03-08)
> **Order**: 1) code/config/tests → 2) verification runs → 3) docs/artifacts update
> Any report generated before final reruns is non-canonical by process.

### Blocker Classification (2026-03-08 v2.0.9)
```
code_blocker: LOW (pytest 1457 passed, CI green, safety PASS)
data_collection_blocker: MEDIUM (quarantines active, some quotes rejected)
market_window_blocker: HIGH (4/5 chains NO_DATA/FAIL despite infra PASS)
```

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

### Multi-chain Coverage Results (2026-03-08 v2.0.9 --cycles 3)
| Chain | RunDir | Infra Gate | run_summary | signals | Quotes | Notes |
|-------|--------|------------|-------------|---------|--------|-------|
| Base | `ci_m5_gate_20260308_112739` | PASS | **PASS** | 1 | 31 | spread 49bps |
| Linea | `ci_m5_gate_20260308_112927` | PASS | NO_DATA | 0 | 27 | no spreads ≥3bps |
| Mantle | `ci_m5_gate_20260308_113028` | PASS | FAIL | 1 | 14 | signal excluded |
| zkSync | `ci_m5_gate_20260308_113052` | PASS | NO_DATA | 0 | 49 | no spreads ≥3bps |
| Scroll | `ci_m5_gate_20260308_113003` | PASS | NO_DATA | 0 | 9 | no spreads ≥3bps |

**Practical changes made (v2.0.9)**:
- Added `ChainQualityLevel` policy (INFRA_READY → SIGNAL_PRODUCING → QUALITY_RAISED)
- Added `classify_chain_quality()` + 14 tests in `test_chain_quality_level.py`
- Lowered `min_spread_bps` from 5 to 3 for all chains (profitable with low L2 gas)
- Fixed AERO token price ($1.5 → $0.35 market correction) in Base config
- Added PUFF/AUSD token prices to Mantle config
- Terminology contract: added `ChainQualityLevel` to table

## 0) Meta
timestamp_utc: 2026-03-08T11:35:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain cycles=3 verification)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest tests/unit -q: 1457 passed, 1 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 3: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 3: PASS (infra)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 3: PASS (infra)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 3: PASS (infra)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 3: PASS (infra)
```

## 2) Evidence Artifacts

**Fresh multi-chain coverage (2026-03-08 --cycles 3 verification)**:
- `ci_m5_gate_20260308_110956` (Base) - **PASS** (infra+signals), 1 signal, 0.342 USDC
- `ci_m5_gate_20260308_111137` (Scroll) - PASS (infra), NO_DATA (signals)
- `ci_m5_gate_20260308_111208` (Linea) - PASS (infra), NO_DATA (signals)
- `ci_m5_gate_20260308_111245` (Mantle) - PASS (infra), FAIL (signals not profitable)
- `ci_m5_gate_20260308_111334` (zkSync) - PASS (infra), NO_DATA (signals)

**Code changes**:
- `config/dexes.yaml`: +sushiswap_v3 for base, scroll
- `config/coverage_intent_base.yaml`: +sushiswap_v3, +use_quoter_v2
- `config/coverage_intent_scroll.yaml`: +sushiswap_v3, require_cross_dex=true
- `strategy/quotes.py`: Fix use_quoter_v2 → use_quoter_global
- `scripts/ci_m5_0_gate.py`: Fix timestamp format
- `tests/unit/test_config_contracts.py`: 27 new tests

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. **Signal flow**: Primary blocker is now market/window, not code. Need wider scan windows or different market conditions.
2. **Mantle**: FAIL due to unprofitable signal - needs route/pair optimization
3. **Linea/zkSync/Scroll**: NO_DATA despite quotes - explore additional DEXes or lower min_spread_bps
4. **Rolling**: Canonical rolling remains arbitrum_one; multi-chain is coverage-only for now

---
*Generated: 2026-03-08T11:15:00Z*
