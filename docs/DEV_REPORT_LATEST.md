# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-08)
**Goal**: Fresh multi-chain coverage runs for all 5 chains + docs alignment

### Multi-chain Coverage Results (2026-03-08)
| Chain | RunDir | Infra Gate | run_summary.status | signals | included | Notes |
|-------|--------|------------|-------------------|---------|----------|-------|
| Base | `ci_m5_gate_20260308_091657` | PASS | NO_DATA | 0 | 0 | infra up, universe needs expansion |
| Linea | `ci_m5_gate_20260308_091717` | PASS | NO_DATA | 0 | 0 | infra up, universe needs expansion |
| Mantle | `ci_m5_gate_20260308_091743` | PASS | FAIL | 1 | 0 | FAIL_ALL_EXCLUDED (contract correct) |
| zkSync | `ci_m5_gate_20260308_091800` | PASS | NO_DATA | 0 | 0 | infra up, universe needs expansion |
| Scroll | `ci_m5_gate_20260308_091812` | PASS | NO_DATA | 0 | 0 | require_cross_dex=false, BLOCKED_BY_SECOND_DEX |

**Interpretation**: All 5 chains pass M5_0 infra validation (artifacts, schemas, quotes), but none produce profitable spreads yet. This confirms we are at infra/universe bring-up stage, not profit-readiness.

## 0) Meta
timestamp_utc: 2026-03-08T09:20:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (multi-chain coverage refresh)

## 1) Commands Executed (This Session)

```
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 -m pytest -q: 1402 passed, 12 skipped
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 1: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 1: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 1: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 1: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 1: PASS
```

## 2) Evidence Artifacts

**Fresh multi-chain coverage (2026-03-08)**:
- `ci_m5_gate_20260308_091657` (Base) - infra PASS, NO_DATA
- `ci_m5_gate_20260308_091717` (Linea) - infra PASS, NO_DATA
- `ci_m5_gate_20260308_091743` (Mantle) - infra PASS, FAIL (FAIL_ALL_EXCLUDED)
- `ci_m5_gate_20260308_091800` (zkSync) - infra PASS, NO_DATA
- `ci_m5_gate_20260308_091812` (Scroll) - infra PASS, NO_DATA

**Rolling canonical** (unchanged):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z, arbitrum_one)

## 3) Next Steps

1. Expand DEX/pair universe on Base/Linea/zkSync/Scroll to produce signals_count > 0
2. Investigate Mantle FAIL_ALL_EXCLUDED at pair level
3. Continue Scroll 2nd DEX search in reproducible mode
4. Do NOT update rolling canonical until coverage runs produce usable signals

---
*Generated: 2026-03-08T09:20:00Z*
