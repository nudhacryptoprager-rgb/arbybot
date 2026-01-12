# Status_M3.md — Opportunity Engine

**Дата:** 2026-01-12  
**Milestone:** M3 — Opportunity Engine  
**Статус:** 🚧 **IN PROGRESS**

---

## 1. M3 Progress

| Item | Status |
|------|--------|
| **Confidence scoring** | ✅ **COMPLETE** |
| Revalidation in paper | ⏳ Next |
| Provider health policy | ⏳ Later |
| Adaptive sizing | ⏳ Later |
| Pool quarantine | ⏳ Later |

---

## 2. Confidence Score (COMPLETE)

### Components (weighted average)

| Component | Weight | What it measures |
|-----------|--------|------------------|
| `freshness` | 15% | Quote latency + block age |
| `ticks` | 15% | Ticks crossed penalty |
| `verification` | 20% | Both DEXes verified |
| `profitability` | 15% | net_pnl_bps quality |
| `gas_efficiency` | 10% | gas_cost_bps / spread_bps |
| `rpc_health` | 10% | Provider success rate |
| `plausibility` | 15% | Economic sanity check |

### Hard caps
- `executable=false` → conf ≤ 0.5
- `net_pnl_bps ≤ 0` → conf ≤ 0.3

### Plausibility thresholds
- spread ≤ 50 bps → 1.0 (normal arb)
- spread ≤ 200 bps → 0.8 (elevated)
- spread ≤ 500 bps → 0.5 (suspicious)
- spread > 500 bps → 0.2 (likely bad data)

### Ranking formula
```python
score = confidence * net_pnl_bps
ranked.sort(key=lambda x: x["score"], reverse=True)
```

---

## 3. New Tests (+8)

| Test | Purpose |
|------|---------|
| `test_confidence_has_breakdown` | Returns breakdown dict |
| `test_high_ticks_lowers_confidence` | Ticks penalty |
| `test_high_latency_lowers_confidence` | Freshness penalty |
| `test_unverified_lowers_confidence` | Verification penalty |
| `test_very_high_spread_suspicious` | Plausibility check |
| `test_unprofitable_caps_confidence` | Hard cap |
| `test_rpc_health_affects_confidence` | RPC factor |
| `test_confidence_between_0_and_1` | Range validation |

---

## 4. Tests

**197 passed ✅** (+8 from M2.3)

---

## 5. Files Changed

| File | Changes |
|------|---------|
| `monitoring/truth_report.py` | Full confidence rewrite with components |
| `tests/unit/test_confidence.py` | +8 new tests |

---

## 6. truth_report Output

```
--- TOP OPPORTUNITIES ---
  #1 [✓] WETH/ARB sushiswap_v3→uniswap_v3: 45 bps ($1.23) conf=78%
       └─ fresh=100% ticks=90% verify=100% profit=80% plaus=100%
  #2 [✗] WETH/LINK uniswap_v3→sushiswap_v3: 30 bps ($0.82) conf=45%
       └─ fresh=95% ticks=60% verify=50% profit=60% plaus=100%
```

---

## 7. Next Steps

1. **Revalidation in paper_trading** - re-quote on +1 block
2. **Provider health policy** - auto-disable bad endpoints
3. **Adaptive sizing** - gas/ticks limits by amount_in
4. **Pool quarantine** - track PRICE_SANITY_FAILED count

---

## 8. Schema v2026-01-12e

```json
{
  "top_opportunities": [{
    "confidence": 0.78,
    "confidence_breakdown": {
      "freshness": 1.0,
      "ticks": 0.9,
      "verification": 1.0,
      "profitability": 0.8,
      "gas_efficiency": 0.8,
      "rpc_health": 0.95,
      "plausibility": 1.0,
      "final": 0.78
    }
  }]
}
```

---

*Оновлено: 2026-01-12*
