# Status_M2.3.md — AlgebraAdapter + P0 Counter Fixes

**Дата:** 2026-01-12  
**Milestone:** M2.3 — AlgebraAdapter + P0 Fixes  
**Статус:** ✅ **COUNTER FIXES COMPLETE** | ⏸️ **CAMELOT DISABLED**

---

## 1. Summary

| Item | Status |
|------|--------|
| **Counter invariants** | ✅ **FIXED** |
| **quotes_passed_gates calculation** | ✅ **FIXED** (from len(quotes_list)) |
| **spread_key consistency** | ✅ **FIXED** (pair included everywhere) |
| **RPC stats persistence** | ✅ **FIXED** (provider reuse) |
| **is_stale threshold** | ✅ **FIXED** (2s → 10s) |
| AlgebraAdapter code | ✅ Ready |
| Camelot in prod pipeline | ⏸️ DISABLED |

---

## 2. Critical Bug Fixes (This Session)

### 2.1 Counter Invariant Violations (ROOT CAUSE)
**Problem:** `quotes_passed_gates=66 > quotes_fetched=54`, `gate_pass_rate=1.22`

**Root causes:**
1. `quotes_passed_gates +=` in loop counted same quotes multiple times
2. Filter `q["dex"] == dex_key and q["fee"] == pool.fee` didn't include pair

**Fix:** Calculate from facts at end:
```python
quotes_passed_gates = len(quotes_list)  # Only passed quotes in list
```

### 2.2 spread_key Inconsistency (ROOT CAUSE of 0 spreads)
**Problem:** Two different spread_key formats:
- anchor_prices: `f"{pair_id}_{pool.fee}_{amount_in}"` ✓
- quotes_by_key: `f"{pool.fee}_{amount_in}"` ✗ (no pair!)

**Result:** Quotes from different pairs mixed in quotes_by_key.

**Fix:** Both use consistent format with pair.

### 2.3 RPC Stats = 0
**Problem:** `register_provider()` created new provider each cycle, discarding stats.

**Fix:** Return existing provider if already registered:
```python
if chain_id in self._providers:
    return self._providers[chain_id]  # Preserve stats
```

### 2.4 is_stale Too Aggressive
**Problem:** `max_block_age_ms=2000` → stale after 2 seconds.
**Fix:** `max_block_age_ms=10000` → 10 seconds (5 L2 blocks).

---

## 3. Invariant Validation

Added validation before snapshot:
```python
# Invariant 1: attempted = fetched + fetch_failed
# Invariant 2: passed <= fetched  
# Invariant 3: gate_pass_rate <= 1.0

if gate_pass_rate > 1.0:
    invariant_errors.append(...)
    gate_pass_rate = min(gate_pass_rate, 1.0)  # Cap
```

---

## 4. Schema Changes (v2026-01-12)

Metrics now calculated from facts:
```python
quotes_passed_gates = len(quotes_list)  # NOT increments
total_reject_reasons = sum(quote_reject_reasons.values())
```

---

## 5. Tests

**183 passed ✅**

---

## 6. Files Changed

| File | Changes |
|------|---------|
| `strategy/jobs/run_scan.py` | Counter calculation from facts, invariant validation |
| `chains/providers.py` | Provider reuse for stats persistence |
| `chains/block.py` | max_block_age_ms: 2000 → 10000 |

---

## 7. Expected After Fix

Run smoke scan should show:
- `gate_pass_rate <= 1.0`
- `quotes_passed_gates <= quotes_fetched`
- `rpc_total_requests > 0`
- `is_stale: false` (for <10s cycles)
- `spreads: [...]` (not empty)

---

*Оновлено: 2026-01-12*
