# PATH: docs/TESTING.md
# ARBY Testing Guide

## Test Structure
```
tests/
├── __init__.py
├── conftest.py              # Pytest configuration
├── unit/                    # Unit tests
│   ├── __init__.py
│   ├── test_algebra_adapter.py   # Algebra DEX adapter
│   ├── test_confidence.py        # calculate_confidence
│   ├── test_config.py            # Configuration loading
│   ├── test_core_models.py       # Token/Pool/Quote models
│   ├── test_edge_cases.py        # Edge case handling
│   ├── test_error_contract.py    # Issue #3 AC tests
│   ├── test_exceptions.py        # Exception classes
│   ├── test_format_money.py      # Money formatting
│   ├── test_gates.py             # Gate validation
│   ├── test_health_metrics.py    # RPC health consistency
│   ├── test_logging_contract.py  # Logging API enforcement
│   ├── test_math.py              # Math utilities
│   ├── test_models.py            # Data models
│   ├── test_paper_trading.py     # PaperSession/PaperTrade
│   ├── test_registry.py          # Pool registry
│   ├── test_spread.py            # Spread calculations
│   ├── test_time.py              # Time utilities
│   ├── test_truth_report.py      # TruthReport
│   └── test_validators.py        # Input validators
└── integration/             # Integration tests
    ├── __init__.py
    └── test_smoke_run.py    # Full SMOKE run test
```

## Running Tests

### All Unit Tests
```bash
python -m pytest tests/unit/ -v
```

### Specific Test File
```bash
python -m pytest tests/unit/test_error_contract.py -v
```

### Tests with Coverage
```bash
python -m pytest tests/unit/ --cov=core --cov=strategy --cov=monitoring --cov-report=html
```

### Run Core Contract Tests
```bash
python -m pytest tests/unit/test_core_models.py tests/unit/test_exceptions.py -v
```

## Test Categories

### Issue #3 Acceptance Criteria Tests

| AC | Test File | Description |
|----|-----------|-------------|
| A) Logging API | `test_error_contract.py` | Verifies extra={"context": {...}} usage |
| A) Logging API | `test_logging_contract.py` | Enforces logging contract |
| B) Money formatting | `test_error_contract.py` | Tests safe money formatting |
| B) Money formatting | `test_format_money.py` | Tests format_money functions |
| C) No-float money | `test_error_contract.py` | Verifies no float in money fields |
| D) RPC consistency | `test_error_contract.py` | Tests RPC health reconciliation |
| D) RPC consistency | `test_health_metrics.py` | Tests health metrics consistency |

### Core Model Tests

| File | Tests |
|------|-------|
| `test_core_models.py` | Token, Pool, Quote dataclasses |
| `test_algebra_adapter.py` | Algebra DEX adapter with correct selector (0x2d9ebd1d) |

## SMOKE Test

### Run SMOKE Simulator
```bash
# Explicit smoke mode
python -m strategy.jobs.run_scan --smoke --cycles 1 --output-dir data/runs/smoke_test

# Or use smoke runner directly
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data/runs/smoke_test
```

### Verify SMOKE Artifacts
```bash
# Check for required files
ls data/runs/smoke_test/
# Should have: scan.log, reports/, snapshots/

# Check for paper_trades.jsonl (if WOULD_EXECUTE trades occurred)
cat data/runs/smoke_test/paper_trades.jsonl

# Check for crashes
grep -E "Traceback|ValueError|TypeError" data/runs/smoke_test/scan.log
```

## Common Test Patterns

### Testing No-Float Enforcement
```python
def test_no_float_in_output(self):
    result = some_function()
    float_paths = validate_no_float(result)
    self.assertEqual(float_paths, [], f"Found floats at: {float_paths}")
```

### Testing Logging Context
```python
def test_uses_extra_context(self):
    # Capture log records
    records = []
    handler = CapturingHandler(records)
    logger.addHandler(handler)
    
    # Trigger logging
    some_function_that_logs()
    
    # Verify context
    self.assertTrue(hasattr(records[0], "context"))
```

## Verifying Core Contracts

After making changes to core/, run:
```bash
# Test constants (DexType, PoolStatus, ErrorCode)
python -c "from core.constants import DexType, PoolStatus, ErrorCode; print('OK')"

# Test models (Token, Pool, Quote)
python -c "from core.models import Token, Pool, Quote; print('OK')"

# Test exceptions (QuoteError with ErrorCode)
python -c "from core.exceptions import QuoteError; from core.constants import ErrorCode; QuoteError(code=ErrorCode.QUOTE_REVERT, message='test'); print('OK')"

# Run full unit tests
python -m pytest tests/unit/ -v --tb=short
```
