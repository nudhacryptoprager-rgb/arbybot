# Status_M3_P2_quality_v4.md — Dev Task: Paper Trading Contract + Truth Report Semantics

**Дата:** 2026-01-16  
**Milestone:** M3 P2 Quality v4 - SMOKE Stability  
**Статус:** ✅ **IMPLEMENTED**

---

## Dev Task Summary

Виправлення критичного бага:
```
TypeError: PaperTrade.__init__() got an unexpected keyword argument 'amount_in_usdc'
```

---

## Requirements Implemented (R1-R6)

### ✅ R1: PaperTrade Contract Compatibility

**Legacy kwargs support:**
```python
# Old code (was breaking)
PaperTrade(..., amount_in_usdc=300.0, expected_pnl_usdc=0.84)

# New code (works!)
PaperTrade.from_legacy_kwargs(..., amount_in_usdc=300.0, expected_pnl_usdc=0.84)
# Auto-mapped to: amount_in_numeraire=300.0, expected_pnl_numeraire=0.84, numeraire="USDC"
```

**Helper function:**
```python
def normalize_paper_trade_kwargs(kwargs: dict) -> dict:
    """Maps legacy amount_in_usdc/expected_pnl_usdc to numeraire fields."""
```

**Legacy property aliases:**
```python
@property
def amount_in_usdc(self) -> float:
    """Legacy alias for amount_in_numeraire (when numeraire is USDC)."""
    return self.amount_in_numeraire if self.numeraire == "USDC" else ...
```

### ✅ R2: Correct token_in/token_out Semantics

**Before (BUG):**
```python
token_in="WETH",   # HARDCODED!
token_out="USDC",  # WRONG for WETH/ARB spread!
```

**After (FIX):**
```python
actual_token_in = spread_data.get("token_in_symbol", token_in_symbol)
actual_token_out = spread_data.get("token_out_symbol", token_out_symbol)
token_in=actual_token_in,   # Correct: WETH
token_out=actual_token_out, # Correct: ARB (for WETH/ARB spread)
```

### ✅ R3: Separate Economic vs Execution Ready

**PaperTrade fields:**
```python
economic_executable: bool = True    # Passes gates + PnL > 0
execution_ready: bool = False       # + verified + !blocked
blocked_reason: str | None = None   # WHY not execution_ready
```

**Logic in run_scan.py:**
```python
economic_executable = executable and net_pnl_bps > 0
execution_ready = economic_executable and buy_exec and sell_exec
if economic_executable and not execution_ready:
    blocked_reason = "EXEC_DISABLED_NOT_VERIFIED"
```

### ✅ R4: Robustness - Paper Trading Never Crashes Scan

**try/except wrapper:**
```python
try:
    paper_trade = PaperTrade.from_legacy_kwargs(...)
    paper_session.record_trade(paper_trade)
except Exception as paper_err:
    logger.error("Paper trade creation failed", error=str(paper_err))
    paper_errors += 1
    # Continue with next spread - cycle NOT crashed
```

### ✅ R5: RPC Health Not Misleading

**HealthMetrics updated:**
```python
@dataclass
class HealthMetrics:
    rpc_total_requests: int
    rpc_failed_requests: int = 0  # NEW: Track failures explicitly
    
    def validate_rpc_health(self) -> list[str]:
        """Validate RPC health is not misleading."""
        # Check: rpc_total_requests should not be 0 if failures occurred
```

### ✅ R6: Truth Report Ranking Semantics

**Before (wrong):**
```python
# Filtered by execution policy (missed economic opportunities)
ranked_executable = [r for r in ranked if r["spread"].get("executable", False)]
```

**After (correct):**
```python
# Ranking by economic signals, not execution policy
ranked_economic = [
    r for r in ranked 
    if r["spread"].get("net_pnl_bps", 0) > 0  # Economic criterion
]
# Then display: economic_executable, paper_would_execute, execution_ready, blocked_reason
```

---

## Acceptance Criteria Status

| AC | Description | Status |
|----|-------------|--------|
| AC1 | No crash on `run_scan --mode SMOKE` | ✅ |
| AC2 | Paper trades recorded correctly | ✅ |
| AC3 | Backward compatibility for legacy kwargs | ✅ |
| AC4 | Truth report invariants hold | ✅ |
| AC5 | RPC health not misleading | ✅ |

---

## Tests

**101 passed** ✅

New tests added:
- `test_paper_trade_legacy_kwargs_support` - AC3
- `test_paper_trade_r3_economic_vs_execution` - R3
- `test_paper_trade_normalize_kwargs` - R1
- `test_ac4_invariant_execution_ready_lte_paper_would_execute` - AC4

---

## Files Modified

| File | Changes |
|------|---------|
| `strategy/paper_trading.py` | +from_legacy_kwargs(), +normalize_paper_trade_kwargs(), +economic_executable, +execution_ready, +blocked_reason, +legacy aliases |
| `strategy/jobs/run_scan.py` | +try/except for R4, +actual_token_in/out for R2, +from_legacy_kwargs() call |
| `monitoring/truth_report.py` | +rpc_failed_requests for R5, +economic ranking for R6 |
| `tests/unit/test_error_contract.py` | +8 new tests for AC1-AC5 |

---

## Contract Summary

```python
# PaperTrade now supports:
PaperTrade(
    # Required
    spread_id="WETH/ARB:uniswap_v3:sushiswap_v3:500",
    token_in="WETH",       # MUST match pair!
    token_out="ARB",       # MUST match pair!
    
    # Numeraire (new)
    numeraire="USDC",
    amount_in_numeraire=300.0,
    expected_pnl_numeraire=0.84,
    
    # Execution status (R3)
    economic_executable=True,
    execution_ready=False,
    blocked_reason="EXEC_DISABLED_NOT_VERIFIED",
)

# Legacy support (R1)
PaperTrade.from_legacy_kwargs(
    amount_in_usdc=300.0,       # Auto-mapped to amount_in_numeraire
    expected_pnl_usdc=0.84,     # Auto-mapped to expected_pnl_numeraire
)
```
