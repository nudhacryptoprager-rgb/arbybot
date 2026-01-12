# Status_M3.md — Opportunity Engine

**Дата:** 2026-01-12  
**Milestone:** M3 — Opportunity Engine  
**Статус:** 🚧 **IN PROGRESS** | **Schema:** 2026-01-12f

---

## 1. M3 Progress

| Item | Status |
|------|--------|
| **Confidence scoring** | ✅ **COMPLETE** |
| **Revalidation in paper** | ✅ **COMPLETE** |
| Provider health policy | ⏳ Next |
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

---

## 3. Revalidation (COMPLETE)

### How it works
1. Each cycle checks for pending trades from previous cycles
2. When same spread_id appears again, compares new vs old PnL
3. Updates trade with `revalidated=true`, `would_still_execute`, `revalidation_block`
4. If trade no longer profitable, outcome changes to `GATES_CHANGED`

### New PaperSession methods
```python
get_pending_revalidation(current_block, min_blocks=1) -> list[PaperTrade]
mark_revalidated(spread_id, original_block, revalidation_block, would_still_execute, new_net_pnl_bps)
```

### Snapshot additions
```json
{
  "revalidations": [
    {
      "spread_id": "WETH/ARB_sushi_uni_3000_1e18",
      "original_block": 12345,
      "would_still_execute": true,
      "original_pnl_bps": 45,
      "new_pnl_bps": 42
    }
  ]
}
```

---

## 4. Tests

**204 passed ✅** (+3 revalidation tests)

| Test | Purpose |
|------|---------|
| `test_get_pending_revalidation_filters_correctly` | Filter logic |
| `test_mark_revalidated_updates_trade` | File update |
| `test_mark_revalidated_updates_stats_on_failure` | Stats correction |

---

## 5. Files Changed

| File | Changes |
|------|---------|
| `monitoring/truth_report.py` | Confidence with 7 components |
| `strategy/paper_trading.py` | +get_pending_revalidation, +mark_revalidated |
| `strategy/jobs/run_scan.py` | Revalidation loop, revalidations in summary |
| `tests/unit/test_confidence.py` | +8 tests |
| `tests/unit/test_paper_trading.py` | +3 tests |

---

## 6. truth_report Output

```
--- TOP OPPORTUNITIES ---
  #1 [✓] WETH/ARB sushi→uni: 45 bps ($1.23) conf=78%
       └─ fresh=100% ticks=90% verify=100% profit=80% plaus=100%
```

---

## 7. Next Steps

1. **Provider health policy** - auto-disable bad endpoints after N failures
2. **Adaptive sizing** - gas/ticks limits by amount_in
3. **Pool quarantine** - track PRICE_SANITY_FAILED count per pool

---

*Оновлено: 2026-01-12*
