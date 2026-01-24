# Status: Milestone 4 (M4) — Execution Layer (Phase 1: REAL Pipeline)

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-23  
**Branch:** `split/code`  
**Depends On:** M3 ✅ DONE

## Definition of Done (M4 Phase 1)

```
⬜ python -m pytest -q                     → PASS
⬜ python scripts/ci_m4_gate.py            → PASS
   M4 Invariants:
   ├── run_mode == "REGISTRY_REAL"
   ├── schema_version == "3.0.0"
   ├── quotes_fetched >= 1
   ├── current_block > 0 (pinned)
   ├── execution_ready_count == 0
   └── 4/4 artifacts generated
```

## Current State: BLOCKED

**BLOCKED UNTIL**: Live RPC integration verified

The M4 skeleton is implemented but requires:
1. Valid RPC endpoints (set `ALCHEMY_API_KEY` in `.env`)
2. Network connectivity to Arbitrum RPC
3. Successful quote fetch from at least one DEX

## How to Run

```powershell
# 1. Activate venv
.\venv\Scripts\Activate.ps1

# 2. Set RPC credentials (create .env file)
# ALCHEMY_API_KEY=your_key_here

# 3. Run M3 gate (must still pass)
python scripts/ci_m3_gate.py

# 4. Run M4 gate
python scripts/ci_m4_gate.py

# 5. Manual REAL run
python -m strategy.jobs.run_scan --mode real --cycles 1 --output-dir data/runs/m4_test

# 6. With minimal config
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml
```

## Expected Output

When M4 gate passes:
```
============================================================
  ARBY M4 CI GATE (REAL Pipeline)
============================================================
✅ Unit Tests (pytest -q) PASSED
✅ REAL Scan (1 cycle) PASSED
✓ Found: scan_*.json
✓ Found: reject_histogram_*.json
✓ Found: truth_report_*.json
✓ Found: scan.log
✅ All 4 artifacts present and valid
✓ run_mode: REGISTRY_REAL
✓ schema_version: 3.0.0
✓ current_block: 150000XXX (pinned)
✓ quotes_fetched: 4 (>= 1 required)
✓ execution_ready_count: 0 (M4: execution disabled)
✅ M4 invariants satisfied
============================================================
  ✅ M4 CI GATE PASSED
============================================================
```

## Implementation Checklist

### Phase 1: REAL Pipeline ✅ (Skeleton Done)

- [x] `--mode real` runs pipeline (no RuntimeError)
- [x] `run_scan_real.py` - REAL scanner implementation
- [x] `run_mode: REGISTRY_REAL` marker in truth_report
- [x] Pinned block invariant (INFRA_BLOCK_PIN_FAILED if fails)
- [x] Real reject reasons from `core/exceptions.py`
- [x] `EXECUTION_DISABLED_M4` blocker on all opportunities
- [x] `execution_ready_count: 0` guaranteed
- [x] `config/real_minimal.yaml` - minimal config
- [x] `ci_m4_gate.py` - M4 gate script
- [ ] **VERIFY**: Live RPC quotes working

### Phase 2: Live RPC Stabilization (Next)

- [ ] Verify ALCHEMY_API_KEY integration
- [ ] Test with public RPC endpoints (no API key)
- [ ] Handle rate limiting gracefully
- [ ] Retry logic for transient failures
- [ ] Fallback between multiple RPC endpoints

### Phase 3: Pre-Trade Simulation (Future)

- [ ] `execution/simulator.py` - pre-trade simulation
- [ ] Simulation gate before execution
- [ ] Expected vs simulated output comparison

### Phase 4: Execution (Future)

- [ ] `execution/state_machine.py` - trade state tracking
- [ ] `execution/dex_dex_executor.py` - DEX swap execution
- [ ] Flash swap integration
- [ ] Private mempool submission
- [ ] Kill switch implementation

## M4 Contracts

### Artifact Contract (Same 4/4 as M3)

```
output_dir/
├── snapshots/scan_*.json
├── reports/
│   ├── reject_histogram_*.json
│   └── truth_report_*.json
└── scan.log
```

### TruthReport Contract (M4 Markers)

```json
{
  "schema_version": "3.0.0",
  "run_mode": "REGISTRY_REAL",
  "health": {
    "gate_breakdown": {"revert": N, "slippage": N, "infra": N, "other": N}
  },
  "stats": {
    "execution_ready_count": 0,
    "quotes_fetched": N
  }
}
```

### Pinned Block Contract (M4)

```python
# Block MUST be pinned from live RPC
if current_block is None or current_block <= 0:
    raise RuntimeError("INFRA_BLOCK_PIN_FAILED")
```

### Execution Disabled Contract (M4)

```python
# All opportunities blocked with:
execution_blockers = ["EXECUTION_DISABLED_M4"]
is_execution_ready = False
execution_ready_count = 0
```

### Reject Reasons Contract (M4)

All reject codes MUST be from `core/exceptions.py`:
```python
VALID_REJECT_CODES = [
    "QUOTE_REVERT",
    "SLIPPAGE_TOO_HIGH",
    "INFRA_RPC_ERROR",
    "INFRA_BLOCK_PIN_FAILED",
    "PRICE_SANITY_FAILED",
    "POOL_NO_LIQUIDITY",
    "PREFLIGHT_VALIDATION_FAILED",
]
```

### M4 Gate Invariants

```python
# ci_m4_gate.py checks:
assert truth_report["run_mode"] == "REGISTRY_REAL"
assert truth_report["schema_version"] == "3.0.0"
assert scan["current_block"] > 0  # pinned
assert scan["stats"]["quotes_fetched"] >= 1
assert truth_report["stats"]["execution_ready_count"] == 0
```

## Files Modified/Created

| File | Change |
|------|--------|
| `strategy/jobs/run_scan.py` | REAL mode dispatcher |
| `strategy/jobs/run_scan_real.py` | NEW: REAL pipeline |
| `config/real_minimal.yaml` | NEW: Minimal REAL config |
| `core/exceptions.py` | Added INFRA_BLOCK_PIN_FAILED |
| `scripts/ci_m4_gate.py` | NEW: M4 gate script |
| `docs/status/Status_M4.md` | This file |

## M3 Baseline Preserved

M4 must NOT break M3:
- ✅ `python scripts/ci_m3_gate.py` must still pass
- ✅ SMOKE mode works unchanged
- ✅ Same artifact structure (4/4)
- ✅ Same TruthReport schema (3.0.0)

## What's Next (After M4 Phase 1)

1. **M4 Phase 2**: Live RPC stabilization
   - Verify quote fetching works reliably
   - Handle network errors gracefully
   
2. **M4 Phase 3**: Pre-trade simulation
   - Add simulation layer before execution
   
3. **M4 Phase 4**: Execution
   - State machine, flash swaps, kill switch

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- M3 Gate Proof: `data/runs/ci_m3_gate_20260123_110359`
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
