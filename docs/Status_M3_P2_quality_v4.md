# Status_M3_P2_quality_v4.md — Dev Task: PaperTrading/TruthReport Contract, KPI, Revalidation Semantics

**Дата:** 2026-01-16  
**Milestone:** M3 P2 Quality v4  
**Статус:** ✅ **IMPLEMENTED**

---

## Problem Summary

1. PaperSession.record_trade() накопичувало PnL через `expected_pnl_usdc` (legacy), не `expected_pnl_numeraire`
2. Змішування paper vs real execution readiness
3. truth_report показував `pnl_normalized._status=NOT_CONFIGURED` попри notion_capital в SMOKE
4. Revalidation "GATES_CHANGED" не розрізняло gates vs policy changes

---

## Acceptance Criteria Status

### ✅ AC-1: SMOKE DoD (стабільність)
- Pinned block ≠ null
- quotes_fetched ≥ 1
- truth_report генерується без крашів
- paper_trades генерується без крашів

### ✅ AC-2: TruthReport інваріанти
- `profitable ≤ total` ✅
- `execution_ready_count ≤ paper_executable_count` ✅

### ✅ AC-3: Notional normalization
**Before:**
```json
"pnl_normalized": {"_status": "NOT_CONFIGURED"}
```

**After:**
```json
"pnl_normalized": {
    "notion_capital_numeraire": 10000.0,
    "normalized_return_pct": 0.015,
    "numeraire": "USDC"
}
```

**Changes:**
- `generate_truth_report()` тепер приймає `notion_capital_numeraire` параметр
- `main()` передає `notion_capital_numeraire=10000.0` до generate_truth_report
- `normalized_return_pct` обчислюється: `total_pnl_numeraire / notion_capital * 100`

### ✅ AC-4: Paper vs Real execution policy

**PaperTrade fields:**
```python
economic_executable: bool = True        # Passes gates + PnL > 0
paper_execution_ready: bool = True      # economic + paper policy
real_execution_ready: bool = False      # economic + verified + !blocked
blocked_reason_real: str | None = None  # WHY not real_execution_ready
```

**In JSONL:**
```json
{
    "paper_execution_ready": true,
    "real_execution_ready": false,
    "blocked_reason_real": "EXEC_DISABLED_NOT_VERIFIED"
}
```

### ✅ AC-5: PaperTrade v4 contract

**Source of truth:** `*_numeraire` fields
```python
numeraire: str = "USDC"
amount_in_numeraire: float = 0.0
expected_pnl_numeraire: float = 0.0
```

**Legacy support:**
```python
@property
def amount_in_usdc(self) -> float:
    return self.amount_in_numeraire if self.numeraire == "USDC" else ...

def from_dict(cls, data: dict) -> "PaperTrade":
    normalized = normalize_paper_trade_kwargs(data)  # Handles legacy
    return cls(**normalized)
```

**PaperSession.record_trade():**
```python
# NOW: Uses numeraire (source of truth)
self.stats["total_pnl_numeraire"] += trade.expected_pnl_numeraire

# BEFORE: Used legacy
self.stats["total_pnl_usdc"] += trade.expected_pnl_usdc  # WRONG
```

### ✅ AC-6: Revalidation KPI коректний

**PaperTrade revalidation fields:**
```python
would_still_paper_execute: bool | None = None
would_still_real_execute: bool | None = None
gates_actually_changed: bool = False  # True only if PnL changed
```

**mark_revalidated() logic:**
```python
# AC-6: Gates changed = PnL changed
gates_changed = (pending_trade.net_pnl_bps != net_pnl_bps)

# GATES_CHANGED outcome ONLY if gates actually changed
if gates_actually_changed and not would_still_paper_execute:
    trade.outcome = TradeOutcome.GATES_CHANGED.value
```

### ✅ AC-7: Тести

**New tests added (42 total):**
- `test_paper_trade_from_dict_accepts_legacy` - AC-7
- `test_paper_trade_ac4_paper_vs_real_readiness` - AC-4
- `test_paper_trade_ac6_revalidation_fields` - AC-6

---

## Files Modified

| File | Changes |
|------|---------|
| `strategy/paper_trading.py` | +paper_execution_ready, +real_execution_ready, +blocked_reason_real, +would_still_paper_execute, +would_still_real_execute, +gates_actually_changed, updated record_trade() to use numeraire |
| `strategy/jobs/run_scan.py` | +notion_capital_numeraire param, AC-4 paper vs real in PaperTrade creation |
| `monitoring/truth_report.py` | +notion_capital_numeraire param, +normalized_return_pct calculation |
| `tests/unit/test_error_contract.py` | +4 new AC tests |

---

## Key Semantics

| Field | Description |
|-------|-------------|
| `economic_executable` | Gates pass + PnL > 0 |
| `paper_execution_ready` | economic (ignores verification) |
| `real_execution_ready` | economic + verified |
| `blocked_reason_real` | Why not real_execution_ready |
| `gates_actually_changed` | True only if quotes/PnL changed |

---

## Tests: **42 passed** ✅
