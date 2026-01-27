# Status: M4 (REAL Pipeline Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-27

## Goal

Run REAL pipeline with live RPC, pinned block, and **truthful metrics**.
Execution remains disabled - only price discovery and validation.

## PNL Contract

**SCHEMA_VERSION = "3.2.0"**

### Rules

1. `signal_pnl_usdc`, `would_execute_pnl_usdc`: **always str**
2. `net_pnl_usdc`: **None when cost_model_available=False**, str otherwise
3. Keys always present in `pnl` dict

```python
# When cost_model_available=False:
pnl = {
    "signal_pnl_usdc": "5.000000",      # str
    "would_execute_pnl_usdc": "5.000000", # str
    "gross_pnl_usdc": "5.000000",       # str
    "net_pnl_usdc": None,               # None (no cost model)
    "net_pnl_bps": None,                # None
    "cost_model_available": False,
}

# When cost_model_available=True:
pnl = {
    "signal_pnl_usdc": "5.000000",      # str
    "would_execute_pnl_usdc": "4.500000", # str
    "gross_pnl_usdc": "5.000000",       # str
    "net_pnl_usdc": "4.500000",         # str (calculated)
    "net_pnl_bps": "12.86",             # str
    "cost_model_available": True,
}
```

### Validation Test

```python
# tests/unit/test_truth_report.py::TestProfitBreakdown::test_net_pnl_none_without_cost_model
def test_net_pnl_none_without_cost_model(self):
    report = build_truth_report(..., cost_model_available=False)
    self.assertIsNone(report.pnl.get("net_pnl_usdc"))
```

## Metrics Contract

```
quotes_total    = attempted quote calls
quotes_fetched  = got RPC response (amount > 0)
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

# C. Unit tests
python -m pytest -q --ignore=tests/integration

# D. All tests
python -m pytest -q

# E. M4 gate (offline)
python scripts/ci_m4_gate.py --offline --skip-python-check
```

All must pass.

## Schema Version History

- `3.2.0`: Current. net_pnl_usdc=None when cost_model_available=False
- `3.1.0`: PnL split (signal vs would_execute)
