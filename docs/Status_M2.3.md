# Status_M2.3.md — AlgebraAdapter (Camelot)

**Дата:** 2026-01-11  
**Milestone:** M2.3 — AlgebraAdapter  
**Статус:** ✅ **COMPLETE** (pending live smoke test)

---

## 1. Summary

| Item | Status |
|------|--------|
| AlgebraAdapter skeleton | ✅ |
| ABI encoding/decoding | ✅ |
| **Correct selector (0x2d9ebd1d)** | ✅ FIXED |
| Unit tests (10) | ✅ |
| Config in dexes.yaml | ✅ |
| Feature flag | ✅ |
| Integration with run_scan.py | ✅ |
| Adapter selector tests | ✅ |
| No fee tiers for Algebra | ✅ |
| ticks_crossed = None for Algebra | ✅ FIXED |
| Live smoke test | ⏳ (RPC blocked in sandbox) |

---

## 2. Critical Fix: Selector

**Problem:** Camelot was reverting because wrong function selector.

**Wrong:** `0xcdca1753` (unknown signature)  
**Correct:** `0x2d9ebd1d` = keccak256("quoteExactInputSingle(address,address,uint256,uint160)")[:4]

**Algebra V1 Quoter signature:**
```solidity
function quoteExactInputSingle(
    address tokenIn,
    address tokenOut,
    uint256 amountIn,
    uint160 limitSqrtPrice
) returns (uint256 amountOut, uint16 fee)
```

---

## 3. Fix: ticks_crossed

**Before:** `ticks_crossed: int = 0` (misleading for Algebra)  
**After:** `ticks_crossed: int | None = None`

Gate updated to skip ticks check when `None`:
```python
def gate_ticks_crossed(quote, max_ticks):
    if quote.ticks_crossed is None:
        return GateResult(passed=True)  # Skip for Algebra
    ...
```

---

## 4. Improved Error Details

Quote errors now include:
- `block_tag`
- `call_data_prefix` (first 18 chars)
- `error_type`
- `error_message`

---

## 5. Tests

**171 passed ✅**

---

## 6. Files Changed

| File | Changes |
|------|---------|
| `dex/adapters/algebra.py` | Fixed selector, better errors, ticks=None |
| `core/models.py` | `ticks_crossed: int \| None` |
| `strategy/gates.py` | Handle ticks_crossed=None |
| `tests/unit/test_algebra_adapter.py` | Updated for new selector |

---

## 7. Live Smoke Test

Run locally with RPC access:

```bash
python -m strategy.jobs.run_scan --chain arbitrum_one --once --smoke
```

Expected: Camelot quotes no longer revert.

---

## 8. Roadmap Alignment

| Criterion | Status |
|-----------|--------|
| AlgebraAdapter created | ✅ |
| Correct ABI encoding | ✅ |
| Integrated in run_scan | ✅ |
| Proper error taxonomy | ✅ |
| Unit tests pass | ✅ |
| Live smoke test | ⏳ |

---

*Документ оновлено: 2026-01-11*
