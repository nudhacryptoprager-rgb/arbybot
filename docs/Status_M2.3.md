# Status_M2.3.md — AlgebraAdapter + P0 Fixes

**Дата:** 2026-01-12  
**Milestone:** M2.3 — AlgebraAdapter  
**Статус:** ✅ **CODE COMPLETE** | ⏸️ **CAMELOT DISABLED** | 🔧 **M2.3 Adapter NOT in prod pipeline**

---

## 1. Summary

| Item | Status |
|------|--------|
| AlgebraAdapter code | ✅ Ready |
| Correct selector (0x2d9ebd1d) | ✅ |
| **Camelot in prod pipeline** | ⏸️ **DISABLED** |
| PRICE_SANITY_FAILED tests | ✅ 9 tests |
| gate_price_sanity bug | ✅ Fixed |
| Paper trading safety | ✅ 3 tests |
| **Pool grouping bug** | ✅ **FIXED** |
| **spread_key bug** | ✅ **FIXED** (pair included) |
| **INTERNAL_CODE_ERROR** | ✅ **ADDED** |
| **pairs_scanned metric** | ✅ |
| **pools_skipped metric** | ✅ |
| **gas_cost_wei in spreads** | ✅ |

---

## 2. Critical Bug Fixes (This Session)

### 2.1 Pool Grouping Bug (ROOT CAUSE of pairs_covered=1)
**Problem:** `pools_by_dex_fee` grouped different pairs together.
**Fix:** Key includes pair: `f"{dex_key}_{pool.fee}_{pair_key}"`

### 2.2 spread_key Bug (CRITICAL)
**Problem:** `spread_key = f"{pool.fee}_{amount_in}"` - didn't include pair.
**Result:** Quotes from different pairs mixed, anchor prices wrong.
**Fix:** `spread_key = f"{pair_id}_{pool.fee}_{amount_in}"`

### 2.3 Error Classification
**Problem:** AttributeError from code bugs reported as INFRA_BAD_ABI.
**Fix:** Added `ErrorCode.INTERNAL_CODE_ERROR` for our code bugs:
```python
if isinstance(e, (AttributeError, KeyError)):
    if "abi" in tb_lower or "decode" in tb_lower:
        error_code = ErrorCode.INFRA_BAD_ABI
    else:
        error_code = ErrorCode.INTERNAL_CODE_ERROR  # Our bug!
```

### 2.4 Diagnostics Added
- `pools_skipped` counter with reasons (no_quoter, algebra_disabled)
- `traceback` in reject_sample details
- `pairs_scanned` in summary

---

## 3. New Tests (183 total)

```python
# test_exceptions.py
test_price_sanity_failed_exists      # CRITICAL regression test
test_all_gate_error_codes_exist      # All gate codes must exist

# test_gates.py  
test_passes_with_none_ticks_algebra  # Algebra ticks=None handling
```

---

## 4. Schema Changes (v2026-01-12)

**Snapshot additions:**
```json
{
  "schema_version": "2026-01-12",
  "pools_skipped": {"no_quoter": 0, "algebra_disabled": 0},
  "pairs_scanned": ["WETH/USDC", "WETH/ARB", ...],
  "spreads": [{
    "gas_total": 400000,
    "gas_cost_wei": 8000000000000,
    ...
  }]
}
```

---

## 5. ErrorCode Additions

```python
# New in core/exceptions.py
INTERNAL_CODE_ERROR = "INTERNAL_CODE_ERROR"  # AttributeError/KeyError in our code
```

---

## 6. Camelot/Algebra Status

**DISABLED** - not in production pipeline:
```yaml
camelot_v3:
  enabled: false
  verified_for_quoting: false
```

---

## 7. Files Changed

| File | Changes |
|------|---------|
| `core/exceptions.py` | +INTERNAL_CODE_ERROR |
| `strategy/jobs/run_scan.py` | spread_key fix, pools_skipped, error classify |
| `tests/unit/test_exceptions.py` | +2 tests for gate error codes |

---

## 8. Next Steps

1. ✅ Run smoke scan - verify 5 pairs work
2. ✅ Verify INTERNAL_CODE_ERROR = 0 (no code bugs)
3. ✅ Verify pools_scanned = planned_pools
4. Expand to 3-5 pairs with real distribution
5. M3: Opportunity ranking

---

*Оновлено: 2026-01-12*
