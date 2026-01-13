# Status_M3.md — Opportunity Engine

**Дата:** 2026-01-13  
**Milestone:** M3 — Opportunity Engine  
**Статус:** ✅ **STABLE** | **Schema:** 2026-01-13a

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
| **Confidence-gated executable** | ✅ COMPLETE |
| Provider health policy | ⏳ Next |

---

## 2. Confidence-Gated Executable (NEW)

### Problem
Spreads with `plausibility=0.2` were still marked `executable=true`.

### Solution
```python
# executable = verified AND profitable AND plausible AND confident
MIN_CONFIDENCE_FOR_EXEC = 0.5
is_confident = confidence >= MIN_CONFIDENCE_FOR_EXEC
executable_final = buy_exec and sell_exec and is_profitable and is_plausible and is_confident
```

### Spread Schema
```json
{
  "spread_bps": 45,
  "net_pnl_bps": 32,
  "profitable": true,
  "plausible": true,
  "confidence": 0.78,
  "confidence_breakdown": {
    "freshness": 1.0,
    "ticks": 0.9,
    "verification": 1.0,
    "profitability": 0.6,
    "gas_efficiency": 0.8,
    "rpc_health": 0.95,
    "plausibility": 1.0,
    "final": 0.78
  },
  "executable": true
}
```

### Execution Gates
| Gate | Threshold | Effect |
|------|-----------|--------|
| `buy_exec` | DEX verified | Block |
| `sell_exec` | DEX verified | Block |
| `profitable` | net_pnl_bps > 0 | Block |
| `plausible` | spread_bps ≤ 500 | Block |
| `confident` | confidence ≥ 0.5 | Block |

---

## 3. Tests

**208 passed ✅**

---

## 4. Files Changed

| File | Changes |
|------|---------|
| `strategy/jobs/run_scan.py` | Confidence calculation per spread, confidence-gated executable |

---

## 5. CLI

```bash
# Single cycle with paper trading
python -m strategy.jobs.run_scan --once --smoke --paper-trading --no-json-logs
```

**Expected:**
- `executable=true` only if `confidence >= 0.5`
- Low plausibility spreads blocked from execution

---

## 6. Next Steps

1. **RPC health routing** - quarantine bad endpoints
2. **PRICE_SANITY_FAILED analysis** - deviation details in reports
3. **Adaptive gates** - gas/ticks limits by amount_in

---

*Оновлено: 2026-01-13*
