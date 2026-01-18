# PATH: docs/ISSUE_3_CHECKLIST.md
# Issue #3 - M3 Quality v4 Checklist

## Acceptance Criteria Status

### A) Logging API correctness
- [x] No calls like `logger.error(..., spread_id=..., ...)` anywhere
- [x] All contextual fields passed only via `extra={"context": {...}}`
- [x] Unit test: "logger forbids kwargs; only extra context is allowed"

### B) Money formatting safety
- [x] Introduced `format_money(x) -> str` that safely formats str|Decimal|int
- [x] Never use `:.2f` directly on money fields in logging
- [x] Unit test: `record_trade()` must not crash when money fields are strings
- [x] Fix rounding: `Decimal("0.005")` with 2 decimals → `"0.01"` (ROUND_HALF_UP)

### C) No-float money (Roadmap 3.2 compliance)
- [x] Remove float conversions from `calculate_usdc_value`
- [x] Remove float conversions from `calculate_pnl_usdc`
- [x] Remove float conversions from session stats
- [x] Canonical representation: string (Decimal-string) in memory/serialization
- [x] Unit test: "no float money in paper_trades dict/stats"

### D) RPC health consistency
- [x] If `reject_histogram` has `INFRA_RPC_ERROR > 0`, then `rpc_total_requests > 0`
- [x] Added `RPCHealthMetrics.reconcile_with_rejects()` method
- [x] `truth_report` does not show "0 requests" when RPC rejects are present

### E) Paper trades file creation
- [x] SMOKE run creates `paper_trades.jsonl` in runDir when `paper_would_execute=true`
- [x] File is JSONL format (one JSON object per line)
- [x] Each trade record has no float values in money fields

## Files Modified/Created

### Core
- `core/__init__.py` - Package exports
- `core/format_money.py` - **NEW** - Safe money formatting with ROUND_HALF_UP
- `core/constants.py` - **NEW** - Enums and constants
- `core/exceptions.py` - **NEW** - Typed exceptions
- `core/math.py` - **NEW** - Safe Decimal math utilities
- `core/models.py` - **NEW** - Data models (Quote, Opportunity, Trade)
- `core/time.py` - **NEW** - Time/freshness utilities
- `core/logging.py` - **NEW** - Structured logging

### Strategy
- `strategy/__init__.py` - Package exports
- `strategy/paper_trading.py` - **MODIFIED** - Fixed money formatting, logging API
- `strategy/jobs/__init__.py` - Package exports
- `strategy/jobs/run_scan.py` - **MODIFIED** - Fixed logging API, creates paper_trades.jsonl

### Monitoring
- `monitoring/__init__.py` - Package exports
- `monitoring/truth_report.py` - **MODIFIED** - RPC health consistency, string money fields

### Tests
- `tests/unit/test_error_contract.py` - **NEW** - Logging API + money formatting tests
- `tests/unit/test_paper_trading.py` - **NEW** - PaperSession/PaperTrade tests
- `tests/unit/test_confidence.py` - **NEW** - calculate_confidence tests
- `tests/unit/test_format_money.py` - **NEW** - format_money tests
- `tests/unit/test_truth_report.py` - **NEW** - TruthReport tests
- `tests/unit/test_rounding.py` - **NEW** - ROUND_HALF_UP verification
- `tests/unit/test_integration.py` - **NEW** - End-to-end tests
- `tests/unit/test_decimal_safety.py` - **NEW** - No-float enforcement tests
- `tests/unit/test_backwards_compat.py` - **NEW** - API compatibility tests

## Verification Commands (PowerShell)
```powershell
# Run required tests
python -m pytest tests/unit/test_error_contract.py -v
python -m pytest tests/unit/test_paper_trading.py -v  
python -m pytest tests/unit/test_confidence.py -v

# Run all unit tests
python -m pytest tests/unit/ -v

# Run SMOKE test
python -m strategy.jobs.run_scan --cycles 1 --output-dir data/runs/verify

# Verify artifacts
Get-ChildItem data/runs/verify/
Get-ChildItem data/runs/verify/paper_trades.jsonl
Select-String -Path data/runs/verify/scan.log -Pattern "Traceback|ValueError|TypeError"
```

## Key Fixes Summary

1. **ValueError crash**: Changed `f"{value:.2f}"` to `f"{format_money_short(value)}"`
2. **TypeError crash**: Changed `logger.error(..., spread_id=x)` to `logger.error(..., extra={"context": {"spread_id": x}})`
3. **RPC inconsistency**: Added `RPCHealthMetrics.reconcile_with_rejects()` 
4. **Rounding**: Uses `ROUND_HALF_UP` so `0.005` → `0.01` (not banker's rounding)
5. **No-float**: All money fields stored/serialized as strings