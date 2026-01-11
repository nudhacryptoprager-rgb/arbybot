# Status_M2.3.md — AlgebraAdapter + P0 Fixes

**Дата:** 2026-01-11  
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
| **Paper trading PnL test** | ✅ NEW |
| **Snapshot schema_version** | ✅ NEW |
| **Snapshot block_pin** | ✅ NEW |

---

## 2. P0 Fixes (This Session)

### 2.1 Paper Trading Safety Test
```python
class TestNegativePnLWithExecutable:
    def test_negative_pnl_executable_true_gives_unprofitable():
        """executable=True + net_pnl_bps<0 → UNPROFITABLE, not WOULD_EXECUTE"""
```
**3 new tests** verifying outcome logic.

### 2.2 Snapshot Schema
```python
summary = {
    "schema_version": "2026-01-11",
    "block_pin": {
        "block_number": block_number,
        "pinned_at_ms": block_state.timestamp_ms,
        "age_ms": block_state.age_ms(),
        "latency_ms": block_state.latency_ms,
        "is_stale": pinner.is_stale(),
    },
    ...
}
```

### 2.3 .gitignore Updated
Added `data/registry/`, `*.jsonl`, all dynamic artifacts excluded.

---

## 3. Tests

**174 passed ✅** (+3 new paper trading tests)

---

## 4. Camelot Status

**Disabled** until live validation:
```yaml
camelot_v3:
  enabled: false
  verified_for_quoting: false
  note: "Algebra V1 Quoter - needs live validation"
```

---

## 5. Files Changed

| File | Changes |
|------|---------|
| `strategy/jobs/run_scan.py` | schema_version, block_pin in snapshot |
| `tests/unit/test_paper_trading.py` | +3 negative PnL tests |
| `.gitignore` | data/registry/, *.jsonl |
| `config/dexes.yaml` | camelot_v3 disabled |

---

## 6. Next Steps → M3

With P0 fixes complete, ready for M3 Opportunity Engine:
- Confidence scoring
- Opportunity ranking
- Sizing policy

---

*Оновлено: 2026-01-11*
