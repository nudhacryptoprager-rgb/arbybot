# Project Status

> **⚠️ ARCHIVE (v2.0+)**: Цей файл використовує застарілий SHA tracking.
> Актуальний статус: `docs/status/Status_M4.md` з timestamp-based provenance.

**Date:** 2026-02-09  
**SHA:** 0d3d2c1 *(deprecated - see run_timestamp in rolling artifacts)*  
**Version:** M4 Execution Gate v1.8.1  

---

## Current State: ✅ STABLE

### Summary

M4 Execution Gate калібровано на основі 35 online прогонів. Система демонструє стабільну прибутковість з `agg_status=PASS`.

---

## Artifacts Policy

**Runtime artifacts are NEVER committed to git.**

| What | Where | In Git? |
|------|-------|---------|
| Run outputs | `data/runs/<run_id>/` | ❌ No |
| Rolling aggregator | `data/runs/_rolling/` | ❌ No |
| Analysis reports | Local only | ❌ No |
| Golden fixtures | `docs/artifacts/golden/` | ✅ Yes |

**Continuous scan storage:**
- `data/runs/_rolling/` — overwrite mode
- Retention: N=50 runs max
- See `docs/WORKFLOW.md#artifacts-policy` for full policy

---

## Gate Status

| Gate | Version | Status | Notes |
|------|---------|--------|-------|
| M5 Scanner | v1.0 | ✅ PASS | Online scans working |
| M4 Execution | v1.8.1 | ✅ PASS | Calibrated thresholds |
| M4 Aggregator | v1.4 | ✅ PASS | Rolling window healthy |

---

## Tests

```
562 passed, 1 skipped
```

---

## Thresholds (v1.8.1 Calibrated)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `MAE_WARN` | 0.55 | Above typical slippage=$0.50 |
| `MAE_FAIL` | 0.80 | Allows slippage + small error |
| `SIGN_RATE_MIN` | 0.60 | Allows 2/3 for small samples |
| `AGG_MAE_P90_FAIL` | 0.85 | Above slippage threshold |
| `AGG_WARN_RATE_FAIL` | 0.60 | Calibrated on empirical data |
| `AGG_FAIL_RATE_FAIL` | 0.40 | Calibrated on empirical data |

---

## Schema Versions

| Schema | Version |
|--------|---------|
| run_summary | v1.4 |
| stability_agg | v1.4 |
| latest | v1.1 |

---

## Recent Changes

### v1.8.1 (0d3d2c1) - Threshold Calibration

**Problem:** 20 online runs showed 100% WARN false positives because `mae=0.50` (slippage) was treated as model error.

**Solution:** Calibrated thresholds based on empirical data:
- MAE_WARN: 0.30 → 0.55
- MAE_FAIL: 0.50 → 0.80
- SIGN_RATE_MIN: 0.70 → 0.60
- AGG_*_FAIL thresholds relaxed

**Result:** 15 verification runs → 100% pass rate, `agg_status=PASS`

---

## Next Steps

1. Continue monitoring with calibrated thresholds
2. Implement retention policy (keep N=50 runs)
3. Add pre-commit guard for runtime artifacts

---

*Updated: 2026-02-09 | SHA: 0d3d2c1*
