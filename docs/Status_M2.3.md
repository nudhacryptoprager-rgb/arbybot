# Status_M2.3.md — AlgebraAdapter + P0 Fixes

**Дата:** 2026-01-12  
**Milestone:** M2.3 — AlgebraAdapter  
**Статус:** ✅ **CODE COMPLETE** | ⏸️ **CAMELOT DISABLED**

---

## 1. Summary

| Item | Status |
|------|--------|
| AlgebraAdapter code | ✅ |
| Correct selector (0x2d9ebd1d) | ✅ |
| Unit tests (10) | ✅ |
| ticks_crossed = None | ✅ |
| Error details improved | ✅ |
| **camelot_v3 enabled** | ⏸️ DISABLED |
| **PRICE_SANITY_FAILED tests** | ✅ 6 tests |
| **gate_price_sanity bug fixed** | ✅ quote.pool.dex_id |
| **Paper trading PnL test** | ✅ 3 tests |
| **Snapshot schema_version** | ✅ |
| **Snapshot block_pin** | ✅ |
| **RejectSample ticks_crossed** | ✅ Optional |
| **fee_tiers reordered** | ✅ 100 last |
| **Smoke harness expanded** | ✅ 5 pairs |
| **Core tokens expanded** | ✅ wstETH, GMX |

---

## 2. Critical Bug Fixes

### 2.1 gate_price_sanity AttributeError
**Bug:** `quote.dex_id` → `AttributeError` (Quote has no dex_id)  
**Fix:** Changed to `quote.pool.dex_id`

### 2.2 RejectSample type error
**Bug:** `ticks_crossed: int` but Algebra returns `None`  
**Fix:** `ticks_crossed: int | None`

### 2.3 fee=100 reordering
**Issue:** fee=100 causes high ticks (15-16) and gas (462k-530k)  
**Fix:** Moved 100 to end of fee_tiers list

---

## 3. Smoke Harness Expansion

**Before:** WETH/USDC only  
**After:** 5 core pairs:
```python
SMOKE_PAIRS = [
    ("WETH", "USDC"),
    ("WETH", "ARB"),
    ("WETH", "LINK"),
    ("wstETH", "WETH"),
    ("WETH", "USDT"),
]
```

**Core tokens added:**
- wstETH: 0x5979D7b546E38E414F7E9822514be443A4800529
- GMX: 0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a

---

## 4. Tests

**181 passed ✅**

New tests:
- TestGatePriceSanity (6 tests)
- TestNegativePnLWithExecutable (3 tests)
- test_passes_with_none_ticks_algebra

---

## 5. Files Changed

| File | Changes |
|------|---------|
| `strategy/gates.py` | quote.pool.dex_id fix |
| `strategy/jobs/run_scan.py` | 5 pair smoke, schema_version, block_pin |
| `config/dexes.yaml` | fee_tiers reordered, camelot disabled |
| `config/core_tokens.yaml` | +wstETH, +GMX |
| `tests/unit/test_gates.py` | +7 tests |
| `tests/unit/test_paper_trading.py` | +3 tests |

---

## 6. Next Steps

1. ✅ INFRA_BAD_ABI root causes fixed
2. Run 20 cycle smoke scan to verify histogram
3. Verify 5 pairs produce diverse spreads
4. M3: Opportunity ranking

---

*Оновлено: 2026-01-12*
