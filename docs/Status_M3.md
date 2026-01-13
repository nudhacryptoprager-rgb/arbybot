# Status_M3.md — Opportunity Engine

**Дата:** 2026-01-13  
**Milestone:** M3 — Opportunity Engine  
**Статус:** ✅ **STABLE** | **Schema:** 2026-01-12h

---

## 1. M3 Progress

| Item | Status |
|------|--------|
| **Confidence scoring** | ✅ COMPLETE |
| **Revalidation in paper** | ✅ COMPLETE |
| **Counter invariant fix** | ✅ COMPLETE |
| **--cycles CLI option** | ✅ COMPLETE |
| **is_anchor_dex (3 args)** | ✅ COMPLETE |
| **code_errors counter** | ✅ COMPLETE |
| **pairs_covered fix** | ✅ COMPLETE |
| **CODE_ERROR status** | ✅ COMPLETE |
| **ErrorCode contract test** | ✅ COMPLETE |
| Provider health policy | ⏳ Next |

---

## 2. Verified API Contract

### apply_single_quote_gates
```python
def apply_single_quote_gates(
    quote: Quote,
    anchor_price: Decimal | None = None,
    is_anchor_dex: bool = False,    # ← 3rd argument
) -> list[GateResult]:
```

### ErrorCodes used by gates
All verified to exist in `core/exceptions.py`:
- QUOTE_ZERO_OUTPUT
- QUOTE_GAS_TOO_HIGH  
- TICKS_CROSSED_TOO_MANY
- QUOTE_STALE_BLOCK
- PRICE_ANCHOR_MISSING
- PRICE_SANITY_FAILED
- SLIPPAGE_TOO_HIGH
- QUOTE_INCONSISTENT

---

## 3. Invariant

```
passed + rejected_by_gates + code_errors == fetched
```

---

## 4. Tests

**208 passed ✅** (+1 ErrorCode contract test)

---

## 5. CLI

```bash
# Single cycle
python -m strategy.jobs.run_scan --chain arbitrum_one --once --smoke

# Multiple cycles  
python -m strategy.jobs.run_scan --chain arbitrum_one --cycles 5 --smoke

# With paper trading
python -m strategy.jobs.run_scan --once --smoke --paper-trading --no-json-logs
```

---

## 6. Files (must be in sync)

| File | Key Changes |
|------|-------------|
| `strategy/gates.py` | `apply_single_quote_gates(quote, anchor_price, is_anchor_dex)` |
| `strategy/jobs/run_scan.py` | Call with 3 args, code_errors counter |
| `core/exceptions.py` | PRICE_ANCHOR_MISSING, all gate ErrorCodes |
| `monitoring/truth_report.py` | pairs_covered from pairs_scanned |

---

## 7. Top Reject Reasons Analysis

From latest scan:
- **PRICE_SANITY_FAILED** (13) - deviation_too_high, mostly sushiswap_v3 vs uniswap_v3 anchor
- **QUOTE_GAS_TOO_HIGH** (12) - gas > threshold  
- **TICKS_CROSSED_TOO_MANY** (9) - illiquid pools
- **QUOTE_REVERT** (6) - QuoterV2 call failures

---

## 8. Next Steps

1. **RPC health routing** - quarantine bad endpoints
2. **Adaptive gates** - gas/ticks limits by amount_in  
3. **Pool quarantine** - track PRICE_SANITY_FAILED count

---

*Оновлено: 2026-01-13*
