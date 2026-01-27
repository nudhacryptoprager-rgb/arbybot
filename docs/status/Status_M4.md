# Status: M4 (REAL Pipeline Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-27

## Goal

Run REAL pipeline with live RPC, pinned block, and **truthful metrics**.
Execution remains disabled - only price discovery and validation.

## 10 Critical Issues Addressed

| # | Issue | Fix |
|---|-------|-----|
| 1 | TruthReport profit misleading | STEP 6: Cost breakdown, NO_COST_MODEL flag |
| 2 | Confidence metric inconsistent | STEP 5: price_stability_factor formula fix |
| 3 | PRICE_SANITY decimals bug | STEP 7: Debug logging + diagnostics |
| 4 | CI gate Windows encoding | STEP 3: ASCII-only output |
| 5 | Online RPC in tests | STEP 8: Offline fixtures default |
| 6 | Import contract fragility | STEP 4: Stable API + tests |
| 7 | Python version drift | STEP 1: Pin 3.11.x permanently |
| 8 | venv inconsistency | STEP 2: Unified .venv |
| 9 | Execution signals unclear | STEP 9: is_actionable + blockers |
| 10 | Roadmap drift | STEP 10: Skeleton stubs |

## Python Version (STEP 1)

**ARBY requires Python 3.11.x**

```yaml
# pyproject.toml
requires-python = ">=3.11,<3.12"

# .python-version
3.11.9
```

Setup:
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Metrics Contract

```
quotes_total    = attempted quote calls
quotes_fetched  = got valid RPC response (amount_out > 0)
gates_passed    = passed all gates (price sanity, etc.)
dexes_active    = DEXes with at least 1 response
```

### Invariants

1. `gates_passed <= quotes_fetched <= quotes_total`
2. If `sample_rejects` has entries with `price != null`, then `quotes_fetched > 0`
3. If `price_sanity_passed > 0`, then `price_stability_factor > 0`

## Confidence Formula (STEP 5)

```python
def calculate_price_stability_factor(
    price_sanity_passed: int,
    quotes_fetched: int,
    price_sanity_failed: int = 0,
) -> float:
    """Never returns 0.0 if price_sanity_passed > 0."""
    if quotes_fetched <= 0:
        return 0.5  # Neutral
    if price_sanity_passed > 0:
        total = price_sanity_passed + price_sanity_failed
        return min(1.0, price_sanity_passed / total) if total > 0 else 0.5
    return 0.0 if price_sanity_failed > 0 else 0.5
```

## Profit Breakdown (STEP 6)

**Truthful profit requires:**

```json
{
  "gross_pnl_usdc": "5.000000",
  "gas_estimate_usdc": null,
  "slippage_estimate_usdc": null,
  "net_pnl_usdc": null,
  "cost_model_available": false
}
```

- If `cost_model_available: false`, `net_pnl_usdc` MUST be `null`
- NO_COST_MODEL blocker added to opportunities
- Never show "fake net profit"

## Execution Semantics (STEP 9)

```json
{
  "execution_enabled": false,
  "execution_blocker": "EXECUTION_DISABLED_M4",
  "top_opportunities": [
    {
      "is_actionable": false,
      "execution_blockers": ["EXECUTION_DISABLED_M4", "NO_COST_MODEL"]
    }
  ]
}
```

- `is_actionable: false` for all signal-only opportunities
- `execution_blocker` explains why disabled

## CI Gate (STEP 3, 8)

```powershell
# Default: offline with fixtures (no network)
python scripts/ci_m4_gate.py --offline

# Live RPC (requires network)
python scripts/ci_m4_gate.py --online
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | Unit tests failed |
| 2 | REAL scan failed |
| 3 | Artifacts missing |
| 4 | M4 invariants failed |
| 6 | Metrics contract violation |
| 7 | Confidence inconsistent (STEP 5) |
| 8 | Profit not truthful (STEP 6) |
| 9 | Execution semantics invalid (STEP 9) |
| 10 | Wrong Python version |
| 11 | Import contract broken |

## Import Contract (STEP 4)

These imports MUST work:

```python
from monitoring.truth_report import calculate_confidence
from monitoring.truth_report import RPCHealthMetrics
from monitoring.truth_report import TruthReport
from monitoring.truth_report import build_truth_report
from monitoring import calculate_confidence
```

## M4 Success Criteria

| Metric | Requirement |
|--------|-------------|
| Python | 3.11.x |
| `run_mode` | `REGISTRY_REAL` |
| `current_block` | `> 0` |
| `execution_enabled` | `false` |
| `execution_ready_count` | `== 0` |
| `quotes_fetched` | `>= 1` |
| `rpc_success_rate` | `> 0` |
| `dexes_active` | `>= 2` |
| `price_sanity_passed` | `>= 1` |
| `price_stability_factor` | `> 0` when sanity_passed > 0 |
| `cost_model_available` | Field present |
| Artifacts | 4/4 |

## Definition of Done

```powershell
# A. Python version
python --version  # Must be 3.11.x

# B. Import contract
python -c "from monitoring.truth_report import calculate_confidence; print('ok')"

# C. Unit tests
python -m pytest -q --ignore=tests/integration

# D. M4 gate (offline)
python scripts/ci_m4_gate.py --offline
```

All must pass.

## M4 Execution Skeleton (STEP 10)

Minimal stubs for future M5:

```
strategy/execution/
├── __init__.py
├── state_machine.py    # States: IDLE, SCANNING, VALIDATING, EXECUTING
├── simulator_gate.py   # Pre-execution validation stub
├── accounting.py       # Post-trade record placeholder
└── kill_switch.py      # Emergency stop config
```

All disabled by config, but structure exists.

## Known Issues

1. **Price 9.7**: Some pools return inverted prices. Fixed by proper decimals handling.
2. **quotes_fetched=0 with prices**: Fixed by separating `rpc_success` from `gate_passed`.
3. **Confidence 0.0 when sanity_passed > 0**: Fixed with `calculate_price_stability_factor`.

## Next Steps (M5)

1. Tighten `price_sanity_max_deviation_bps` to 1000 (10%)
2. Implement cost model (gas estimation)
3. Enable paper trade execution
4. Add slippage estimation
5. Activate state machine
