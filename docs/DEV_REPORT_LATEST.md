# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-08)
**Goal**: Practical bring-up - expand DEX coverage on Base and Scroll + establish workflow contract

### Workflow Contract (enforced 2026-03-08)
> **Order**: 1) code/config/tests → 2) verification runs → 3) docs/artifacts update
> Any report generated before final reruns is non-canonical by process.

### Multi-chain Coverage Results (2026-03-08 final)
| Chain | RunDir | Infra Gate | DEXes | Quotes | Cross-dex | Notes |
|-------|--------|------------|-------|--------|-----------|-------|
| Base | `ci_m5_gate_20260308_103805` | **PASS** | 3 | 45 | 11 | uniswap_v3 + aerodrome + sushiswap_v3 |
| Linea | `ci_m5_gate_20260308_103953` | **PASS** | 2 | 42 | 12 | lynex_v3 + pancakeswap_v3 |
| Mantle | `ci_m5_gate_20260308_104024` | **PASS** | 2 | 22 | 5 | agni_v3 + stratum (ve33) |
| zkSync | `ci_m5_gate_20260308_104108` | **PASS** | 2 | 62 | 10 | uniswap_v3 + pancakeswap_v3 |
| Scroll | `ci_m5_gate_20260308_103930` | FAIL | 2 | 23 | 8 | nuri_v3 + sushiswap_v3 (PRICE_SCALE quality fail) |

**Practical changes made**:
- Added SushiSwap V3 to Base (factory+quoter from sushi.com deployment)
- Added SushiSwap V3 to Scroll (unblocked SECOND_DEX)
- Fixed `use_quoter_v2` variable bug in `strategy/quotes.py`
- Fixed malformed ISO-8601 timestamp in `ci_m5_0_gate.py` (+00:00Z → Z)
- Added 27 config contract tests (`tests/unit/test_config_contracts.py`)
- Updated `scroll_dex_audit.json` to reflect SushiSwap V3 availability

## 0) Meta
timestamp_utc: 2026-03-08T10:42:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain coverage refresh + practical bring-up)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest -q: 1424 passed, 1 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml: FAIL (quality)
```

## 2) Evidence Artifacts

**Fresh multi-chain coverage (2026-03-08 final verification)**:
- `ci_m5_gate_20260308_103805` (Base) - PASS, 3 DEXes, 45 quotes
- `ci_m5_gate_20260308_103953` (Linea) - PASS, 2 DEXes, 42 quotes
- `ci_m5_gate_20260308_104024` (Mantle) - PASS, 2 DEXes, 22 quotes
- `ci_m5_gate_20260308_104108` (zkSync) - PASS, 2 DEXes, 62 quotes
- `ci_m5_gate_20260308_103930` (Scroll) - FAIL (quality), 2 DEXes, 23 quotes

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

1. Fix Scroll PRICE_SCALE validation errors (anchor/price data quality)
2. Continue Base signal expansion beyond LOW_SAMPLE
3. Maintain strict workflow: code→runs→docs

---
*Generated: 2026-03-08T10:30:00Z*
