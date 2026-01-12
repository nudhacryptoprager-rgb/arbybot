# Status_M2.3.md — P0 Fixes Complete — M3 READY

**Дата:** 2026-01-12  
**Milestone:** M2.3 — Complete  
**Статус:** ✅ **M3 READY** | **Schema:** 2026-01-12d

---

## 1. P0 Fixes (This Session)

### P0-1: spread_id Collision
**Problem:** Same spread_id for different pairs (e.g., WETH/ARB vs WETH/LINK).
**Impact:** Cooldown would block wrong trades, paper trading corrupted.

**Fix:**
```python
# Before: f"{buy_dex}_{sell_dex}_{fee}_{amount}"
# After:
spread_id = f"{pair}_{buy_dex}_{sell_dex}_{fee}_{amount}"
```

### P0-2: executable=true for Unprofitable
**Problem:** Spread with `net_pnl_bps=-2` had `executable=true`.
**Impact:** M3 ranking would accept losing trades as "ready to execute".

**Fix:**
```python
is_profitable = net_pnl_bps > 0
executable_final = buy_exec and sell_exec and is_profitable
```

---

## 2. New Tests (+6)

| Test | Purpose |
|------|---------|
| `test_different_pairs_have_different_spread_ids` | P0-1 regression |
| `test_spread_id_contains_pair` | Debug support |
| `test_unprofitable_spread_not_executable` | P0-2 regression |
| `test_profitable_but_unverified_not_executable` | Edge case |
| `test_profitable_and_verified_is_executable` | Happy path |
| `test_zero_pnl_not_executable` | Edge case |

---

## 3. Tests

**189 passed ✅**

---

## 4. Schema v2026-01-12d

```json
{
  "spreads": [{
    "id": "WETH/ARB_sushiswap_v3_uniswap_v3_3000_1000000000000000000",
    "pair": "WETH/ARB",
    "executable": false,  // false if net_pnl_bps <= 0
    "profitable": false
  }]
}
```

---

## 5. M3 Prerequisites ✅

| Requirement | Status |
|-------------|--------|
| Counter invariants | ✅ |
| spread_id unique | ✅ |
| executable=profitable | ✅ |
| 5-pair smoke | ✅ |
| RPC stats preserved | ✅ |
| PRICE_SANITY working | ✅ |

---

## 6. M3 Scope

1. **Confidence scoring** (freshness, reliability, ticks penalty)
2. **Ranking formula:** `rank = net_usdc * confidence`
3. **gas_cost_usdc** in opportunity rows
4. **Adaptive sizing ladder** (3+ amounts)
5. **Provider health policy** (auto-disable bad endpoints)

---

*Оновлено: 2026-01-12*
