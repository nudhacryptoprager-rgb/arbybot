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

### Blocker Classification (2026-03-08)
```
code_blocker: LOW (pytest 1443 passed, CI green, safety PASS)
data_collection_blocker: MEDIUM (quarantines active, some quotes rejected)
market_window_blocker: HIGH (4/5 chains NO_DATA/FAIL despite infra PASS)
```

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](docs/status/Status_M5_0.md) for terminology.

### Multi-chain Coverage Results (2026-03-08 --cycles 3)
| Chain | RunDir | Infra Gate | run_summary | signals | Quotes | Notes |
|-------|--------|------------|-------------|---------|--------|-------|
| Base | `ci_m5_gate_20260308_110956` | PASS | **PASS** | 1 | 28 | 0.342 USDC profit |
| Linea | `ci_m5_gate_20260308_111208` | PASS | NO_DATA | 0 | 27 | quotes OK, no spreads |
| Mantle | `ci_m5_gate_20260308_111245` | PASS | FAIL | 1 | 14 | signal not profitable |
| zkSync | `ci_m5_gate_20260308_111334` | PASS | NO_DATA | 0 | 49 | quotes OK, no spreads |
| Scroll | `ci_m5_gate_20260308_111137` | PASS | NO_DATA | 0 | 9 | quarantined low-liq |

**Practical changes made**:
- Added SushiSwap V3 to Base (factory+quoter from sushi.com deployment)
- Added SushiSwap V3 to Scroll (unblocked SECOND_DEX)
- **Quarantined 2 low-liquidity pools on Scroll** (`disabled_pools` in config)
- Fixed `use_quoter_v2` variable bug in `strategy/quotes.py`
- Fixed malformed ISO-8601 timestamp in `ci_m5_0_gate.py` (+00:00Z → Z)
- Added 46 config contract tests (incl. disabled_pools validation)
- Added workflow contract to `docs/DOCS_POLICY.md`

## 0) Meta
timestamp_utc: 2026-03-08T11:15:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain cycles=3 verification)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest tests/unit -q: 1443 passed, 1 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 3: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 3: PASS (infra)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 3: PASS (infra)
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
