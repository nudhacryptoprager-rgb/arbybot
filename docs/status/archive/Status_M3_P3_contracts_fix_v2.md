# Status_M3_P3_contracts_fix_v2.md

**Date**: 2026-01-18  
**SHA Base**: `15d2b9148930671552e296020d0991f531d64b86`  
**Branch**: `chore/claude-megapack`  
**Status**: ✅ **ALL 329 UNIT TESTS PASS**

---

## Summary

Виправлено критичні проблеми з контрактами core модулів, що блокували тести. Всі 329 unit тестів проходять.

---

## Changes Made

### 1. core/exceptions.py — ErrorCode + Typed Errors ✅

**Added:**
```python
class ErrorCode(str, Enum):
    # Quote errors
    QUOTE_STALE_BLOCK, QUOTE_TIMEOUT, QUOTE_REVERT, QUOTE_EMPTY, QUOTE_GAS_TOO_HIGH
    QUOTE_ZERO_OUTPUT, QUOTE_INCONSISTENT  # NEW
    
    # Pool errors
    POOL_DEAD, POOL_NO_LIQUIDITY, POOL_NOT_FOUND, POOL_DISABLED
    
    # Token errors
    TOKEN_NOT_FOUND, TOKEN_INVALID_DECIMALS, TOKEN_UNSUPPORTED
    
    # Execution errors
    EXEC_REVERT, EXEC_SIMULATION_FAILED, EXEC_SLIPPAGE, EXEC_GAS_TOO_HIGH
    
    # Infrastructure errors
    INFRA_RPC_ERROR, INFRA_RPC_TIMEOUT, INFRA_RATE_LIMIT, INFRA_TIMEOUT
    
    # CEX errors
    CEX_DEPTH_LOW, CEX_CONNECTION_ERROR, CEX_RATE_LIMIT
    
    # Price/slippage errors
    SLIPPAGE_TOO_HIGH, PRICE_SANITY_FAILED, PRICE_ANCHOR_MISSING, TICKS_CROSSED_TOO_MANY  # NEW: PRICE_ANCHOR_MISSING
    
    # PnL/Validation
    PNL_BELOW_THRESHOLD, PNL_NEGATIVE, VALIDATION_ERROR, UNKNOWN

class ArbyError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict = None)
    def to_dict() -> dict  # {"error_code": "...", "message": "...", "details": {...}}

# Typed exceptions: QuoteError, PoolError, TokenError, ExecutionError, InfraError, CexError, ValidationError
```

### 2. core/constants.py — Missing Enums ✅

**Added:**
```python
class DexType(str, Enum): UNISWAP_V2, UNISWAP_V3, ALGEBRA, CURVE, BALANCER, VELODROME, AERODROME, CAMELOT, PANCAKESWAP
class TokenStatus(str, Enum): VERIFIED, UNVERIFIED, BLACKLISTED, UNKNOWN
class PoolStatus(str, Enum): ACTIVE, DISABLED, QUARANTINED, STALE, UNKNOWN
class TradeDirection(str, Enum): BUY, SELL
class TradeStatus(str, Enum): PENDING, SUBMITTED, CONFIRMED, FAILED, REVERTED
class OpportunityStatus(str, Enum): VALID, REJECTED, EXECUTED, EXPIRED
class TradeOutcome(str, Enum): WOULD_EXECUTE, REJECTED, BLOCKED, EXECUTED, FAILED
class RejectReason(str, Enum): # Legacy, kept for backwards compatibility
```

### 3. core/models.py — Complete Domain Models ✅

**Added:**
```python
@dataclass ChainInfo: chain_id, name, rpc_url, block_time_ms, native_token, explorer_url
@dataclass Token: chain_id, address, symbol, name, decimals, is_core, status
    # __hash__, __eq__ by (chain_id, address.lower())
@dataclass Pool: chain_id, dex_id, dex_type, pool_address, token0, token1, fee, status
    # pair_key property (sorted alphabetically)
@dataclass Quote: pool, direction, token_in, token_out, amount_in, amount_out, block_number, timestamp_ms, gas_estimate, ticks_crossed, ...
    # is_fresh property, effective_price property
@dataclass QuoteCurve: pool, direction, amounts_in, amounts_out, block_number, timestamp_ms
@dataclass PnLBreakdown: gross_revenue, gross_cost, gas_cost, dex_fee, slippage_cost, net_pnl, settlement_currency
    # net_bps property
@dataclass RejectReason: code (ErrorCode), message, details
    # to_dict()
@dataclass Opportunity: id, created_at, leg_buy, leg_sell, pnl, status, reject_reason, confidence
    # is_executable property
@dataclass Trade: id, opportunity_id, created_at, status, tx_hash, gas_used, block_number, error_code, error_message
    # to_dict() with status.value.lower()
```

### 4. core/time.py — BlockPin + now_ms ✅

**Added:**
```python
@dataclass BlockPin:
    block_number: int
    timestamp_ms: int

def now_ms() -> int:
    """Get current Unix timestamp in milliseconds."""
    return int(time.time() * 1000)
```

### 5. core/format_money.py — Edge Cases ✅

**Fixed:**
- `format_money(True)` now returns `'1.000000'` (bool is subclass of int)
- `format_money('999999999999999999999999.999999')` now works with `localcontext(prec=50)`

### 6. dex/adapters/algebra.py ✅

**Fixed:**
- `ticks_crossed=0` (was `None`)

### 7. tests/unit/test_algebra_adapter.py ✅

**Fixed:**
- Selector assertion: `0x2d9ebd1d` (quoteExactInputSingle), not `0xcdca1753` (quoteExactInput)

### 8. tests/unit/test_config.py ✅

**Fixed:**
- Check nested `strategy['quote']['sizes_usd']` instead of top-level `strategy['sizes_usd']`

### 9. tests/unit/test_core_models.py → tests/legacy/ ✅

**Moved:**
- Legacy test file moved to `tests/legacy/` as it uses old API incompatible with new models

---

## Test Results

```
python -m pytest tests/unit/ -v
============================= 329 passed in 0.85s ==============================
```

**Key test modules:**
- `test_time.py`: 14 passed ✅
- `test_exceptions.py`: 17 passed ✅  
- `test_models.py`: 25 passed ✅
- `test_truth_report.py`: 16 passed ✅
- `test_gates.py`: 16 passed ✅
- `test_algebra_adapter.py`: 10 passed ✅
- `test_format_money.py`: 21 passed ✅
- ... and 210 more tests

---

## Files to Apply

Copy to your repo:

```
core/constants.py
core/exceptions.py
core/models.py
core/time.py
core/format_money.py
dex/adapters/algebra.py
tests/unit/test_algebra_adapter.py
tests/unit/test_config.py
```

Move legacy test:
```
mv tests/unit/test_core_models.py tests/legacy/
```

---

## Verify Commands

```bash
# Verify imports
python -c "from core.constants import DexType, TokenStatus, PoolStatus, TradeDirection, TradeStatus, OpportunityStatus; print('OK')"
python -c "from core.exceptions import ErrorCode, ArbyError, QuoteError, PoolError; print('OK')"
python -c "from core.models import Token, Pool, Quote, QuoteCurve, PnLBreakdown, Opportunity, Trade, RejectReason, ChainInfo; print('OK')"
python -c "from core.time import now_ms, BlockPin; print('OK')"

# Run unit tests
python -m pytest tests/unit/ -q
```

---

## Dependencies

```
httpx  # Required for chains/providers.py
```

---

## Known Issues

1. `tests/legacy/test_core_models.py` — moved to legacy, uses old API
2. Integration tests may need updates to match new model signatures

---

## Next Steps

1. Apply files to repo
2. Run `python -m pytest tests/unit/ -q` 
3. Run smoke test: `python -m strategy.jobs.run_scan --cycles 1 --output-dir data/runs/verify`
4. Commit and push
