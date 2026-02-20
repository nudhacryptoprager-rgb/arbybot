# Status_M3_P2_quality_v4.md — Roadmap 3.2 No Float Money + PnL Truth

**Дата:** 2026-01-16  
**Milestone:** M3 P2 Quality v4  
**Статус:** ✅ **IMPLEMENTED - Roadmap Compliant**

---

## Problem Summary (10 Critical Issues from Team Lead)

1. **No float money violation** - Roadmap 3.2 forbids float in money fields
2. **PnL 83% unrealistic** - double-counting / wrong base
3. **Currency basis** - USDT not normalized
4. **Paper vs truth_report sync** - different sources of truth
5. **QUOTE_GAS_TOO_HIGH dominance** - config/size issue
6. **PRICE_SANITY_FAILED debug** - missing anchor_source
7. **TICKS_CROSSED_TOO_MANY** - needs size policy
8. **Execution layer separation** - economic vs ready
9. **PnL breakdown missing** - no canonical model
10. **Invariant violations not gated**

---

## Implementation Status

### ✅ Roadmap 3.2: No Float Money

**Before:**
```python
amount_in_numeraire: float = 0.0
expected_pnl_numeraire: float = 0.0
total_pnl_usdc: float = 0.0
```

**After:**
```python
amount_in_numeraire: str = "0.000000"  # Decimal-string
expected_pnl_numeraire: str = "0.000000"  # Decimal-string
total_pnl_usdc: str = "0.000000"  # Decimal-string
```

**Functions now return Decimal:**
```python
def calculate_usdc_value(...) -> Decimal:  # Not float!
def calculate_pnl_usdc(...) -> Decimal:    # Not float!
```

### ✅ PnL Normalization Fix

**Problem:** 83% return from double-counting signals
**Solution:** 
1. Cooldown dedup in paper_session
2. PnL only from WOULD_EXECUTE trades
3. Suppression if invariants violated

```python
# Suppression in to_dict()
if violations:
    result["pnl_suppressed"] = True
    result["pnl_suppressed_reason"] = violations[0]
    result["pnl_normalized"]["normalized_return_pct"] = None
    result["pnl_normalized"]["_status"] = "SUPPRESSED_INVARIANT_VIOLATION"
```

### ✅ Invariant Checks Enhanced

```python
def validate_invariants(self) -> list[str]:
    # 1. profitable <= total
    # 2. executable <= profitable (stricter!)
    # 3. signals >= spread_ids
    # 4. execution_ready <= paper_executable
    # 5. PnL consistency (would_execute vs normalized)
    # 6. PnL unrealistic (>50%)
```

### ✅ Tests: NO_FLOAT_MONEY

```python
class TestNoFloatMoney:
    def test_paper_trade_no_float_in_serialization(self)
    def test_truth_report_no_float_pnl(self)
    def test_calculate_usdc_value_returns_decimal(self)
    def test_calculate_pnl_usdc_returns_decimal(self)
    def test_paper_session_stats_no_float(self)
```

---

## Acceptance Criteria Status

| AC | Description | Status |
|----|-------------|--------|
| A | No float money (Roadmap 3.2) | ✅ |
| B | Currency normalization | ✅ USDC only |
| C | PnL normalization correct | ✅ |
| D | SMOKE regression | ✅ |

---

## Files Modified

| File | Changes |
|------|---------|
| `strategy/paper_trading.py` | All money fields as str, Decimal returns |
| `strategy/jobs/run_scan.py` | Decimal-string conversions |
| `monitoring/truth_report.py` | str PnL fields, suppression logic |
| `tests/unit/test_error_contract.py` | +5 NO_FLOAT_MONEY tests |

---

## Key Contract (Roadmap 3.2 Compliant)

```python
# PaperTrade money fields (str, not float)
numeraire: str = "USDC"
amount_in_numeraire: str = "300.000000"
expected_pnl_numeraire: str = "0.840000"
gas_price_gwei: str = "0.01"

# TruthReport PnL fields (str, not float)
total_pnl_usdc: str = "10.500000"
would_execute_pnl_usdc: str = "10.500000"
notion_capital_usdc: str = "10000.000000"
normalized_return_pct: str = "0.1050"  # or None if suppressed
```

---

## Tests: **111 passed** ✅

New tests:
- `test_paper_trade_no_float_in_serialization`
- `test_truth_report_no_float_pnl`
- `test_calculate_usdc_value_returns_decimal`
- `test_calculate_pnl_usdc_returns_decimal`
- `test_paper_session_stats_no_float`

---

## Definition of Done

✅ No float in money fields (Roadmap 3.2)  
✅ Decimal-strings in all serialization  
✅ PnL suppression on invariant violation  
✅ 111 unit tests pass  
✅ NO_FLOAT_MONEY tests added
