# Status_M3.md — Opportunity Engine

**Дата:** 2026-01-12  
**Milestone:** M3 — Opportunity Engine  
**Статус:** 🚧 **IN PROGRESS** | **Schema:** 2026-01-12g

---

## 1. M3 Progress

| Item | Status |
|------|--------|
| **Confidence scoring** | ✅ **COMPLETE** |
| **Revalidation in paper** | ✅ **COMPLETE** |
| **Counter invariant fix** | ✅ **COMPLETE** |
| **--cycles CLI option** | ✅ **COMPLETE** |
| **is_anchor_dex tests** | ✅ **COMPLETE** |
| Provider health policy | ⏳ Next |
| Adaptive sizing | ⏳ Later |

---

## 2. P0 Fixes (This Session)

### 2.1 Counter Invariant Fix
**Problem:** `passed(0) + rejected(60) > fetched(54)` - anomaly because `rejected` included fetch errors.

**Root cause:** `quotes_rejected` was incremented both for:
- Gate failures (fetched quotes that failed gates) ✓
- Fetch errors (exceptions, not actually fetched) ✗

**Fix:**
```python
# Before: quotes_rejected (ambiguous)
# After:
quotes_rejected_by_gates  # Only fetched quotes that failed gates
quotes_fetch_failed = attempted - fetched  # RPC/decode errors
```

**Correct invariant:**
```
passed + rejected_by_gates == fetched
```

### 2.2 --cycles CLI Option
Added `--cycles N` to run N cycles and exit:
```bash
# Single cycle (same as --once)
python -m strategy.jobs.run_scan --cycles 1 --smoke

# Multiple cycles with interval
python -m strategy.jobs.run_scan --cycles 5 --smoke --interval 3000
```

### 2.3 is_anchor_dex Tests
Added 3 tests for anchor DEX handling:
- `test_anchor_dex_skips_price_sanity`
- `test_non_anchor_without_anchor_price_rejected`
- `test_apply_single_quote_gates_accepts_is_anchor_dex`

---

## 3. Tests

**207 passed ✅** (+3 from last)

---

## 4. Files Changed

| File | Changes |
|------|---------|
| `strategy/jobs/run_scan.py` | Counter fix, --cycles option |
| `tests/unit/test_gates.py` | +3 is_anchor_dex tests |

---

## 5. CLI Usage

```bash
# Single cycle
python -m strategy.jobs.run_scan --chain arbitrum_one --once --smoke

# Multiple cycles
python -m strategy.jobs.run_scan --chain arbitrum_one --cycles 5 --smoke --paper-trading

# Infinite loop (default)
python -m strategy.jobs.run_scan --chain arbitrum_one --smoke
```

---

## 6. Next Steps

1. **Provider health policy** - auto-disable bad endpoints after N failures
2. **Adaptive sizing** - gas/ticks limits by amount_in
3. **Pool quarantine** - track PRICE_SANITY_FAILED count per pool

---

*Оновлено: 2026-01-12*
