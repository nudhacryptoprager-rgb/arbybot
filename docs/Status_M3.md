# Status_M3.md — Opportunity Engine

**Дата:** 2026-01-12  
**Milestone:** M3 — Opportunity Engine  
**Статус:** 🚧 **IN PROGRESS** | **Schema:** 2026-01-12h

---

## 1. M3 Progress

| Item | Status |
|------|--------|
| **Confidence scoring** | ✅ COMPLETE |
| **Revalidation in paper** | ✅ COMPLETE |
| **Counter invariant fix** | ✅ COMPLETE |
| **--cycles CLI option** | ✅ COMPLETE |
| **is_anchor_dex tests** | ✅ COMPLETE |
| **code_errors counter** | ✅ COMPLETE |
| **pairs_covered fix** | ✅ COMPLETE |
| **CODE_ERROR status** | ✅ COMPLETE |
| Provider health policy | ⏳ Next |

---

## 2. P0 Fixes (This Session)

### 2.1 Code Errors Counter
**Problem:** TypeError/AttributeError during quote processing weren't counted, breaking invariant.

**Fix:** Added `quotes_code_errors` counter for errors that happen AFTER fetch but BEFORE gates.

**Correct invariant:**
```
passed + rejected_by_gates + code_errors == fetched
```

### 2.2 pairs_covered Fix
**Problem:** `truth_report.health.pairs_covered=0` despite `pairs_scanned=5` in snapshot.

**Root cause:** Code tried to get pairs from `quotes` list (which was empty due to code errors).

**Fix:** Get pairs directly from `cycle.get("pairs_scanned", [])`.

### 2.3 CODE_ERROR Status
**Problem:** `status="NO_QUOTES"` when quotes WERE fetched but had code errors.

**Fix:** New status logic:
```python
"OK" if quotes_passed_gates > 0 
else ("CODE_ERROR" if quotes_code_errors > 0 else "NO_QUOTES")
```

---

## 3. Snapshot Schema v2026-01-12h

```json
{
  "quotes_attempted": 60,
  "quotes_fetched": 54,
  "quotes_fetch_failed": 6,
  "quotes_rejected_by_gates": 20,
  "quotes_code_errors": 4,
  "quotes_passed_gates": 30,
  "status": "OK",
  "invariants_ok": true
}
```

---

## 4. Files Changed

| File | Changes |
|------|---------|
| `strategy/jobs/run_scan.py` | +quotes_code_errors, invariant fix, CODE_ERROR status |
| `monitoring/truth_report.py` | pairs_covered from pairs_scanned |
| `strategy/gates.py` | **ALREADY HAS** is_anchor_dex (verified) |

---

## 5. Tests

**207 passed ✅**

---

## 6. Verification Steps

```bash
# 1. Verify gates.py has correct signature
grep -A3 "def apply_single_quote_gates" strategy/gates.py

# 2. Run gates tests
python -m pytest tests/unit/test_gates.py -q

# 3. Run scan
python -m strategy.jobs.run_scan --chain arbitrum_one --once --smoke --paper-trading --no-json-logs
```

Expected: `invariants_ok=true`, `quotes_passed_gates > 0`

---

## 7. Next Steps

1. **Provider health policy** - auto-disable bad endpoints
2. **Adaptive sizing** - gas/ticks limits by amount_in
3. **Pool quarantine** - track PRICE_SANITY_FAILED count

---

*Оновлено: 2026-01-12*
