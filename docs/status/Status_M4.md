# Status: Milestone 4 (M4) — Execution Layer (Phase 1: REAL Pipeline)

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-23  
**Branch:** `split/code`  
**Depends On:** M3 (DONE)

## Overview

M4 Phase 1 focuses on REAL RPC pipeline (execution disabled):
- Real quotes from configured RPC providers
- Pinned block invariant
- Real reject reasons in histogram
- Same artifact contract as M3

## M4 Definition of Done

```
⬜ python scripts/ci_m4_gate.py       → PASS
⬜ --mode real runs pipeline (no execution)
⬜ Real RPC quotes (1 chain × 1-2 DEX × 1-2 pairs)
⬜ Pinned block invariant enforced
⬜ Real reject reasons in histogram
⬜ Same 4 artifacts as M3:
   - snapshots/scan_*.json
   - reports/reject_histogram_*.json
   - reports/truth_report_*.json
   - scan.log
```

## Commands

```powershell
# Activate venv (assumes M3 setup done)
.\venv\Scripts\Activate.ps1

# Run M3 gate (should still pass)
python scripts/ci_m3_gate.py

# Run M4 gate (will fail until REAL implemented)
python scripts/ci_m4_gate.py

# Manual REAL run (once implemented)
python -m strategy.jobs.run_scan --mode real --cycles 1 --output-dir data/runs/m4_test
```

## Implementation Checklist

### Phase 1: REAL Pipeline (Current)

- [ ] Remove "not yet implemented" from `--mode real`
- [ ] Run same pipeline as SMOKE but with real providers
- [ ] Add `REGISTRY_REAL_IMPLEMENTED = True` flag
- [ ] Pinned block invariant (fail if block not pinned)
- [ ] Real reject reasons (from actual RPC errors)
- [ ] `ci_m4_gate.py` passes

### Phase 2: Pre-Trade Simulation (Next)

- [ ] `execution/simulator.py` - pre-trade simulation
- [ ] Simulation gate before execution
- [ ] Expected vs simulated output comparison
- [ ] Slippage estimation improvement

### Phase 3: Execution (Future)

- [ ] `execution/state_machine.py` - trade state tracking
- [ ] `execution/dex_dex_executor.py` - DEX swap execution
- [ ] Flash swap integration
- [ ] Private mempool submission
- [ ] Kill switch implementation
- [ ] Post-trade accounting

## Contracts (Inherited from M3)

### Artifact Contract (Same as M3)

```
output_dir/
├── snapshots/scan_*.json
├── reports/
│   ├── reject_histogram_*.json
│   └── truth_report_*.json
└── scan.log
```

### TruthReport Contract (M4 Extension)

```json
{
  "schema_version": "3.0.0",
  "run_mode": "REGISTRY_REAL",    // M4: must be REAL
  "health": {
    "gate_breakdown": {...},
    "dex_coverage": {
      "configured": [...],
      "with_quotes": [...],       // M4: real quotes
      "passed_gates": [...]
    }
  }
}
```

### Pinned Block Contract (M4 New)

```python
# In REAL mode, block MUST be pinned
if run_mode == "REGISTRY_REAL":
    if current_block is None:
        raise RuntimeError("INFRA_BLOCK_PIN_FAILED: block must be pinned in REAL mode")
```

### Reject Reasons Contract (M4)

```python
# Real reject codes from core/exceptions.py
REAL_REJECT_CODES = [
    "QUOTE_REVERT",           # Contract reverted
    "SLIPPAGE_TOO_HIGH",      # Exceeds threshold
    "INFRA_RPC_ERROR",        # RPC timeout/error
    "INFRA_BLOCK_PIN_FAILED", # Block not pinned
    "PRICE_SANITY_FAILED",    # Price out of range
    "LIQUIDITY_INSUFFICIENT", # Not enough liquidity
]
```

## Files to Modify

| File | Change |
|------|--------|
| `strategy/jobs/run_scan.py` | Enable `--mode real` (REGISTRY_REAL_IMPLEMENTED = True) |
| `strategy/jobs/run_scan_real.py` | Create real scanner implementation |
| `chains/providers.py` | Real RPC provider configuration |
| `config/chains.yaml` | Minimal chain config (1 chain × 1-2 DEX) |
| `monitoring/truth_report.py` | Add `dexes_quoted` to coverage |
| `scripts/ci_m4_gate.py` | M4 gate (created) |

## M3 Baseline

M4 must not break M3 contracts:
- `python scripts/ci_m3_gate.py` must still pass
- SMOKE mode must work unchanged
- Same artifact structure

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- M3 Gate Proof: `data/runs/ci_m3_gate_20260123_110359`
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
