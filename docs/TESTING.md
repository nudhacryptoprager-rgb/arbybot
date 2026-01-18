# PATH: docs/TESTING.md
# ARBY Testing Guide

## Test Structure
```
tests/
├── __init__.py
├── conftest.py              # Pytest configuration
├── unit/                    # Unit tests
│   ├── __init__.py
│   ├── test_error_contract.py    # Issue #3 AC tests
│   ├── test_paper_trading.py     # PaperSession/PaperTrade
│   ├── test_confidence.py        # calculate_confidence
│   ├── test_format_money.py      # Money formatting
│   ├── test_truth_report.py      # TruthReport
│   ├── test_rounding.py          # ROUND_HALF_UP verification
│   ├── test_health_metrics.py    # RPC health consistency
│   ├── test_logging_contract.py  # Logging API enforcement
│   ├── test_decimal_safety.py    # No-float enforcement
│   ├── test_integration.py       # End-to-end tests
│   └── test_backwards_compat.py  # API compatibility
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

### Required Tests for Issue #3
```bash
python -m pytest tests/unit/test_error_contract.py tests/unit/test_paper_trading.py tests/unit/test_confidence.py -v
```

## Test Categories

### Issue #3 Acceptance Criteria Tests

| AC | Test File | Test Class/Method |
|----|-----------|-------------------|
| A) Logging API | `test_error_contract.py` | `TestLoggingAPICorrectness` |
| A) Logging API | `test_logging_contract.py` | `TestLoggingContractEnforcement` |
| B) Money formatting | `test_error_contract.py` | `TestMoneyFormattingSafety` |
| B) Rounding | `test_rounding.py` | `TestRoundingHalfUp` |
| C) No-float money | `test_error_contract.py` | `TestNoFloatMoneyContract` |
| C) No-float money | `test_decimal_safety.py` | `TestDecimalSafetyInPaperTrading` |
| D) RPC consistency | `test_error_contract.py` | `TestRPCHealthConsistency` |
| D) RPC consistency | `test_health_metrics.py` | `TestRPCHealthReconciliation` |

### Critical Rounding Test

Per Issue #3: `Decimal("0.005")` with 2 decimals must become `"0.01"`.
```python
# From test_rounding.py
def test_point_five_rounds_up(self):
    result = format_money_short(Decimal("0.005"))
    self.assertEqual(result, "0.01")  # MUST pass
```

## SMOKE Test

### Run SMOKE
```bash
python -m strategy.jobs.run_scan --cycles 1 --output-dir data/runs/smoke_test
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

### Testing Rounding
```python
def test_round_half_up(self):
    # 0.005 -> 0.01 (not 0.00 as ROUND_HALF_EVEN would give)
    self.assertEqual(format_money_short("0.005"), "0.01")
    
    # 0.025 -> 0.03 (not 0.02 as ROUND_HALF_EVEN would give)
    self.assertEqual(format_money_short("0.025"), "0.03")
```