# Status: M4 (REAL Pipeline Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-27

## Goal

Run REAL pipeline with live RPC, pinned block, and **truthful metrics**.
Execution remains disabled - only price discovery and validation.

## PNL Contract (Requirement C - Critical)

**All pnl money fields are ALWAYS strings, NEVER None, NEVER float.**

```python
# Guaranteed keys in report_dict["pnl"]:
pnl = {
    "signal_pnl_usdc": "0.000000",      # Always str
    "signal_pnl_bps": "0.00",           # Always str
    "would_execute_pnl_usdc": "0.000000",  # Always str (CRITICAL)
    "would_execute_pnl_bps": "0.00",    # Always str
    "gross_pnl_usdc": "0.000000",       # Always str
    "net_pnl_usdc": "0.000000",         # Always str
    "net_pnl_bps": "0.00",              # Always str
    "cost_model_available": False,      # bool
}

# Guaranteed keys in report_dict["cumulative_pnl"]:
cumulative_pnl = {
    "total_bps": "0.00",   # Always str
    "total_usdc": "0.000000",  # Always str
}

# Guaranteed keys in report_dict["pnl_normalized"]:
pnl_normalized = {
    "notion_capital_numeraire": "10000.000000",  # Always str
    "normalized_return_pct": "0.0000",           # Always str
    "numeraire": "USDC",
}
```

### Contract Rules

1. All money fields in `pnl`, `cumulative_pnl`, `pnl_normalized` are **strings**
2. Keys are **always present** (never missing, never optional)
3. Default value: `"0.000000"` for USDC, `"0.00"` for bps
4. **Never use float** for money fields
5. **Never use None** for money fields

### Validation Test

```python
# tests/unit/test_error_contract.py::TestNoFloatMoneyContract::test_truth_report_pnl_no_float
def test_truth_report_pnl_no_float(self):
    report_dict = report.to_dict()
    # These must ALL be strings:
    self.assertIsInstance(report_dict["pnl"]["signal_pnl_usdc"], str)
    self.assertIsInstance(report_dict["pnl"]["would_execute_pnl_usdc"], str)
```

## Metrics Contract

```
quotes_total    = attempted quote calls
quotes_fetched  = got valid RPC response (amount > 0)
gates_passed    = passed all gates (price sanity, etc.)
dexes_active    = DEXes with at least 1 response
```

## M4 Success Criteria

| Metric | Requirement |
|--------|-------------|
| Python | 3.11.x |
| `run_mode` | `REGISTRY_REAL` |
| `current_block` | `> 0` |
| `execution_enabled` | `false` |
| `quotes_fetched` | `>= 1` |
| `rpc_success_rate` | `> 0` |
| `dexes_active` | `>= 2` |
| `price_sanity_passed` | `>= 1` |
| Artifacts | 4/4 |

## Definition of Done

```powershell
# A. Python version
python --version  # Must be 3.11.x

# B. Import contract
python -c "from monitoring.truth_report import calculate_confidence; print('ok')"

# C. Unit tests (including pnl contract)
python -m pytest -q --ignore=tests/integration

# D. All tests
python -m pytest -q

# E. M4 gate (offline)
python scripts/ci_m4_gate.py --offline --skip-python-check
```

All must pass.

## Known Issues (Resolved)

1. **Missing `would_execute_pnl_usdc`**: Fixed in v3.2.1 - key now always present
2. **pytest-env warning**: Removed `env=` from pyproject.toml (not needed)
3. **pnl fields as None**: Fixed - all money fields now always strings

## Schema Version

Current: `3.2.1`

Changes in 3.2.1:
- Added `would_execute_pnl_usdc` to pnl dict
- All pnl money fields now always strings (never None)
- Removed optional pnl keys - all keys always present
