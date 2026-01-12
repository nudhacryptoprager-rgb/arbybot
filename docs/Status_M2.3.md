# Status_M2.3.md — AlgebraAdapter + P0 Counter Fixes — READY FOR M3

**Дата:** 2026-01-12  
**Milestone:** M2.3 — Complete  
**Статус:** ✅ **READY FOR M3** | ⏸️ **CAMELOT DISABLED**

---

## 1. Summary

| Item | Status |
|------|--------|
| **All counter invariants** | ✅ FIXED & VALIDATED |
| **Metric clarity** | ✅ FIXED |
| **pairs_covered** | ✅ FIXED |
| **invariants_ok in snapshot** | ✅ ADDED |
| **Top opportunities filter** | ✅ ≥5 bps only |
| AlgebraAdapter | ✅ Ready (disabled) |
| 5-pair smoke test | ✅ Working |

---

## 2. Schema v2026-01-12c (Final M2.3)

### Quote Metrics (Unambiguous)
```json
{
  "quotes_attempted": 60,
  "quotes_fetched": 54,
  "quotes_fetch_failed": 6,
  "quotes_rejected_by_gates": 38,
  "quotes_passed_gates": 16,
  "reject_reasons_total": 42
}
```

### New Fields
```json
{
  "pairs_covered": 5,
  "invariants_ok": true,
  "invariant_errors": null
}
```

### Relationships
```
attempted = fetched + fetch_failed
rejected_by_gates = fetched - passed_gates
reject_reasons_total >= rejected_by_gates (multi-reason quotes)
```

---

## 3. Critical Fixes Applied

| Fix | Before | After |
|-----|--------|-------|
| pairs_covered | None | `len(pairs_scanned)` |
| quotes_rejected | Ambiguous | `quotes_rejected_by_gates` |
| invariants_ok | Logs only | In snapshot |
| Top opps filter | All | `net_pnl_bps >= 5` |

---

## 4. Tests

**183 passed ✅**

---

## 5. Files Changed (This Session)

| File | Changes |
|------|---------|
| `strategy/jobs/run_scan.py` | pairs_covered, metric rename, invariants_ok |
| `monitoring/truth_report.py` | MIN_NET_PNL_BPS = 5 filter |

---

## 6. Ready for M3: Opportunity Engine

**Prerequisites complete:**
- ✅ Counter invariants validated
- ✅ Metric names unambiguous
- ✅ 5-pair smoke working
- ✅ PRICE_SANITY_FAILED working
- ✅ RPC stats preserved

**M3 scope:**
1. Confidence scoring (freshness, reliability, ticks penalty)
2. `rank_key = net_usdc * confidence`
3. Adaptive sizing ladder
4. PRICE_SANITY soft/hard thresholds

---

*Оновлено: 2026-01-12*
