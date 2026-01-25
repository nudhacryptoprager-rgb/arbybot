# Status: Milestone 4 (M4) — Execution Layer (Phase 1: REAL Pipeline)

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-24  
**Branch:** `split/code`  
**Depends On:** M3 ✅ DONE

## M4 Contract

```
REAL mode:
  ✓ Runs without raising RuntimeError
  ✓ Produces 4 artifacts (always)
  ✓ Pins current_block from RPC
  ✓ Execution disabled (execution_ready_count == 0)
  ⚠ quotes_fetched may be 0 (network-dependent, not a failure)
```

## Definition of Done (M4)

| Check | Requirement | Status |
|-------|-------------|--------|
| A | `python -m pytest -q` green | ✅ |
| B | `python scripts/ci_m3_gate.py` PASS | ✅ |
| C | `python scripts/ci_m4_gate.py` PASS | ⬜ |

### M4 Gate Criteria (ci_m4_gate.py)

**REQUIRED** (gate fails if not met):
- REAL scan executes without RuntimeError
- 4 artifacts generated: scan.log, scan_*.json, reject_histogram_*.json, truth_report_*.json
- run_mode == "REGISTRY_REAL"
- current_block > 0 (pinned)
- execution_ready_count == 0 (execution disabled)

**NOT REQUIRED** (warn only):
- quotes_fetched >= 1 (network-dependent)

## Verification Commands

```powershell
# Setup venv
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Run tests
python -m pytest -q

# Run gates
python scripts/ci_m3_gate.py
python scripts/ci_m4_gate.py
```

## Expected Output

### pytest -q

```
....................
X passed in Y.YYs
```

### ci_m3_gate.py

```
✅ M3 CI GATE PASSED
```

### ci_m4_gate.py

```
============================================================
  ARBY M4 CI GATE (REAL Pipeline)
============================================================
✅ Unit Tests (pytest -q) PASSED
✅ REAL Scan (1 cycle) PASSED
✓ Found: scan.log
✓ Found: scan_*.json
✓ Found: reject_histogram_*.json
✓ Found: truth_report_*.json
✅ All 4 artifacts present and valid
✓ run_mode: REGISTRY_REAL
✓ schema_version: 3.0.0
✓ current_block: XXXXXXXX (pinned)
✓ execution_ready_count: 0 (execution disabled)
⚠ quotes_fetched: 0/4 (network-dependent, not a gate failure)
✅ M4 invariants satisfied
============================================================
  ✅ M4 CI GATE PASSED
============================================================
```

## What's Working

1. **REAL mode runs**: No RuntimeError, executes pipeline
2. **Artifacts generated**: All 4 files created (always)
3. **Block pinned**: Fetched from live RPC
4. **Execution disabled**: execution_ready_count == 0

## Known Limitations

1. **quotes_fetched may be 0**: Quoter calls may revert due to:
   - Simplified calldata encoding (missing ABI)
   - Missing token parameters
   - RPC rate limiting
   
2. **rpc_success_rate semantics**: 
   - Measures "RPC returned valid JSON"
   - NOT "quote succeeded"
   - QUOTE_REVERT = RPC success, quote failure

## Files

| File | Purpose |
|------|---------|
| `strategy/jobs/run_scan.py` | Entry point (SMOKE/REAL router) |
| `strategy/jobs/run_scan_real.py` | REAL pipeline implementation |
| `config/real_minimal.yaml` | Canary config (1 chain, 1 DEX, 2 pairs) |
| `scripts/ci_m4_gate.py` | M4 gate script |
| `tests/integration/test_smoke_run.py` | Integration tests |

## Canary Config

`config/real_minimal.yaml`:
- 1 chain: Arbitrum One
- 1 DEX: Uniswap V3
- 2 pairs: WETH/USDC, WETH/USDT

Use for deterministic debugging:
```powershell
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml
```

## M3 Baseline Preserved

- ✅ `python scripts/ci_m3_gate.py` must still pass
- ✅ SMOKE mode works unchanged
- ✅ Same artifact structure (4 files)

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
