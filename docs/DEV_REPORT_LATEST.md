# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-08)
**Goal**: Practical bring-up - expand DEX coverage on Base and Scroll to produce signals

### Multi-chain Coverage Results (2026-03-08)
| Chain | RunDir | Infra Gate | run_summary.status | signals | included | Notes |
|-------|--------|------------|-------------------|---------|----------|-------|
| Base | `ci_m5_gate_20260308_100732` | PASS | PASS | 1 | 1 | **CBETH/WETH 49.2bps** aerodrome→sushiswap_v3 |
| Linea | `ci_m5_gate_20260308_091717` | PASS | NO_DATA | 0 | 0 | infra up, universe needs expansion |
| Mantle | `ci_m5_gate_20260308_091743` | PASS | FAIL | 1 | 0 | FAIL_ALL_EXCLUDED (contract correct) |
| zkSync | `ci_m5_gate_20260308_091800` | PASS | NO_DATA | 0 | 0 | infra up, universe needs expansion |
| Scroll | `ci_m5_gate_20260308_100612` | FAIL | N/A | 0 | 0 | structural unblock, PRICE_SCALE quality fail |

**Practical changes made**:
- Added SushiSwap V3 to Base (factory+quoter from sushi.com deployment)
- Added SushiSwap V3 to Scroll (unblocked SECOND_DEX)
- Added PancakeSwap V3 to Base config (later removed - pools have no liquidity)
- Fixed `use_quoter_v2` variable bug in `strategy/quotes.py`
- Fixed malformed ISO-8601 timestamp in `ci_m5_0_gate.py` (+00:00Z → Z)
- Added 27 config contract tests (`tests/unit/test_config_contracts.py`)
- Updated `scroll_dex_audit.json` to reflect SushiSwap V3 availability

## 0) Meta
timestamp_utc: 2026-03-08T10:30:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain coverage refresh + practical bring-up)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest -q: 1397 passed, 1 skipped
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 1: PASS (1 signal)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 1: FAIL (quality)
```

## 2) Evidence Artifacts

**Fresh multi-chain coverage (2026-03-08)**:
- `ci_m5_gate_20260308_100732` (Base) - **infra PASS, status PASS, 1 signal**
- `ci_m5_gate_20260308_100612` (Scroll) - structural unblock (2 DEXes, 8 cross-dex), quality FAIL

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
2. Expand Base to get more than 1 signal (currently WARN_LOW_SAMPLE)
3. Re-run Linea/zkSync with expanded DEX configs
4. Do NOT update rolling canonical until coverage runs are repeatable

---
*Generated: 2026-03-08T10:30:00Z*
